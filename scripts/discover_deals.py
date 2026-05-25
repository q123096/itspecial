"""
TechDeal KR — 자동 딜 발굴 스크립트
=====================================
실행 주기: GitHub Actions 하루 3회 자동 실행
설정 파일: config/search_config.json  ← 이것만 수정하면 됨

발굴 소스 (우선순위 순):
  1. 쿠팡 파트너스 API  - 카테고리별 베스트셀러 + 키워드 검색 + 링크 동시 생성
  2. 네이버 쇼핑 검색 API - 키워드 검색 (하루 25,000건 무료)
  3. 뽐뿌 RSS 파싱       - 커뮤니티 핫딜 신호 감지

결과:
  - data/deals.json 자동 업데이트 (신규 추가 + 만료 제거)
  - 제휴링크는 update_affiliate_links.py 가 후속 처리
"""

import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

try:
    import requests
except ImportError:
    print("pip install requests 실행 후 다시 시도하세요.")
    sys.exit(1)

# ─── 경로 설정 ───────────────────────────────────────────────────
ROOT               = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEALS_PATH         = os.path.join(ROOT, "data", "deals.json")
CONFIG_PATH        = os.path.join(ROOT, "config", "search_config.json")
PRICE_HISTORY_PATH = os.path.join(ROOT, "data", "price_history.json")
SUBSCRIBERS_PATH   = os.path.join(ROOT, "data", "subscribers.json")

SITE_URL           = "https://q123096.github.io/itspecial"
FROM_EMAIL         = "ITSpecial <no-reply@itspecial.co.kr>"

# ─── Supabase (구독자 DB) ────────────────────────────────────────
# GitHub Secrets에 SUPABASE_URL + SUPABASE_SERVICE_KEY 추가 시 자동 연동
# 미설정 시 data/subscribers.json 폴백
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


