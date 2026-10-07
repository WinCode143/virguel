/* Modo sin señal de la app de campo.
 * Los formularios con [data-offline] se envían por fetch. Si no hay conexión,
 * se guardan en IndexedDB (incluidas las fotos) y se reenvían solos al volver
 * la señal, en el mismo orden en que se cargaron.
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
  const todos = () => tx("readonly", (s) => s.getAll());
  const borrar = (id) => tx("readwrite", (s) => s.delete(id));

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

  async function aviso() {
    let n = 0;
    try { n = (await todos()).length; } catch (e) { return; }
    let el = document.getElementById("pendientes-offline");
    if (!n) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement("div");
      el.id = "pendientes-offline";
      el.className = "card";
      el.style.borderColor = "var(--aviso)";
      const cont = document.querySelector(".movil header");
      cont && cont.after(el);
    }
    el.innerHTML = `<span class="estado aviso">${n} envío${n > 1 ? "s" : ""} sin señal</span>
      <span class="muted"> · se mandan solos al volver la conexión</span>`;
  }

  let sincronizando = false;
  async function sincronizar() {
    if (sincronizando || !navigator.onLine) return;
    sincronizando = true;
    try {
      for (const item of await todos()) {
        let r;
        try {
          r = await fetch(item.url, { method: "POST", body: deserializar(item.datos), credentials: "same-origin" });
        } catch (e) { break; }  // sigue sin señal
        // 403 = sesión vencida / CSRF: se conserva hasta que vuelva a iniciar sesión
        if (r.status === 403 || r.url.includes("/login/")) break;
        await borrar(item.id);
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
    if (ev.submitter && ev.submitter.name) fd.append(ev.submitter.name, ev.submitter.value);
    const url = form.action || location.href;
    try {
      const r = await fetch(url, { method: "POST", body: fd, credentials: "same-origin" });
      // el servidor respondió: mostrar su página (redirección o formulario con errores)
      const html = await r.text();
      history.replaceState(null, "", r.url);
      document.open(); document.write(html); document.close();
    } catch (e) {
      await guardar({ url, datos: serializar(fd), cuando: Date.now() });
      alert("Sin señal: quedó guardado en el celular y se enviará solo cuando vuelva la conexión.");
      location.href = form.dataset.offline || "/app/";
    }
  });

  window.addEventListener("online", sincronizar);
  document.addEventListener("DOMContentLoaded", () => { aviso(); sincronizar(); });
})();
