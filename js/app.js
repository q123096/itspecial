/* ===== TechDeal KR — Main App ===== */

// ── Kakao 공유 키 (kakao.com/developers → 내 애플리케이션 → JavaScript 키)
const KAKAO_JS_KEY = 'db4206611cd19ecfa9ae35fff67039d8';

const CATEGORIES = [
  { id: 'all',        label: '전체',        icon: '🏷️' },
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
};

function saveWishlist() {
  localStorage.setItem('tdkr_wishlist', JSON.stringify(state.wishlist));
}

function toggleWish(dealId, e) {
  e.preventDefault(); e.stopPropagation();
  const idx = state.wishlist.indexOf(dealId);
  if (idx === -1) {
    state.wishlist.push(dealId);
    showToast('❤️ 찜 목록에 추가했어요!', 'success');
  } else {
    state.wishlist.splice(idx, 1);
    showToast('찜 목록에서 제거했어요', 'info');
  }
  saveWishlist();
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
  const text  = `${deal.name}\n${fmt(deal.originalPrice)} → ${fmt(deal.salePrice)} (${disc}% 할인)\n\nITSpecial에서 더 많은 특가 확인하기`;

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
const fmt = n => n.toLocaleString('ko-KR') + '원';
const pct = (o, s) => Math.round((o - s) / o * 100);

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
// affiliateUrl 이 비어있으면 productUrl 사용 (제휴링크 미설정 상태)
function resolveLink(deal) {
  const url = deal.affiliateUrl?.trim();
  return { href: url || deal.productUrl, isAffiliate: !!url };
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
  const disc     = pct(deal.originalPrice, deal.salePrice);
  const savings  = deal.originalPrice - deal.salePrice;
  const tLeft    = timeLeft(deal.expiresAt);
  const { href, isAffiliate } = resolveLink(deal);
  const isWished = state.wishlist.includes(deal.id);

  const badgesHtml = [
    `<span class="badge badge-discount">${disc}% 할인</span>`,
    ...deal.tags.map(t => {
      const info = TAG_MAP[t] || { cls: 'badge-hot', icon: '' };
      return `<span class="badge ${info.cls}">${info.icon} ${t}</span>`;
    }),
  ].join('');

  // 제휴링크 설정 시 소표시 (공정위 추천보증 심사지침 대응)
  const affiliateBadge = isAffiliate
    ? `<span class="meta-tag affiliate-tag" title="이 링크를 통해 구매 시 소정의 수수료를 받을 수 있습니다">🤝 파트너스</span>`
    : '';

  const timerHtml = tLeft
    ? `<div class="timer-wrap">
         <span class="timer-icon">⏱️</span>
         <span class="timer" data-expires="${deal.expiresAt}">${tLeft}</span>
       </div>`
    : '';

  return `
    <div class="deal-card" data-id="${deal.id}">
      <div class="deal-img-wrap">
        <img class="deal-img" src="${deal.image}" alt="${deal.name}" loading="lazy"
             onerror="this.src='https://placehold.co/400x300/f1f3f5/adb5bd?text=이미지없음'">
        <div class="deal-badges">${badgesHtml}</div>
        ${timerHtml}
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
          <div class="deal-rating">
            <span class="stars">${starsHtml(deal.rating)}</span>
            <span>(${deal.reviewCount.toLocaleString()})</span>
          </div>
        </div>
        <p class="deal-name">${deal.name}</p>
        <div class="deal-prices">
          <span class="original-price">
            ${deal.priceType === 'hprice'
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
            ${deal.inStock ? '<span class="meta-tag">✅ 재고있음</span>' : '<span class="meta-tag">❌ 품절</span>'}
            <span class="meta-tag savings">💰 ${fmt(savings)} 절약</span>
            ${affiliateBadge}
          </div>
          <a href="${href}"
             target="_blank"
             rel="noopener ${isAffiliate ? 'sponsored' : ''}"
             class="btn-buy"
             onclick="trackClick(${deal.id}, ${isAffiliate})">
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
    return;
  }
  $grid.innerHTML = state.filtered.map(renderCard).join('');
  $count.innerHTML = `특가 <strong>${state.filtered.length}</strong>개`;
}

/* ─── Filter & Sort ─── */
function applyFilters() {
  let list = [...state.deals];
  if (state.category === 'wish') {
    list = list.filter(d => state.wishlist.includes(d.id));
  } else if (state.category !== 'all') {
    list = list.filter(d => d.category === state.category);
  }
  if (state.query) {
    const q = state.query.toLowerCase();
    list = list.filter(d => d.name.toLowerCase().includes(q) || d.store.toLowerCase().includes(q));
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

/* ─── Affiliate click tracking ─── */
function trackClick(dealId, isAffiliate) {
  const deal = state.deals.find(d => d.id === dealId);
  if (!deal) return;
  // Google Analytics 이벤트 (GA 연동 시 활성화)
  if (window.gtag) {
    window.gtag('event', 'affiliate_click', {
      item_name: deal.name,
      store: deal.store,
      price: deal.salePrice,
      is_affiliate: isAffiliate,
    });
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
  const email = document.getElementById('alert-email')?.value?.trim();
  const cats  = [...document.querySelectorAll('.cat-checkbox input:checked')].map(cb => cb.value);

  if (!email || !email.includes('@')) { showToast('유효한 이메일을 입력해주세요', 'warn'); return; }
  if (!cats.length)                   { showToast('카테고리를 하나 이상 선택해주세요', 'warn'); return; }

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
        // 이미 구독 중인 이메일 — 성공으로 처리
        closeAlertModal();
        showToast('✅ 이미 구독 중입니다! 알림이 계속 발송됩니다.', 'success');
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

  // Kakao SDK 초기화
  if (KAKAO_JS_KEY && window.Kakao && !Kakao.isInitialized()) {
    Kakao.init(KAKAO_JS_KEY);
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
  updateHeroStats();
  document.getElementById('live-count').textContent = state.deals.length;
  applyFilters();
  setInterval(updateTimers, 1000);
}

document.addEventListener('DOMContentLoaded', init);