# ─── 7일 평균가 시스템 ───────────────────────────────────────────
def load_price_history() -> dict:
    """저장된 가격 히스토리 로드 (없으면 빈 딕셔너리)"""
    if os.path.exists(PRICE_HISTORY_PATH):
        with open(PRICE_HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def update_price_history(history: dict, keyword: str, lprice: int) -> None:
    """
    키워드별 오늘 최저가 기록 → 7일치만 유지 → 7일 평균 재계산
    하루 3회 실행 시 그날의 최솟값으로 갱신
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if keyword not in history:
        history[keyword] = {"history": [], "avg_7d": 0, "days": 0}

    entries = history[keyword]["history"]
    today_entry = next((e for e in entries if e["date"] == today), None)
    if today_entry:
        today_entry["lprice"] = min(today_entry["lprice"], lprice)
    else:
        entries.append({"date": today, "lprice": lprice})

    # 7일 이전 데이터 제거
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    history[keyword]["history"] = [e for e in entries if e["date"] >= cutoff]

    # 7일 평균 재계산
    valid = [e["lprice"] for e in history[keyword]["history"] if e["lprice"] >= 30000]
    history[keyword]["avg_7d"] = round(sum(valid) / len(valid)) if valid else 0
    history[keyword]["days"]   = len(valid)


def get_reference_price(history: dict, keyword: str, msrp: int) -> int:
    """
    기준가 결정:
      - 3일 이상 데이터 축적 → 7일 평균가 (실제 시장가 기반)
      - 3일 미만             → msrp fallback (초기 부트스트랩)
      - 7일 평균이 msrp의 110% 초과 시 msrp 우선 (품귀·가격 급등 방어)
    """
    entry = history.get(keyword, {})
    avg   = entry.get("avg_7d", 0)
    days  = entry.get("days", 0)

    if days >= 3 and avg > 0:
        if msrp > 0 and avg > msrp * 1.1:
            return msrp   # 시장가가 MSRP보다 비정상적으로 높으면 MSRP 사용
        return avg

    return msrp   # 데이터 부족 → MSRP fallback


def save_price_history(history: dict) -> None:
    with open(PRICE_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ─── Resend 딜 알림 이메일 ───────────────────────────────────────
CAT_LABEL = {
    "smartphone": "스마트폰", "laptop": "노트북",   "desktop": "데스크탑/PC",
    "tablet":     "태블릿",   "audio":  "이어폰/헤드폰", "monitor": "모니터",
    "camera":     "카메라",   "gaming": "게이밍",   "wearable": "웨어러블",
    "accessory":  "주변기기",
}


def _deal_card_html(deal: dict) -> str:
    disc = round((deal["originalPrice"] - deal["salePrice"]) / deal["originalPrice"] * 100)
    savings = deal["originalPrice"] - deal["salePrice"]
    href = deal.get("affiliateUrl") or deal.get("productUrl", "#")
    return f"""
    <div style="border:1.5px solid #e9ecef;border-radius:12px;overflow:hidden;margin-bottom:16px;font-family:sans-serif;">
      <div style="position:relative;">
        <img src="{deal['image']}" alt="{deal['name']}"
             style="width:100%;height:180px;object-fit:cover;display:block;"
             onerror="this.style.display='none'">
        <span style="position:absolute;top:10px;left:10px;background:#FF4136;color:#fff;
                     font-weight:700;font-size:13px;padding:4px 10px;border-radius:6px;">
          {disc}% 할인
        </span>
      </div>
      <div style="padding:14px;">
        <div style="font-size:11px;color:#868e96;margin-bottom:4px;">{deal['store']}</div>
        <div style="font-size:14px;font-weight:700;color:#1a1a2e;margin-bottom:8px;
                    line-height:1.4;">{deal['name'][:55]}</div>
        <div style="margin-bottom:10px;">
          <span style="font-size:12px;color:#adb5bd;text-decoration:line-through;">
            {deal['originalPrice']:,}원
          </span>
          <span style="font-size:20px;font-weight:800;color:#FF4136;margin-left:6px;">
            {deal['salePrice']:,}원
          </span>
        </div>
        <div style="font-size:11px;color:#868e96;margin-bottom:12px;">
          💰 {savings:,}원 절약
        </div>
        <a href="{href}"
           style="display:block;text-align:center;background:#FF4136;color:#fff;
                  font-weight:700;font-size:13px;padding:10px;border-radius:8px;
                  text-decoration:none;">
          구매하러 가기 →
        </a>
      </div>
    </div>"""


def _build_email_html(deals: list[dict], categories: list[str], recipient_email: str = "") -> str:
    cat_names = " · ".join(CAT_LABEL.get(c, c) for c in categories)
    unsub_url = f"{SITE_URL}/unsubscribe.html?email={urllib.parse.quote(recipient_email)}" if recipient_email else f"{SITE_URL}/unsubscribe.html"
    cards = "".join(_deal_card_html(d) for d in deals[:5])  # 최대 5개
    return f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f8f9fa;font-family:'Apple SD Gothic Neo',sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:20px;">

    <!-- 헤더 -->
    <div style="background:linear-gradient(135deg,#1A1A2E,#0F3460);border-radius:14px;
                padding:28px 24px;text-align:center;margin-bottom:20px;">
      <div style="font-size:26px;font-weight:800;color:#fff;letter-spacing:-0.5px;">
        ⚡ <span style="color:#FF4136;">IT</span>Special
      </div>
      <div style="font-size:13px;color:rgba(255,255,255,0.7);margin-top:6px;">
        카테고리별 특가 알림 · {cat_names}
      </div>
    </div>

    <!-- 소개 -->
    <div style="background:#fff;border-radius:12px;padding:18px 20px;margin-bottom:16px;
                border:1px solid #e9ecef;font-size:14px;color:#495057;line-height:1.7;">
      새로운 특가 상품 <strong>{len(deals)}개</strong>가 발견됐습니다.
      지금 바로 확인하고 놓치지 마세요! 🔥
    </div>

    <!-- 딜 카드 -->
    {cards}

    <!-- 더보기 버튼 -->
    <div style="text-align:center;margin:20px 0;">
      <a href="{SITE_URL}"
         style="display:inline-block;background:#1a1a2e;color:#fff;font-weight:700;
                font-size:14px;padding:12px 32px;border-radius:999px;text-decoration:none;">
        전체 특가 보러가기
      </a>
    </div>

    <!-- 푸터 -->
    <div style="text-align:center;font-size:11px;color:#adb5bd;margin-top:20px;line-height:1.8;">
      이 메일은 ITSpecial 특가 알림을 신청하셨기 때문에 발송됩니다.<br>
      이 메일은 <a href="mailto:no-reply@itspecial.co.kr"
                  style="color:#adb5bd;">no-reply@itspecial.co.kr</a>에서 발송되었습니다.<br>
      더 이상 받지 않으려면
      <a href="{unsub_url}" style="color:#adb5bd;text-decoration:underline;">수신거부</a>를 클릭하세요.<br>
      © 2026 ITSpecial · 개인정보는 알림 발송 목적으로만 사용됩니다.
    </div>
  </div>
</body>
</html>"""


def load_subscribers() -> list[dict]:
    """
    구독자 목록 로드.
    우선순위: Supabase REST API → data/subscribers.json 폴백
    Supabase: service role key로 전체 조회 (RLS 우회)
    """
    if SUPABASE_URL and SUPABASE_SERVICE_KEY:
        try:
            res = requests.get(
                f"{SUPABASE_URL}/rest/v1/subscribers",
                params={"select": "email,categories"},
                headers={
                    "apikey":         SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                },
                timeout=10,
            )
            if res.status_code == 200:
                data = res.json()
                print(f"  ☁️  Supabase에서 구독자 {len(data)}명 로드")
                # categories 는 jsonb → Python list 로 자동 파싱됨
                return [{"email": d["email"], "categories": d.get("categories", [])} for d in data]
            else:
                print(f"  ⚠️  Supabase 조회 실패 [{res.status_code}]: {res.text[:120]}")
        except Exception as e:
            print(f"  ⚠️  Supabase 로드 예외: {e}")

    # ── 폴백: 로컬 subscribers.json ───────────────────────────────
    if os.path.exists(SUBSCRIBERS_PATH):
        with open(SUBSCRIBERS_PATH, encoding="utf-8") as f:
            subs = json.load(f)
        if subs:
            print(f"  📄 subscribers.json에서 구독자 {len(subs)}명 로드")
        return subs

    return []


def send_deal_alerts(new_deals: list[dict], api_key: str) -> None:
    """새로 발굴된 딜을 카테고리별 구독자에게 Resend로 발송."""
    if not api_key or not new_deals:
        return

    subscribers = load_subscribers()
    if not subscribers:
        print("  📭 구독자 없음 — 알림 발송 스킵")
        return

    # 카테고리별 새 딜 인덱스
    deals_by_cat: dict[str, list] = {}
    for d in new_deals:
        cat = d.get("category", "")
        deals_by_cat.setdefault(cat, []).append(d)

    sent = skipped = 0
    for sub in subscribers:
        email = sub.get("email", "").strip()
        cats  = sub.get("categories", [])
        if not email or not cats:
            continue

        matching = [d for c in cats for d in deals_by_cat.get(c, [])]
        if not matching:
            skipped += 1
            continue

        html    = _build_email_html(matching, cats, email)
        subject = f"🔥 {len(matching)}개 특가 발견! ({', '.join(CAT_LABEL.get(c,c) for c in cats[:2])})"

        try:
            res = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"from": FROM_EMAIL, "to": [email], "subject": subject, "html": html},
                timeout=15,
            )
            if res.status_code == 200:
                sent += 1
                print(f"  ✉️  발송 완료: {email} ({len(matching)}개 딜)")
            else:
                print(f"  ⚠️  발송 실패 [{res.status_code}]: {email} — {res.text[:100]}")
        except Exception as e:
            print(f"  ❌ 발송 오류: {email} — {e}")

    print(f"  📬 알림 발송 완료: {sent}명 발송 | {skipped}명 해당 딜 없음")


