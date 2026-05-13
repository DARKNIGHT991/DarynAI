// ================================================================
// Daryn AI — Service Worker (PWA)
// ================================================================

const CACHE_NAME    = "daryn-ai-v3";
const OFFLINE_URL   = "/";

// Ресурсы для кэширования при установке
const STATIC_ASSETS = [
  "/",
  "/manifest.json",
  "/static/css/main.css",
  "/static/js/app.js",
  "/icon-192.png",
  "/icon-512.png",
  "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;900&family=JetBrains+Mono:wght@400;700&display=swap",
  "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
  "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css",
  "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js",
];

// ── INSTALL ────────────────────────────────────────────────────
self.addEventListener("install", event => {
  console.log("[SW] Installing Daryn AI Service Worker...");
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log("[SW] Caching static assets");
      // Кэшируем по одному чтобы одна ошибка не ломала всё
      return Promise.allSettled(
        STATIC_ASSETS.map(url =>
          cache.add(url).catch(err =>
            console.warn(`[SW] Failed to cache: ${url}`, err)
          )
        )
      );
    })
  );
  self.skipWaiting();
});

// ── ACTIVATE ───────────────────────────────────────────────────
self.addEventListener("activate", event => {
  console.log("[SW] Activating Daryn AI Service Worker...");
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => {
            console.log(`[SW] Deleting old cache: ${key}`);
            return caches.delete(key);
          })
      )
    )
  );
  self.clients.claim();
});

// ── FETCH ──────────────────────────────────────────────────────
self.addEventListener("fetch", event => {
  const { request } = event;
  const url = new URL(request.url);

  // Пропускаем не-GET запросы (POST к /chat, /login и т.д.)
  if (request.method !== "GET") return;

  // Пропускаем chrome-extension и другие схемы
  if (!url.protocol.startsWith("http")) return;

  // API запросы — только сеть, без кэша
  const apiPaths = [
    "/auth", "/chat", "/chats", "/login", "/register", "/history",
    "/my_plan", "/plans", "/upgrade_plan",
    "/transcribe", "/update_profile", "/clear_history",
    "/admin"
  ];
  if (apiPaths.some(path => url.pathname.startsWith(path))) {
    event.respondWith(
      fetch(request).catch(() => {
        // Если API недоступен — возвращаем JSON ошибку
        return new Response(
          JSON.stringify({
            status: "error",
            message: "Нет подключения к интернету"
          }),
          {
            status: 503,
            headers: { "Content-Type": "application/json" }
          }
        );
      })
    );
    return;
  }

  // Стратегия: Cache First → Network Fallback
  event.respondWith(
    caches.match(request).then(cached => {
      if (cached) {
        // Обновляем кэш в фоне
        fetch(request)
          .then(response => {
            if (response && response.status === 200) {
              caches.open(CACHE_NAME).then(cache => {
                cache.put(request, response.clone());
              });
            }
          })
          .catch(() => {});
        return cached;
      }

      // Нет в кэше — идём в сеть
      return fetch(request)
        .then(response => {
          // Кэшируем успешные GET ответы
          if (
            response &&
            response.status === 200 &&
            response.type === "basic"
          ) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then(cache => {
              cache.put(request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          // Если совсем нет сети — показываем главную из кэша
          if (request.destination === "document") {
            return caches.match(OFFLINE_URL);
          }
        });
    })
  );
});

// ── PUSH УВЕДОМЛЕНИЯ (задел на будущее) ───────────────────────
self.addEventListener("push", event => {
  if (!event.data) return;
  const data = event.data.json();
  self.registration.showNotification(data.title || "Daryn AI", {
    body:    data.body    || "",
    icon:    "/icon-192.png",
    badge:   "/icon-192.png",
    vibrate: [200, 100, 200],
    data:    { url: data.url || "/" }
  });
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil(
    clients.openWindow(event.notification.data.url || "/")
  );
});