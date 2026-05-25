"""
enrich_products.py — 제품 스펙 자동 보강
==========================================
deals.json의 각 딜을 Icecat → Naver Shopping 순으로 조회하여
핵심 스펙 한줄("6.2인치 · 256GB · 50MP")을 Supabase products 테이블에 저장.

- 이미 Supabase에 있는 제품은 스킵 (1회만 조회)
- 완본체(desktop) 카테고리는 스펙이 제각각이므로 Naver 폴백만 사용
"""

import json
import os
import re
import time
from datetime import datetime, timezone

import requests
from requests.auth import HTTPBasicAuth

# ── 환경변수 ────────────────────────────────────────────────────
SUPABASE_URL        = os.environ["SUPABASE_URL"]
SUPABASE_KEY        = os.environ["SUPABASE_SERVICE_KEY"]
ICECAT_USERNAME     = os.environ["ICECAT_USERNAME"]
ICECAT_API_KEY      = os.environ["ICECAT_API_KEY"]
NAVER_CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]

ICECAT_AUTH = HTTPBasicAuth(ICECAT_USERNAME, ICECAT_API_KEY)

SB_READ_HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
}
SB_WRITE_HEADERS = {
    **SB_READ_HEADERS,
    "Content-Type": "application/json",
    "Prefer":       "resolution=merge-duplicates",
}

# ── makeProductKey (JS 동일 로직) ────────────────────────────────
_COLOR_RE = re.compile(
    r"[\s,·]*(블랙|화이트|실버|그레이|블루|레드|핑크|퍼플|골드|그린|베이지|티타늄|"
    r"카키|네이비|코랄|민트|라벤더|크림|챠콜|미드나잇|스타라이트|아이보리|스카이블루|"
    r"옐로우?|오렌지|브라운|팬텀블랙|팬텀화이트|아이스블루|에버그린)(?=[\s,]|$)",
    re.IGNORECASE,
)
_PREFIX_RE = re.compile(
    r"^\s*\[?(쿠팡|11번가|G마켓|옥션|SSG닷컴?|네이버쇼핑?|롯데온|다나와|에누리)\]?\s*[-_]?\s*",
    re.IGNORECASE,
)

def make_product_key(name: str) -> str:
    name = _PREFIX_RE.sub("", name)
    name = _COLOR_RE.sub("", name)
    return re.sub(r"\s+", " ", name).strip()


# ── 불량 설명 필터 ───────────────────────────────────────────────
_BAD_RE = re.compile(
    r"security verification|보안 확인|접근할 수 있는 권한|서비스로 이동 중|"
    r"서비스 접속이 일시적|@@description|enable javascript|페이지를 찾을 수 없|"
    r"로그인이 필요|잠시만 기다려|please wait|access denied|error 4\d\d",
    re.IGNORECASE,
)

def is_bad(text: str) -> bool:
    return not text or len(text.strip()) < 10 or bool(_BAD_RE.search(text))


# ── 카테고리별 핵심 스펙 우선순위 ────────────────────────────────
SPEC_PRIORITY = {
    "smartphone": [
        "display diagonal", "화면 크기",
        "storage capacity", "내장 저장 용량",
        "rear camera resolution", "후면 카메라 해상도",
        "battery capacity", "배터리 용량",
        "operating system", "운영 체제",
    ],
    "laptop": [
        "display diagonal", "화면 크기",
        "processor", "프로세서",
        "ram", "메모리 용량",
        "ssd capacity", "스토리지 용량",
    ],
    "tablet": [
        "display diagonal", "화면 크기",
        "storage capacity", "저장 용량",
        "ram", "operating system",
    ],
    "audio": [
        "form factor", "헤드폰 유형",
        "noise cancelling", "노이즈 캔슬링",
        "battery life", "배터리 수명",
        "bluetooth version", "블루투스 버전",
    ],
    "monitor": [
        "display diagonal", "화면 크기",
        "native aspect ratio", "화면 비율",
        "maximum refresh rate", "주사율",
        "panel type", "패널 유형",
    ],
    "wearable": [
        "display diagonal", "화면 크기",
        "battery life", "배터리 수명",
        "operating system", "운영 체제",
    ],
    "camera": [
        "megapixels", "유효 픽셀",
        "optical zoom", "광학 줌",
        "video resolution", "동영상 해상도",
    ],
    "gaming": [
        "processor", "그래픽 카드",
        "ram", "display diagonal",
    ],
}


