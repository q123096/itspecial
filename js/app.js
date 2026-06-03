/* ===== TechDeal KR — Main App ===== */

// ── Kakao 공유 키 (kakao.com/developers → 내 애플리케이션 → JavaScript 키)
const KAKAO_JS_KEY = 'db4206611cd19ecfa9ae35fff67039d8';

const CATEGORIES = [
  { id: 'all',        label: '전체',        icon: '🏷️' },
  { id: 'lowest',     label: '역대최저',    icon: '📉' },
  { id: 'wish',       label: '찜 목록',     icon: '❤️' },
  { id: 'smartphone', label: '스마트폰',     icon: '📱' },
  { id: 'laptop',     label: '노트북',       icon: '💻' },
  { id: 'desktop',    label: '데스크탑/PC',  icon: '🖥️' },
  { id: 'tablet',     label: '태블릿',       icon: '📲' },
  { id: 'audio',      label: '이어폰/헤드폰', icon: '🎧' },
  { id: 'monitor',    label: '모니터',       icon: '📺' },
  { id: 'camera',     label: '카메라',       icon: '📷' },
  { id: 'gaming',     label: '게이밍',       icon: '🎮' },
  { id: 'wearable',   label: '웨어러블',     icon: '⌚' },
  { id: 'accessory',  label: '주변기기',     icon: '🖱️' },
];

const TAG_MAP = {
  '핫딜':     { cls: 'badge-hot',      icon: '🔥' },
  '역대최저':  { cls: 'badge-lowest',   icon: '📉' },
  '타임딜':   { cls: 'badge-timedeal', icon: '⏰' },
  '카드할인':  { cls: 'badge-card',     icon: '💳' },
  '패키지':   { cls: 'badge-hot',      icon: '📦' },
};

/* ─── Product Key (색상·접두어 제거 → products.json 조회키) ─── */
function makeProductKey(name) {
  const COLOR_RE  = /\s*[,·]?\s*(?:블랙|화이트|실버|그레이|블루|레드|핑크|퍼플|골드|그린|베이지|티타늄|카키|네이비|코랄|민트|라벤더|크림|챠콜|미드나잇|스타라이트|아이보리|스카이블루|옐로우?|오렌지|브라운|팬텀블랙|팬텀화이트|아이스블루|에버그린)(?=\s|,|$)/gi;
  const PREFIX_RE = /^\s*\[?(?:쿠팡|11번가|G마켓|옥션|SSG닷컴?|네이버쇼핑?|롯데온|다나와|에누리)\]?\s*[-_]?\s*/i;
  return (name || '').replace(PREFIX_RE, '').replace(COLOR_RE, '').replace(/\s+/g, ' ').trim();
}

/* ─── State ─── */
const state = {
  deals: [],
  filtered: [],
  category: 'all',
  sort: 'discount',
  minDiscount: 0,
  maxPrice: Infinity,
  query: '',
  wishlist: JSON.parse(localStorage.getItem('tdkr_wishlist') || '[]'),
  products: {},   // 상품 설명 DB (products.json)
};

function saveWishlist() {
  localStorage.setItem('tdkr_wishlist', JSON.stringify(state.wishlist));
}

/** 찜한 딜의 상품명 키를 Supabase push_subscriptions에 동기화
 *  → 서버에서 가격 하락 감지 후 해당 구독자에게만 알림 발송 */
async function syncWishlistToPush() {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return;
  try {
    const reg = await navigator.serviceWorker?.ready;
    if (!reg) return;
    const sub = await reg.pushManager?.getSubscription();
    if (!sub) return;
    const wishlisted_keys = state.wishlist
      .map(id => state.deals.find(d => d.id === id))
      .filter(Boolean)
      .map(d => makeProductKey(d.name));
    await fetch(`${SUPABASE_URL}/rest/v1/push_subscriptions?endpoint=eq.${encodeURIComponent(sub.endpoint)}`, {
      method:  'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'apikey':        SUPABASE_ANON_KEY,
        'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
      },
      body: JSON.stringify({ wishlisted_keys }),
    }).catch(() => {});
  } catch (_) {}
}

function toggleWish(dealId, e) {
  e.preventDefault(); e.stopPropagation();
  const idx = state.wishlist.indexOf(dealId);
  if (idx === -1) {
    state.wishlist.push(dealId);
    showToast('❤️ 찜 목록에 추가했어요! 가격 하락 시 알림을 받으려면 알림 신청을 해주세요.', 'success');
  } else {
    state.wishlist.splice(idx, 1);
    showToast('찜 목록에서 제거했어요', 'info');
  }
  saveWishlist();
  syncWishlistToPush();
  // 카드 하트 아이콘만 업데이트 (전체 리렌더 없이)
  const btn = document.querySelector(`.btn-wish[data-id="${dealId}"]`);
  if (btn) {
    const active = state.wishlist.includes(dealId);
    btn.classList.toggle('active', active);
    btn.innerHTML = active ? '❤️' : '🤍';
    btn.title = active ? '찜 해제' : '찜하기';
  }
  // 찜 탭 뱃지 갱신
  updateWishBadge();
  // 현재 찜 탭이면 목록 갱신
  if (state.category === 'wish') applyFilters();
}
window.toggleWish = toggleWish;

