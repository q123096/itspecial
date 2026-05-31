"""
generate_deal_pages.py — 딜 상세 정적 HTML 페이지 + sitemap.xml 자동 생성
===========================================================================
GitHub Actions에서 affiliate-links 완료 후 자동 실행.

생성 결과:
  /deals/{id}.html  — 딜별 개별 URL (SEO 롱테일 키워드 크롤링)
  /sitemap.xml      — 메인 + 딜 전체 URL 목록

효과:
  "갤럭시 S25 자급제 특가" 같은 롱테일 키워드로 구글 자연 검색 유입
  딜 SNS 공유 시 딜별 OG 이미지/타이틀 적용
"""

import html
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEALS_PATH   = os.path.join(ROOT, "data", "deals.json")
DEALS_DIR    = os.path.join(ROOT, "deals")
SITEMAP_PATH = os.path.join(ROOT, "sitemap.xml")
SITE_URL     = "https://itspecial.co.kr"

CATEGORY_LABELS = {
    "smartphone": "스마트폰",
    "laptop":     "노트북",
    "tablet":     "태블릿",
    "audio":      "이어폰/헤드폰",
    "monitor":    "모니터",
    "gaming":     "게이밍",
    "wearable":   "스마트워치/웨어러블",
    "desktop":    "데스크탑/미니PC",
    "accessory":  "주변기기",
    "camera":     "카메라",
}


# ── 유틸 ─────────────────────────────────────────────────────────────
def fmt_price(n: int) -> str:
    try:
        return f"{int(n):,}원"
    except Exception:
        return "-"


def make_sparkline_svg(history: list, width: int = 300, height: int = 80) -> str:
    """가격 히스토리 → 인라인 SVG 스파크라인"""
    prices = [(h.get("lprice") or h.get("hprice") or 0) for h in history]
    prices = [p for p in prices if p > 0]
    if len(prices) < 2:
        return ""
    mn, mx = min(prices), max(prices)
    rng    = mx - mn or 1
    pts    = []
    for i, p in enumerate(prices):
        x = round(i / (len(prices) - 1) * width, 1)
        y = round(height - (p - mn) / rng * (height - 12) - 6, 1)
        pts.append(f"{x},{y}")
    trend = "#4ADE80" if prices[-1] <= prices[0] else "#F87171"
    lx, ly = pts[-1].split(",")
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="display:block">'
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{trend}" stroke-width="2.5"'
        f' stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{lx}" cy="{ly}" r="4" fill="{trend}"/>'
        f"</svg>"
    )


def make_schema(deal: dict) -> str:
    """Schema.org Product JSON-LD"""
    obj: dict = {
        "@context": "https://schema.org",
        "@type":    "Product",
        "name":     deal["name"],
        "offers": {
            "@type":          "Offer",
            "price":          deal["salePrice"],
            "priceCurrency":  "KRW",
            "availability":   "https://schema.org/InStock",
            "url":            deal.get("affiliateUrl") or deal.get("productUrl", ""),
            "priceValidUntil": (deal.get("expiresAt") or "")[:10],
            "seller": {"@type": "Organization", "name": deal.get("store", "")},
        },
    }
    img = deal.get("image", "")
    if img and "placehold" not in img:
        obj["image"] = img
    return json.dumps(obj, ensure_ascii=False)