# ── Icecat ────────────────────────────────────────────────────────
def _extract_specs(product: dict, category: str) -> str | None:
    """Icecat 제품 JSON → 핵심 스펙 한줄 ("A · B · C")"""
    try:
        features: dict[str, str] = {}
        for grp in product.get("FeaturesGroups", []):
            for feat in grp.get("Features", []):
                raw = feat.get("Feature", {}).get("Name", "")
                name = (raw if isinstance(raw, str) else raw.get("Value", "")).strip()
                val  = (feat.get("Presentation_Value") or feat.get("Value", "")).strip()
                if name and val:
                    features[name.lower()] = val

        selected = []
        for key in SPEC_PRIORITY.get(category, []):
            if len(selected) >= 3:
                break
            for feat_key, val in features.items():
                if key in feat_key and val not in selected:
                    selected.append(val)
                    break

        # 부족하면 임의 feature 보충
        if len(selected) < 2:
            for val in list(features.values())[:6]:
                if val not in selected and len(selected) < 3:
                    selected.append(val)

        return " · ".join(selected) if selected else None
    except Exception as e:
        print(f"    [스펙 파싱 오류] {e}")
        return None


def fetch_icecat(name: str, category: str) -> str | None:
    # 완본체(desktop)는 Icecat 스킵 — 조립 제품이라 카탈로그 없음
    if category == "desktop":
        return None
    try:
        # 1) 검색
        r = requests.get(
            "https://icecat.us/search.html",
            params={"q": name, "lang": "ko", "format": "json", "limit": 3},
            auth=ICECAT_AUTH,
            timeout=12,
        )
        if not r.ok:
            print(f"    [Icecat] 검색 실패 HTTP {r.status_code}")
            return None

        body  = r.json()
        items = body if isinstance(body, list) else body.get("data", [])
        if not items:
            print("    [Icecat] 검색 결과 없음")
            return None

        prod_id = (
            items[0].get("product_id")
            or items[0].get("Prod_id")
            or items[0].get("id")
        )
        if not prod_id:
            return None

        # 2) 상세 조회
        r2 = requests.get(
            "https://icecat.us/api/full_live_icecat_index.php",
            params={"prod_id": prod_id, "lang": "ko", "output": "json"},
            auth=ICECAT_AUTH,
            timeout=15,
        )
        if not r2.ok:
            return None

        data    = r2.json()
        product = data.get("data", data)
        return _extract_specs(product, category)

    except Exception as e:
        print(f"    [Icecat 오류] {e}")
        return None


# ── Naver Shopping (폴백) ─────────────────────────────────────────
def fetch_naver(name: str) -> str | None:
    try:
        r = requests.get(
            "https://openapi.naver.com/v1/search/shop.json",
            params={"query": name, "display": 1},
            headers={
                "X-Naver-Client-Id":     NAVER_CLIENT_ID,
                "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
            },
            timeout=8,
        )
        if not r.ok:
            return None
        items = r.json().get("items", [])
        if not items:
            return None
        item  = items[0]
        parts = [
            p for p in [
                item.get("brand") or item.get("maker"),
                item.get("category3") or item.get("category4"),
            ]
            if p
        ]
        return " · ".join(parts) if parts else None
    except Exception as e:
        print(f"    [Naver 오류] {e}")
        return None


# ── Supabase ──────────────────────────────────────────────────────
def load_existing_keys() -> set[str]:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/products?select=key",
        headers=SB_READ_HEADERS,
        timeout=10,
    )
    return {row["key"] for row in r.json()} if r.ok else set()


def save_to_supabase(key: str, description: str) -> bool:
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/products",
        headers=SB_WRITE_HEADERS,
        json={
            "key":         key,
            "description": description,
            "fetched_at":  datetime.now(timezone.utc).isoformat(),
        },
        timeout=10,
    )
    return r.ok


# ── Main ─────────────────────────────────────────────────────────
def main() -> None:
    with open("data/deals.json", encoding="utf-8") as f:
        deals = json.load(f)
    print(f"[시작] 딜 {len(deals)}개 로드")

    existing = load_existing_keys()
    print(f"[Supabase] 기존 제품 {len(existing)}개")

    seen: set[str] = set()
    to_do: list[dict] = []
    for deal in deals:
        key = make_product_key(deal.get("name", ""))
        if not key or key in existing or key in seen:
            continue
        seen.add(key)
        to_do.append({
            "key":      key,
            "name":     deal["name"],
            "category": deal.get("category", ""),
        })

    print(f"[처리 대상] {len(to_do)}개 (스펙 없음)\n")

    success = 0
    for i, item in enumerate(to_do):
        key, name, cat = item["key"], item["name"], item["category"]
        print(f"[{i+1}/{len(to_do)}] {key}")

        # 1순위: Icecat
        desc = fetch_icecat(name, cat)
        src  = "Icecat"

        # 2순위: Naver Shopping
        if not desc or is_bad(desc):
            desc = fetch_naver(name)
            src  = "Naver"

        if desc and not is_bad(desc):
            if save_to_supabase(key, desc):
                success += 1
                print(f"    ✅ [{src}] {desc}")
            else:
                print(f"    ❌ Supabase 저장 실패")
        else:
            print(f"    ⚠️  유효한 스펙 없음 — 스킵")

        time.sleep(0.8)   # API rate limit 배려

    print(f"\n[완료] {success}/{len(to_do)}개 Supabase 저장")


if __name__ == "__main__":
    main()
