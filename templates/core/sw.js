// Service Worker Vatel Smart Canteen :
// Met en cache UNIQUEMENT les fichiers statiques publics, /menu/ et /hors-ligne/.
// Ne met JAMAIS en cache les pages privées (solde, historique, ticket, parent, équipe, admin).

const CACHE_NAME = "vsc-public-v2";
const PUBLIC_ASSETS = [
    "/menu/",
    "/hors-ligne/",
    "/static/css/fonts.css",
    "/static/vendor/bootstrap.min.css",
    "/static/vendor/bootstrap-icons.css",
    "/static/css/tokens.css",
    "/static/css/app.css",
    "/static/vendor/bootstrap.bundle.min.js",
    "/static/vendor/htmx.min.js",
    "/static/js/app.js",
    "/static/js/pwa.js",
    "/static/img/logo-vatel.svg",
    "/static/img/logo-vatel-dark.svg",
    "/static/fonts/vatel_48d1e9cdfb.woff2",
    "/static/fonts/vatel_f7b83de3ad.woff2",
    "/static/fonts/vatel_faccb37f71.woff2"
];

const PRIVATE_PREFIXES = [
    "/portefeuille/",
    "/reservations/",
    "/parents/",
    "/equipe/",
    "/administration/",
    "/compte/",
    "/notifications/",
    "/paiements/",
    "/gestion-securisee/"
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(PUBLIC_ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", (event) => {
    if (event.request.method !== "GET") {
        return;
    }
    const url = new URL(event.request.url);
    if (url.origin !== self.location.origin) {
        return;
    }
    if (PRIVATE_PREFIXES.some((prefix) => url.pathname.startsWith(prefix))) {
        return;
    }

    const isStatic = url.pathname.startsWith("/static/");
    const isPublicMenu = url.pathname === "/menu/" || url.pathname === "/hors-ligne/";
    if (!isStatic && !isPublicMenu) {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                if (response && response.ok) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
                }
                return response;
            })
            .catch(() =>
                caches.match(event.request).then((cached) => cached || caches.match("/hors-ligne/"))
            )
    );
});
