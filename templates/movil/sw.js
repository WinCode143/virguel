{% load static %}// Service worker de la app de campo.
// - Archivos estáticos y pantallas de /app/: red primero; sin señal, lo último guardado.
// - Al cerrar sesión se borran las pantallas guardadas (privacidad en celulares compartidos).
const ESTATICO = "virguel-estatico-v6";
const PAGINAS = "virguel-paginas-v6";
const META = "virguel-meta";
const PREFIJO_STATIC = "{% get_static_prefix %}";
const INICIALES = ["{% static 'css/app.css' %}", "{% static 'img/icono.svg' %}", "{% static 'js/offline.js' %}"];

self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(ESTATICO).then((c) => c.addAll(INICIALES)));
});
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => ![ESTATICO, PAGINAS, META].includes(k)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim())));
// (META guarda sólo el identificador del último usuario; no se borra en activate para poder comparar)

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

// Identidad: la página avisa qué usuario está activo. Si cambió (otra cuenta en el mismo celular,
// sesión vencida y nuevo ingreso) o no hay sesión, se borran las pantallas guardadas del anterior.
self.addEventListener("message", (e) => {
  if (!e.data || e.data.tipo !== "usuario") return;
  const actual = String(e.data.usuario || "");
  e.waitUntil(caches.open(META).then(async (c) => {
    const r = await c.match("/__usuario");
    const anterior = r ? await r.text() : null;
    if (anterior !== actual) {
      await caches.delete(PAGINAS);
      await c.put("/__usuario", new Response(actual));
    }
  }));
});

// Notificaciones push (avisos del sistema al celular)
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data.json(); } catch (_) { d = { titulo: "Virguel", texto: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.titulo || "Virguel", {
    body: d.texto || "", icon: "{% static 'img/icono.svg' %}", data: { url: d.url || "/app/" } }));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(self.clients.openWindow(e.notification.data.url));
});
