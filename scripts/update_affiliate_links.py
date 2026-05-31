"""
쿠팡 파트너스 + 11번가 제휴링크 자동 생성 스크립트
GitHub Actions에서 하루 3회 자동 실행됨

환경변수 (GitHub Secrets에 저장):
  COUPANG_ACCESS_KEY  — 쿠팡 파트너스 오픈 API 액세스 키
  COUPANG_SECRET_KEY  — 쿠팡 파트너스 오픈 API 시크릿 키
  ST11_API_KEY        — 11번가 오픈 API 키 (선택)
"""

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("requests 패키지가 없습니다. pip install requests 실행 후 다시 시도하세요.")
    sys.exit(1)

# ─── 쿠팡 파트너스 API ───────────────────────────────────────────
COUPANG_API_HOST = "https://api-gateway.coupang.com"
COUPANG_LINK_PATH = "/v2/providers/affiliate_open_api/apis/openapi/products/links"


def _coupang_hmac(method: str, path: str, query: str, secret_key: str, access_key: str) -> tuple[str, str]:
    """HMAC-SHA256 인증 헤더 생성 (쿠팡 파트너스 오픈 API 스펙)"""
    dt = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    message = dt + method + path + query
    signature = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    auth = f"CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={dt}, signature={signature}"
    return auth, dt


