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
  -- 찜 가격 하락 알림용: 구독자가 찜한 상품 정규화 키 목록
  ALTER TABLE push_subscriptions ADD COLUMN IF NOT EXISTS wishlisted_keys TEXT[] DEFAULT '{}';
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
    """Supabase push_subscriptions 테이블 전체 조회 (wishlisted_keys 포함)"""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return []
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/push_subscriptions?select=endpoint,p256dh,auth,categories,wishlisted_keys",
        headers={
            "apikey":        SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        },
        timeout=10,
    )
    return r.json() if r.ok else []


def make_product_key(name: str) -> str:
    """색상·브랜드 접두어 제거 → 상품명 정규화 (app.js makeProductKey와 동일 로직)"""
    import re
    color_re  = r"\s*[,·]?\s*(?:블랙|화이트|실버|그레이|블루|레드|핑크|퍼플|골드|그린|베이지|티타늄|카키|네이비|코랄|민트|라벤더|크림|챠콜|미드나잇|스타라이트|아이보리|스카이블루|옐로우?|오렌지|브라운|팬텀블랙|팬텀화이트|아이스블루|에버그린)(?=\s|,|$)"
    prefix_re = r"^\s*\[?(?:쿠팡|11번가|G마켓|옥션|SSG닷컴?|네이버쇼핑?|롯데온|다나와|에누리)\]?\s*[-_]?\s*"
    name = re.sub(prefix_re, "", name, flags=re.IGNORECASE)
    name = re.sub(color_re,  "", name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", name).strip()


def send_wishlist_drop_alerts(all_deals: list[dict], subscriptions: list[dict]) -> int:
    """
    찜한 상품이 현재 딜 목록에 있고 역대최저/핫딜 태그가 붙어있으면 알림 발송.
    - wishlisted_keys: 구독자가 찜한 상품의 정규화된 이름 목록
    - 이미 알림 받은 딜은 중복 발송 방지 (tag 기반)
    """
    sent_total = 0
    deal_key_map = {make_product_key(d["name"]): d for d in all_deals}

    for sub in subscriptions:
        wk = sub.get("wishlisted_keys") or []
        if not wk:
            continue
        for key in wk:
            deal = deal_key_map.get(key)
            if not deal:
                continue
            tags = deal.get("tags", [])
            if not any(t in tags for t in ["역대최저", "핫딜"]):
                continue
            disc = round((deal["originalPrice"] - deal["salePrice"]) / deal["originalPrice"] * 100) \
                   if deal.get("originalPrice") else 0
            payload = {
                "title": f"📉 찜한 상품 가격 하락! {disc}% 할인",
                "body":  f"{deal['name'][:50]}\n{deal['salePrice']:,}원",
                "url":   f"{SITE_URL}/deals/{deal['id']}.html",
                "tag":   f"wish-{deal['id']}",
            }
            if send_push(sub, payload):
                sent_total += 1
                print(f"    💌 찜 알림: {deal['name'][:40]}")

    return sent_total


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

    with open(DEALS_PATH, encoding="utf-8") as f:
        all_deals = json.load(f)

    new_deals = get_new_deals()
    subscriptions = get_subscriptions()
    if not subscriptions:
        print("구독자 없음 — 스킵")
        return

    print(f"구독자 {len(subscriptions)}명")
    sent_total = 0

    # ── 1. 신규 딜 알림 ──
    if new_deals:
        print(f"\n신규 딜 {len(new_deals)}개 → 카테고리 구독자 알림")
        for deal in new_deals[:5]:
            cat       = deal.get("category", "")
            cat_label = CATEGORY_LABELS.get(cat, cat)
            disc      = round((deal["originalPrice"] - deal["salePrice"]) / deal["originalPrice"] * 100) \
                        if deal.get("originalPrice") and deal.get("salePrice") else 0
            payload = {
                "title": f"⚡ {cat_label} 특가 {disc}% 할인",
                "body":  f"{deal['name'][:50]}\n{deal['salePrice']:,}원",
                "url":   f"{SITE_URL}/deals/{deal['id']}.html",
                "tag":   f"deal-{deal['id']}",
            }
            sent = 0
            for sub in subscriptions:
                sub_cats = sub.get("categories") or []
                if sub_cats and cat not in sub_cats:
                    continue
                if send_push(sub, payload):
                    sent += 1
            print(f"  [{disc}%][{cat_label}] {deal['name'][:40]} → {sent}명 발송")
            sent_total += sent
    else:
        print("신규 딜 없음")

    # ── 2. 찜 상품 가격 하락 알림 ──
    wish_sent = send_wishlist_drop_alerts(all_deals, subscriptions)
    if wish_sent:
        print(f"\n💌 찜 가격 하락 알림 {wish_sent}건 발송")
    sent_total += wish_sent

    print(f"\n✅ 총 {sent_total}건 푸시 발송 완료")


if __name__ == "__main__":
    main()
