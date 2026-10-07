{% load static %}// Service worker: guarda la "cáscara" de la app para que abra rápido y sin señal.
const CACHE = "virguel-v1";
const ESTATICOS = ["{% static 'css/app.css' %}", "{% static 'img/icono.svg' %}"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ESTATICOS))));
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))));
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  // Red primero. Sólo se guardan archivos estáticos (nunca páginas con datos personales).
  e.respondWith(fetch(e.request).then((r) => {
    const u = new URL(e.request.url);
    if (r.ok && u.origin === location.origin && u.pathname.startsWith("{% get_static_prefix %}")) {
      const copia = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copia));
    }
    return r;
  }).catch(() => caches.match(e.request)));
});
