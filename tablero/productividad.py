"""Pantallas de indicadores de productividad (IPT técnicos, IGS supervisores)."""
from datetime import timedelta

from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.models import Indicador, Persona
from core.roles import GERENCIA, SUPERVISOR, persona_de, requiere_rol, rol_de

from .metricas import referencia_equipo, tableros_supervisores, tableros_tecnicos
from .views import grafico


def _dias(request):
    try:
        return max(7, min(180, int(request.GET.get("dias", 30))))
    except ValueError:
        return 30


def _tecnicos_visibles(request):
    qs = Persona.objects.filter(rol="tecnico", activo=True)
    if rol_de(request.user) == SUPERVISOR:
        qs = qs.filter(supervisor=persona_de(request.user))
    return qs


@requiere_rol(GERENCIA, SUPERVISOR)
def tecnicos(request):
    dias = _dias(request)
    tbs = tableros_tecnicos(dias=dias, tecnicos=_tecnicos_visibles(request))
    ref = referencia_equipo(tableros_tecnicos(dias=dias))  # referencia: todo el plantel
    indicadores = list(Indicador.objects.filter(rol="tecnico", activo=True))
    return render(request, "tablero/productividad_tecnicos.html", {
        "tbs": tbs, "indicadores": indicadores, "ref": ref, "dias": dias,
        "g": grafico("bar", [tb.persona.apellido for tb in tbs],
                     [{"nombre": "IPT", "datos": [tb.indice for tb in tbs], "serie": 1}], max=100)})


@requiere_rol(GERENCIA, SUPERVISOR)
def diccionario(request):
    """Diccionario de indicadores: contrato de cálculo y versión de criterio de cada medida (B35)."""
    from django.shortcuts import render
    grupos = []
    for rol, nombre in Indicador.Rol.choices:
        inds = list(Indicador.objects.filter(rol=rol).order_by("orden"))
        if inds:
            grupos.append((nombre, inds))
    return render(request, "tablero/diccionario_indicadores.html", {"grupos": grupos})


@requiere_rol(GERENCIA)
def supervisores(request):
    dias = _dias(request)
    tbs = tableros_supervisores(dias=dias)
    indicadores = list(Indicador.objects.filter(rol="supervisor", activo=True))
    nombres = [tb.persona.apellido for tb in tbs]
    g_igs = grafico("bar", nombres, [{"nombre": "IGS", "datos": [tb.indice for tb in tbs],
                                      "colores": [f"--{tb.estado}" for tb in tbs]}], max=100)
    # puntos por grupo de indicadores (resultados, control, personas, gestión), comparables 0-100
    grupos = [("Resultados del equipo", ["eficiencia_equipo", "primera_visita_equipo", "mejora_equipo"]),
              ("Control y corrección", ["cobertura_control", "respuesta_desvios", "efectividad_correccion"]),
              ("Personas y clima", ["clima_equipo", "faltas_sin_aviso", "seguridad_equipo"]),
              ("Gestión", ["objetivos", "tiempo_respuesta"])]

    def puntos_grupo(tb, codigos):
        ms = [tb.get(c) for c in codigos]
        ps = [(m.puntos, m.indicador.peso) for m in ms if m and m.puntos is not None and m.indicador.peso]
        return sum(p * w for p, w in ps) / sum(w for _, w in ps) if ps else None
    g_grupos = grafico("bar", nombres, [{"nombre": g, "datos": [puntos_grupo(tb, cods) for tb in tbs], "serie": k + 1}
                                        for k, (g, cods) in enumerate(grupos)], max=100)
    return render(request, "tablero/productividad_supervisores.html", {
        "tbs": tbs, "indicadores": indicadores, "ref": referencia_equipo(tbs), "dias": dias,
        "g_igs": g_igs, "g_grupos": g_grupos})


@requiere_rol(GERENCIA, SUPERVISOR)
def ficha(request, pk):
    """Tarjeta de indicadores de una persona, con referencia del grupo y evolución del índice."""
    dias = _dias(request)
    if rol_de(request.user) == SUPERVISOR:
        yo = persona_de(request.user)
        p = get_object_or_404(Persona, pk=pk, supervisor=yo) if pk != yo.pk else yo
    else:
        p = get_object_or_404(Persona, pk=pk, rol__in=["tecnico", "supervisor"])
    hoy = timezone.localdate()
    if p.rol == "tecnico":
        todos = tableros_tecnicos(dias=dias)
        calcular = lambda hasta: tableros_tecnicos(hasta=hasta, dias=dias, tecnicos=[p])[0].indice  # noqa: E731
    else:
        todos = tableros_supervisores(dias=dias)
        calcular = lambda hasta: tableros_supervisores(hasta=hasta, dias=dias, supervisores=[p])[0].indice  # noqa: E731
    tb = next(t for t in todos if t.persona.id == p.id)
    ref = referencia_equipo(todos)
    posicion = [t.persona.id for t in todos].index(p.id) + 1
    semanas = [hoy - timedelta(weeks=n) for n in range(11, -1, -1)]
    g = grafico("line", [s.strftime("%d/%m") for s in semanas],
                [{"nombre": "Índice", "datos": [calcular(s) for s in semanas], "serie": 1}], max=100)
    return render(request, "tablero/productividad_ficha.html", {
        "p": p, "tb": tb, "ref": ref, "posicion": posicion, "total": len(todos), "g": g, "dias": dias,
        "sigla": "IPT" if p.rol == "tecnico" else "IGS"})


