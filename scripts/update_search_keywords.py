"""
update_search_keywords.py — 최신 기기 자동 트래킹
====================================================
Naver News API + GSMArena RSS에서 신규 출시 테크 기기를 탐지하여
config/search_config.json에 새 검색 키워드를 자동 추가합니다.

실행 주기: 주 1회 (GitHub Actions — 일요일)
결과: search_config.json 업데이트 → 다음 discover_deals 실행 시 자동 반영
"""

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "search_config.json")

NAVER_CLIENT_ID     = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

# ── 카테고리 감지 패턴 (제품명 → 카테고리) ─────────────────────────
CATEGORY_PATTERNS = {
    "smartphone": [
        "갤럭시 S", "갤럭시 Z", "갤럭시 A", "아이폰", "iPhone",
        "Galaxy S", "Galaxy Z", "Galaxy A", "Pixel",
        "샤오미", "원플러스", "OnePlus", "OPPO", "vivo",
    ],
    "laptop": [
        "맥북", "MacBook", "그램", "갤럭시북", "GalaxyBook",
        "ThinkPad", "씽크패드", "레노버 요가", "Lenovo Yoga",
        "ASUS Vivobook", "ASUS Zenbook", "HP Spectre", "HP Envy",
        "Surface Laptop", "서피스",
    ],
    "tablet": [
        "아이패드", "iPad", "갤럭시탭", "Galaxy Tab", "MatePad", "Tab S",
    ],
    "audio": [
        "에어팟", "AirPods", "갤럭시 버즈", "Galaxy Buds",
        "WH-", "WF-", "QuietComfort", "Momentum", "FreeBuds",
        "노이즈캔슬링 이어폰", "무선 헤드폰",
    ],
    "monitor": [
        "오디세이 모니터", "울트라기어", "UltraGear", "Odyssey",
        "ProArt", "OLED 모니터",
    ],
    "wearable": [
        "갤럭시 워치", "Galaxy Watch", "애플워치", "Apple Watch",
        "Pixel Watch", "Garmin", "Fitbit", "스마트워치",
    ],
    "camera": [
        "미러리스", "Alpha", "EOS", "OM System", "GH", "Lumix",
        "소니 카메라", "캐논 카메라",
    ],
    "gaming": [
        "닌텐도 스위치", "PlayStation", "Steam Deck", "Xbox",
        "ROG Ally", "MSI Claw",
    ],
}

# 한국 시장에 주요 관심 브랜드 (GSMArena 필터용)
KO_BRANDS = [
    "Samsung", "Apple", "Galaxy", "iPhone", "Google Pixel",
    "LG", "Sony", "Xiaomi", "OnePlus", "Realme",
]

# 추출할 최대 신규 키워드 수 (1회 실행당)
MAX_NEW_KEYWORDS = 10


