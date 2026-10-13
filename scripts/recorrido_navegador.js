// Recorrido en navegador: pantallas por rol (tiempos y errores JS), archivos privados y ciclo sin señal.
//
// Requiere el servidor corriendo con los datos de `generar_demo` (contraseña virguel2026) y Playwright:
//   ORDEN=<id de una orden abierta de t001> node scripts/recorrido_navegador.js
// Variables opcionales: BASE (http://localhost:8000), PLAYWRIGHT (ruta del módulo), CHROMIUM (ejecutable),
// SOLO_PANTALLAS=1 (sólo pantallas por rol).
const { chromium } = require(process.env.PLAYWRIGHT || 'playwright');
const BASE = process.env.BASE || 'http://localhost:8000';
const ORDEN = process.env.ORDEN;
const resultados = [];
const ok = (nombre, cond, extra = '') => { const r = [cond ? 'OK ' : 'FAIL', nombre, extra]; resultados.push(r); console.log(r.join('  ')); };

async function login(page, usuario) {
  await page.goto(`${BASE}/login/`);
  await page.fill('input[name=username]', usuario);
  await page.fill('input[name=password]', 'virguel2026');
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit], form button')]);
}

const PANTALLAS = {
  gerencia: ['/tablero/', '/tablero/tecnicos/', '/tablero/supervisores/', '/tablero/productividad/',
    '/tablero/productividad/supervisores/', '/tablero/stock/', '/tablero/planificacion/', '/tablero/importar/',
    '/tablero/operacion/', '/tablero/capacitacion/', '/finanzas/', '/finanzas/caja/', '/finanzas/ingresos/',
    '/finanzas/comprobantes/', '/finanzas/comprobantes/?ver=a_pagar', '/personal/legajos/', '/personal/asistencia/'],
  contable: ['/finanzas/', '/finanzas/caja/', '/finanzas/ingresos/', '/finanzas/comprobantes/', '/finanzas/sueldos/',
    '/finanzas/alternativas-de-pago/?nombre_1=Contado&anticipo_1=1000000&nombre_2=Cuotas&cuotas_2=6&monto_cuota_2=180000'],
  deposito: ['/tablero/stock/', '/tablero/stock/tecnicos/', '/tablero/pedidos/', '/tablero/partes-adeudadas/'],
  s001: ['/app/', '/app/no-resueltas/', '/app/novedades/', '/app/indicadores/', '/tablero/tecnicos/'],
  t001: ['/app/', '/app/stock/', '/app/desempeno/', `/app/orden/${ORDEN}/`, '/app/asistencia/'],
};

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});

  // 1. Pantallas por rol: sin errores de servidor ni de JavaScript
  for (const [usuario, urls] of Object.entries(PANTALLAS)) {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const errores = [];
    page.on('pageerror', (e) => errores.push(e.message));
    await login(page, usuario);
    for (const u of urls) {
      const t0 = Date.now();
      const r = await page.goto(BASE + u);
      const ms = Date.now() - t0;
      ok(`${usuario} ${u}`, r.status() === 200, `${r.status()} ${ms} ms`);
    }
    ok(`${usuario} sin errores JS`, errores.length === 0, errores.join(' | ').slice(0, 200));
    await ctx.close();
  }

  if (process.env.SOLO_PANTALLAS) { await browser.close(); return; }
  // 2. Archivos privados
  {
    const ctx = await browser.newContext();
    const r = await ctx.request.get(`${BASE}/media/recibos/demo.pdf`, { maxRedirects: 0 });
    ok('media sin sesión → login', r.status() === 302 && (r.headers()['location'] || '').includes('/login/'), String(r.status()));
    const page = await ctx.newPage();
    await login(page, 'contable');
    const r2 = await ctx.request.get(`${BASE}/media/recibos/demo.pdf`);
    ok('recibo: contabilidad → 200 sin caché', r2.status() === 200 && (r2.headers()['cache-control'] || '').includes('no-store'), String(r2.status()));
    await ctx.clearCookies();
    await login(page, 't001');
    const r3 = await ctx.request.get(`${BASE}/media/egresos/demo.pdf`);
    ok('comprobante de egreso: técnico → 404', r3.status() === 404, String(r3.status()));
    await ctx.close();
  }

  // 3. Ciclo sin señal (sin service worker: page.route no intercepta lo que pasa por él)
  {
    const ctx = await browser.newContext({ serviceWorkers: 'block' });
    const page = await ctx.newPage();
    page.on('dialog', (d) => d.accept().catch(() => {}));
    await login(page, 't001');
    const url = `${BASE}/app/orden/${ORDEN}/notas/`;
    await page.goto(url);
    const contar = () => page.evaluate(() => new Promise((res) => {
      const r = indexedDB.open('virguel-offline', 1);
      r.onupgradeneeded = () => r.result.createObjectStore('pendientes', { keyPath: 'id', autoIncrement: true });
      r.onsuccess = () => {
        const t = r.result.transaction('pendientes', 'readonly').objectStore('pendientes').getAll();
        t.onsuccess = () => res(t.result.map((i) => ({ estado: i.estado, usuario: i.usuario, mensaje: i.mensaje })));
      };
    }));
    const POST = (fn) => (route) => route.request().method() === 'POST' ? fn(route) : route.continue();

    // sin señal: el envío falla en la red (se simula cortando sólo ese POST)
    await page.route('**/notas/', POST((route) => route.abort('internetdisconnected')));
    await page.fill('textarea[name=texto]', 'Nota cargada sin señal (prueba)');
    await page.click('form[data-offline] button');
    await page.waitForTimeout(2000);
    let p = await contar();
    ok('sin señal: queda pendiente con su usuario', p.length === 1 && p[0].usuario, JSON.stringify(p));

    // vuelve la señal pero el servidor falla (500): se conserva
    await page.unroute('**/notas/');
    await page.route('**/notas/', POST((route) => route.fulfill({ status: 500, body: 'error' })));
    await page.goto(`${BASE}/app/`);
    await page.waitForTimeout(2500);
    p = await contar();
    ok('error 500: el pendiente se conserva', p.length === 1 && p[0].estado === 'pendiente', JSON.stringify(p));

    // el servidor rechaza los datos: queda "con error" para corregir
    await page.unroute('**/notas/');
    await page.route('**/notas/', POST((route) => route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ ok: false, mensaje: 'Dato inválido' }) })));
    await page.goto(`${BASE}/app/`);
    await page.waitForTimeout(2500);
    p = await contar();
    ok('rechazo: queda con error y motivo', p.length === 1 && p[0].estado === 'error' && p[0].mensaje === 'Dato inválido', JSON.stringify(p));
    const aviso = await page.textContent('#pendientes-offline').catch(() => '');
    ok('rechazo: se muestra al técnico', (aviso || '').includes('No aceptado'), (aviso || '').slice(0, 80));

    // reintentar con el servidor real: se acepta y se borra
    await page.unroute('**/notas/');
    await page.click('[data-reintentar]', { timeout: 5000 }).catch(() => console.log('sin botón reintentar'));
    await page.waitForTimeout(2500);
    p = await contar();
    ok('reintento aceptado: se borra el pendiente', p.length === 0, JSON.stringify(p));

    // pendiente de t001 y luego entra otro usuario en el mismo celular: no lo envía
    await page.goto(url);
    await page.route('**/notas/', POST((route) => route.abort()));  // sin señal sólo para ese envío
    await page.fill('textarea[name=texto]', 'Otra nota sin señal');
    await page.click('form[data-offline] button');
    await page.waitForTimeout(1500);
    await ctx.clearCookies();          // cierra la sesión de t001 con el pendiente guardado
    await login(page, 't002');
    await page.unroute('**/notas/');
    let envios = 0;
    await page.route('**/notas/', POST((route) => { envios += 1; return route.continue(); }));
    await page.goto(`${BASE}/app/`);
    await page.waitForTimeout(2500);
    p = await contar();
    const aviso2 = await page.textContent('#pendientes-offline').catch(() => '');
    ok('otro usuario: no envía el pendiente ajeno', p.length === 1 && envios === 0, `${JSON.stringify(p)} envíos=${envios}`);
    ok('otro usuario: se le avisa', (aviso2 || '').includes('otro usuario'), (aviso2 || '').slice(0, 100));
    await ctx.close();
  }

  await browser.close();

  const fallas = resultados.filter((r) => r[0] === 'FAIL').length;
  console.log(`\n${resultados.length - fallas}/${resultados.length} OK`);
  process.exit(fallas ? 1 : 0);
})();