# ─── 쿠팡 파트너스 API 인증 ──────────────────────────────────────
COUPANG_HOST = "https://api-gateway.coupang.com"


def coupang_auth(method: str, path: str, query: str, secret: str, access: str) -> str:
    dt = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    msg = dt + method + path + (("?" + query) if query else "")
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={access}, signed-date={dt}, signature={sig}"


def coupang_get(path: str, params: dict, access: str, secret: str) -> dict | None:
    query = urllib.parse.urlencode(params)
    url   = f"{COUPANG_HOST}{path}?{query}"
    auth  = coupang_auth("GET", path, query, secret, access)
    try:
        r = requests.get(url, headers={"Authorization": auth}, timeout=10)
        if r.status_code == 200:
            return r.json()
        print(f"  ⚠️  쿠팡 API {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  ❌ 요청 오류: {e}")
    return None


# ─── 쿠팡 상품 검색 ──────────────────────────────────────────────
def search_coupang_products(keyword: str, access: str, secret: str, limit: int = 5) -> list[dict]:
    """키워드로 쿠팡 상품 검색 → 할인율 높은 순 반환"""
    data = coupang_get(
        "/v2/providers/affiliate_open_api/apis/openapi/products/search",
        {"keyword": keyword, "limit": limit},
        access, secret,
    )
    if not data:
        return []
    return data.get("data", {}).get("productData", [])


