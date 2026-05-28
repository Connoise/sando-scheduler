// Sando Scheduler service worker.
//
// Two caches:
//   - sando-shell-<v>: pinned app shell (CSS, manifest, icon).
//   - sando-pages-<v>: most-recently-viewed HTML pages, used as an
//     offline fallback when the network is unavailable.
//
// Strategy:
//   * Static under /static/* and the manifest    -> cache-first.
//   * Navigations and other GETs to same-origin  -> network-first,
//     populating sando-pages on success and falling back to the cached
//     copy when offline.
//   * Anything non-GET (POST /event, etc.)       -> bypass the cache.

const VERSION = "v1";
const SHELL_CACHE = `sando-shell-${VERSION}`;
const PAGES_CACHE = `sando-pages-${VERSION}`;
const SHELL_ASSETS = [
  "/static/app.css",
  "/static/icon.svg",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k !== SHELL_CACHE && k !== PAGES_CACHE)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

function isShellAsset(url) {
  return url.pathname.startsWith("/static/")
    || url.pathname === "/manifest.webmanifest";
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Cache-first for static + manifest.
  if (isShellAsset(url)) {
    event.respondWith(
      caches.match(req).then((cached) =>
        cached || fetch(req).then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(SHELL_CACHE).then((c) => c.put(req, copy));
          }
          return resp;
        })
      )
    );
    return;
  }

  // Network-first for everything else (HTML, /api/events).
  event.respondWith(
    fetch(req)
      .then((resp) => {
        if (resp && resp.ok && req.headers.get("accept")?.includes("text/html")) {
          const copy = resp.clone();
          caches.open(PAGES_CACHE).then((c) => c.put(req, copy));
        }
        return resp;
      })
      .catch(() =>
        caches.match(req).then((cached) =>
          cached || caches.match("/").then((root) => root || new Response(
            "<h1>Offline</h1><p>No cached version of this page.</p>",
            { status: 503, headers: { "Content-Type": "text/html" } }
          ))
        )
      )
  );
});
