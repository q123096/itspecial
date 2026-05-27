/* =====================================================
   ITSpecial Service Worker — PWA 오프라인 지원
   전략: Network-first (딜 데이터는 항상 최신),
         Cache-fallback (오프라인 시 캐시 반환)
   ===================================================== */

const CACHE_NAME    = 'itspecial-v1';
const CACHE_STATIC  = 'itspecial-static-v1';

// 정적 자산 (앱 셸) — 설치 시 미리 캐시
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/css/style.css',
  '/js/app.js',
];

// 캐시하지 않을 경로 (항상 네트워크)
const BYPASS_PATHS  = [
  '/admin.html',
  '/unsubscribe.html',
  'supabase.co',
  'formspree.io',
  'resend.com',
  'api.github.com',
];


// ── Install: 정적 자산 미리 캐시 ──────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_STATIC).then(cache =>
      cache.addAll(STATIC_ASSETS).catch(() => {})  // 실패해도 설치 계속
    )
  );
  self.skipWaiting();
});


// ── Activate: 오래된 캐시 정리 ────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME && k !== CACHE_STATIC)
          .map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});


// ── Fetch: 요청 인터셉트 ──────────────────────────────────────
self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // 바이패스: 어드민·외부 API는 항상 네트워크
  if (BYPASS_PATHS.some(p => request.url.includes(p))) return;

  // deals.json / price_history.json / msrp.json — Network-first, Cache-fallback
  if (url.pathname.includes('/data/') && url.pathname.endsWith('.json')) {
    event.respondWith(networkFirstWithCache(request, CACHE_NAME));
    return;
  }

  // 정적 자산 (CSS/JS/HTML) — Cache-first, Network-fallback
  if (
    request.method === 'GET' &&
    (url.hostname === self.location.hostname || url.hostname === '')
  ) {
    event.respondWith(cacheFirstWithNetwork(request));
    return;
  }
});


// Cache-first: 캐시 있으면 캐시, 없으면 네트워크 후 캐시 저장
async function cacheFirstWithNetwork(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const res = await fetch(request);
    if (res.ok) {
      const cache = await caches.open(CACHE_STATIC);
      cache.put(request, res.clone());
    }
    return res;
  } catch {
    return new Response('오프라인 상태입니다.', {
      status: 503, headers: { 'Content-Type': 'text/plain;charset=utf-8' },
    });
  }
}


// Network-first: 네트워크 시도 → 실패 시 캐시 반환
async function networkFirstWithCache(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(request);
    if (res.ok) cache.put(request, res.clone());
    return res;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    return new Response('[]', {
      status: 200, headers: { 'Content-Type': 'application/json' },
    });
  }
}