function updateWishBadge() {
  const badge = document.querySelector('.wish-badge');
  if (badge) {
    badge.textContent = state.wishlist.length || '';
    badge.style.display = state.wishlist.length ? 'inline-block' : 'none';
  }
}

async function shareDeal(dealId, e) {
  e.preventDefault(); e.stopPropagation();
  const deal = state.deals.find(d => d.id === dealId);
  if (!deal) return;
  const { href } = resolveLink(deal);
  const disc = pct(deal.originalPrice, deal.salePrice);
  const title = `🔥 ${disc}% 할인! ${deal.name}`;
  const text  = `${fmt(deal.originalPrice)} → ${fmt(deal.salePrice)} (${disc}% 할인)\n\nITSpecial에서 더 많은 특가 확인하기`;

  // 1순위: 카카오톡 SDK (JS 키 설정 + 도메인 등록 시)
  if (KAKAO_JS_KEY && window.Kakao?.isInitialized()) {
    try {
      window.Kakao.Share.sendDefault({
        objectType: 'commerce',
        content: {
          title: deal.name,
          imageUrl: deal.image,
          link: { mobileWebUrl: href, webUrl: href },
          description: `${disc}% 할인 · ${fmt(deal.salePrice)} · ${deal.store}`,
        },
        commerce: {
          productName: deal.name,
          regularPrice: deal.originalPrice,
          salePrice:    deal.salePrice,
          discountRate: disc,
        },
        buttons: [{ title: '구매하러 가기', link: { mobileWebUrl: href, webUrl: href } }],
      });
      return;
    } catch { /* 도메인 미등록 등 Kakao 오류 → 다음 수단으로 폴백 */ }
  }
  // 2순위: Web Share API (모바일 — 카카오톡 포함)
  if (navigator.share) {
    try { await navigator.share({ title, text, url: href }); return; } catch {}
  }
  // 3순위: 클립보드 복사 (데스크탑)
  try {
    await navigator.clipboard.writeText(`${title}\n${href}`);
    showToast('🔗 링크가 복사되었습니다!', 'success');
  } catch {
    showToast('공유를 지원하지 않는 브라우저예요', 'warn');
  }
}
window.shareDeal = shareDeal;

/* ─── DOM refs ─── */
const $grid     = document.getElementById('deals-grid');
const $count    = document.getElementById('result-count');
const $search   = document.getElementById('search-input');
const $cats     = document.getElementById('cat-tabs');
const $toast    = document.getElementById('toast');

/* ─── Utils ─── */
// fmt: 유효하지 않거나 0 이하 가격 → '-' 표시 (0원·NaN 방지)
const fmt = n => (isFinite(n) && n > 0 ? Math.round(n).toLocaleString('ko-KR') + '원' : '-');
// pct: 정가 0 방어 (division by zero → 0%)
const pct = (o, s) => (o > 0 ? Math.round((o - s) / o * 100) : 0);

function timeLeft(expiresAt) {
  const diff = new Date(expiresAt) - Date.now();
  if (diff <= 0) return null;
  const h = Math.floor(diff / 3600000);
  const m = Math.floor((diff % 3600000) / 60000);
  const s = Math.floor((diff % 60000) / 1000);
  if (h > 48) return `${Math.floor(h / 24)}일 남음`;
  if (h > 0)  return `${h}시간 ${m}분 남음`;
  return `${m}분 ${s}초 남음`;
}

function showToast(msg, type = 'info') {
  $toast.textContent = msg;
  $toast.className = 'toast show toast-' + type;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => $toast.classList.remove('show'), 3000);
}

function starsHtml(r) {
  return '★'.repeat(Math.floor(r)) + (r % 1 >= 0.5 ? '½' : '') + '☆'.repeat(5 - Math.ceil(r));
}

/* ─── Affiliate link resolution ─── */
function resolveLink(deal) {
  const affUrl = deal.affiliateUrl?.trim();
  const prodUrl = deal.productUrl || '';

  // Linkprice (click.linkprice.com?l=0000): 메인 랜딩이라 상품 직링크 불가
  // → 사용자는 productUrl(실제 상품)로, Linkprice 추적은 백그라운드 픽셀로
  if (affUrl && affUrl.includes('click.linkprice.com') && prodUrl) {
    return { href: prodUrl, isAffiliate: true, trackingUrl: affUrl };
  }

  return { href: affUrl || prodUrl, isAffiliate: !!affUrl, trackingUrl: null };
}

/* ─── Render ─── */
function renderSkeletons() {
  $grid.innerHTML = Array.from({ length: 8 }, () => `
    <div class="skeleton-card">
      <div class="skeleton skeleton-img"></div>
      <div class="skeleton-body">
        <div class="skeleton skeleton-line short"></div>
        <div class="skeleton skeleton-line long"></div>
        <div class="skeleton skeleton-line long"></div>
        <div class="skeleton skeleton-price"></div>
      </div>
    </div>`).join('');
}