def _evolucion(hasta, dias, semanas=10):
    """IPT e IGS promedio de la empresa, una foto por semana (se guarda 30 min en caché)."""
    from django.core.cache import cache
    clave = f"prod_evolucion:{hasta}:{dias}:{semanas}"
    datos = cache.get(clave)
    if datos is None:
        datos = []
        for n in range(semanas - 1, -1, -1):
            f = hasta - timedelta(weeks=n)
            ipt = [t.indice for t in tableros_tecnicos(hasta=f, dias=dias) if t.indice is not None]
            igs = [t.indice for t in tableros_supervisores(hasta=f, dias=dias) if t.indice is not None]
            datos.append((f, sum(ipt) / len(ipt) if ipt else None, sum(igs) / len(igs) if igs else None))
        cache.set(clave, datos, 1800)
    return datos


@requiere_rol(GERENCIA)
def general(request):
    """Panel general: la productividad de toda la empresa en una pantalla."""
    from collections import defaultdict
    from statistics import mean
    dias = _dias(request)
    hoy = timezone.localdate()
    tt = tableros_tecnicos(dias=dias)
    ts = tableros_supervisores(dias=dias)
    con_ipt = [t for t in tt if t.indice is not None]
    con_igs = [t for t in ts if t.indice is not None]
    bandas = {"ok": 0, "aviso": 0, "critico": 0}
    for t in con_ipt:
        bandas[t.estado] += 1

    # Indicadores de la empresa: mediana de cada indicador contra su meta
    def empresa(tableros, rol):
        ref = referencia_equipo(tableros)
        filas = []
        for i in Indicador.objects.filter(rol=rol, activo=True):
            v = ref.get(i.codigo)
            pts = i.puntos(v)
            filas.append({"i": i, "valor": v, "puntos": pts,
                          "estado": "info" if pts is None else "ok" if pts >= 80 else "aviso" if pts >= 50 else "critico"})
        return filas
    ind_tec, ind_sup = empresa(tt, "tecnico"), empresa(ts, "supervisor")
    problemas = sorted([f for f in ind_tec + ind_sup if f["i"].peso and f["puntos"] is not None and f["puntos"] < 50],
                       key=lambda f: f["puntos"])[:4]

    # Por equipo y por zona
    por_sup = defaultdict(list)
    por_zona = defaultdict(list)
    for t in con_ipt:
        por_sup[t.persona.supervisor_id].append(t)
        por_zona[t.persona.zona.nombre if t.persona.zona else "Sin zona"].append(t)
    igs = {t.persona.id: t for t in ts}
    equipos = []
    for sid, lista in por_sup.items():
        s = igs.get(sid)
        val = lambda cod: mean([x.get(cod).valor for x in lista if x.get(cod) and x.get(cod).valor is not None] or [0])  # noqa: E731
        equipos.append({"sup": s.persona if s else None, "igs": s, "n": len(lista),
                        "ipt": mean(t.indice for t in lista), "eficiencia": val("eficiencia_jornada"),
                        "primera": val("primera_visita"), "rojos": sum(1 for t in lista if t.estado == "critico")})
    equipos.sort(key=lambda e: -e["ipt"])
    zonas = sorted([{"zona": z, "n": len(l), "ipt": mean(t.indice for t in l)} for z, l in por_zona.items()],
                   key=lambda z: -z["ipt"])

    evol = _evolucion(hoy, dias)
    g_evol = grafico("line", [f.strftime("%d/%m") for f, _, _ in evol], [
        {"nombre": "IPT promedio (técnicos)", "datos": [a for _, a, _ in evol], "serie": 1},
        {"nombre": "IGS promedio (supervisores)", "datos": [b for _, _, b in evol], "serie": 2},
    ], max=100)
    g_dist = grafico("bar", ["Bien (≥ 75)", "Intermedio (55–74)", "Bajo (< 55)"], [
        {"nombre": "Técnicos", "datos": [bandas["ok"], bandas["aviso"], bandas["critico"]],
         "colores": ["--ok", "--aviso", "--critico"]}])
    g_eq = grafico("bar", [e["sup"].apellido if e["sup"] else "Sin supervisor" for e in equipos], [
        {"nombre": "IPT promedio del equipo", "datos": [e["ipt"] for e in equipos], "serie": 1},
        {"nombre": "IGS del supervisor", "datos": [e["igs"].indice if e["igs"] else None for e in equipos], "serie": 2},
    ], max=100)
    con_peso = [f for f in ind_tec + ind_sup if f["i"].peso and f["puntos"] is not None]
    g_ind = grafico("bar", [f"{f['i'].nombre} ({'téc.' if f['i'].rol == 'tecnico' else 'sup.'})" for f in con_peso], [
        {"nombre": "Puntos (100 = meta cumplida)", "datos": [f["puntos"] for f in con_peso],
         "colores": [f"--{f['estado']}" for f in con_peso]}], horizontal=True, max=100)
    primero, ultimo = (evol[0][1], evol[-1][1]) if evol else (None, None)
    return render(request, "tablero/productividad_general.html", {
        "dias": dias, "ipt_prom": mean(t.indice for t in con_ipt) if con_ipt else None,
        "igs_prom": mean(t.indice for t in con_igs) if con_igs else None,
        "variacion": (ultimo - primero) if primero and ultimo else None, "semanas": len(evol),
        "bandas": bandas, "n_tec": len(con_ipt), "sin_datos": len(tt) - len(con_ipt),
        "ind_tec": ind_tec, "ind_sup": ind_sup, "problemas": problemas, "equipos": equipos, "zonas": zonas,
        "mejores": con_ipt[:5], "peores": con_ipt[-5:][::-1], "g_evol": g_evol, "g_dist": g_dist, "g_eq": g_eq,
        "g_ind": g_ind})


