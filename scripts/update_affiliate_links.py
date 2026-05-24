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
def get_11st_affiliate_link(product_url: str, api_key: str) -> str:
    """
    11번가 상품 URL → 제휴 링크 변환
    11번가 오픈 API를 통한 링크 생성
    """
    # 11번가는 URL에 appKey 파라미터 추가 방식
    try:
        parsed = urllib.parse.urlparse(product_url)
        product_id = ""
        # /products/XXXXXXX 형태에서 ID 추출
        parts = parsed.path.split("/")
        for i, p in enumerate(parts):
            if p in ("products", "product") and i + 1 < len(parts):
                product_id = parts[i + 1]
                break

        if product_id:
            # 11번가 제휴 링크 포맷
            return f"https://www.11st.co.kr/products/{product_id}?trTypeCd=PW&trCtgrNo=585021&appKey={api_key}"
    except Exception as e:
        print(f"  ❌ 11번가 링크 생성 예외: {e}")
    return ""


# ─── G마켓/옥션 (Linkprice 정식 연동 전 UTM 추적) ────────────────
STORE_AFFILIATE_PARAM = {
    "gmarket.co.kr": "partner=itspecial&trackingCode=itspecial",
    "auction.co.kr": "partner=itspecial&trackingCode=itspecial",
}

def get_generic_affiliate_link(product_url: str, store: str) -> str:
    """
    G마켓, 옥션 — UTM 파라미터 기반 추적 (Linkprice 정식 연동 전 임시)
    실제 수수료 발생은 Linkprice 연동 후 가능
    """
    for domain, param in STORE_AFFILIATE_PARAM.items():
        if domain in product_url:
            sep = "&" if "?" in product_url else "?"
            return product_url + sep + param
    return ""


# ─── 메인 로직 ────────────────────────────────────────────────────
def main():
    coupang_key    = os.environ.get("COUPANG_ACCESS_KEY", "")
    coupang_secret = os.environ.get("COUPANG_SECRET_KEY", "")
    st11_key       = os.environ.get("ST11_API_KEY", "")

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

        # 쿠팡
        if "coupang.com" in product_url and coupang_key:
            affiliate_url = get_coupang_affiliate_link(product_url, coupang_key, coupang_secret)

        # 11번가
        elif "11st.co.kr" in product_url and st11_key:
            affiliate_url = get_11st_affiliate_link(product_url, st11_key)

        # G마켓 / 옥션
        elif any(d in product_url for d in STORE_UTM_MAP):
            affiliate_url = get_generic_affiliate_link(product_url, store)

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