function renderCard(deal) {
  const disc    = Math.max(0, pct(deal.originalPrice, deal.salePrice));
  const savings = Math.max(0, (deal.originalPrice || 0) - (deal.salePrice || 0));
  const { href, isAffiliate, trackingUrl } = resolveLink(deal);
  const isWished = state.wishlist.includes(deal.id);

  // ── 배지 ──
  const badgesHtml = [
    `<span class="badge badge-discount">${disc}% 할인</span>`,
    ...(deal.tags || []).map(t => {
      const info = TAG_MAP[t] || { cls: 'badge-hot', icon: '' };
      return `<span class="badge ${info.cls}">${info.icon} ${t}</span>`;
    }),
  ].join('');

  // ── 제휴 뱃지 ──
  const affiliateBadge = isAffiliate
    ? `<span class="meta-tag affiliate-tag" title="이 링크를 통해 구매 시 소정의 수수료를 받을 수 있습니다">🤝 파트너스</span>`
    : '';

  // ── 업데이트 날짜 뱃지 (expiresAt - 7일 = 수집일) ──
  const updateHtml = (() => {
    if (!deal.expiresAt) return '';
    const d = new Date(new Date(deal.expiresAt) - 7 * 24 * 3600 * 1000);
    const mm = d.getMonth() + 1;
    const dd = String(d.getDate()).padStart(2, '0');
    return `<div class="update-badge">📅 ${mm}.${dd} 업데이트</div>`;
  })();

  // ── 이미지 호버 툴팁 (상세 요약) ──
  const tagBadges = (deal.tags || []).slice(0, 2).map(t => {
    const info = TAG_MAP[t];
    return info ? `<span class="img-tooltip-tag">${info.icon} ${t}</span>` : '';
  }).join('');

  const prodKey  = makeProductKey(deal.name);
  const prodDesc = (state.products[prodKey]?.description || '').slice(0, 100);

  const tooltipHtml = `
    <div class="img-tooltip" aria-hidden="true">
      <div class="img-tooltip-header">
        <span class="img-tooltip-disc">${disc}% 할인</span>
        ${tagBadges}
      </div>
      <div class="img-tooltip-name">${deal.name}</div>
      ${prodDesc ? `<div class="img-tooltip-desc">${prodDesc}${prodDesc.length >= 100 ? '…' : ''}</div>` : ''}
      <div class="img-tooltip-prices">
        <div class="img-tooltip-orig">${fmt(deal.originalPrice)}</div>
        <div class="img-tooltip-sale">${fmt(deal.salePrice)}</div>
      </div>
      <div class="img-tooltip-meta">
        <span>🏪 ${deal.store}</span>
        ${deal.freeShipping ? '<span>🚚 무료배송</span>' : ''}
        <span>💰 ${fmt(savings)} 절약</span>
      </div>
      ${deal.priceHistory?.length >= 2 ? makeSparkline(deal.priceHistory) : ''}
    </div>`;

  // ── 별점: 실제 리뷰 데이터 있을 때만 표시 ──
  const ratingHtml = deal.reviewCount > 0
    ? `<div class="deal-rating">
         <span class="stars">${starsHtml(deal.rating)}</span>
         <span>(${deal.reviewCount.toLocaleString()})</span>
       </div>`
    : '';

  return `
    <div class="deal-card" data-id="${deal.id}">
      <div class="deal-img-wrap">
        <img class="deal-img" src="${deal.image}" alt="${deal.name}" loading="lazy"
             onerror="this.src='https://placehold.co/400x300/f1f3f5/adb5bd?text=이미지없음'">
        <div class="deal-badges">${badgesHtml}</div>
        ${tooltipHtml}
        ${updateHtml}
        <div class="card-actions">
          <button class="btn-wish ${isWished ? 'active' : ''}" data-id="${deal.id}"
                  onclick="toggleWish(${deal.id}, event)"
                  title="${isWished ? '찜 해제' : '찜하기'}">${isWished ? '❤️' : '🤍'}</button>
          <button class="btn-share" onclick="shareDeal(${deal.id}, event)" title="공유">
            <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24">
              <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
              <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
              <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
            </svg>
          </button>
        </div>
      </div>
      <div class="deal-body">
        <div class="deal-store-row">
          <span class="store-badge">${deal.store}</span>
          ${ratingHtml}
        </div>
        <a class="deal-name-link" href="/deals/${deal.id}.html">${deal.name}</a>
        <div class="deal-prices">
          <span class="original-price">
            ${deal.priceType === 'msrp'
              ? '<span class="price-type-label">출고가</span>'
              : deal.priceType === 'hprice'
                ? '<span class="price-type-label">타사 최고가</span>'
                : deal.priceType === 'avg7d'
                  ? '<span class="price-type-label">7일 평균가</span>'
                  : ''}
            ${fmt(deal.originalPrice)}
          </span>
          <span class="sale-price">${fmt(deal.salePrice)}</span>
        </div>
        <div class="deal-footer">
          <div class="deal-meta">
            ${deal.freeShipping ? '<span class="meta-tag">🚚 무료배송</span>' : ''}
            <span class="meta-tag savings">💰 ${fmt(savings)} 절약</span>
            ${affiliateBadge}
          </div>
          <a href="${href}"
             target="_blank"
             rel="noopener ${isAffiliate ? 'sponsored' : ''}"
             class="btn-buy"
             onclick="trackClick(${deal.id}, ${isAffiliate}, ${trackingUrl ? JSON.stringify(trackingUrl) : 'null'})">
            구매 →
          </a>
        </div>
      </div>
    </div>`;
}

