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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEALS_PATH  = os.path.join(ROOT, "data", "deals.json")
CONFIG_PATH = os.path.join(ROOT, "config", "search_config.json")

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


def search_naver_products(keyword: str, client_id: str, client_secret: str, display: int = 10) -> list[dict]:
    """
    네이버 쇼핑 검색 API
    - 가입: https://developers.naver.com/apps/#/register
    - 무료: 하루 25,000건
    - 반환: lprice(최저가), hprice(최고가), mallName, image, link, title
    """
    try:
        r = requests.get(
            NAVER_SHOP_URL,
            headers={
                "X-Naver-Client-Id":     client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={"query": keyword, "display": display, "sort": "asc"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("items", [])
        print(f"  ⚠️  네이버 API {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  ❌ 네이버 API 오류: {e}")
    return []


def naver_product_to_deal(p: dict, category: str, next_id: int, min_disc: int) -> dict | None:
    """네이버 쇼핑 API 상품 → deals.json 포맷"""
    title = re.sub(r"<[^>]+>", "", p.get("title", "")).strip()
    lp    = int(p.get("lprice") or 0)   # 최저가 (특가)
    hp    = int(p.get("hprice") or 0)   # 최고가 (정가로 사용)
    mall  = p.get("mallName", "네이버쇼핑")
    link  = p.get("link", "")
    image = p.get("image", "")

    if not lp or not hp or hp <= lp:
        return None

    disc = round((hp - lp) / hp * 100)
    if disc < min_disc:
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
        "originalPrice": hp,
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
    뽐뿌 RSS에서 테크 관련 핫딜 포스팅 수집.
    제목에서 가격 정보를 파싱해 deals 후보로 변환.
    """
    rss_cfg = config.get("ppomppu_rss", {})
    if not rss_cfg.get("enabled"):
        return []

    tech_kw = rss_cfg.get("tech_keywords", [])
    max_posts = rss_cfg.get("max_posts", 20)
    url = rss_cfg.get("url", "")

    print(f"\n📡 뽐뿌 RSS 파싱 중...")
    candidates = []

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TechDealKR/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read().decode("utf-8", errors="replace")

        root = ET.fromstring(xml_data)
        items = root.findall(".//item")[:max_posts]

        for item in items:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            desc  = (item.findtext("description") or "").strip()

            # 테크 키워드 포함 여부 확인
            if not any(kw in title for kw in tech_kw):
                continue

            # 가격 추출 (예: 79,000원 / 79000 패턴)
            prices = re.findall(r"[\d,]+(?=원)", title + " " + desc)
            prices = [int(p.replace(",", "")) for p in prices if int(p.replace(",", "")) > 1000]

            if len(prices) >= 2:
                orig, sale = max(prices), min(prices)
            elif len(prices) == 1:
                # 가격 1개만 있으면 원가 추정 불가 → 스킵
                continue
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
        print(f"  ❌ 뽐뿌 RSS 오류: {e}")

    print(f"  → 뽐뿌에서 {len(candidates)}개 테크 딜 감지")
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
        print(f"\n🛍️  네이버 쇼핑 검색 시작...")
        for kw_cfg in config["search_keywords"]:
            keyword  = kw_cfg["keyword"]
            category = kw_cfg["category"]
            products = search_naver_products(keyword, naver_id, naver_secret, display=5)
            for p in products:
                deal = naver_product_to_deal(p, category, next_id, min_disc)
                if deal and not is_duplicate(deal, deals + new_deals):
                    new_deals.append(deal)
                    next_id += 1
                    disc = round((deal["originalPrice"] - deal["salePrice"]) / deal["originalPrice"] * 100)
                    print(f"  ✅ [{disc}%][{deal['store']}] {deal['name'][:35]}")
            time.sleep(0.2)
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


if __name__ == "__main__":
    main()
