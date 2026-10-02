/* Sona web installé (PWA) : l'appli s'ouvre même sans réseau ou sur un
   réseau lent. Seuls les fichiers du site passent par ici — l'API, les
   flux audio et les pochettes (autres adresses) vont directement au réseau.

   Page, script et styles : réseau d'abord (une mise à jour du site est prise
   tout de suite), la copie gardée ne sert que hors connexion. Icônes : copie
   gardée d'abord. */

const CACHE = "sona-shell-v1";
const SHELL = ["./", "app.css", "app.js", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  const scope = new URL(self.registration.scope);
  if (url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname)) return;
  // Flux audio servi sous /web ? jamais : seulement les fichiers du site.
  if (request.headers.has("range")) return;

  if (url.pathname.includes("/icons/")) {
    event.respondWith(caches.match(request).then((hit) => hit || fetch(request).then((res) => keep(request, res))));
    return;
  }
  const isPage = request.mode === "navigate";
  event.respondWith((async () => {
    try {
      const res = await fetch(request);
      return keep(isPage ? new Request(scope.href) : request, res);
    } catch {
      const hit = await caches.match(isPage ? scope.href : request, { ignoreSearch: true });
      return hit || Response.error();
    }
  })());
});

function keep(request, response) {
  if (response && response.ok && response.type === "basic") {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(request, copy)).catch(() => {});
  }
  return response;
}
