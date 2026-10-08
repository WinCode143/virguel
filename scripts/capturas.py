"""Genera una galería con capturas de todas las pantallas (escritorio y celular).

    uv run --with playwright python scripts/capturas.py      (con el servidor levantado)
    → abre capturas/index.html
"""
import glob
import html
import pathlib

from playwright.sync_api import sync_playwright

B = "http://127.0.0.1:8765"
OUT = pathlib.Path(__file__).resolve().parent.parent / "capturas"
OUT.mkdir(exist_ok=True)
CLAVE = "virguel2026"

ESCRITORIO = [  # (usuario, ruta, título, sección)
    ("gerencia", "/tablero/", "Resumen · tablero de mando", "Inicio"),
    ("gerencia", "/tablero/alertas/", "Alertas", "Inicio"),
    ("gerencia", "/personal/", "Asistencia de hoy", "Personal"),
    ("gerencia", "/personal/asistencia/", "Presentismo y ausencias", "Personal"),
    ("gerencia", "/personal/legajos/", "Legajos", "Personal"),
    ("gerencia", "/personal/legajos/515/", "Legajo de una persona", "Personal"),
    ("gerencia", "/personal/documentos/", "Documentación", "Personal"),
    ("gerencia", "/personal/dotacion/", "Dotación y rotación", "Personal"),
    ("gerencia", "/personal/parte/", "Parte diario por mail", "Personal"),
    ("gerencia", "/tablero/productividad/general/", "Panel general de productividad", "Productividad"),
    ("gerencia", "/tablero/productividad/", "Índice de técnicos (IPT)", "Productividad"),
    ("gerencia", "/tablero/productividad/supervisores/", "Índice de supervisores (IGS)", "Productividad"),
    ("gerencia", "/tablero/productividad/505/", "Ficha de indicadores de un supervisor", "Productividad"),
    ("gerencia", "/tablero/metas/", "Metas y semáforos", "Productividad"),
    ("gerencia", "/tablero/tecnicos/", "Técnicos y riesgo", "Desempeño y calidad"),
    ("gerencia", "/tablero/tecnicos/515/", "Desempeño de un técnico", "Desempeño y calidad"),
    ("gerencia", "/tablero/capacitacion/", "Capacitación", "Desempeño y calidad"),
    ("gerencia", "/tablero/supervisores/", "Evaluación de supervisores", "Desempeño y calidad"),
    ("gerencia", "/tablero/encuestas/", "Encuestas del día", "Desempeño y calidad"),
    ("gerencia", "/tablero/incidentes/", "Incidentes y daños", "Desempeño y calidad"),
    ("gerencia", "/tablero/operacion/", "Operación diaria", "Operación"),
    ("gerencia", "/tablero/asignacion/", "Asignación automática de órdenes", "Operación"),
    ("gerencia", "/tablero/planificacion/", "Planificación y capacidad", "Operación"),
    ("gerencia", "/tablero/partes-adeudadas/", "Partes adeudadas", "Inventario"),
    ("gerencia", "/tablero/stock/", "Stock y demanda", "Inventario"),
    ("gerencia", "/tablero/stock/tecnicos/", "Partes en manos de técnicos", "Inventario"),
    ("gerencia", "/tablero/pedidos/", "Pedidos de partes", "Inventario"),
    ("gerencia", "/tablero/herramientas/", "Herramientas y EPP", "Inventario"),
    ("gerencia", "/tablero/flota/", "Flota", "Recursos"),
    ("gerencia", "/tablero/finanzas/", "Finanzas", "Recursos"),
    ("gerencia", "/personal/usuarios/", "Usuarios y accesos", "Administración"),
    ("gerencia", "/personal/usuarios/515/", "Acceso de una persona", "Administración"),
    ("gerencia", "/personal/accesos/", "Registro de accesos", "Administración"),
    ("gerencia", "/tablero/importar/", "Importar Excel / CSV", "Administración"),
    ("gerencia", "/tablero/powerbi/", "Power BI y exportar", "Administración"),
    ("gerencia", "/admin/", "Carga de datos", "Administración"),
    ("s002", "/tablero/", "Resumen visto por un supervisor (sólo su equipo)", "Supervisor en la PC"),
]
CELULAR = [
    ("t014", "/app/", "Inicio del técnico", "App del técnico"),
    ("t014", "/app/orden/248349/", "Orden: ficha y cierre", "App del técnico"),
    ("t014", "/app/asistencia/", "Mi asistencia", "App del técnico"),
    ("t014", "/app/ausencia/", "Avisar ausencia", "App del técnico"),
    ("t014", "/app/stock/", "Mis partes y deudas", "App del técnico"),
    ("t014", "/app/stock/pedir/?faltante=1", "Pedir partes", "App del técnico"),
    ("t014", "/app/yo/", "Menú Yo", "App del técnico"),
    ("t014", "/app/desempeno/", "Mi rendimiento", "App del técnico"),
    ("t014", "/app/mi-supervisor/", "Evaluar a mi supervisor", "App del técnico"),
    ("t014", "/app/legajo/", "Mi legajo", "App del técnico"),
    ("t014", "/app/historial/", "Historial de órdenes", "App del técnico"),
    ("t014", "/app/epp/", "Mi EPP", "App del técnico"),
    ("t014", "/app/notificaciones/", "Notificaciones", "App del técnico"),
    ("t014", "/app/incidente/", "Reportar incidente", "App del técnico"),
    ("s002", "/app/", "Inicio del supervisor", "App del supervisor"),
    ("s002", "/app/informe/", "Nuevo control en calle", "App del supervisor"),
    ("s002", "/app/novedades/", "Ausencias del equipo", "App del supervisor"),
    ("s002", "/app/pedidos/", "Pedidos de partes del equipo", "App del supervisor"),
    ("s002", "/app/deudas/", "Partes adeudadas del equipo", "App del supervisor"),
    ("s002", "/app/indicadores/", "Mis indicadores", "App del supervisor"),
]
OSCURO = [("gerencia", "/tablero/", "Resumen en modo oscuro", "Modo oscuro"),
          ("gerencia", "/tablero/productividad/general/", "Panel general en modo oscuro", "Modo oscuro")]