# ── HTML 페이지 생성 ──────────────────────────────────────────────────
def make_deal_page(deal: dict) -> str:
    name      = html.escape(deal["name"])
    category  = deal.get("category", "")
    cat_label = html.escape(CATEGORY_LABELS.get(category, category))
    sale      = deal.get("salePrice", 0)
    orig      = deal.get("originalPrice", 0)
    disc      = round((orig - sale) / orig * 100) if orig > sale else 0
    buy_url   = html.escape(deal.get("affiliateUrl") or deal.get("productUrl") or "#")
    store     = html.escape(deal.get("store", ""))
    image     = deal.get("image", "")
    has_img   = bool(image and "placehold" not in image)
    tags      = deal.get("tags", [])
    deal_id   = deal["id"]
    savings   = orig - sale

    # 가격 히스토리 섹션
    hist_section = ""
    ph = deal.get("priceHistory") or []
    if len(ph) >= 2:
        svg = make_sparkline_svg(ph)
        valid_p = [(h.get("lprice") or h.get("hprice") or 0) for h in ph if (h.get("lprice") or h.get("hprice") or 0) > 0]
        hist_min = min(valid_p) if valid_p else 0
        hist_section = f"""
  <section class="dp-history">
    <h2>최근 가격 추이 ({len(ph)}일)</h2>
    {svg}
    {"<p class='dp-hist-min'>최근 최저가 <strong>" + fmt_price(hist_min) + "</strong></p>" if hist_min else ""}
  </section>"""

    # 태그
    tag_html = " ".join(
        f'<span class="dp-tag dp-tag-{"hot" if t=="핫딜" else "low"}">{t}</span>'
        for t in tags
    )

    og_desc   = f"{fmt_price(orig)} → {fmt_price(sale)} ({disc}% 할인). {cat_label} 최저가 특가 정보."
    schema_js = make_schema(deal)

    img_html = (
        f'<img class="dp-img" src="{html.escape(image)}" alt="{name}" loading="lazy">'
        if has_img else
        '<div class="dp-img-placeholder">📦</div>'
    )
    og_img_tag = (
        f'<meta property="og:image"       content="{html.escape(image)}">\n'
        f'  <meta name="twitter:image"       content="{html.escape(image)}">\n'
        if has_img else ""
    )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{name} {disc}% 할인 특가 — ITSpecial</title>
  <meta name="description" content="{html.escape(og_desc)}">
  <link rel="canonical" href="{SITE_URL}/deals/{deal_id}.html">

  <meta property="og:title"       content="{name} {disc}% 특가">
  <meta property="og:description" content="{html.escape(og_desc)}">
  <meta property="og:url"         content="{SITE_URL}/deals/{deal_id}.html">
  <meta property="og:type"        content="product">
  <meta property="og:site_name"   content="ITSpecial">
  {og_img_tag}
  <meta name="twitter:card"        content="summary_large_image">
  <meta name="twitter:title"       content="{name} {disc}% 특가">
  <meta name="twitter:description" content="{html.escape(og_desc)}">

  <script type="application/ld+json">{schema_js}</script>

  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚡</text></svg>">
  <link rel="stylesheet" href="../css/style.css">
  <style>
    body{{max-width:680px;margin:0 auto;padding:0 16px 48px;font-family:'Noto Sans KR','Apple SD Gothic Neo',sans-serif;color:#1A1A2E}}
    .dp-back{{display:inline-flex;align-items:center;gap:6px;color:#6C757D;text-decoration:none;font-size:14px;padding:16px 0 12px;transition:color .15s}}
    .dp-back:hover{{color:#5B6BF8}}
    .dp-img{{width:100%;max-height:320px;object-fit:contain;border-radius:14px;background:#f8f9fa;margin-bottom:16px}}
    .dp-img-placeholder{{height:180px;display:flex;align-items:center;justify-content:center;font-size:56px;background:#f8f9fa;border-radius:14px;margin-bottom:16px}}
    .dp-tags{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}}
    .dp-tag{{padding:3px 10px;border-radius:20px;font-size:12px;font-weight:700;letter-spacing:-.3px}}
    .dp-tag-hot{{background:#FF6B35;color:#fff}}
    .dp-tag-low{{background:#d1fae5;color:#065f46}}
    h1{{font-size:clamp(15px,4vw,21px);font-weight:700;line-height:1.45;margin:0 0 16px}}
    .dp-price-box{{background:#f8f9fa;border-radius:14px;padding:20px 20px 16px;margin-bottom:20px}}
    .dp-orig{{font-size:14px;color:#adb5bd;text-decoration:line-through;margin-bottom:2px}}
    .dp-sale{{font-size:34px;font-weight:900;color:#1A1A2E;margin-bottom:6px;letter-spacing:-1px}}
    .dp-disc{{display:inline-block;background:#FF6B35;color:#fff;border-radius:6px;padding:4px 10px;font-size:14px;font-weight:700}}
    .dp-savings{{font-size:13px;color:#5B6BF8;margin-top:10px;font-weight:600}}
    .dp-store{{font-size:13px;color:#6C757D;margin-top:3px}}
    .dp-buy{{display:block;width:100%;box-sizing:border-box;background:#5B6BF8;color:#fff;border:none;border-radius:14px;padding:17px;font-size:17px;font-weight:700;text-align:center;text-decoration:none;margin-bottom:10px;letter-spacing:-.3px;transition:background .15s}}
    .dp-buy:hover{{background:#4A5AE8}}
    .dp-notice{{font-size:12px;color:#adb5bd;text-align:center;margin-bottom:24px}}
    .dp-history{{background:#f8f9fa;border-radius:14px;padding:18px;margin-bottom:20px}}
    .dp-history h2{{font-size:14px;font-weight:700;margin:0 0 14px;color:#495057}}
    .dp-hist-min{{font-size:13px;color:#6C757D;margin-top:10px}}
    .dp-cat-link{{display:inline-flex;align-items:center;gap:6px;color:#5B6BF8;text-decoration:none;font-size:14px;font-weight:600;border:1.5px solid #5B6BF8;border-radius:10px;padding:10px 18px;transition:all .15s}}
    .dp-cat-link:hover{{background:#5B6BF8;color:#fff}}
  </style>
</head>
<body>
  <a class="dp-back" href="/">
    ← ITSpecial 전체 특가
  </a>

  {img_html}

  <div class="dp-tags">{tag_html}</div>
  <h1>{name}</h1>

  <div class="dp-price-box">
    <div class="dp-orig">{fmt_price(orig)}</div>
    <div class="dp-sale">{fmt_price(sale)}</div>
    <span class="dp-disc">{disc}% 할인</span>
    <div class="dp-savings">💰 {fmt_price(savings)} 절약</div>
    <div class="dp-store">🏪 {store}</div>
  </div>

  <a class="dp-buy" href="{buy_url}" target="_blank" rel="noopener noreferrer sponsored">
    지금 구매하기 →
  </a>
  <p class="dp-notice">⚠️ 가격은 실시간 변동됩니다. 구매 전 반드시 확인하세요.</p>

  {hist_section}

  <a class="dp-cat-link" href="/?cat={category}">
    🔍 {cat_label} 특가 더보기
  </a>
</body>
</html>"""


# ── sitemap.xml ───────────────────────────────────────────────────────
def generate_sitemap(deals: list) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts = [
        f"  <url>\n"
        f"    <loc>{SITE_URL}/</loc>\n"
        f"    <lastmod>{today}</lastmod>\n"
        f"    <changefreq>daily</changefreq>\n"
        f"    <priority>1.0</priority>\n"
        f"  </url>"
    ]
    for deal in deals:
        lastmod = (deal.get("addedAt") or today)[:10]
        parts.append(
            f"  <url>\n"
            f"    <loc>{SITE_URL}/deals/{deal['id']}.html</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            f"    <changefreq>daily</changefreq>\n"
            f"    <priority>0.8</priority>\n"
            f"  </url>"
        )
    body = "\n".join(parts)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n"
        "</urlset>\n"
    )


# ── Main ──────────────────────────────────────────────────────────────
def main() -> None:
    with open(DEALS_PATH, encoding="utf-8") as f:
        deals: list = json.load(f)

    os.makedirs(DEALS_DIR, exist_ok=True)

    generated = 0
    skipped   = 0
    for deal in deals:
        if not deal.get("salePrice") or not deal.get("originalPrice"):
            skipped += 1
            continue
        page_path = os.path.join(DEALS_DIR, f"{deal['id']}.html")
        with open(page_path, "w", encoding="utf-8") as f:
            f.write(make_deal_page(deal))
        generated += 1

    print(f"✅ 딜 상세 페이지 {generated}개 생성 → /deals/  (스킵: {skipped}개)")

    # sitemap.xml 갱신
    sitemap = generate_sitemap(deals)
    with open(SITEMAP_PATH, "w", encoding="utf-8") as f:
        f.write(sitemap)
    print(f"✅ sitemap.xml 갱신 → {len(deals) + 1}개 URL (메인 1 + 딜 {len(deals)})")


if __name__ == "__main__":
    main()
