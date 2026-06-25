// 芸陽バス 接近情報 — Service Worker
//
// 方針:
//  - アプリシェル（HTML/CSS/JS/アイコン）はキャッシュし、オフラインでも起動可能にする
//  - バス時刻などのAPI応答は「絶対にキャッシュしない」（古い到着予測を見せないため）
//    → 常に network-only。オフライン時は素直に失敗させる
//  - シェルは stale-while-revalidate、画面遷移は network-first(+シェルfallback)

const VERSION = "geiyo-bus-v1";
const SHELL_CACHE = `shell-${VERSION}`;

const SHELL = [
  "/",
  "/app/app.js",
  "/app/styles.css",
  "/manifest.webmanifest",
  "/app/icons/icon-192.png",
  "/app/icons/icon-512.png",
];

// APIパス（リアルタイム/動的データ。キャッシュ禁止）
const API_PREFIXES = [
  "/arrivals", "/dashboard", "/stops", "/favorites",
  "/alerts", "/health", "/agencies",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function isApi(url) {
  return API_PREFIXES.some((p) => url.pathname === p || url.pathname.startsWith(p + "/"));
}
function isShellAsset(url) {
  return (
    url.pathname === "/" ||
    url.pathname === "/manifest.webmanifest" ||
    url.pathname.startsWith("/app/")
  );
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // 別オリジン（地図CDN等）はそのままネットワークへ
  if (url.origin !== self.location.origin) return;

  // APIは常にネットワーク（キャッシュしない）
  if (isApi(url)) {
    event.respondWith(fetch(req));
    return;
  }

  // 画面遷移: network-first、ダメならシェル(index)を返す
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() => caches.match("/"))
    );
    return;
  }

  // シェル資産: stale-while-revalidate
  if (isShellAsset(url)) {
    event.respondWith(
      caches.open(SHELL_CACHE).then(async (cache) => {
        const cached = await cache.match(req);
        const network = fetch(req).then((res) => {
          if (res && res.ok) cache.put(req, res.clone());
          return res;
        }).catch(() => cached);
        return cached || network;
      })
    );
    return;
  }

  // それ以外はネットワーク
  event.respondWith(fetch(req).catch(() => caches.match(req)));
});