OSCURO_CEL = [("t014", "/app/", "App del técnico en modo oscuro", "Modo oscuro")]


def nombre(i, sec):
    return f"{i:02d}_{sec.lower().replace(' ', '_')}.png"


def main():
    exe = (glob.glob(str(pathlib.Path.home() / ".cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))
           or [None])[-1]
    fichas = []
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path=exe)
        k = 0
        for lista, movil, tema in ((ESCRITORIO, False, "light"), (CELULAR, True, "light"),
                                   (OSCURO, False, "dark"), (OSCURO_CEL, True, "dark")):
            sesiones = {}
            for usuario, ruta, titulo, seccion in lista:
                if usuario not in sesiones:
                    kw = (dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True,
                               user_agent="Mozilla/5.0 (Linux; Android 14) Mobile") if movil
                          else dict(viewport={"width": 1440, "height": 900}))
                    ctx = br.new_context(**kw)
                    ctx.add_init_script(f"try{{localStorage.setItem('tema','{tema}')}}catch(e){{}}")
                    pg = ctx.new_page()
                    pg.goto(B + "/login/")
                    pg.fill("#id_username", usuario)
                    pg.fill("#id_password", CLAVE)
                    pg.click("button.btn")
                    pg.wait_for_load_state("networkidle")
                    sesiones[usuario] = pg
                pg = sesiones[usuario]
                pg.goto(B + ruta)
                pg.wait_for_timeout(900)
                k += 1
                archivo = nombre(k, seccion)
                pg.screenshot(path=str(OUT / archivo), full_page=True)
                fichas.append((seccion, titulo, archivo, movil, usuario, ruta))
                print(f"{k:2d} {titulo}")
            for pg in sesiones.values():
                pg.context.close()
        br.close()
    secciones = []
    for f in fichas:
        if f[0] not in secciones:
            secciones.append(f[0])
    partes = []
    for s in secciones:
        tarjetas = "".join(
            f'<figure class="{"cel" if m else "pc"}"><a href="{a}" target="_blank"><img src="{a}" loading="lazy" alt=""></a>'
            f'<figcaption><b>{html.escape(t)}</b><span>{html.escape(u)} · {html.escape(r)}</span></figcaption></figure>'
            for sec, t, a, m, u, r in fichas if sec == s)
        partes.append(f'<section id="{s}"><h2>{html.escape(s)}</h2><div class="grilla">{tarjetas}</div></section>')
    indice = " · ".join(f'<a href="#{s}">{html.escape(s)}</a>' for s in secciones)
    (OUT / "index.html").write_text(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Virguel · todas las pantallas</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;margin:0;background:#f6f6f3;color:#0f0f0e}}
header{{position:sticky;top:0;background:#fff;border-bottom:1px solid #e5e4de;padding:12px 24px;z-index:2}}
h1{{margin:0;font-size:1.3rem}} nav{{font-size:.88rem;margin-top:4px}} a{{color:#2a78d6}}
main{{padding:16px 24px 60px}} h2{{margin:28px 0 12px;font-size:1.1rem}}
.grilla{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}}
figure{{margin:0;background:#fff;border:1px solid #e5e4de;border-radius:12px;overflow:hidden}}
figure img{{display:block;width:100%;height:240px;object-fit:cover;object-position:top;border-bottom:1px solid #eee}}
figure.cel img{{height:420px}} figcaption{{padding:8px 12px;font-size:.85rem}}
figcaption span{{display:block;color:#84827c;font-size:.76rem}}
@media (prefers-color-scheme:dark){{body{{background:#0e0e0d;color:#f4f3ef}}header,figure{{background:#181817;border-color:#2b2b29}}}}
</style></head><body><header><h1>Virguel · todas las pantallas ({len(fichas)})</h1><nav>{indice}</nav>
<p style="margin:4px 0 0;font-size:.8rem;color:#84827c">Clic en una captura para verla completa. Datos de prueba.</p></header>
<main>{"".join(partes)}</main></body></html>""")
    print(f"Galería: {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