function render() {
  if (!state.filtered.length) {
    $grid.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🔍</div>
        <h3>검색 결과가 없어요</h3>
        <p>다른 카테고리나 검색어를 시도해보세요</p>
      </div>`;
    $count.innerHTML = `결과 <strong>0</strong>개`;
    injectSchemaMarkup([]);
    return;
  }
  $grid.innerHTML = state.filtered.map(renderCard).join('');
  $count.innerHTML = `특가 <strong>${state.filtered.length}</strong>개`;
  injectSchemaMarkup(state.filtered);
}

/* ─── Schema Markup (JSON-LD) ─── */
/**
 * 현재 필터된 딜 목록을 구글이 읽을 수 있는 구조화 데이터로 변환해 <head>에 주입.
 * - ItemList  : 딜 목록 전체 (카테고리/검색 결과)
 * - Product   : 개별 상품 (이름·이미지)
 * - Offer     : 가격·재고·판매처·유효기간
 * - AggregateRating : 별점·리뷰수 (있을 때만)
 * 구글 리치 스니펫 기준: https://developers.google.com/search/docs/appearance/structured-data/product
 */
function injectSchemaMarkup(deals) {
  // 기존 동적 스키마 제거 (render 호출마다 최신 데이터로 교체)
  document.getElementById('schema-deals-ld')?.remove();
  if (!deals.length) return;

  const SITE_URL = 'https://itspecial.co.kr';

  const itemListElements = deals.slice(0, 20).map((deal, i) => {
    const { href } = resolveLink(deal);
    const expiresDate = deal.expiresAt ? deal.expiresAt.split('T')[0] : '';

    const product = {
      '@type': 'Product',
      name: deal.name,
      image: [deal.image],
      offers: {
        '@type': 'Offer',
        priceCurrency: 'KRW',
        price: String(deal.salePrice),
        // inStock 미정의 시 InStock 기본값 (undefined → 재고없음 오류 방지)
        availability: deal.inStock === false
          ? 'https://schema.org/OutOfStock'
          : 'https://schema.org/InStock',
        ...(expiresDate ? { priceValidUntil: expiresDate } : {}),
        url: href,
        seller: { '@type': 'Organization', name: deal.store },
      },
    };

    // 별점/리뷰수가 있을 때만 AggregateRating 추가
    // (구글 가이드: 리뷰 없는 별점은 스팸으로 분류될 수 있음)
    if (deal.rating >= 1 && deal.reviewCount > 0) {
      product.aggregateRating = {
        '@type': 'AggregateRating',
        ratingValue: deal.rating.toFixed(1),
        reviewCount: String(deal.reviewCount),
        bestRating: '5',
        worstRating: '1',
      };
    }

    return { '@type': 'ListItem', position: i + 1, item: product };
  });

  const schema = {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    name: '한국 테크 특가 모음 — ITSpecial',
    description: '스마트폰·노트북·이어폰 등 IT 기기 최저가를 한눈에',
    url: SITE_URL,
    numberOfItems: deals.length,
    itemListElement: itemListElements,
  };

  const script = document.createElement('script');
  script.id   = 'schema-deals-ld';
  script.type = 'application/ld+json';
  script.textContent = JSON.stringify(schema, null, 0);
  document.head.appendChild(script);
}

/* ─── Filter & Sort ─── */
function applyFilters() {
  let list = [...state.deals];
  if (state.category === 'wish') {
    list = list.filter(d => state.wishlist.includes(d.id));
  } else if (state.category === 'lowest') {
    list = list.filter(d => (d.tags || []).includes('역대최저'));
  } else if (state.category !== 'all') {
    list = list.filter(d => d.category === state.category);
  }
  if (state.query) {
    const q = state.query.toLowerCase();
    // 한영 동시 검색: "iPhone" → 아이폰도 매칭, "갤럭시" → Galaxy도 매칭
    const SEARCH_ALIAS = {
      'iphone': '아이폰', '아이폰': 'iphone',
      'galaxy': '갤럭시', '갤럭시': 'galaxy',
      'airpods': '에어팟', '에어팟': 'airpods',
      'macbook': '맥북',  '맥북': 'macbook',
      'ipad': '아이패드', '아이패드': 'ipad',
      'apple watch': '애플워치', '애플워치': 'apple watch',
      'galaxy buds': '갤럭시버즈', '갤럭시버즈': 'galaxy buds',
      'galaxy watch': '갤럭시워치', '갤럭시워치': 'galaxy watch',
      'galaxy tab': '갤럭시탭', '갤럭시탭': 'galaxy tab',
      'lg gram': '그램', '그램': 'lg gram',
      'nintendo switch': '닌텐도', '닌텐도': 'nintendo',
    };
    const alias = SEARCH_ALIAS[q] || '';
    list = list.filter(d => {
      const name = d.name.toLowerCase();
      return name.includes(q) || d.store.toLowerCase().includes(q)
        || (alias && name.includes(alias));
    });
  }
  if (state.minDiscount > 0)
    list = list.filter(d => pct(d.originalPrice, d.salePrice) >= state.minDiscount);
  if (state.maxPrice < Infinity)
    list = list.filter(d => d.salePrice <= state.maxPrice);

  switch (state.sort) {
    case 'discount':   list.sort((a, b) => pct(b.originalPrice, b.salePrice) - pct(a.originalPrice, a.salePrice)); break;
    case 'price-asc':  list.sort((a, b) => a.salePrice - b.salePrice); break;
    case 'price-desc': list.sort((a, b) => b.salePrice - a.salePrice); break;
    case 'latest':     list.sort((a, b) => b.id - a.id); break;
    case 'savings':    list.sort((a, b) => (b.originalPrice - b.salePrice) - (a.originalPrice - a.salePrice)); break;
  }
  state.filtered = list;
  render();
}

/* ─── Category tabs ─── */
function renderCategories() {
  $cats.innerHTML = CATEGORIES.map(c => {
    const badge = c.id === 'wish' && state.wishlist.length
      ? `<span class="wish-badge">${state.wishlist.length}</span>` : '';
    return `<button class="cat-btn ${c.id === state.category ? 'active' : ''}" data-cat="${c.id}">
      ${c.icon} ${c.label}${badge}
    </button>`;
  }).join('');

  $cats.querySelectorAll('.cat-btn').forEach(btn =>
    btn.addEventListener('click', () => {
      state.category = btn.dataset.cat;
      $cats.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applyFilters();
    })
  );
}

/* ─── Timers ─── */
function updateTimers() {
  document.querySelectorAll('.timer[data-expires]').forEach(el => {
    const t = timeLeft(el.dataset.expires);
    if (t) el.textContent = t;
    else el.closest('.timer-wrap')?.remove();
  });
}

/* ─── Price Sparkline (SVG 인라인 — 외부 라이브러리 불필요) ─── */
function makeSparkline(history) {
  if (!history || history.length < 2) return '';
  const prices = history.map(h => h.lprice || h.hprice).filter(Boolean);
  if (prices.length < 2) return '';
  const min   = Math.min(...prices);
  const max   = Math.max(...prices);
  const range = max - min || 1;
  const W = 72, H = 22;
  const points = prices.map((p, i) => {
    const x = (i / (prices.length - 1)) * W;
    const y = H - ((p - min) / range) * (H - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  // 마지막 가격이 첫 가격보다 낮으면 초록(하락), 높으면 빨강(상승)
  const trend = prices[prices.length - 1] <= prices[0] ? '#4ADE80' : '#F87171';
  const lastX = W;
  const lastY = (H - ((prices[prices.length - 1] - min) / range) * (H - 4) - 2).toFixed(1);
  const minPrice = Math.min(...prices).toLocaleString('ko-KR') + '원';
  const maxPrice = Math.max(...prices).toLocaleString('ko-KR') + '원';
  return `<div class="sparkline-wrap" title="${history.length}일 가격 추이 · 최저 ${minPrice} · 최고 ${maxPrice}">
    <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" overflow="visible">
      <polyline points="${points}" fill="none" stroke="${trend}" stroke-width="1.8"
        stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${lastX}" cy="${lastY}" r="2.5" fill="${trend}"/>
    </svg>
    <span class="sparkline-days">${history.length}일</span>
  </div>`;
}

/* ─── Affiliate click tracking ─── */
function trackClick(dealId, isAffiliate, trackingUrl) {
  const deal = state.deals.find(d => d.id === dealId);
  if (!deal) return;

  // Linkprice 백그라운드 추적 픽셀
  // (l=0000 메인랜딩 대신 productUrl 직접 사용 시 쿠키 설정용)
  if (trackingUrl) {
    try { new Image().src = trackingUrl; } catch (e) {}
  }

  // Google Analytics 이벤트 (GA 연동 시 활성화)
  if (window.gtag) {
    window.gtag('event', 'affiliate_click', {
      item_name: deal.name,
      store: deal.store,
      price: deal.salePrice,
      is_affiliate: isAffiliate,
    });
  }

  // Supabase 클릭 로그 (fire-and-forget — UI 블로킹 없음)
  if (SUPABASE_URL && SUPABASE_ANON_KEY) {
    fetch(`${SUPABASE_URL}/rest/v1/click_logs`, {
      method: 'POST',
      headers: {
        'Content-Type':  'application/json',
        'apikey':         SUPABASE_ANON_KEY,
        'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
        'Prefer':        'return=minimal',
      },
      body: JSON.stringify({
        deal_id:      deal.id,
        deal_name:    deal.name.slice(0, 100),
        category:     deal.category,
        store:        deal.store,
        sale_price:   deal.salePrice,
        is_affiliate: isAffiliate,
      }),
    }).catch(() => {});  // 실패해도 무시
  }
}
window.trackClick = trackClick;

/* ─── Hero stats ─── */
function updateHeroStats() {
  const el = document.getElementById('hero-deal-count');
  if (el) el.textContent = state.deals.length;
}

/* ───────────────────────────────────────────
   ALERT MODAL — 카테고리별 특가 알림 구독
─────────────────────────────────────────── */
// ── 구독자 저장 백엔드 ──────────────────────────────────────────
// ── Web Push VAPID 공개키 (private key는 GitHub Secret VAPID_PRIVATE_KEY) ──
const VAPID_PUBLIC_KEY = 'BAINi54MJSirm_eO9dGq9e-HI3Tg36T-YIWR_q-MbhE1wicBj24KDNNCI-eOviDppxDK_PSBcotL8G4P6_a8O2E';

/** base64url → Uint8Array 변환 (PushManager.subscribe 용) */
function urlBase64ToUint8Array(b64) {
  const pad  = '='.repeat((4 - b64.length % 4) % 4);
  const raw  = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

/** 웹 푸시 구독 — Service Worker 통해 브라우저 구독 엔드포인트 획득 */
async function getPushSubscription() {
  if (!('PushManager' in window) || !('serviceWorker' in navigator)) return null;
  try {
    const reg = await navigator.serviceWorker.ready;
    // 이미 구독돼 있으면 기존 것 반환
    const existing = await reg.pushManager.getSubscription();
    if (existing) return existing;
    // 새로 구독 (브라우저가 사용자에게 알림 권한 요청)
    return await reg.pushManager.subscribe({
      userVisibleOnly:      true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
    });
  } catch (e) {
    console.warn('[Push] 구독 실패:', e);
    return null;
  }
}

/** Supabase push_subscriptions 테이블에 저장 */
async function savePushSubscription(sub, email, categories) {
  if (!sub || !SUPABASE_URL || !SUPABASE_ANON_KEY) return;
  const key = sub.getKey('p256dh');
  const auth = sub.getKey('auth');
  await fetch(`${SUPABASE_URL}/rest/v1/push_subscriptions`, {
    method:  'POST',
    headers: {
      'Content-Type': 'application/json',
      'apikey':        SUPABASE_ANON_KEY,
      'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
      'Prefer':        'resolution=merge-duplicates',
    },
    body: JSON.stringify({
      endpoint:   sub.endpoint,
      p256dh:     btoa(String.fromCharCode(...new Uint8Array(key))),
      auth:       btoa(String.fromCharCode(...new Uint8Array(auth))),
      email:      email || null,
      categories: categories || [],
    }),
  }).catch(e => console.warn('[Push] Supabase 저장 실패:', e));
}

// Supabase 설정 후 아래 두 값을 채우면 모달 → Supabase 자동 저장
// (anon key는 RLS가 INSERT만 허용하므로 공개 커밋 OK)
const SUPABASE_URL      = 'https://dcwxomhlezoqyliexatv.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRjd3hvbWhsZXpvcXlsaWV4YXR2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk2ODE2MzQsImV4cCI6MjA5NTI1NzYzNH0.VcB0ivWpzynM7QnbqRtPLZ3fGJONFuUykUB-Gr1lSzU';

// Formspree: contact.html 연락처 폼 전용 유지 (Supabase 미설정 시 알림모달 폴백)
const FORMSPREE_ENDPOINT = 'https://formspree.io/f/xnjrbjwn';

function openAlertModal(preselectedCat) {
  const modal = document.getElementById('alert-modal');
  if (!modal) return;

  // 저장된 구독 정보 불러오기
  const saved = JSON.parse(localStorage.getItem('tdkr_subscription') || '{}');

  // 카테고리 체크박스 렌더
  const catBoxes = CATEGORIES.filter(c => c.id !== 'all').map(c => `
    <label class="cat-checkbox ${(preselectedCat === c.id || saved.categories?.includes(c.id)) ? 'checked' : ''}">
      <input type="checkbox" name="category" value="${c.id}"
             ${(preselectedCat === c.id || saved.categories?.includes(c.id)) ? 'checked' : ''}>
      ${c.icon} ${c.label}
    </label>`).join('');

  document.getElementById('modal-cat-grid').innerHTML = catBoxes;

  // 이전에 입력한 이메일 복원
  const emailInput = document.getElementById('alert-email');
  if (saved.email) emailInput.value = saved.email;

  // 체크박스 체크 시 시각적 피드백
  document.querySelectorAll('.cat-checkbox input').forEach(cb => {
    cb.addEventListener('change', () => {
      cb.closest('.cat-checkbox').classList.toggle('checked', cb.checked);
    });
  });

  modal.classList.add('open');
}
window.openAlertModal = openAlertModal;

function closeAlertModal() {
  document.getElementById('alert-modal')?.classList.remove('open');
}

async function submitAlertForm() {
  const email    = document.getElementById('alert-email')?.value?.trim();
  const cats     = [...document.querySelectorAll('.cat-checkbox input:checked')].map(cb => cb.value);
  const wantPush = document.getElementById('push-toggle')?.checked ?? true;

  // 이메일 OR 푸시 중 하나 이상 선택해야 함
  if (!wantPush && (!email || !email.includes('@'))) {
    showToast('이메일을 입력하거나 브라우저 푸시 알림을 활성화해주세요', 'warn'); return;
  }
  if (email && !email.includes('@')) { showToast('유효한 이메일 주소를 입력해주세요', 'warn'); return; }
  if (!cats.length) { showToast('카테고리를 하나 이상 선택해주세요', 'warn'); return; }

  // 웹 푸시 구독 처리 (이메일 저장과 병렬)
  if (wantPush) {
    const permission = await Notification.requestPermission();
    if (permission === 'granted') {
      const sub = await getPushSubscription();
      if (sub) {
        await savePushSubscription(sub, email || null, cats);
        console.log('[Push] 구독 완료');
      }
    } else {
      showToast('브라우저 알림 권한이 거부됐습니다. 브라우저 설정에서 허용해주세요.', 'warn');
    }
  }

  // 이메일 없으면 이메일 저장 단계 스킵 (푸시만 구독한 경우)
  if (!email || !email.includes('@')) {
    closeAlertModal();
    showToast('✅ 브라우저 푸시 알림이 등록됐습니다!', 'success');
    return;
  }

  // 로컬스토리지 저장 (재방문 시 복원용)
  localStorage.setItem('tdkr_subscription', JSON.stringify({ email, categories: cats }));

  // ── Supabase 저장 (설정된 경우 우선 사용) ─────────────────────────
  if (SUPABASE_URL && SUPABASE_ANON_KEY) {
    try {
      const res = await fetch(`${SUPABASE_URL}/rest/v1/subscribers`, {
        method:  'POST',
        headers: {
          'Content-Type':  'application/json',
          'apikey':         SUPABASE_ANON_KEY,
          'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
        },
        body: JSON.stringify({ email, categories: cats }),
      });
      if (res.status === 409) {
        // 이미 구독 중 → 기존 카테고리와 병합(union) 후 PATCH
        try {
          const getRes = await fetch(
            `${SUPABASE_URL}/rest/v1/subscribers?email=eq.${encodeURIComponent(email)}&select=categories`,
            { headers: { 'apikey': SUPABASE_ANON_KEY, 'Authorization': `Bearer ${SUPABASE_ANON_KEY}` } }
          );
          const rows = getRes.ok ? await getRes.json() : [];
          const existing = rows[0]?.categories || [];
          // 기존 + 신규 카테고리 합집합
          const merged = [...new Set([...existing, ...cats])];
          await fetch(
            `${SUPABASE_URL}/rest/v1/subscribers?email=eq.${encodeURIComponent(email)}`,
            {
              method:  'PATCH',
              headers: {
                'Content-Type':  'application/json',
                'apikey':         SUPABASE_ANON_KEY,
                'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
              },
              body: JSON.stringify({ categories: merged }),
            }
          );
          const added = cats.filter(c => !existing.includes(c));
          closeAlertModal();
          showToast(
            added.length
              ? `✅ ${added.length}개 카테고리가 추가되었습니다!`
              : '✅ 이미 모든 카테고리를 구독 중입니다.',
            'success'
          );
        } catch {
          closeAlertModal();
          showToast('✅ 이미 구독 중입니다!', 'success');
        }
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.message || `HTTP ${res.status}`);
      }
    } catch (e) {
      console.error('구독 저장 오류:', e);
      showToast('전송 실패 — 잠시 후 다시 시도해주세요', 'warn');
      return;
    }

  // ── Formspree 폴백 (Supabase 미설정 시) ──────────────────────────
  } else if (FORMSPREE_ENDPOINT) {
    try {
      const res = await fetch(FORMSPREE_ENDPOINT, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body:    JSON.stringify({ email, categories: cats.join(', '), _subject: '특가 알림 신청' }),
      });
      if (!res.ok) throw new Error();
    } catch {
      showToast('전송 실패 — 잠시 후 다시 시도해주세요', 'warn');
      return;
    }
  }

  closeAlertModal();
  showToast(`✅ ${cats.length}개 카테고리 알림 신청 완료!`, 'success');
}

/* ─── Sort buttons ─── */
document.querySelectorAll('.sort-btn').forEach(btn =>
  btn.addEventListener('click', () => {
    state.sort = btn.dataset.sort;
    document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyFilters();
  })
);

/* ─── Filter selects ─── */
document.getElementById('filter-min-discount')?.addEventListener('change', e => {
  state.minDiscount = parseInt(e.target.value) || 0;
  applyFilters();
});
document.getElementById('filter-max-price')?.addEventListener('change', e => {
  state.maxPrice = e.target.value ? parseInt(e.target.value) * 10000 : Infinity;
  applyFilters();
});

/* ─── Search ─── */
$search?.addEventListener('input', e => {
  state.query = e.target.value.trim();
  applyFilters();
});

/* ─── 제보 모달 ─── */
function openReportModal() {
  document.getElementById('report-modal').classList.add('open');
  document.getElementById('report-url').focus();
}
function closeReportModal() {
  document.getElementById('report-modal').classList.remove('open');
}
async function submitReport() {
  const url  = document.getElementById('report-url').value.trim();
  const name = document.getElementById('report-name').value.trim();
  const sale = parseInt(document.getElementById('report-sale').value) || 0;
  const orig = parseInt(document.getElementById('report-orig').value) || 0;
  const note = document.getElementById('report-note').value.trim();

  if (!url || !name || !sale) {
    showToast('URL, 상품명, 특가는 필수 입력입니다.', 'error'); return;
  }
  try { new URL(url); } catch { showToast('올바른 URL을 입력해주세요.', 'error'); return; }

  const btn = document.getElementById('report-submit');
  btn.disabled = true; btn.textContent = '전송 중...';

  try {
    if (SUPABASE_URL && SUPABASE_ANON_KEY) {
      await fetch(`${SUPABASE_URL}/rest/v1/deal_reports`, {
        method:  'POST',
        headers: {
          'Content-Type': 'application/json',
          'apikey':        SUPABASE_ANON_KEY,
          'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
          'Prefer':        'return=minimal',
        },
        body: JSON.stringify({ url, name, sale_price: sale, original_price: orig || null, note: note || null }),
      });
    }
    showToast('✅ 제보가 접수됐어요! 검토 후 반영할게요 🙏', 'success');
    closeReportModal();
    ['report-url','report-name','report-orig','report-sale','report-note'].forEach(id => {
      document.getElementById(id).value = '';
    });
  } catch (e) {
    showToast('전송 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.', 'error');
  } finally {
    btn.disabled = false; btn.textContent = '제보 전송 →';
  }
}
document.getElementById('report-modal')?.addEventListener('click', e => {
  if (e.target.id === 'report-modal') closeReportModal();
});
window.openReportModal  = openReportModal;
window.closeReportModal = closeReportModal;
window.submitReport     = submitReport;

/* ─── Modal wiring ─── */
document.getElementById('btn-alert')?.addEventListener('click', () => openAlertModal(null));
document.getElementById('modal-close')?.addEventListener('click', closeAlertModal);
document.getElementById('modal-submit')?.addEventListener('click', submitAlertForm);
document.getElementById('alert-modal')?.addEventListener('click', e => {
  if (e.target.id === 'alert-modal') closeAlertModal();
});

/* ─── Footer category links ─── */
window.selectCat = function(id) {
  const btn = document.querySelector(`[data-cat="${id}"]`);
  if (btn) btn.click();
  window.scrollTo({ top: 0, behavior: 'smooth' });
};

/* ─── Init ─── */
async function init() {
  // GA4 초기화
  if (window.GA_ID) {
    const s = document.createElement('script');
    s.src = `https://www.googletagmanager.com/gtag/js?id=${GA_ID}`;
    s.async = true;
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function(){ dataLayer.push(arguments); };
    gtag('js', new Date());
    gtag('config', GA_ID);
  }

  // Kakao SDK 초기화 (실패해도 딜 로드는 계속)
  if (KAKAO_JS_KEY && window.Kakao && !Kakao.isInitialized()) {
    try { Kakao.init(KAKAO_JS_KEY); } catch (e) { console.warn('Kakao init 실패:', e); }
  }

  renderSkeletons();
  renderCategories();
  try {
    const res = await fetch('./data/deals.json?v=' + Date.now());
    if (!res.ok) throw new Error();
    state.deals = await res.json();
  } catch {
    $grid.innerHTML = `<div class="empty-state"><div class="empty-icon">⚡</div><h3>데이터를 불러오는 중이에요</h3></div>`;
    return;
  }
  // 상품 설명 DB — Supabase에서 로드 (실패 시 products.json 폴백)
  try {
    const res = await fetch(
      `${SUPABASE_URL}/rest/v1/products?select=key,description`,
      { headers: { 'apikey': SUPABASE_ANON_KEY, 'Authorization': `Bearer ${SUPABASE_ANON_KEY}` } }
    );
    if (res.ok) {
      const rows = await res.json();
      rows.forEach(r => { if (r.key) state.products[r.key] = { description: r.description }; });
    }
  } catch {
    try {
      const pr = await fetch('./data/products.json?v=' + Date.now());
      if (pr.ok) state.products = await pr.json();
    } catch {}
  }
  updateHeroStats();
  document.getElementById('live-count').textContent = state.deals.length;
  applyFilters();
}

document.addEventListener('DOMContentLoaded', init);