def _rangos(valores):
    orden = sorted(range(len(valores)), key=lambda i: -valores[i])
    r = [0] * len(valores)
    for pos, i in enumerate(orden, 1):
        r[i] = pos
    return r


def _spearman(a, b):
    n = len(a)
    if n < 3:
        return None
    ra, rb = _rangos(a), _rangos(b)
    return 1 - 6 * sum((x - y) ** 2 for x, y in zip(ra, rb)) / (n * (n * n - 1))


@requiere_rol(GERENCIA)
def calibrar(request):
    """Simulador de pesos (contraste B26): recalcula el índice con los pesos propuestos, SIN guardarlos, y
    muestra cuánto cambia el orden de las personas y qué indicadores tienen datos suficientes para pesar.
    Sirve para acordar los pesos con la empresa antes de cambiarlos en «Metas y semáforos»."""
    rol = request.GET.get("rol", "tecnico") if request.GET.get("rol") in ("tecnico", "supervisor") else "tecnico"
    dias = _dias(request)
    tbs = tableros_tecnicos(dias=dias) if rol == "tecnico" else tableros_supervisores(dias=dias)
    inds = list(Indicador.objects.filter(rol=rol, activo=True, tipo="calculado").order_by("orden"))
    propuesto = {}
    for i in inds:
        try:
            propuesto[i.codigo] = max(0, min(100, int(request.GET.get(f"peso_{i.codigo}", i.peso))))
        except ValueError:
            propuesto[i.codigo] = i.peso

    def indice(tb, pesos):
        con = [(m.puntos, pesos.get(m.indicador.codigo, 0)) for m in tb.mediciones if m.puntos is not None]
        total = sum(p for _, p in con)
        return sum(v * p for v, p in con) / total if total else None

    actuales = {i.codigo: i.peso for i in inds}
    filas = []
    for tb in tbs:
        a, b = indice(tb, actuales), indice(tb, propuesto)
        if a is not None and b is not None:
            filas.append({"persona": tb.persona, "actual": a, "propuesto": b})
    for f, ra, rb in zip(filas, _rangos([f["actual"] for f in filas]), _rangos([f["propuesto"] for f in filas])):
        f["pos_actual"], f["pos_propuesta"], f["salto"] = ra, rb, ra - rb
    cobertura = []
    for i in inds:
        pts = [m.puntos for tb in tbs for m in tb.mediciones if m.indicador.codigo == i.codigo and m.puntos is not None]
        media = sum(pts) / len(pts) if pts else None
        disp = (sum((p - media) ** 2 for p in pts) / len(pts)) ** .5 if pts else None
        cobertura.append({"i": i, "propuesto": propuesto[i.codigo], "con_dato": len(pts), "total": len(tbs),
                          "media": media, "dispersion": disp,
                          "aviso": "pocos datos" if len(pts) < max(3, len(tbs) // 2) else
                          ("no distingue" if disp is not None and disp < 5 else "")})
    cambio = request.GET and any(propuesto[k] != actuales[k] for k in actuales)
    return render(request, "tablero/calibrar.html", {
        "rol": rol, "dias": dias, "cobertura": cobertura, "cambio": cambio,
        "filas": sorted(filas, key=lambda f: -abs(f["salto"]))[:20] if cambio else [],
        "spearman": _spearman([f["actual"] for f in filas], [f["propuesto"] for f in filas]) if cambio else None,
        "n": len(filas)})
