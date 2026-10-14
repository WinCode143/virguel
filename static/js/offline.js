/* Modo sin señal de la app de campo.
 * Los formularios con [data-offline] se envían por fetch. Si no hay conexión,
 * se guardan en IndexedDB (incluidas las fotos) y se reenvían solos al volver
 * la señal, en el mismo orden en que se cargaron.
 *
 * Reglas de la sincronización (ver core/offline.py):
 *  - cada envío lleva un identificador (_id_operacion): si llega dos veces, el
 *    servidor no lo aplica de nuevo;
 *  - un pendiente se borra SÓLO cuando el servidor confirma {ok: true};
 *  - si el servidor rechaza los datos, el pendiente queda "con error" para
 *    corregirlo o descartarlo a mano (nunca se pierde en silencio);
 *  - sin red, error del servidor (5xx) o sesión vencida: se conserva y se reintenta;
 *  - cada pendiente pertenece al usuario que lo cargó: con otra sesión no se envía.
 */
(function () {
  const DB = "virguel-offline", STORE = "pendientes";

  function abrir() {
    return new Promise((ok, mal) => {
      const r = indexedDB.open(DB, 1);
      r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
      r.onsuccess = () => ok(r.result);
      r.onerror = () => mal(r.error);
    });
  }
  async function tx(modo, fn) {
    const db = await abrir();
    return new Promise((ok, mal) => {
      const t = db.transaction(STORE, modo);
      const res = fn(t.objectStore(STORE));
      t.oncomplete = () => ok(res && res.result);
      t.onerror = () => mal(t.error);
    });
  }
  const guardar = (item) => tx("readwrite", (s) => s.add(item));
  const actualizar = (item) => tx("readwrite", (s) => s.put(item));
  const todos = () => tx("readonly", (s) => s.getAll());
  const borrar = (id) => tx("readwrite", (s) => s.delete(id));

  const usuario = () => (document.body && document.body.dataset.usuario) || null;
  const mios = async () => (await todos()).filter((i) => !i.usuario || i.usuario === usuario());

  function nuevoId() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    const b = crypto.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
    const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
    return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
  }

  function serializar(fd) {
    // FormData -> lista de pares (los File se guardan como Blob)
    return Array.from(fd.entries()).map(([k, v]) =>
      v instanceof File ? [k, { blob: v, nombre: v.name }] : [k, v]);
  }
  function deserializar(pares) {
    const fd = new FormData();
    for (const [k, v] of pares) {
      if (v && v.blob) { if (v.blob.size) fd.append(k, v.blob, v.nombre); } else fd.append(k, v);
    }
    return fd;
  }
  function escapar(t) {
    return String(t || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  async function aviso() {
    let lista = [], ajenos = 0;
    try {
      const t = await todos();
      lista = t.filter((i) => !i.usuario || i.usuario === usuario());
      ajenos = t.length - lista.length;
    } catch (e) { return; }
    const pendientes = lista.filter((i) => i.estado !== "error");
    const conError = lista.filter((i) => i.estado === "error");
    let el = document.getElementById("pendientes-offline");
    if (!lista.length && !ajenos) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement("div");
      el.id = "pendientes-offline";
      el.className = "card";
      el.style.borderColor = "var(--aviso)";
      const cont = document.querySelector(".movil header");
      if (!cont) return;
      cont.after(el);
    }
    let html = "";
    if (pendientes.length) {
      html += `<div><span class="estado aviso">${pendientes.length} envío${pendientes.length > 1 ? "s" : ""} sin enviar</span>
        <span class="muted"> · se mandan solos al volver la conexión</span></div>`;
    }
    for (const i of conError) {
      html += `<div style="margin-top:.5rem"><span class="estado critico">No aceptado</span>
        <span> ${escapar(i.mensaje || "El servidor no aceptó el envío.")}</span>
        <span class="muted" style="font-size:.8rem"> (${new Date(i.cuando).toLocaleString()})</span><br>
        ${i.html ? `<button class="btn sec" type="button" data-corregir="${i.id}">Corregir</button>` : ""}
        <button class="btn sec" type="button" data-reintentar="${i.id}">Reintentar</button>
        <button class="btn sec" type="button" data-descartar="${i.id}">Descartar</button></div>`;
    }
    if (ajenos) {
      html += `<div class="muted" style="margin-top:.5rem;font-size:.85rem">${ajenos} envío${ajenos > 1 ? "s" : ""} de otro usuario guardado${ajenos > 1 ? "s" : ""} en este celular: se envían cuando esa persona vuelva a ingresar.</div>`;
    }
    el.innerHTML = html;
  }

  document.addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-corregir],[data-reintentar],[data-descartar]");
    if (!b) return;
    const id = Number(b.dataset.corregir || b.dataset.reintentar || b.dataset.descartar);
    const item = (await mios()).find((i) => i.id === id);
    if (!item) return;
    if (b.dataset.descartar !== undefined) {
      if (!confirm("¿Descartar este envío? Los datos cargados se pierden.")) return;
      await borrar(id);
      aviso();
    } else if (b.dataset.reintentar !== undefined) {
      item.estado = "pendiente"; delete item.mensaje; delete item.html;
      await actualizar(item);
      sincronizar();
    } else {
      // Se muestra el formulario tal como lo devolvió el servidor (con los errores marcados).
      // El pendiente se borra recién cuando el envío corregido sea aceptado.
      try { sessionStorage.setItem("virguel-corrigiendo", String(id)); } catch (e) { /* sin storage */ }
      history.replaceState(null, "", item.url);
      document.open(); document.write(item.html); document.close();
    }
  });

  let sincronizando = false, espera = 15000, reintento = null;
  function reintentarMasTarde() {
    clearTimeout(reintento);
    reintento = setTimeout(sincronizar, espera);
    espera = Math.min(espera * 2, 10 * 60 * 1000);
  }

  async function sincronizar() {
    if (sincronizando || !navigator.onLine || !usuario()) return;
    sincronizando = true;
    try {
      for (const item of await mios()) {
        if (item.estado === "error") continue;
        let r;
        try {
          r = await fetch(item.url, { method: "POST", body: deserializar(item.datos), credentials: "same-origin",
                                      headers: { "X-Virguel-Sync": "1", "Accept": "application/json" } });
        } catch (e) { reintentarMasTarde(); break; }  // sigue sin señal
        // 403 = sesión vencida / CSRF: se conserva hasta que vuelva a iniciar sesión
        if (r.status === 403 || r.url.includes("/login/")) break;
        // error del servidor: se conserva y se reintenta (sin saltear, para respetar el orden)
        if (r.status >= 500) { reintentarMasTarde(); break; }
        let j = null;
        if ((r.headers.get("Content-Type") || "").includes("application/json")) {
          try { j = await r.json(); } catch (e) { j = null; }
        }
        if (j && j.ok === true) {
          await borrar(item.id);
          espera = 15000;
          continue;
        }
        // Rechazado: queda guardado con el motivo, para corregir o descartar a mano.
        item.estado = "error";
        item.mensaje = (j && j.mensaje) || `El servidor respondió ${r.status}.`;
        if (j && j.html) item.html = j.html;
        await actualizar(item);
      }
    } finally {
      sincronizando = false;
      aviso();
    }
  }

  document.addEventListener("submit", async (ev) => {
    const form = ev.target;
    if (!form.matches("form[data-offline]") || !window.indexedDB) return;
    ev.preventDefault();
    const fd = new FormData(form);
    // fecha local en que se cargó: si se envía más tarde, el servidor la respeta
    const d = new Date();
    fd.append("_fecha_cliente", `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
    fd.append("_momento_cliente", d.toISOString());  // hora exacta de la fichada
    if (!fd.get("_id_operacion")) fd.append("_id_operacion", nuevoId());
    if (ev.submitter && ev.submitter.name) fd.append(ev.submitter.name, ev.submitter.value);
    const url = form.action || location.href;
    let corrigiendo = null;
    try { corrigiendo = Number(sessionStorage.getItem("virguel-corrigiendo")) || null; } catch (e) { /* sin storage */ }
    try {
      const r = await fetch(url, { method: "POST", body: fd, credentials: "same-origin" });
      // el servidor respondió: mostrar su página (redirección o formulario con errores)
      if (corrigiendo && r.redirected && !r.url.includes("/login/")) {
        await borrar(corrigiendo);  // el envío corregido fue aceptado
        try { sessionStorage.removeItem("virguel-corrigiendo"); } catch (e) { /* sin storage */ }
      }
      const html = await r.text();
      history.replaceState(null, "", r.url);
      document.open(); document.write(html); document.close();
    } catch (e) {
      await guardar({ url, datos: serializar(fd), cuando: Date.now(), usuario: usuario(), estado: "pendiente" });
      alert("Sin señal: quedó guardado en el celular y se enviará solo cuando vuelva la conexión.");
      location.href = form.dataset.offline || "/app/";
    }
  });

  // Formularios con [data-gps]: completar ubicación en los campos ocultos lat/lng
  function ubicar() {
    const forms = document.querySelectorAll("form[data-gps]");
    if (!forms.length || !navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((pos) => {
      forms.forEach((f) => {
        const lat = f.querySelector("[name=lat]"), lng = f.querySelector("[name=lng]");
        if (lat) lat.value = pos.coords.latitude.toFixed(6);
        if (lng) lng.value = pos.coords.longitude.toFixed(6);
        const nota = f.querySelector(".gps-estado");
        if (nota) nota.textContent = "Ubicación lista ✓";
      });
    }, () => forms.forEach((f) => { const n = f.querySelector(".gps-estado"); if (n) n.textContent = "Sin ubicación (revisá permisos)"; }),
    { timeout: 10000, enableHighAccuracy: true });
  }

  window.addEventListener("online", () => { espera = 15000; sincronizar(); });

  // Avisar al service worker quién está usando la app (borra pantallas guardadas de otra cuenta)
  function avisarIdentidad() {
    if (!navigator.serviceWorker || !navigator.serviceWorker.controller) return;
    navigator.serviceWorker.controller.postMessage({ tipo: "usuario", usuario: usuario() || "" });
  }
  document.addEventListener("DOMContentLoaded", avisarIdentidad);

  // Pendientes de más de 7 días: el servidor ya no respeta su fecha; quedan para revisar o descartar
  const VENCE_MS = 7 * 24 * 3600 * 1000;
  async function vencer() {
    try {
      for (const i of await mios()) {
        if (i.estado !== "error" && Date.now() - i.cuando > VENCE_MS) {
          i.estado = "error";
          i.mensaje = "Envío vencido (más de 7 días sin enviarse): revisalo antes de reintentar o descartalo.";
          await actualizar(i);
        }
      }
    } catch (e) { /* sin IndexedDB */ }
  }
  document.addEventListener("DOMContentLoaded", ubicar);
  document.addEventListener("DOMContentLoaded", async () => { await vencer(); aviso(); sincronizar(); });
})();