# ── 텍스트 정제 ──────────────────────────────────────────────────
def clean_text(text: str) -> str:
    """HTML 태그·특수문자 제거, 공백 정리"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[「」『』【】《》<>'\"'""…•]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def detect_category(text: str) -> str | None:
    """제품명 텍스트에서 카테고리 유추"""
    for cat, patterns in CATEGORY_PATTERNS.items():
        for p in patterns:
            if p.lower() in text.lower():
                return cat
    return None


# ── 네이버 뉴스 API ──────────────────────────────────────────────
NAVER_NEWS_QUERIES = [
    ("스마트폰 신제품 출시 2026",  "smartphone"),
    ("노트북 신제품 출시 2026",    "laptop"),
    ("이어폰 헤드폰 신제품 2026",  "audio"),
    ("태블릿 신제품 출시 2026",    "tablet"),
    ("스마트워치 신제품 2026",     "wearable"),
]

# 제품명 추출 정규식 패턴들
PRODUCT_NAME_RE = [
    # "삼성 갤럭시 S26 Ultra 출시" → "삼성 갤럭시 S26 Ultra"
    re.compile(r"((?:삼성|애플|소니|LG|레노버|아수스|HP|델)\s+[\w가-힣\s\-\.]+?)\s+(?:출시|발표|공개|론칭|예약)", re.IGNORECASE),
    # "갤럭시 S26 자급제" 형태
    re.compile(r"(갤럭시\s+[A-Z]\d+\s*(?:Ultra|Plus|FE|Lite|자급제)?)", re.IGNORECASE),
    # "아이폰 18" 형태
    re.compile(r"(아이폰\s+\d+\s*(?:Pro|Plus|Max|Mini)?)", re.IGNORECASE),
    # "맥북 에어 M5" 형태
    re.compile(r"(맥북\s+(?:에어|프로)\s*M\d+)", re.IGNORECASE),
    # "갤럭시 버즈 4" 형태
    re.compile(r"(갤럭시\s+(?:버즈|워치|탭)\s+[\w\s]+?)(?=\s|$|출시|발표)", re.IGNORECASE),
]


def extract_product_names_from_text(text: str, hint_cat: str) -> list[dict]:
    """뉴스 텍스트에서 제품명 후보 추출"""
    results = []
    for pattern in PRODUCT_NAME_RE:
        for m in pattern.finditer(text):
            name = m.group(1).strip()
            name = re.sub(r"\s+", " ", name)
            if 3 <= len(name) <= 30:
                cat = detect_category(name) or hint_cat
                results.append({"keyword": name, "category": cat})
    return results


def get_naver_news_keywords() -> list[dict]:
    """네이버 뉴스 API → 신제품 출시 기사 → 제품명 추출"""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("  [네이버 뉴스] API 키 미설정 — 스킵")
        return []

    headers = {
        "X-Naver-Client-Id":     NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    results = []
    for query, hint_cat in NAVER_NEWS_QUERIES:
        try:
            r = requests.get(
                "https://openapi.naver.com/v1/search/news.json",
                headers=headers,
                params={"query": query, "display": 10, "sort": "date"},
                timeout=8,
            )
            if not r.ok:
                print(f"  [뉴스 API] {r.status_code}: {query}")
                continue

            for item in r.json().get("items", []):
                text = clean_text(item.get("title", "")) + " " + clean_text(item.get("description", ""))
                results.extend(extract_product_names_from_text(text, hint_cat))

            time.sleep(0.3)

        except Exception as e:
            print(f"  [네이버 뉴스 오류] {query}: {e}")

    print(f"  → 뉴스에서 {len(results)}개 제품명 후보 추출")
    return results


# ── GSMArena RSS ─────────────────────────────────────────────────
GSMARENA_RSS = "https://www.gsmarena.com/rss-news-reviews.php3"
GSMARENA_TRIGGER = ["announced", "unveiled", "launched", "goes official", "specs revealed"]

# 모델명 → 한국어 검색어 간단 변환
KO_TRANS = {
    "Samsung Galaxy": "갤럭시",
    "Galaxy":         "갤럭시",
    "Apple iPhone":   "아이폰",
    "iPhone":         "아이폰",
    "Apple Watch":    "애플워치",
    "AirPods":        "에어팟",
    "iPad":           "아이패드",
    "MacBook":        "맥북",
    "Galaxy Watch":   "갤럭시 워치",
    "Galaxy Tab":     "갤럭시탭",
    "Galaxy Buds":    "갤럭시 버즈",
}


def to_korean_keyword(name: str) -> str:
    """영문 모델명 → 한국어 검색어 (부분 변환)"""
    for en, ko in KO_TRANS.items():
        name = name.replace(en, ko)
    # 자급제 추가 (스마트폰 계열)
    if any(w in name for w in ["아이폰", "갤럭시 S", "갤럭시 Z", "갤럭시 A"]):
        if "자급제" not in name:
            name = name.strip() + " 자급제"
    return re.sub(r"\s+", " ", name).strip()


def get_gsmarena_keywords() -> list[dict]:
    """GSMArena RSS → 신규 기기 출시 뉴스 → 한국어 키워드 추출"""
    try:
        r = requests.get(
            GSMARENA_RSS,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ITSpecialBot/1.0)"},
            timeout=15,
        )
        if not r.ok:
            print(f"  [GSMArena] HTTP {r.status_code}")
            return []

        root  = ET.fromstring(r.content)
        items = root.findall(".//item")
        results = []

        for item in items:
            title = (item.findtext("title") or "").strip()

            # 출시/발표 관련 기사만
            if not any(t in title.lower() for t in GSMARENA_TRIGGER):
                continue

            # 한국 관심 브랜드만
            if not any(b.lower() in title.lower() for b in KO_BRANDS):
                continue

            # 제품명 추출: "Samsung Galaxy S26 Ultra announced" → "Samsung Galaxy S26 Ultra"
            name_raw = re.split(
                r"\s+(?:announced|unveiled|launched|goes official|specs revealed)",
                title, maxsplit=1, flags=re.IGNORECASE
            )[0].strip()

            if len(name_raw) < 4 or len(name_raw) > 50:
                continue

            kw_ko = to_korean_keyword(name_raw)
            cat   = detect_category(name_raw) or detect_category(kw_ko) or "smartphone"

            results.append({
                "keyword":  kw_ko[:30],
                "category": cat,
                "source":   "gsmarena",
            })

        print(f"  → GSMArena에서 {len(results)}개 기기 감지")
        return results

    except Exception as e:
        print(f"  [GSMArena 오류] {e}")
        return []


# ── config.json 업데이트 ─────────────────────────────────────────
def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_existing_keywords(config: dict) -> set[str]:
    """현재 config에 있는 모든 키워드 set (소문자 정규화)"""
    return {
        re.sub(r"\s+", " ", kw["keyword"]).strip().lower()
        for kw in config.get("search_keywords", [])
        if "keyword" in kw
    }


def add_new_keywords(config: dict, candidates: list[dict], existing: set[str]) -> list[str]:
    """
    중복 제거 후 새 키워드를 해당 카테고리 그룹 끝에 삽입.
    _auto:true 플래그를 달아 자동 추가 출처 구분.
    """
    keywords_list = config.get("search_keywords", [])

    # 카테고리별 마지막 항목 인덱스 매핑
    cat_last_idx: dict[str, int] = {}
    for i, entry in enumerate(keywords_list):
        if "keyword" in entry and "category" in entry:
            cat_last_idx[entry["category"]] = i

    # 삽입 위치 오프셋 추적 (삽입할 때마다 인덱스 밀림)
    insert_offset: dict[str, int] = {}
    added: list[str] = []

    for c in candidates:
        if len(added) >= MAX_NEW_KEYWORDS:
            break

        kw  = re.sub(r"\s+", " ", c["keyword"]).strip()
        cat = c["category"]
        src = c.get("source", "auto")

        normalized = kw.lower()
        if not kw or len(kw) < 4 or normalized in existing:
            continue

        existing.add(normalized)

        new_entry = {
            "keyword":  kw,
            "category": cat,
            "priority": 3,
            "sort":     "date",   # 최신 등록순 — 신제품 탐색에 적합
            "_auto":    True,
            "_source":  src,
            "_added":   datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }

        if cat in cat_last_idx:
            base_idx  = cat_last_idx[cat]
            offset    = insert_offset.get(cat, 0)
            insert_at = base_idx + 1 + offset
            keywords_list.insert(insert_at, new_entry)
            insert_offset[cat] = offset + 1
            # 이후 카테고리의 인덱스도 밀어줌
            for k in list(cat_last_idx.keys()):
                if cat_last_idx[k] >= insert_at:
                    cat_last_idx[k] += 1
            cat_last_idx[cat] = insert_at
        else:
            # 해당 카테고리 섹션이 없으면 맨 뒤에 추가
            keywords_list.append(new_entry)
            cat_last_idx[cat] = len(keywords_list) - 1

        added.append(kw)
        print(f"  ✅ [{src}][{cat}] {kw}")

    config["search_keywords"] = keywords_list
    return added


# ── 후보 정제 및 중복 제거 ────────────────────────────────────────
def deduplicate(candidates: list[dict]) -> list[dict]:
    """소스 중복 제거 (같은 키워드 정규화 기준)"""
    seen  = set()
    dedup = []
    for c in candidates:
        key = re.sub(r"\s+", " ", c["keyword"]).strip().lower()
        if key and len(key) >= 4 and key not in seen:
            seen.add(key)
            dedup.append(c)
    return dedup


# ── Main ─────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 55)
    print("⚡ 최신 기기 키워드 자동 트래킹 시작")
    print("=" * 55)

    config   = load_config()
    existing = get_existing_keywords(config)
    print(f"기존 키워드: {len(existing)}개\n")

    # ① 네이버 뉴스
    print("🔍 네이버 뉴스 파싱 중...")
    news_cands = get_naver_news_keywords()

    # ② GSMArena RSS
    print("\n🔍 GSMArena RSS 파싱 중...")
    gsm_cands = get_gsmarena_keywords()

    # 통합 + 중복 제거
    all_cands = deduplicate(
        [{"source": "naver_news", **c} for c in news_cands]
        + gsm_cands
    )

    # 기존 키워드와 교차 필터
    new_cands = [c for c in all_cands if c["keyword"].lower() not in existing]
    print(f"\n신규 후보: {len(new_cands)}개 (기존 제외)")

    if not new_cands:
        print("\n[완료] 새 키워드 없음 — 변경 없음")
        return

    added = add_new_keywords(config, new_cands, existing)

    if added:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print(f"\n✅ {len(added)}개 키워드 추가 완료")
        print(f"   → {', '.join(added)}")
    else:
        print("\n[완료] 추가된 키워드 없음 (모두 중복 또는 짧음)")


if __name__ == "__main__":
    main()