def get_coupang_affiliate_link(product_url: str, access_key: str, secret_key: str) -> str:
    """
    쿠팡 상품 URL → 파트너스 단축 링크 자동 변환
    예) https://www.coupang.com/vp/products/123 → https://link.coupang.com/a/XXXXXX
    """
    encoded = urllib.parse.quote(product_url, safe="")
    query = f"coupangUrls={encoded}"
    auth, _ = _coupang_hmac("GET", COUPANG_LINK_PATH, query, secret_key, access_key)

    url = f"{COUPANG_API_HOST}{COUPANG_LINK_PATH}?{query}"
    try:
        resp = requests.get(url, headers={"Authorization": auth}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            links = data.get("data", {}).get("productLinks", [])
            if links:
                return links[0].get("shortenUrl", "")
        else:
            print(f"  ⚠️  쿠팡 API 오류 {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"  ❌ 쿠팡 API 예외: {e}")
    return ""


# ─── 11번가 API ────────────────────────────────────────────────────
def _extract_11st_prd_no(product_url: str) -> str:
    """
    11번가 URL에서 상품 번호(prdNo) 추출.
    지원 형식:
      - /products/XXXXXX
      - Gateway.tmall?prdNo=XXXXXX  (Naver Shopping 경유 링크)
    """
    try:
        parsed = urllib.parse.urlparse(product_url)
        # 1) Query param: ?prdNo=XXXXXX
        params = urllib.parse.parse_qs(parsed.query)
        if "prdNo" in params:
            return params["prdNo"][0]
        # 2) Path: /products/XXXXXX
        parts = parsed.path.rstrip("/").split("/")
        for i, p in enumerate(parts):
            if p in ("products", "product") and i + 1 < len(parts):
                pid = parts[i + 1].split("?")[0]
                if pid.isdigit():
                    return pid
    except Exception:
        pass
    return ""


def get_11st_affiliate_link(product_url: str, api_key: str) -> str:
    """11번가 상품 URL → 제휴 링크 (appKey 추적 파라미터 추가)"""
    prd_no = _extract_11st_prd_no(product_url)
    if prd_no:
        return (f"https://www.11st.co.kr/products/{prd_no}"
                f"?trTypeCd=PW&trCtgrNo=585021&appKey={api_key}")
    return ""


def search_11st_by_keyword(keyword: str, api_key: str, max_results: int = 3) -> list[dict]:
    """
    11번가 오픈 API로 키워드 검색 → 상품 목록 반환.
    네이버/기타 소스 딜을 11번가 제휴링크로 교차 연결할 때 사용.
    API: https://openapi.11st.co.kr/openapi/OpenApiService.tmall
    """
    try:
        resp = requests.get(
            "https://openapi.11st.co.kr/openapi/OpenApiService.tmall",
            params={
                "method":  "getProductSearch",
                "appKey":  api_key,
                "keyword": keyword,
                "display": max_results,
                "format":  "json",
            },
            timeout=8,
        )
        if not resp.ok:
            return []
        data = resp.json()
        items = (data.get("ProductSearchResponse") or {}).get("Products") or {}
        return items.get("Product", []) if isinstance(items, dict) else []
    except Exception as e:
        print(f"    ⚠️  11번가 검색 오류: {e}")
        return []


def make_11st_affiliate_from_search(deal_name: str, api_key: str) -> str:
    """
    딜 이름으로 11번가 검색 → 가장 유사한 상품의 제휴링크 반환.
    네이버 쇼핑 딜 등 11번가 직링크가 없는 경우 교차 연결용.
    """
    # 너무 긴 이름은 핵심 키워드만 추출 (앞 20자)
    keyword = deal_name[:40].strip()
    products = search_11st_by_keyword(keyword, api_key, max_results=1)
    if not products:
        return ""
    prd = products[0]
    prd_no = str(prd.get("productId") or prd.get("prdNo") or "")
    if prd_no:
        return (f"https://www.11st.co.kr/products/{prd_no}"
                f"?trTypeCd=PW&trCtgrNo=585021&appKey={api_key}")
    return ""


# ─── Linkprice 제휴링크 (G마켓 · 옥션 · 추후 11번가) ─────────────
# 매체 코드(PID)는 GitHub Secret LINKPRICE_PID 에 저장
# Linkprice 대시보드 → 제휴 현황에서 승인된 광고주 코드 확인

# Linkprice 광고주 코드 매핑
# 승인된 쇼핑몰만 활성화 (미승인 = 주석 처리)
LINKPRICE_MERCHANTS: dict[str, str] = {
    "auction.co.kr": "auction",    # 옥션 — 승인 완료
    "gmarket.co.kr": "gmarket",    # G마켓 — 승인 완료
    # "11st.co.kr":  "11st",       # 11번가 — Linkprice 승인 후 주석 해제
}


def _to_direct_url(product_url: str) -> str:
    """
    Naver Shopping 경유 URL → 실제 쇼핑몰 직링크 변환.
    Linkprice는 실제 쇼핑몰 URL을 감싸야 정확한 추적 가능.

    지원 형식:
      link.auction.co.kr/gate/pcs?item-no=F481888804 → auction.co.kr/Item?itemno=F481888804
      link.gmarket.co.kr/gate/pcs?item-no=12345678   → item.gmarket.co.kr/Item?goodscode=12345678
    """
    try:
        parsed = urllib.parse.urlparse(product_url)
        params = urllib.parse.parse_qs(parsed.query)

        if "auction" in parsed.hostname:
            item_no = (params.get("item-no") or [""])[0]
            if item_no:
                return f"https://www.auction.co.kr/Item?itemno={item_no}"

        if "gmarket" in parsed.hostname:
            item_no = (params.get("item-no") or params.get("goodscode") or [""])[0]
            if item_no:
                return f"https://item.gmarket.co.kr/Item?goodscode={item_no}"
    except Exception:
        pass
    return product_url   # 변환 불가 시 원본 반환


def get_linkprice_link(product_url: str, pid: str) -> str:
    """
    상품 URL → Linkprice 제휴링크 생성.
    형식: https://click.linkprice.com/click.php?m={merchant}&a={pid}&l={encoded_url}
    """
    try:
        parsed = urllib.parse.urlparse(product_url)
        hostname = parsed.hostname or ""

        merchant_code = ""
        for domain, code in LINKPRICE_MERCHANTS.items():
            if domain in hostname:
                merchant_code = code
                break
        if not merchant_code:
            return ""

        direct_url = _to_direct_url(product_url)
        encoded    = urllib.parse.quote(direct_url, safe="")
        return f"https://click.linkprice.com/click.php?m={merchant_code}&a={pid}&l={encoded}"
    except Exception as e:
        print(f"    ⚠️  Linkprice 링크 생성 오류: {e}")
        return ""


# ─── 메인 로직 ────────────────────────────────────────────────────
def main():
    coupang_key    = os.environ.get("COUPANG_ACCESS_KEY", "")
    coupang_secret = os.environ.get("COUPANG_SECRET_KEY", "")
    st11_key       = os.environ.get("ST11_API_KEY", "")
    linkprice_pid  = os.environ.get("LINKPRICE_PID", "")

    if not coupang_key or not coupang_secret:
        print("⚠️  COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY 환경변수가 없습니다.")
        print("   GitHub Secrets에 추가하거나 로컬에서 직접 설정하세요.\n")
        print("   로컬 테스트: $env:COUPANG_ACCESS_KEY='키'; $env:COUPANG_SECRET_KEY='시크릿'")

    deals_path = os.path.join(os.path.dirname(__file__), "..", "data", "deals.json")
    with open(deals_path, encoding="utf-8") as f:
        deals = json.load(f)

    print(f"\n📦 총 {len(deals)}개 딜 처리 시작...\n")
    updated = 0
    skipped = 0

    for deal in deals:
        name = deal.get("name", "")
        store = deal.get("store", "")
        product_url = deal.get("productUrl", "")
        existing = deal.get("affiliateUrl", "").strip()

        if existing:
            print(f"  ⏭️  [{store}] {name[:30]} — 이미 설정됨, 스킵")
            skipped += 1
            continue

        if not product_url:
            print(f"  ⚠️  [{store}] {name[:30]} — productUrl 없음, 스킵")
            continue

        print(f"  🔄 [{store}] {name[:30]}...", end=" ")
        affiliate_url = ""

        # ── 쿠팡 직링크 ──────────────────────────────────────────────
        if "coupang.com" in product_url and coupang_key:
            affiliate_url = get_coupang_affiliate_link(product_url, coupang_key, coupang_secret)

        # ── 11번가 직링크 ─────────────────────────────────────────────
        elif "11st.co.kr" in product_url and st11_key:
            affiliate_url = get_11st_affiliate_link(product_url, st11_key)

        # ── 네이버 쇼핑 딜 → 11번가 교차 연결 ───────────────────────
        # 네이버 API에서 가져온 딜은 개별 쇼핑몰 URL이라 직접 제휴 불가.
        # 11번가 검색 API로 동일 상품을 찾아 11번가 제휴링크로 대체.
        elif st11_key and store in ("네이버", "네이버쇼핑") and name:
            print(f"\n      → 11번가 교차 검색 중...", end=" ")
            affiliate_url = make_11st_affiliate_from_search(name, st11_key)

        # ── Linkprice: G마켓 · 옥션 (승인 완료) ─────────────────────
        elif linkprice_pid and any(d in product_url for d in LINKPRICE_MERCHANTS):
            affiliate_url = get_linkprice_link(product_url, linkprice_pid)

        if affiliate_url:
            deal["affiliateUrl"] = affiliate_url
            print(f"✅ {affiliate_url}")
            updated += 1
        else:
            print(f"❌ 링크 생성 실패 (API 키 확인 필요)")

        time.sleep(0.3)  # API 속도 제한 방지

    # 결과 저장
    with open(deals_path, "w", encoding="utf-8") as f:
        json.dump(deals, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✅ 완료: {updated}개 신규 생성 | {skipped}개 스킵 | 총 {len(deals)}개")
    print(f"{'='*50}\n")

    if updated == 0 and not coupang_key:
        print("💡 COUPANG_ACCESS_KEY를 설정하면 쿠팡 딜 링크가 자동 생성됩니다.")
        print("   파트너스 가입: https://partners.coupang.com")


if __name__ == "__main__":
    main()
