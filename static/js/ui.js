/* Interacciones comunes de la interfaz: tema, menú lateral, avisos. */
(function () {
  const raiz = document.documentElement;
  const ETIQUETA = { auto: "Automático", light: "Claro", dark: "Oscuro" };
  const ICONO = { auto: "auto", light: "sol", dark: "luna" };

  function temaGuardado() {
    try { return localStorage.getItem("tema") || "auto"; } catch (e) { return "auto"; }
  }
  function aplicar(tema) {
    if (tema === "light" || tema === "dark") raiz.dataset.theme = tema; else delete raiz.dataset.theme;
    try { tema === "auto" ? localStorage.removeItem("tema") : localStorage.setItem("tema", tema); } catch (e) {}
    const oscuro = tema === "dark" || (tema === "auto" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", oscuro ? "#181817" : "#2a78d6"));
    document.querySelectorAll("[data-tema-actual]").forEach((el) => {
      const use = el.querySelector("use");
      if (use) use.setAttribute("href", use.getAttribute("href").replace(/#.*/, "#" + ICONO[tema]));
      el.setAttribute("title", "Tema: " + ETIQUETA[tema]);
      el.setAttribute("aria-label", "Cambiar tema (actual: " + ETIQUETA[tema] + ")");
    });
    document.querySelectorAll("[data-tema]").forEach((b) => b.setAttribute("aria-checked", b.dataset.tema === tema));
    document.dispatchEvent(new CustomEvent("tema-cambiado"));
  }
  window.virguelTema = aplicar;

  document.addEventListener("click", (ev) => {
    const opcion = ev.target.closest("[data-tema]");
    if (opcion) { aplicar(opcion.dataset.tema); opcion.closest(".tema-menu")?.classList.remove("abierto"); return; }
    const boton = ev.target.closest("[data-tema-actual]");
    const menu = document.querySelector(".tema-menu.abierto");
    if (boton) {
      const contenedor = boton.closest(".tema-menu");
      if (contenedor) { contenedor.classList.toggle("abierto"); }
      else {  // sin menú: rota automático → claro → oscuro
        const orden = ["auto", "light", "dark"];
        aplicar(orden[(orden.indexOf(temaGuardado()) + 1) % 3]);
      }
      return;
    }
    if (menu && !ev.target.closest(".tema-menu")) menu.classList.remove("abierto");
    // menú lateral en pantallas chicas
    if (ev.target.closest("[data-menu-toggle]")) {
      document.getElementById("sidebar")?.classList.toggle("abierto");
      document.querySelector(".sidebar-velo")?.classList.toggle("visible");
    } else if (ev.target.closest(".sidebar-velo")) {
      document.getElementById("sidebar")?.classList.remove("abierto");
      ev.target.classList.remove("visible");
    }
    const cerrar = ev.target.closest(".mensajes li button");
    if (cerrar) cerrar.parentElement.remove();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") document.querySelector(".tema-menu.abierto")?.classList.remove("abierto");
    // "/" enfoca el buscador
    if (ev.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) {
      const b = document.querySelector(".buscador input");
      if (b) { ev.preventDefault(); b.focus(); }
    }
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (temaGuardado() === "auto") aplicar("auto");
  });

  // grupos del menú lateral: recordar cuáles quedaron abiertos
  function gruposGuardados() { try { return JSON.parse(localStorage.getItem("menu-abierto") || "[]"); } catch (e) { return []; } }
  function prepararMenu() {
    const abiertos = new Set(gruposGuardados());
    document.querySelectorAll("details.nav-grupo").forEach((d) => {
      const clave = d.querySelector("summary").textContent.trim();
      if (abiertos.has(clave)) d.open = true;
      d.addEventListener("toggle", () => {
        const s = new Set(gruposGuardados());
        d.open ? s.add(clave) : s.delete(clave);
        try { localStorage.setItem("menu-abierto", JSON.stringify([...s])); } catch (e) {}
      });
    });
    document.querySelector(".nav-item.activo")?.scrollIntoView({ block: "nearest" });
  }


  document.addEventListener("DOMContentLoaded", () => {
    aplicar(temaGuardado());
    prepararMenu();
    // los avisos se cierran solos (los de error quedan hasta que se cierren)
    document.querySelectorAll(".mensajes li").forEach((li) => {
      li.insertAdjacentHTML("beforeend", '<button type="button" aria-label="Cerrar">✕</button>');
      if (!li.classList.contains("error") && !li.classList.contains("warning")) {
        setTimeout(() => { li.classList.add("saliendo"); setTimeout(() => li.remove(), 350); }, 5000);
      }
    });
  });
})();
