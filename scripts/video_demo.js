// Video de las principales funciones (escritorio + app móvil), con subtítulos en pantalla.
//
// Requiere el servidor con los datos de `generar_demo` (contraseña virguel2026) y Playwright:
//   ORDEN=<id de una orden abierta de t001> SALIDA=/tmp/video node scripts/video_demo.js
// Deja un .webm por escena en SALIDA; scripts/video_demo.sh los une en un .mp4.
const { chromium } = require(process.env.PLAYWRIGHT || 'playwright');
const BASE = process.env.BASE || 'http://localhost:8000';
const SALIDA = process.env.SALIDA || '/tmp/video';
const ORDEN = process.env.ORDEN;
const espera = (ms) => new Promise((r) => setTimeout(r, ms));

async function subtitulo(page, titulo, texto) {
  await page.evaluate(([t, x]) => {
    let d = document.getElementById('__sub');
    if (!d) {
      d = document.createElement('div');
      d.id = '__sub';
      d.style.cssText = 'position:fixed;left:50%;bottom:22px;transform:translateX(-50%);z-index:99999;' +
        'max-width:min(92vw,980px);background:rgba(15,23,42,.92);color:#fff;padding:12px 18px;border-radius:12px;' +
        'font:500 17px/1.35 Inter,system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.35);text-align:center';
      document.body.appendChild(d);
    }
    d.innerHTML = `<div style="font-weight:700;font-size:19px;margin-bottom:4px">${t}</div><div>${x}</div>`;
  }, [titulo, texto]);
}

async function scroll(page, px, pasos = 6) {
  for (let i = 0; i < pasos; i++) {
    await page.mouse.wheel(0, px / pasos);
    await espera(350);
  }
}

async function login(page, usuario) {
  await page.goto(`${BASE}/login/`);
  await page.fill('input[name=username]', usuario);
  await page.fill('input[name=password]', 'virguel2026');
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], form button')]);
}

async function escena(browser, nombre, opciones, fn) {
  const ctx = await browser.newContext({ ...opciones, recordVideo: { dir: `${SALIDA}/${nombre}`, size: opciones.viewport } });
  const page = await ctx.newPage();
  try { await fn(page); } catch (e) { console.log(`escena ${nombre}: ${e.message}`); }
  await ctx.close();
  console.log(`escena ${nombre} lista`);
}

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
  const escritorio = { viewport: { width: 1280, height: 720 }, colorScheme: 'light' };
  const celular = { viewport: { width: 390, height: 720 }, isMobile: true, hasTouch: true, colorScheme: 'light',
                    serviceWorkers: 'block' };

  await escena(browser, '01_gerencia', escritorio, async (page) => {
    await login(page, 'gerencia');
    await page.goto(`${BASE}/tablero/`);
    await subtitulo(page, 'Virguel · Tablero de gerencia', 'Resumen del día: asistencia, productividad, stock, flota, finanzas y alertas en una pantalla.');
    await espera(3500); await scroll(page, 900); await espera(1500);

    await page.goto(`${BASE}/tablero/supuestos/`);
    await subtitulo(page, 'Supuestos e inventados', 'Todo valor de prueba está marcado INVENTADO: la empresa sabe qué tiene que confirmar.');
    await espera(3500); await scroll(page, 700); await espera(1500);

    await page.goto(`${BASE}/tablero/asignacion/`);
    await subtitulo(page, 'Agenda automática', 'Reparte órdenes por minutos de jornada, ventanas horarias, competencias, EPP, vehículo y material; dice por qué no asigna.');
    await espera(3500); await scroll(page, 900); await espera(1800);

    await page.goto(`${BASE}/tablero/stock/`);
    await subtitulo(page, 'Stock y previsión de compras', 'Necesidad inmediata y backlog, reservas, lo que llega tarde y la sugerencia de compra.');
    await espera(3500); await scroll(page, 700); await espera(1500);
  });

  await escena(browser, '02_calidad', escritorio, async (page) => {
    await login(page, 'gerencia');
    await page.goto(`${BASE}/tablero/productividad/`);
    await subtitulo(page, 'Productividad de técnicos (IPT)', 'Indicadores con meta y semáforo; cada uno con su contrato de cálculo en el diccionario.');
    await espera(3500); await scroll(page, 600); await espera(1200);

    await page.goto(`${BASE}/tablero/objetivos/`);
    await subtitulo(page, 'Objetivos verificados', 'El supervisor reporta con evidencia; gerencia verifica o rechaza. Sólo lo verificado cuenta.');
    await espera(3500);

    await page.goto(`${BASE}/tablero/plantillas/`);
    await subtitulo(page, 'Controles con plantilla', 'Puntos, criterios y defectos tipificados, versionados. Se ven los defectos más frecuentes.');
    await espera(3500);

    await page.goto(`${BASE}/tablero/incidentes/`);
    await subtitulo(page, 'Incidentes y daños', 'Atribución con fundamento, costos, recuperos y el próximo plazo de cada expediente.');
    await espera(2500);
    const link = page.locator('table a[href*="/tablero/incidentes/"]').first();
    if (await link.count()) {
      await link.click(); await page.waitForLoadState();
      await subtitulo(page, 'Expediente del incidente', 'Cronología: denuncia, aseguradora, descargo, pago y recupero con su comprobante y plazo.');
      await espera(2000); await scroll(page, 600); await espera(1800);
    }
  });

  await escena(browser, '03_finanzas', escritorio, async (page) => {
    await login(page, 'gerencia');
    await page.goto(`${BASE}/finanzas/caja/`);
    await subtitulo(page, 'Caja proyectada', 'Cobros esperados de Claro, pagos pendientes por prioridad y compras netas: dinero real, no costos.');
    await espera(3500); await scroll(page, 700); await espera(1500);
    await page.goto(`${BASE}/finanzas/ingresos/`);
    await subtitulo(page, 'Liquidación de Claro', 'Estimación versionada, confirmación y cobro separados; las tarifas tienen vigencia.');
    await espera(3500);
  });

  await escena(browser, '04_tecnico', celular, async (page) => {
    await login(page, 't001');
    await page.goto(`${BASE}/app/`);
    await subtitulo(page, 'App del técnico', 'Fichada, órdenes del día y partes a cargo. Funciona sin señal.');
    await espera(3500); await scroll(page, 500); await espera(1200);
    if (ORDEN) {
      await page.goto(`${BASE}/app/orden/${ORDEN}/`);
      await subtitulo(page, 'Preparar la visita', 'Antecedentes del cliente, qué llevar y qué le falta, cada aviso con su fuente.');
      await espera(3500); await scroll(page, 500); await espera(1500);
      await page.goto(`${BASE}/app/orden/${ORDEN}/cierre/`);
      await subtitulo(page, 'Cierre de la llamada', 'Resultado, materiales según la receta, series, fotos, gastos y firma del cliente.');
      await espera(3500);
    }
  });

  await escena(browser, '05_supervisor', celular, async (page) => {
    await login(page, 's001');
    await page.goto(`${BASE}/app/`);
    await subtitulo(page, 'App del supervisor', 'Equipo del día, quién no tuvo control, desvíos sin acción y objetivos a reportar.');
    await espera(3500); await scroll(page, 700); await espera(1500);
    await page.goto(`${BASE}/app/informe/?plantilla=1`);
    await subtitulo(page, 'Control en calle', 'Motivo del control y puntos de la plantilla: un punto crítico que no cumple es un desvío.');
    await espera(3000); await scroll(page, 600); await espera(1500);
  });

  await browser.close();
})();