def get_coupang_bestsellers(category_id: str, access: str, secret: str, limit: int = 5) -> list[dict]:
    """카테고리 베스트셀러 조회"""
    data = coupang_get(
        f"/v2/providers/affiliate_open_api/apis/openapi/products/bestcategories/{category_id}",
        {"limit": limit},
        access, secret,
    )
    if not data:
        return []
    return data.get("data", {}).get("productData", [])


def coupang_product_to_deal(p: dict, category: str, next_id: int) -> dict | None:
    """쿠팡 API 상품 데이터 → deals.json 포맷 변환"""
    orig = p.get("originalPrice") or p.get("basePrice", 0)
    sale = p.get("salePrice") or p.get("price", 0)
    if not orig or not sale or sale >= orig:
        return None

    disc = round((orig - sale) / orig * 100)

    tags = []
    if disc >= 30: tags.append("핫딜")
    if disc >= 40: tags.append("역대최저")

    return {
        "id":            next_id,
        "name":          p.get("productName", ""),
        "category":      category,
        "image":         p.get("productImage", ""),
        "originalPrice": int(orig),
        "salePrice":     int(sale),
        "store":         "쿠팡",
        "productUrl":    p.get("productUrl", ""),
        "affiliateUrl":  p.get("shortenUrl", ""),   # 검색 결과에 링크 포함 시 바로 사용
        "expiresAt":     (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT23:59:00"),
        "tags":          tags if tags else ["핫딜"],
        "rating":        round(float(p.get("productRating", 4.0)), 1),
        "reviewCount":   int(p.get("reviewCount", 0)),
        "inStock":       True,
        "freeShipping":  p.get("isRocket", False) or p.get("freeShipping", False),
    }


# ─── 네이버 쇼핑 검색 API ────────────────────────────────────────
NAVER_SHOP_URL = "https://openapi.naver.com/v1/search/shop.json"


def search_naver_products(keyword: str, client_id: str, client_secret: str,
                          display: int = 10, min_price: int = 30000) -> list[dict]:
    """
    네이버 쇼핑 검색 API
    - 가입: https://developers.naver.com/apps/#/register
    - 무료: 하루 25,000건
    - 반환: lprice(최저가), hprice(최고가), mallName, image, link, title
    - min_price: config의 min_price 필드로 가격대 필터 (기본 3만원)
                 "게이밍 완본체"처럼 광범위한 키워드에 700000 걸면 잡동사니 차단
    """
    try:
        r = requests.get(
            NAVER_SHOP_URL,
            headers={
                "X-Naver-Client-Id":     client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={
                "query":   keyword,
                "display": display,
                "sort":    "sim",                        # 정확도순
                "filter":  f"minPrice:{min_price}",      # 가격 하한 필터
            },
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("items", [])
        print(f"  ⚠️  네이버 API {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  ❌ 네이버 API 오류: {e}")
    return []


def naver_product_to_deal(p: dict, category: str, next_id: int, min_disc: int, msrp: int = 0) -> dict | None:
    """
    네이버 쇼핑 API 상품 → deals.json 포맷
    할인율 판단 우선순위:
      1) hprice > lprice (API 제공 최고가 활용)
      2) 제목에서 "N% 할인" 파싱
      3) 제목에서 "정가→판매가" 파싱
      4) config msrp 기준가 활용 (API가 hprice를 안 줄 때 핵심 fallback)
    """
    title = re.sub(r"<[^>]+>", "", p.get("title", "")).strip()
    lp    = int(p.get("lprice") or 0)
    hp    = int(p.get("hprice") or 0)
    mall  = p.get("mallName", "네이버쇼핑")
    link  = p.get("link", "")
    image = p.get("image", "")

    if not lp or lp < 30000:   # 3만원 미만 제품 제외 (케이스·스티커 등 잡동사니)
        return None

    # 중고 / 리퍼 제품 제외
    if re.search(r'중고|B급|리퍼|리퍼비시|반품|A급|S급|최상급|판매완료', title):
        return None

    # 스마트폰 카테고리: 자급제 / 공기계 표기 없으면 전부 차단
    if category == 'smartphone':
        # ① 화이트리스트: 제목에 자급제·공기계 표기가 없으면 통신사 개통폰으로 간주
        #    (Naver sort=sim이 "자급제" 검색에도 통신사 폰을 반환하는 문제 대응)
        if not any(kw in title for kw in ['자급제', '공기계']):
            return None

        # ② 블랙리스트: 자급제 표기가 있어도 개통 관련 키워드 있으면 제외
        carrier_title_kw = [
            '개통', '약정', '공시지원금', '선택약정', '번호이동',
            '기기변경', '신규가입', '통신사', '유심',
        ]
        if any(kw in title for kw in carrier_title_kw):
            return None

        # ③ 통신사 공식몰 블랙리스트 (쇼핑몰명 기준)
        carrier_mall_kw = [
            '텔레콤', '유플러스', 'lgu', 'kt공식', 'sk공식',
            'olleh', '브로드밴드', '티플', '엔텔레콤',
        ]
        if any(kw in mall.lower() for kw in carrier_mall_kw):
            return None

    disc = 0
    orig = 0
    sale = lp

    # Case 1: hprice(최고가)가 있고 lprice보다 클 때 → 정상 할인율 계산
    if hp > lp:
        disc = round((hp - lp) / hp * 100)
        orig = hp

    # Case 2: hprice 없음 → 제목에서 할인율 파싱 (예: "30% 할인", "[20%↓]")
    elif re.search(r'(\d+)\s*%\s*할인|(\d+)%↓|(\d+)%\s*off', title, re.IGNORECASE):
        m    = re.search(r'(\d+)\s*%', title)
        disc = int(m.group(1)) if m else 0
        orig = round(lp / (1 - disc / 100)) if disc < 100 else lp

    # Case 3: 제목에서 두 가격 파싱 (예: "89,000원→59,000원")
    elif re.search(r'[\d,]+원\s*[→\-]\s*[\d,]+원', title):
        prices = [int(x.replace(",", "")) for x in re.findall(r'([\d,]+)원', title)]
        if len(prices) >= 2:
            orig = max(prices)
            sale = min(prices)
            lp   = sale
            disc = round((orig - sale) / orig * 100) if orig > sale else 0

    # Case 4: config의 msrp를 기준가로 사용 (네이버 API가 hprice를 안 줄 때 핵심 fallback)
    if orig == 0 and msrp > 0:
        if lp < msrp:
            disc = round((msrp - lp) / msrp * 100)
            orig = msrp
        # lp >= msrp이면 할인 없음 → orig=0 유지 → 아래에서 필터

    if disc < min_disc or orig == 0:
        return None

    # 과도한 할인율 필터: 55% 초과는 중고·오류 가능성 높음
    if disc > 55:
        return None

    tags = []
    if disc >= 20: tags.append("핫딜")
    if disc >= 35: tags.append("역대최저")
    if not tags:   tags = ["핫딜"]

    return {
        "id":            next_id,
        "name":          title[:60],
        "category":      category,
        "image":         image,
        "originalPrice": orig,
        "salePrice":     lp,
        "store":         mall,
        "productUrl":    link,
        "affiliateUrl":  "",
        "expiresAt":     (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT23:59:00"),
        "tags":          tags,
        "rating":        4.0,
        "reviewCount":   int(p.get("reviewCount") or 0),
        "inStock":       True,
        "freeShipping":  False,
    }


# ─── 뽐뿌 RSS 파싱 ───────────────────────────────────────────────
def fetch_ppomppu_deals(config: dict) -> list[dict]:
    """
    뽐뿌 RSS 여러 게시판에서 테크 핫딜 수집.
    - ppomppu (핫딜 통합), computer (PC/부품), phone (스마트폰)
    """
    rss_cfg = config.get("ppomppu_rss", {})
    if not rss_cfg.get("enabled"):
        return []

    tech_kw   = rss_cfg.get("tech_keywords", [])
    max_posts = rss_cfg.get("max_posts", 30)
    # 단일 url 또는 urls 배열 모두 지원
    urls = rss_cfg.get("urls") or ([rss_cfg["url"]] if rss_cfg.get("url") else [])

    print(f"\n📡 뽐뿌 RSS 파싱 중... ({len(urls)}개 게시판)")
    candidates = []
    seen_links = set()

    for url in urls:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ITSpecialBot/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            # ppomppu는 EUC-KR 인코딩 사용 — UTF-8 실패 시 EUC-KR로 재시도
            try:
                xml_data = raw.decode("utf-8")
            except UnicodeDecodeError:
                xml_data = raw.decode("euc-kr", errors="replace")

            root  = ET.fromstring(xml_data)
            items = root.findall(".//item")[:max_posts]
            board_name = url.split('id=')[-1]
            print(f"  📂 {board_name} 게시판: {len(items)}개 포스팅")
            # 첫 3개 제목 출력 (디버그)
            for dbg in items[:3]:
                print(f"    └ {(dbg.findtext('title') or '')[:60]}")

            for item in items:
                title = (item.findtext("title") or "").strip()
                link  = (item.findtext("link") or "").strip()
                desc  = (item.findtext("description") or "").strip()

                if link in seen_links:
                    continue
                seen_links.add(link)

                # 테크 키워드 포함 여부
                combined = title + " " + desc
                if not any(kw in combined for kw in tech_kw):
                    continue

                # 가격 추출
                raw_prices = re.findall(r"[\d,]+(?=원)", combined)
                prices = []
                for rp in raw_prices:
                    v = int(rp.replace(",", ""))
                    if 1000 < v < 10_000_000:
                        prices.append(v)

                if len(prices) >= 2:
                    orig, sale = max(prices), min(prices)
                else:
                    # 가격 1개뿐: 제목에서 할인율 파싱 시도
                    m = re.search(r'(\d+)\s*%\s*할인', title)
                    if m and len(prices) == 1:
                        disc_pct = int(m.group(1))
                        sale = prices[0]
                        orig = round(sale / (1 - disc_pct / 100))
                    else:
                        continue

                if sale >= orig or orig <= 0:
                    continue

                disc = round((orig - sale) / orig * 100)
                if disc < config["settings"]["min_discount_pct"]:
                    continue

                candidates.append({
                    "_source": "ppomppu",
                    "title":   title,
                    "link":    link,
                    "originalPrice": orig,
                    "salePrice":     sale,
                    "discount":      disc,
                })
                print(f"  📌 [{disc}%할인] {title[:50]}")

        except Exception as e:
            print(f"  ❌ {url} 오류: {e}")

    print(f"  → 뽐뿌 합계 {len(candidates)}개 테크 딜 감지")
    return candidates


def ppomppu_candidate_to_deal(c: dict, category: str, next_id: int) -> dict:
    """뽐뿌 후보 → deals.json 포맷 (productUrl이 게시글 링크)"""
    disc = c["discount"]
    tags = ["핫딜"]
    if disc >= 30: tags.append("역대최저")

    return {
        "id":            next_id,
        "name":          c["title"][:60],
        "category":      category,
        "image":         "https://placehold.co/400x300/f1f3f5/adb5bd?text=뽐뿌+핫딜",
        "originalPrice": c["originalPrice"],
        "salePrice":     c["salePrice"],
        "store":         "뽐뿌 핫딜",
        "productUrl":    c["link"],
        "affiliateUrl":  "",   # 쇼핑몰 직링크 아니므로 수동 확인 필요
        "expiresAt":     (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT23:59:00"),
        "tags":          tags,
        "rating":        4.0,
        "reviewCount":   0,
        "inStock":       True,
        "freeShipping":  False,
    }


# ─── 중복/만료 관리 ──────────────────────────────────────────────
def is_duplicate(new_deal: dict, existing: list[dict]) -> bool:
    """이름 유사도 또는 productUrl 기준 중복 체크"""
    new_url  = new_deal.get("productUrl", "")
    new_name = new_deal.get("name", "").lower()

    for d in existing:
        if new_url and d.get("productUrl") == new_url:
            return True
        # 이름 앞 10글자가 같으면 중복으로 간주
        if new_name[:10] and d.get("name", "").lower().startswith(new_name[:10]):
            return True
    return False


def remove_expired(deals: list[dict], keep_days: int = 1) -> tuple[list[dict], int]:
    """만료된 딜 제거 (keep_days 유예기간 적용)"""
    now     = datetime.now(timezone.utc)
    cutoff  = now - timedelta(days=keep_days)
    active  = []
    removed = 0

    for d in deals:
        exp = d.get("expiresAt")
        if exp:
            try:
                exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                # 시간대 정보 없으면 UTC로 간주
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if exp_dt < cutoff:
                    removed += 1
                    continue
            except ValueError:
                pass
        active.append(d)

    return active, removed


# ─── 메인 ────────────────────────────────────────────────────────
def main():
    access       = os.environ.get("COUPANG_ACCESS_KEY", "")
    secret       = os.environ.get("COUPANG_SECRET_KEY", "")
    naver_id     = os.environ.get("NAVER_CLIENT_ID", "")
    naver_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    resend_key   = os.environ.get("RESEND_API_KEY", "")

    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    with open(DEALS_PATH, encoding="utf-8") as f:
        deals = json.load(f)

    settings       = config["settings"]
    min_disc       = settings["min_discount_pct"]
    max_total      = settings["max_deals_total"]
    per_keyword    = settings["deals_per_keyword"]
    keep_days      = settings.get("keep_expired_days", 1)

    # ── 만료 딜 제거 ──
    deals, expired_count = remove_expired(deals, keep_days)
    print(f"\n🗑️  만료 딜 {expired_count}개 제거")

    new_deals  = []
    next_id    = max((d["id"] for d in deals), default=0) + 1

    # ── 1. 쿠팡 키워드 검색 ──
    if access and secret:
        print(f"\n🔍 쿠팡 파트너스 키워드 검색 시작 ({len(config['search_keywords'])}개 키워드)...")
        for kw_cfg in sorted(config["search_keywords"], key=lambda x: x.get("priority", 9)):
            keyword  = kw_cfg["keyword"]
            category = kw_cfg["category"]
            print(f"\n  🔎 [{category}] '{keyword}' 검색 중...")

            products = search_coupang_products(keyword, access, secret, limit=per_keyword * 2)
            added = 0
            for p in products:
                orig = p.get("originalPrice") or p.get("basePrice", 0)
                sale = p.get("salePrice") or p.get("price", 0)
                if not orig or not sale or sale >= orig:
                    continue
                disc = round((orig - sale) / orig * 100)
                if disc < min_disc:
                    continue

                deal = coupang_product_to_deal(p, category, next_id)
                if deal and not is_duplicate(deal, deals + new_deals):
                    new_deals.append(deal)
                    next_id += 1
                    added += 1
                    print(f"    ✅ [{disc}%] {deal['name'][:40]}")
                    if added >= per_keyword:
                        break

            time.sleep(0.5)  # API 속도 제한

        # ── 2. 쿠팡 카테고리 베스트셀러 ──
        print(f"\n📈 카테고리 베스트셀러 조회...")
        for cat_cfg in config["coupang_categories"]:
            products = get_coupang_bestsellers(cat_cfg["id"], access, secret, limit=5)
            for p in products:
                orig = p.get("originalPrice") or p.get("basePrice", 0)
                sale = p.get("salePrice") or p.get("price", 0)
                if not orig or not sale or sale >= orig:
                    continue
                disc = round((orig - sale) / orig * 100)
                if disc < min_disc:
                    continue
                deal = coupang_product_to_deal(p, cat_cfg["category"], next_id)
                if deal and not is_duplicate(deal, deals + new_deals):
                    new_deals.append(deal)
                    next_id += 1
                    print(f"  ✅ [{disc}%][{cat_cfg['name']}] {deal['name'][:35]}")
            time.sleep(0.3)
    else:
        print("\n⚠️  COUPANG_ACCESS_KEY 없음 — 쿠팡 검색 스킵")
        print("   GitHub Secrets에 키를 추가하면 완전 자동화됩니다.")

    # ── 3. 네이버 쇼핑 검색 ──
    if naver_id and naver_secret:
        print(f"\n🛍️  네이버 쇼핑 검색 시작 ({len(config['search_keywords'])}개 키워드)...")
        price_history = load_price_history()

        for kw_cfg in config["search_keywords"]:
            keyword   = kw_cfg["keyword"]
            category  = kw_cfg["category"]
            msrp      = kw_cfg.get("msrp", 0)
            min_price = kw_cfg.get("min_price", 30000)
            products  = search_naver_products(keyword, naver_id, naver_secret, display=10, min_price=min_price)

            # 오늘 최저가 기록 → 7일 평균 업데이트
            if products:
                min_lp = min(
                    (int(p.get("lprice") or 0) for p in products if p.get("lprice")),
                    default=0,
                )
                if min_lp >= 30000:
                    update_price_history(price_history, keyword, min_lp)

            # 기준가 결정: 7일 평균(3일 이상 데이터) 또는 MSRP fallback
            ref_price = get_reference_price(price_history, keyword, msrp)
            hist_entry = price_history.get(keyword, {})
            hist_days  = hist_entry.get("days", 0)
            ref_label  = f"7일평균({hist_days}일치)" if hist_days >= 3 else "MSRP"

            # 첫 결과 디버그
            if products:
                p0 = products[0]
                lp0 = int(p0.get("lprice") or 0)
                disc_ref = round((ref_price - lp0) / ref_price * 100) if ref_price and lp0 < ref_price else 0
                print(f"  [DEBUG] lprice={lp0:,} {ref_label}={ref_price:,} → 기준가대비 {disc_ref}% | {re.sub(r'<[^>]+>','',p0.get('title',''))[:30]}")

            passed = 0
            for p in products:
                deal = naver_product_to_deal(p, category, next_id, min_disc, msrp=ref_price)
                if deal and not is_duplicate(deal, deals + new_deals):
                    new_deals.append(deal)
                    next_id += 1
                    passed += 1
                    disc = round((deal["originalPrice"] - deal["salePrice"]) / deal["originalPrice"] * 100)
                    print(f"  ✅ [{disc}%][{deal['store']}] {deal['name'][:35]}")
            print(f"  → [{keyword}] API {len(products)}개 수신, 필터 통과 {passed}개 ({ref_label} {ref_price:,}원 기준)")
            time.sleep(0.3)

        save_price_history(price_history)
        print(f"  💾 가격 히스토리 저장 완료 ({len(price_history)}개 키워드 누적)")
    else:
        print("\n⚠️  NAVER_CLIENT_ID 없음 — 네이버 검색 스킵")

    # ── 4. 뽐뿌 RSS ──
    ppomppu_candidates = fetch_ppomppu_deals(config)
    for c in ppomppu_candidates[:5]:   # 뽐뿌에서 최대 5개
        # 카테고리 자동 추정
        title_lower = c["title"].lower()
        category = "accessory"
        for kw_cfg in config["search_keywords"]:
            if any(w in c["title"] for w in kw_cfg["keyword"].split()):
                category = kw_cfg["category"]
                break
        deal = ppomppu_candidate_to_deal(c, category, next_id)
        if not is_duplicate(deal, deals + new_deals):
            new_deals.append(deal)
            next_id += 1

    # ── 병합 및 한도 적용 ──
    all_deals = deals + new_deals
    all_deals.sort(key=lambda d: (d.get("originalPrice", 0) - d.get("salePrice", 0)) / max(d.get("originalPrice", 1), 1), reverse=True)
    all_deals = all_deals[:max_total]

    # ── ID 재정렬 (빈 번호 없이) ──
    for i, d in enumerate(all_deals, start=1):
        d["id"] = i

    with open(DEALS_PATH, "w", encoding="utf-8") as f:
        json.dump(all_deals, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*55}")
    print(f"✅ 기존 {len(deals)}개 | 신규 {len(new_deals)}개 추가 | 최종 {len(all_deals)}개 딜")
    print(f"{'='*55}\n")

    # ── 구독자 딜 알림 발송 ──
    test_alert = os.environ.get("SEND_TEST_ALERT", "").lower() == "true"
    if new_deals:
        print(f"\n📨 구독자 알림 발송 중...")
        send_deal_alerts(new_deals, resend_key)
    elif test_alert and all_deals:
        sample = all_deals[:3]
        print(f"\n🧪 테스트 알림 발송 중 (기존 딜 {len(sample)}개)...")
        send_deal_alerts(sample, resend_key)
    else:
        print("\n📭 신규 딜 없음 — 알림 발송 스킵")


if __name__ == "__main__":
    main()
