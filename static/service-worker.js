const CACHE_NAME = "expense-tracker-v3";
// Only truly static, account-agnostic assets. Page navigations are
// deliberately excluded: the topbar is server-rendered with the logged-in
// user's email/business name baked into the HTML, so caching a page and
// falling back to it offline could show one account's identity to whoever
// is using the browser next (e.g. on a shared device after a logout).
const APP_SHELL = [
  "/static/css/style.css",
  "/static/js/common.js",
  "/static/js/app.js",
  "/static/js/history.js",
  "/static/js/transactions.js",
  "/static/js/budgets.js",
  "/static/js/insights.js",
  "/static/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

// Never cache API calls (data must always be fresh) or page navigations
// (the HTML carries the current account's identity) — only the static
// asset shell below.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || event.request.mode === "navigate" || url.pathname.startsWith("/api/")) {
    return;
  }
  if (!url.pathname.startsWith("/static/")) {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
