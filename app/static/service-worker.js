const CACHE_NAME = "central-aguas-app-v2";
const APP_SHELL = [
  "/app",
  "/manifest.webmanifest",
  "/static/img/logo_central.jpg",
  "/static/img/mascote_novo.png",
  "/static/assets/gotinha/emotions/alegria.webp",
  "/static/assets/gotinha/emotions/curiosidade.webp",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        const copy = response.clone();
        if (response.ok && new URL(event.request.url).origin === self.location.origin) {
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      });
    })
  );
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { title: "Central Águas", body: event.data ? event.data.text() : "" };
  }
  const title = payload.title || "Central Águas";
  const options = {
    body: payload.body || "Você tem uma novidade no app.",
    icon: payload.icon || "/static/icons/icon-192.png",
    badge: "/static/icons/icon-192.png",
    data: { url: payload.url || "/app" }
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/app";
  event.waitUntil(clients.openWindow(url));
});
