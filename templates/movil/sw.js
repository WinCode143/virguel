{% load static %}// Service worker de la app de campo.
// - Archivos estáticos y pantallas de /app/: red primero; sin señal, lo último guardado.
// - Al cerrar sesión se borran las pantallas guardadas (privacidad en celulares compartidos).
const ESTATICO = "virguel-estatico-v2";
const PAGINAS = "virguel-paginas-v2";
const PREFIJO_STATIC = "{% get_static_prefix %}";
const INICIALES = ["{% static 'css/app.css' %}", "{% static 'img/icono.svg' %}", "{% static 'js/offline.js' %}"];

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(ESTATICO).then((c) => c.addAll(INICIALES)));
});
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => ![ESTATICO, PAGINAS].includes(k)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim())));

self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (u.origin !== location.origin) return;
  if (e.request.method === "POST" && u.pathname === "/logout/") {
    e.waitUntil(caches.delete(PAGINAS));
    return;
  }
  if (e.request.method !== "GET") return;
  const esEstatico = u.pathname.startsWith(PREFIJO_STATIC);
  const esPagina = u.pathname.startsWith("/app/") && !u.pathname.endsWith("sw.js");
  if (!esEstatico && !esPagina) return;
  e.respondWith(fetch(e.request).then((r) => {
    // sólo se guardan respuestas OK que no sean redirecciones al login
    if (r.ok && !r.redirected) {
      const copia = r.clone();
      caches.open(esEstatico ? ESTATICO : PAGINAS).then((c) => c.put(e.request, copia));
    }
    return r;
  }).catch(() => caches.match(e.request).then((r) => r || caches.match("/app/"))));
});
