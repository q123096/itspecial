"""
send_push_notifications.py — 신규 딜 웹 푸시 발송
===================================================
GitHub Actions에서 discover_deals.py 완료 후 실행.
최근 N시간 내 추가된 딜을 구독자 카테고리에 맞게 푸시 발송.

필요한 GitHub Secrets:
  SUPABASE_URL, SUPABASE_SERVICE_KEY
  VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY
  VAPID_MAILTO (예: mailto:admin@itspecial.co.kr)

Supabase push_subscriptions 테이블 SQL (최초 1회 실행):
  CREATE TABLE IF NOT EXISTS push_subscriptions (
    id          BIGSERIAL PRIMARY KEY,
    endpoint    TEXT NOT NULL UNIQUE,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    email       TEXT,
    categories  TEXT[] DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
  );
  CREATE INDEX IF NOT EXISTS idx_push_cats ON push_subscriptions USING GIN (categories);
  -- RLS: anon INSERT, service_role SELECT/UPDATE/DELETE
  ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "anon_insert"  ON push_subscriptions FOR INSERT TO anon  WITH CHECK (true);
  CREATE POLICY "service_all"  ON push_subscriptions FOR ALL   TO service_role USING (true);
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

try:
    from pywebpush import webpush, WebPushException
except ImportError:
    print("⚠️  pywebpush 미설치 — pip install pywebpush")
    sys.exit(0)

# ── 환경변수 ─────────────────────────────────────────────────────────
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
VAPID_PUBLIC_KEY     = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY    = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_MAILTO         = os.environ.get("VAPID_MAILTO", "mailto:admin@itspecial.co.kr")

# 최근 몇 시간 내 추가된 딜만 알림 발송
NOTIFY_WINDOW_HOURS = 6

ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEALS_PATH = os.path.join(ROOT, "data", "deals.json")
SITE_URL   = "https://itspecial.co.kr"

CATEGORY_LABELS = {
    "smartphone": "스마트폰", "laptop": "노트북", "tablet": "태블릿",
    "audio": "이어폰/헤드폰", "monitor": "모니터", "gaming": "게이밍",
    "wearable": "스마트워치", "desktop": "데스크탑", "accessory": "주변기기",
    "camera": "카메라",
}


def get_new_deals() -> list[dict]:
    """최근 NOTIFY_WINDOW_HOURS 시간 내 추가된 딜 목록"""
    with open(DEALS_PATH, encoding="utf-8") as f:
        deals = json.load(f)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=NOTIFY_WINDOW_HOURS)
    new = []
    for d in deals:
        added_str = d.get("addedAt", "")
        if not added_str:
            continue
        try:
            # "2026-05-31T12:34:56" → UTC aware
            added = datetime.fromisoformat(added_str).replace(tzinfo=timezone.utc)
            if added >= cutoff:
                new.append(d)
        except ValueError:
            pass
    return new


def get_subscriptions() -> list[dict]:
    """Supabase push_subscriptions 테이블 전체 조회"""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return []
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/push_subscriptions?select=endpoint,p256dh,auth,categories",
        headers={
            "apikey":        SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        },
        timeout=10,
    )
    return r.json() if r.ok else []


def send_push(sub: dict, payload: dict) -> bool:
    """단일 구독자에게 푸시 발송"""
    try:
        webpush(
            subscription_info={
                "endpoint": sub["endpoint"],
                "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
            },
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_MAILTO},
        )
        return True
    except WebPushException as e:
        # 410 Gone = 구독 만료 → 삭제 처리
        if e.response and e.response.status_code == 410:
            delete_subscription(sub["endpoint"])
        else:
            print(f"    ⚠️  발송 실패 ({sub['endpoint'][:50]}...): {e}")
        return False
    except Exception as e:
        print(f"    ❌ 오류: {e}")
        return False


def delete_subscription(endpoint: str) -> None:
    """만료된 구독 삭제 (410 응답 시)"""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return
    requests.delete(
        f"{SUPABASE_URL}/rest/v1/push_subscriptions?endpoint=eq.{requests.utils.quote(endpoint)}",
        headers={
            "apikey":        SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        },
        timeout=8,
    )


def main() -> None:
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        print("⚠️  VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY 미설정 — 스킵")
        return

    new_deals = get_new_deals()
    if not new_deals:
        print("신규 딜 없음 — 푸시 발송 스킵")
        return

    print(f"신규 딜 {len(new_deals)}개 감지 → 푸시 발송 준비")

    subscriptions = get_subscriptions()
    if not subscriptions:
        print("구독자 없음 — 스킵")
        return

    print(f"구독자 {len(subscriptions)}명")

    sent_total = 0
    for deal in new_deals[:5]:   # 한 번에 최대 5개 딜 알림 (과도한 발송 방지)
        cat      = deal.get("category", "")
        cat_label = CATEGORY_LABELS.get(cat, cat)
        disc     = round((deal["originalPrice"] - deal["salePrice"]) / deal["originalPrice"] * 100) \
                   if deal.get("originalPrice") and deal.get("salePrice") else 0
        sale_fmt = f"{deal['salePrice']:,}원" if deal.get("salePrice") else ""

        payload = {
            "title": f"⚡ {cat_label} 특가 {disc}% 할인",
            "body":  f"{deal['name'][:50]}\n{sale_fmt}",
            "url":   f"{SITE_URL}/deals/{deal['id']}.html",
            "tag":   f"deal-{deal['id']}",
        }

        sent = 0
        for sub in subscriptions:
            # 카테고리 매칭: 구독자가 해당 카테고리 또는 전체 구독
            sub_cats = sub.get("categories") or []
            if sub_cats and cat not in sub_cats:
                continue
            if send_push(sub, payload):
                sent += 1

        print(f"  [{disc}%][{cat_label}] {deal['name'][:40]} → {sent}명 발송")
        sent_total += sent

    print(f"\n✅ 총 {sent_total}건 푸시 발송 완료")


if __name__ == "__main__":
    main()
