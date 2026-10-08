/* Campos numéricos (escritorio, app y carga de datos):
 *   data-moneda  → muestra "$", separa miles con punto y decimales con coma; no deja escribir letras
 *   data-numero  → sólo números (con coma o punto)
 *   data-entero  → sólo enteros (cantidades de partes)
 * El servidor acepta el mismo formato (core/numeros.py). */
(function () {
  // ---- Campos numéricos: data-moneda ($, miles con punto, coma decimal), data-numero, data-entero
  const MILES = /^-?\d{1,3}(\.\d{3})+$/;
  function aNumero(v) {
    v = String(v || "").replace(/[$\s\u00a0]/g, "");
    if (!v) return null;
    if (v.includes(",") || MILES.test(v)) v = v.replace(/\./g, "").replace(",", ".");
    const n = Number(v);
    return Number.isFinite(n) ? n : NaN;
  }
  const fmtPesos = new Intl.NumberFormat("es-AR", { maximumFractionDigits: 2 });
  function prepararNumeros(raiz) {
    raiz.querySelectorAll("input[data-moneda]:not([data-listo])").forEach((inp) => {
      inp.dataset.listo = "1";
      inp.setAttribute("inputmode", "decimal");
      if (inp.type === "number") inp.type = "text";
      const caja = document.createElement("span");
      caja.className = "campo-moneda" + (inp.style.width ? "" : " lleno");
      inp.parentNode.insertBefore(caja, inp);
      caja.appendChild(inp);
      const formatear = () => {
        const n = aNumero(inp.value);
        if (n !== null && !Number.isNaN(n)) inp.value = fmtPesos.format(n);
      };
      formatear();
      inp.addEventListener("input", () => {
        const limpio = inp.value.replace(/[^\d.,-]/g, "");
        if (limpio !== inp.value) inp.value = limpio;
      });
      inp.addEventListener("blur", formatear);
    });
    raiz.querySelectorAll("input[data-numero]:not([data-listo])").forEach((inp) => {
      inp.dataset.listo = "1";
      inp.setAttribute("inputmode", "decimal");
      inp.addEventListener("input", () => {
        const limpio = inp.value.replace(/[^\d.,-]/g, "");
        if (limpio !== inp.value) inp.value = limpio;
      });
    });
    raiz.querySelectorAll("input[data-entero]:not([data-listo])").forEach((inp) => {
      inp.dataset.listo = "1";
      inp.setAttribute("inputmode", "numeric");
      inp.addEventListener("keydown", (ev) => {
        if ([".", ",", "e", "E", "+", "-"].includes(ev.key)) ev.preventDefault();
      });
      inp.addEventListener("input", () => {
        const limpio = inp.value.replace(/[^\d]/g, "");
        if (limpio !== inp.value) inp.value = limpio;
      });
    });
  }
  // antes de enviar: si quedó algo que no es número, se avisa en el campo
  document.addEventListener("submit", (ev) => {
    for (const inp of ev.target.querySelectorAll("input[data-moneda], input[data-numero]")) {
      if (inp.value && Number.isNaN(aNumero(inp.value))) {
        inp.setCustomValidity("Escribí sólo números (ej. 125.000,50).");
        inp.reportValidity();
        inp.addEventListener("input", () => inp.setCustomValidity(""), { once: true });
        ev.preventDefault();
        return;
      }
    }
  }, true);

  function iniciar() {
    // en la carga de datos (admin) los campos vienen marcados por el servidor
    prepararNumeros(document);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
})();
