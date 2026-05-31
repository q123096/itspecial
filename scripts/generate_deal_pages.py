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


def make_price_chart(deal: dict) -> tuple[str, str]:
    """
    Chart.js 가격 추이 풀 차트 생성.
    Returns (section_html, script_html) — script는 </body> 직전에 삽입.

    포함 요소:
      - lprice 라인 (파란색, 최저가)
      - hprice 라인 (회색 점선, 최고가 — 데이터 있을 때만)
      - 현재 특가 가격 수평 점선 (주황색)
      - X축: 날짜 / Y축: 만원 단위
    """
    ph = deal.get("priceHistory") or []
    if len(ph) < 2:
        return "", ""

    dates    = [h.get("date", "")[:10] for h in ph]
    lprices  = [h.get("lprice") or 0 for h in ph]
    hprices  = [h.get("hprice") or 0 for h in ph]
    has_hp   = any(h > 0 for h in hprices)
    sale     = deal.get("salePrice", 0)
    deal_id  = deal["id"]

    valid_l  = [p for p in lprices if p > 0]
    hist_min = min(valid_l) if valid_l else 0
    hist_max = max(valid_l) if valid_l else 0

    # ── HTML 섹션 ────────────────────────────────────────────────
    section = (
        '\n  <section class="dp-history">'
        '\n    <h2>가격 추이 (' + str(len(ph)) + '일)</h2>'
        '\n    <div class="dp-chart-wrap">'
        '\n      <canvas id="pc' + str(deal_id) + '" height="220"></canvas>'
        '\n    </div>'
        '\n    <div class="dp-chart-meta">'
        + (('\n      <span class="dp-cm-low">최저 <strong>' + fmt_price(hist_min) + '</strong></span>') if hist_min else "")
        + (('\n      <span class="dp-cm-high">최고 <strong>' + fmt_price(hist_max) + '</strong></span>') if hist_max else "")
        + (('\n      <span class="dp-cm-sale">현재특가 <strong>' + fmt_price(sale) + '</strong></span>') if sale else "")
        + '\n    </div>'
        '\n  </section>'
    )

    # ── Chart.js 초기화 스크립트 ─────────────────────────────────
    # Python f-string 대신 문자열 연결로 JS 중괄호 충돌 방지
    script = (
        '\n<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>'
        '\n<script>'
        '\n(function(){'
        '\n  var el=document.getElementById("pc' + str(deal_id) + '");'
        '\n  if(!el)return;'
        '\n  var D=' + json.dumps(dates) + ';'
        '\n  var L=' + json.dumps(lprices) + ';'
        '\n  var H=' + json.dumps(hprices) + ';'
        '\n  var hasH=' + ("true" if has_hp else "false") + ';'
        '\n  var sp=' + str(sale) + ';'
        '\n  var ds=[{label:"최저가",data:L,borderColor:"#5B6BF8",'
        'backgroundColor:"rgba(91,107,248,0.08)",tension:0.3,fill:true,'
        'pointRadius:4,pointHoverRadius:6,pointBackgroundColor:"#5B6BF8"}];'
        '\n  if(hasH)ds.push({label:"최고가",data:H,borderColor:"#adb5bd",'
        'borderDash:[5,5],tension:0.3,fill:false,pointRadius:2,pointHoverRadius:4});'
        # 현재 특가 수평선 플러그인
        '\n  var saleLine={id:"sl",afterDraw:function(c){'
        '\n    var ys=c.scales.y,xs=c.scales.x;'
        '\n    if(!ys||sp<=0)return;'
        '\n    var y=ys.getPixelForValue(sp),cx=c.ctx;'
        '\n    cx.save();cx.beginPath();cx.setLineDash([6,4]);'
        '\n    cx.strokeStyle="#FF6B35";cx.lineWidth=1.5;'
        '\n    cx.moveTo(xs.left,y);cx.lineTo(xs.right,y);cx.stroke();'
        '\n    cx.fillStyle="#FF6B35";cx.font="bold 11px sans-serif";'
        '\n    cx.fillText("현재특가",xs.right-56,y-4);'
        '\n    cx.restore();'
        '\n  }};'
        '\n  new Chart(el,{'
        '\n    type:"line",'
        '\n    data:{labels:D,datasets:ds},'
        '\n    options:{'
        '\n      responsive:true,'
        '\n      interaction:{mode:"index",intersect:false},'
        '\n      plugins:{'
        '\n        legend:{display:hasH,position:"top",labels:{font:{size:12}}},'
        '\n        tooltip:{callbacks:{label:function(c){'
        '\n          if(!c.parsed.y)return null;'
        '\n          return c.dataset.label+": "+c.parsed.y.toLocaleString("ko-KR")+"원";'
        '\n        }}}'
        '\n      },'
        '\n      scales:{'
        '\n        x:{ticks:{font:{size:11},maxRotation:30,maxTicksLimit:7}},'
        '\n        y:{ticks:{callback:function(v){'
        '\n          return v>=10000?(v/10000).toFixed(1)+"만":v.toLocaleString("ko-KR");'
        '\n        },font:{size:11}}}'
        '\n      }'
        '\n    },'
        '\n    plugins:[saleLine]'
        '\n  });'
        '\n})();'
        '\n</script>'
    )

    return section, script


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

    # 가격 히스토리 — Chart.js 풀 차트
    hist_section, chart_script = make_price_chart(deal)

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
    .dp-chart-wrap{{position:relative;width:100%}}
    .dp-chart-meta{{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;font-size:12px}}
    .dp-cm-low{{color:#5B6BF8}}.dp-cm-high{{color:#6C757D}}.dp-cm-sale{{color:#FF6B35}}
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
{chart_script}
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
