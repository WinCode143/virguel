/* Dibuja los gráficos declarados en la página.
 * <canvas data-grafico="id-json"></canvas>
 * <script type="application/json" id="id-json">
 *   {"tipo":"bar|line|doughnut","etiquetas":[...],
 *    "series":[{"nombre":"...","datos":[...],"serie":1,"estado":"ok|aviso|critico"}],
 *    "apilado":false,"horizontal":false,"formato":"num|pct|pesos"}
 * </script>
 */
(function () {
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmt = {
    num: (v) => Number(v).toLocaleString("es-AR", { maximumFractionDigits: 1 }),
    pct: (v) => Number(v).toLocaleString("es-AR", { maximumFractionDigits: 0 }) + "%",
    pesos: (v) => "$" + Number(v).toLocaleString("es-AR", { maximumFractionDigits: 0 }),
  };
  const graficos = [];

  function color(s) {
    if (s.estado) return css("--" + s.estado);
    return css("--s" + (s.serie || 1));
  }

  function crear(canvas) {
    const cfg = JSON.parse(document.getElementById(canvas.dataset.grafico).textContent);
    const f = fmt[cfg.formato || "num"];
    const tipo = cfg.tipo || "bar";
    const multi = cfg.series.length > 1;
    const ink2 = css("--ink-2"), grid = css("--grid"), muted = css("--muted"), surface = css("--surface");
    const datasets = cfg.series.map((s) => {
      const c = s.colores ? s.colores.map((k) => css(k)) : color(s);
      const t = s.tipo || tipo;  // una serie puede ser línea dentro de un gráfico de barras
      const base = { label: s.nombre, data: s.datos, backgroundColor: c, borderColor: tipo === "doughnut" ? surface : c };
      if (t === "line") Object.assign(base, { borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.25,
        fill: false, pointBackgroundColor: c, borderDash: s.punteada ? [6, 4] : undefined });
      if (t === "bar") Object.assign(base, { borderRadius: 4, borderSkipped: "start", borderWidth: 0,
        maxBarThickness: 28, categoryPercentage: 0.75, barPercentage: 0.9, stack: s.pila });
      if (tipo === "doughnut") Object.assign(base, { borderWidth: 2 });
      if (s.tipo) Object.assign(base, { type: s.tipo, order: -1 });  // la línea se dibuja encima
      return base;
    });
    const ejes = tipo === "doughnut" ? {} : {
      x: { stacked: !!cfg.apilado, grid: { display: !!cfg.horizontal, color: grid }, border: { color: css("--axis") },
           ticks: { color: muted, maxRotation: 0, autoSkip: true } },
      y: { stacked: !!cfg.apilado, grid: { display: !cfg.horizontal, color: grid }, border: { display: false },
           beginAtZero: true, ticks: { color: muted, callback: (v) => f(v) }, max: cfg.max },
    };
    if (cfg.horizontal) {
      // en horizontal la escala numérica es x
      ejes.x.beginAtZero = true; ejes.x.max = cfg.max; delete ejes.y.max;
      ejes.x.ticks.callback = (v) => f(v);
      ejes.y.ticks = { color: ink2, autoSkip: false };  // en horizontal se muestran todas las etiquetas
    }
    return new Chart(canvas, {
      type: tipo,
      data: { labels: cfg.etiquetas, datasets },
      options: {
        responsive: true, maintainAspectRatio: false, indexAxis: cfg.horizontal ? "y" : "x",
        interaction: { mode: tipo === "line" ? "index" : "nearest", intersect: tipo !== "line" },
        animation: { duration: 250 },
        scales: ejes,
        cutout: tipo === "doughnut" ? "62%" : undefined,
        plugins: {
          legend: { display: multi || tipo === "doughnut", position: "bottom",
                    labels: { color: ink2, boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 2 } },
          tooltip: { backgroundColor: css("--surface"), titleColor: css("--ink"), bodyColor: ink2,
                     borderColor: css("--axis"), borderWidth: 1, padding: 10, boxPadding: 4,
                     callbacks: { label: (ctx) => {
                       const v = typeof ctx.parsed === "number" ? ctx.parsed : (cfg.horizontal ? ctx.parsed.x : ctx.parsed.y);
                       return `${tipo === "doughnut" ? ctx.label : ctx.dataset.label}: ${f(v)}`; } } },
        },
      },
    });
  }

  function dibujarTodo() {
    graficos.splice(0).forEach((g) => g.destroy());
    document.querySelectorAll("canvas[data-grafico]").forEach((c) => graficos.push(crear(c)));
  }
  document.addEventListener("DOMContentLoaded", dibujarTodo);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", dibujarTodo);
})();
