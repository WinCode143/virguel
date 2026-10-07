"""Tableros de escritorio (gerencia / administración; supervisores con vista de su equipo)."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncMonth, TruncWeek
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from capacitacion.evaluacion import Diagnostico, evaluar_tecnicos
from capacitacion.models import EvaluacionHistorica, Participacion
from core.models import Alerta, Parametros, Persona, Zona
from core.roles import GERENCIA, SUPERVISOR, TECNICO, persona_de, requiere_rol, rol_de
from finanzas.models import CostoFijo, Egreso
from finanzas.proyeccion import historico_mensual, proyectar
from flota.models import ServiceRealizado, Vehiculo, proximos_services
from herramientas.models import Asignacion, Elemento
from incidentes.models import Siniestro
from inventario.models import Salida
from inventario.services import lotes_envejecidos, prevision_materiales, stock_diario, tecnicos_en_calle
from operaciones.models import Jornada, OrdenTrabajo
from supervision.evaluacion import evaluar_supervisores
from supervision.models import EncuestaSupervisor

from .planificacion import (capacidad, decodificadores_necesarios, demanda_vs_capacidad,
                            hectareas_reales_por_cuadrilla, probabilidad_decodificador, stock_decodificadores)

TODOS = (GERENCIA, SUPERVISOR)


def grafico(tipo, etiquetas, series, **opciones):
    """Estructura que consume static/js/graficos.js."""
    return {"tipo": tipo, "etiquetas": [str(e) for e in etiquetas],
            "series": [{**s, "datos": [float(x) if x is not None else None for x in s["datos"]]} for s in series],
            **opciones}


def _rango(request, dias_defecto=30):
    hoy = timezone.localdate()
    try:
        hasta = date.fromisoformat(request.GET.get("hasta", ""))
    except ValueError:
        hasta = hoy
    try:
        dias = max(7, min(365, int(request.GET.get("dias", dias_defecto))))
    except ValueError:
        dias = dias_defecto
    return hasta - timedelta(days=dias - 1), hasta, dias


def _equipo(request):
    """Técnicos visibles para el usuario: todos (gerencia) o su equipo (supervisor)."""
    qs = Persona.objects.filter(rol=Persona.Rol.TECNICO, activo=True)
    if rol_de(request.user) == SUPERVISOR:
        qs = qs.filter(supervisor=persona_de(request.user))
    return qs


def ultimo_dia_con_datos(hasta):
    j = Jornada.objects.filter(fecha__lte=hasta, en_calle=True).order_by("-fecha").first()
    return j.fecha if j else hasta


# ---------------------------------------------------------------- inicio
def raiz(request):
    rol = rol_de(request.user)
    if rol is None:
        return redirect("login")
    es_celular = "Mobi" in request.headers.get("User-Agent", "")
    if rol == TECNICO or (rol == SUPERVISOR and es_celular):
        return redirect("movil:inicio")
    return redirect("tablero:inicio")


@requiere_rol(*TODOS)
def inicio(request):
    hoy = timezone.localdate()
    dia = ultimo_dia_con_datos(hoy)
    equipo = _equipo(request)
    en_calle = Jornada.objects.filter(fecha=dia, en_calle=True, tecnico__in=equipo).count()
    desde30 = hoy - timedelta(days=29)
    ots = OrdenTrabajo.objects.filter(tecnico__in=equipo)
    completadas_dia = ots.filter(fecha_ejecucion=dia, estado=OrdenTrabajo.Estado.COMPLETADA).count()
    cap = capacidad(en_calle)
    lotes = lotes_envejecidos(hoy)
    parado = [f for f in lotes if f["estado"] == "critico"]
    evs = evaluar_tecnicos(hoy, tecnicos=equipo)
    riesgo = [e for e in evs if e.diagnostico == Diagnostico.RIESGO]
    capacitar = [e for e in evs if e.diagnostico == Diagnostico.CAPACITACION]
    mes = hoy.replace(day=1)
    siniestros_mes = Siniestro.objects.filter(fecha__gte=mes, tecnico__in=equipo)
    egresos_mes = Egreso.objects.filter(fecha__gte=mes).aggregate(t=Sum("monto"))["t"] or 0
    enc = EncuestaSupervisor.objects.filter(fecha__gte=desde30, respondida__isnull=False)
    if rol_de(request.user) == SUPERVISOR:
        enc = enc.filter(supervisor=persona_de(request.user))
    nota_sup = enc.aggregate(t=Avg("trato"), c=Avg("claridad"), a=Avg("apoyo"), p=Avg("presencia"))
    notas = [v for v in nota_sup.values() if v is not None]

    # Serie: OT completadas por día vs. capacidad estimada (misma unidad: clientes/día)
    por_dia = dict(ots.filter(fecha_ejecucion__range=(desde30, hoy), estado=OrdenTrabajo.Estado.COMPLETADA)
                   .values_list("fecha_ejecucion").annotate(n=Count("id")))
    calle_dia = dict(Jornada.objects.filter(fecha__range=(desde30, hoy), en_calle=True, tecnico__in=equipo)
                     .values_list("fecha").annotate(n=Count("id")))
    dias = [desde30 + timedelta(days=i) for i in range(30)]
    caps = [capacidad(calle_dia.get(d, 0)) for d in dias]
    g_prod = grafico("bar", [d.strftime("%d/%m") for d in dias], [
        {"nombre": "OT completadas", "datos": [por_dia.get(d, 0) for d in dias], "serie": 1},
        {"nombre": "Capacidad estimada", "datos": [(c.clientes_min + c.clientes_max) / 2 for c in caps],
         "serie": 2, "tipo": "line"},
    ])
    diag = Counter(e.diagnostico for e in evs)
    orden_diag = [Diagnostico.ADECUADO, Diagnostico.APRENDIZAJE, Diagnostico.MEJORANDO, Diagnostico.OBSERVACION,
                  Diagnostico.CAPACITACION, Diagnostico.RIESGO]
    estado_diag = {Diagnostico.ADECUADO: "ok", Diagnostico.APRENDIZAJE: None, Diagnostico.MEJORANDO: None,
                   Diagnostico.OBSERVACION: "aviso", Diagnostico.CAPACITACION: "aviso", Diagnostico.RIESGO: "critico"}
    g_diag = grafico("bar", orden_diag, [{"nombre": "Técnicos", "datos": [diag.get(d, 0) for d in orden_diag],
                                          "colores": [f"--{estado_diag[d]}" if estado_diag[d] else "--s1"
                                                      for d in orden_diag]}], horizontal=True)

    ctx = {
        "dia": dia, "en_calle": en_calle, "completadas_dia": completadas_dia, "cap": cap,
        "parado_valor": sum(f["valor"] for f in parado), "parado_lotes": len(parado),
        "riesgo": riesgo, "capacitar": capacitar, "siniestros_mes": siniestros_mes.count(),
        "siniestros_graves_mes": siniestros_mes.exclude(gravedad="leve").count(),
        "egresos_mes": egresos_mes, "nota_sup": sum(notas) / len(notas) if notas else None,
        "g_prod": g_prod, "g_diag": g_diag, "prob": probabilidad_decodificador(hoy), "p": Parametros.actual(),
    }
    ctx["alertas"] = sorted(Alerta.objects.filter(resuelta=False), key=lambda a: (a.nivel != "critica", -a.id))[:8]
    # Control de personal: foto de hoy y presentismo del mes
    from personal.indicadores import estado_del_dia, resumen
    from personal.views import personal_visible
    personas = personal_visible(request)
    estado = estado_del_dia(hoy, personas)
    res_mes = resumen(hoy.replace(day=1), hoy, personas)
    pres = sum(r.presentes for r in res_mes)
    base = sum(r.esperados - r.no_computables for r in res_mes)
    ctx.update({
        "per_total": sum(1 for e in estado if e.laborable or e.asistencia),
        "per_presentes": sum(1 for e in estado if e.asistencia),
        "per_sin_aviso": sum(1 for e in estado if e.situacion[1] == "Sin fichar y sin aviso"),
        "per_tarde": sum(1 for e in estado if e.asistencia and e.asistencia.minutos_tarde),
        "per_con_aviso": sum(1 for e in estado if not e.asistencia and e.novedad),
        "per_presentismo_mes": pres / base if base else None,
        "per_injustificadas_mes": sum(r.injustificadas for r in res_mes),
    })
    return render(request, "tablero/inicio.html", ctx)


# ---------------------------------------------------------------- 1. operación
@requiere_rol(*TODOS)
def operacion(request):
    desde, hasta, dias = _rango(request)
    equipo = _equipo(request)
    ots = OrdenTrabajo.objects.filter(tecnico__in=equipo, fecha_ejecucion__range=(desde, hasta))
    jornadas = Jornada.objects.filter(tecnico__in=equipo, fecha__range=(desde, hasta))
    fechas = [desde + timedelta(days=i) for i in range(dias)]
    calle = dict(jornadas.filter(en_calle=True).values_list("fecha").annotate(n=Count("id")))
    ha = dict(jornadas.filter(en_calle=True).values_list("fecha").annotate(t=Sum("hectareas_cubiertas")))
    por_estado = defaultdict(dict)
    for f, est, n in ots.values_list("fecha_ejecucion", "estado").annotate(n=Count("id")):
        por_estado[est][f] = n
    etiquetas = [f.strftime("%d/%m") for f in fechas]
    g_estado = grafico("bar", etiquetas, [
        {"nombre": "Completadas", "datos": [por_estado["completada"].get(f, 0) for f in fechas], "serie": 1},
        {"nombre": "Fallidas", "datos": [por_estado["fallida"].get(f, 0) for f in fechas], "serie": 2},
        {"nombre": "Reprogramadas", "datos": [por_estado["reprogramada"].get(f, 0) for f in fechas], "serie": 3},
    ], apilado=True)
    g_calle = grafico("line", etiquetas, [{"nombre": "Técnicos en calle", "datos": [calle.get(f, 0) for f in fechas]}])
    g_ha = grafico("line", etiquetas, [{"nombre": "Hectáreas cubiertas", "datos": [ha.get(f, 0) for f in fechas],
                                        "serie": 3}])
    tipos = (ots.filter(estado="completada").values("tipo__nombre")
             .annotate(n=Count("id"), mins=Avg("minutos_reales"), est=Avg("tipo__minutos_estandar"))
             .order_by("-n"))
    total = ots.count()
    comp = ots.filter(estado="completada").count()
    jornadas_calle = sum(calle.values())
    ranking = (ots.filter(estado="completada").values("tecnico__id", "tecnico__apellido", "tecnico__nombre")
               .annotate(n=Count("id")).order_by("-n"))
    calle_tec = dict(jornadas.filter(en_calle=True).values_list("tecnico").annotate(n=Count("id")))
    filas = [{"id": r["tecnico__id"], "nombre": f"{r['tecnico__apellido']}, {r['tecnico__nombre']}", "ots": r["n"],
              "dias": calle_tec.get(r["tecnico__id"], 0),
              "prom": r["n"] / calle_tec[r["tecnico__id"]] if calle_tec.get(r["tecnico__id"]) else 0} for r in ranking]
    ctx = {"desde": desde, "hasta": hasta, "dias": dias, "g_estado": g_estado, "g_calle": g_calle, "g_ha": g_ha,
           "tipos": tipos, "total": total, "comp": comp, "efectividad": comp / total * 100 if total else 0,
           "jornadas_calle": jornadas_calle, "ots_por_jornada": comp / jornadas_calle if jornadas_calle else 0,
           "retrabajos": ots.filter(es_retrabajo=True).count(),
           "ha_prom": (sum(ha.values()) / jornadas_calle) if jornadas_calle else 0,
           "filas": filas, "p": Parametros.actual()}
    return render(request, "tablero/operacion.html", ctx)


# ---------------------------------------------------------------- 5. técnicos / capacitación
@requiere_rol(*TODOS)
def tecnicos(request):
    hoy = timezone.localdate()
    evs = evaluar_tecnicos(hoy, tecnicos=_equipo(request))
    filtro = request.GET.get("diagnostico")
    if filtro:
        evs = [e for e in evs if e.diagnostico == filtro]
    # riesgo de hace ~4 semanas (última foto semanal anterior a esa fecha)
    previa = (EvaluacionHistorica.objects.filter(fecha__lte=hoy - timedelta(days=28))
              .order_by("-fecha").values_list("fecha", flat=True).first())
    antes = dict(EvaluacionHistorica.objects.filter(fecha=previa).values_list("persona_id", "riesgo")) if previa else {}
    for e in evs:
        r = antes.get(e.tecnico.id)
        e.delta_riesgo = (e.riesgo - float(r)) if r is not None else None
    return render(request, "tablero/tecnicos.html", {
        "evs": evs, "filtro": filtro, "diagnosticos": list(Diagnostico.COLOR), "previa": previa,
        "ventana": Parametros.actual().dias_ventana_evaluacion})


@requiere_rol(*TODOS)
def tecnico_detalle(request, pk):
    t = get_object_or_404(_equipo(request), pk=pk)
    hoy = timezone.localdate()
    ev = evaluar_tecnicos(hoy, tecnicos=[t])[0]
    # Productividad semanal del técnico vs. promedio del equipo (26 semanas)
    desde = hoy - timedelta(weeks=26)
    def semanal(qs_ots, qs_jor):
        ots = dict(qs_ots.annotate(s=TruncWeek("fecha_ejecucion")).values_list("s").annotate(n=Count("id")))
        jor = dict(qs_jor.annotate(s=TruncWeek("fecha")).values_list("s").annotate(n=Count("id")))
        return {s: ots.get(s, 0) / n for s, n in jor.items() if n}
    base_o = OrdenTrabajo.objects.filter(estado="completada", fecha_ejecucion__gte=desde)
    base_j = Jornada.objects.filter(en_calle=True, fecha__gte=desde)
    propio = semanal(base_o.filter(tecnico=t), base_j.filter(tecnico=t))
    equipo = semanal(base_o, base_j)
    semanas = sorted(equipo)
    capac = list(Participacion.objects.filter(persona=t).select_related("capacitacion__curso")
                 .order_by("-capacitacion__fecha")[:20])
    g = grafico("line", [s.strftime("%d/%m") for s in semanas], [
        {"nombre": t.nombre_completo, "datos": [propio.get(s) for s in semanas], "serie": 1},
        {"nombre": "Promedio del equipo", "datos": [equipo.get(s) for s in semanas], "serie": 2, "punteada": True},
    ])
    hist = list(EvaluacionHistorica.objects.filter(persona=t).order_by("fecha"))
    g_hist = grafico("line", [h.fecha.strftime("%d/%m") for h in hist], [
        {"nombre": "Riesgo (0-100)", "datos": [h.riesgo for h in hist], "estado": "critico"}], max=100) if hist else None
    return render(request, "tablero/tecnico_detalle.html", {
        "t": t, "ev": ev, "g": g, "g_hist": g_hist, "hist": hist[-8:][::-1], "capacitaciones": capac,
        "acciones": t.acciones_correctivas.select_related("aplicada_por")[:20],
        "siniestros": t.siniestros.all()[:20],
        "informes": t.informes_recibidos.select_related("supervisor")[:15],
        "asignaciones": t.asignaciones.select_related("elemento").filter(estado="en_uso"),
    })


@requiere_rol(*TODOS)
def capacitacion(request):
    """Efectividad de la capacitación: productividad 30 días antes vs. 30 días después."""
    hoy = timezone.localdate()
    evs = evaluar_tecnicos(hoy, tecnicos=_equipo(request))
    pendientes = [e for e in evs if e.diagnostico in (Diagnostico.CAPACITACION, Diagnostico.APRENDIZAJE)]
    filas = []
    parts = (Participacion.objects.filter(asistio=True, capacitacion__fecha__lte=hoy - timedelta(days=14),
                                          capacitacion__fecha__gte=hoy - timedelta(days=180),
                                          persona__in=_equipo(request))
             .select_related("persona", "capacitacion__curso").order_by("-capacitacion__fecha"))
    for p in parts:
        f = p.capacitacion.fecha
        def prod(a, b):
            n = OrdenTrabajo.objects.filter(tecnico=p.persona, estado="completada", fecha_ejecucion__range=(a, b)).count()
            d = Jornada.objects.filter(tecnico=p.persona, en_calle=True, fecha__range=(a, b)).count()
            return n / d if d else None
        antes, despues = prod(f - timedelta(days=30), f - timedelta(days=1)), prod(f + timedelta(days=1), f + timedelta(days=30))
        var = ((despues - antes) / antes * 100) if antes and despues is not None else None
        filas.append({"p": p, "antes": antes, "despues": despues, "var": var})
    vars_ = [f["var"] for f in filas if f["var"] is not None]
    return render(request, "tablero/capacitacion.html", {
        "pendientes": pendientes, "filas": filas[:60], "mejora_prom": sum(vars_) / len(vars_) if vars_ else None})


# ---------------------------------------------------------------- 2. supervisores
@requiere_rol(GERENCIA)
def supervisores(request):
    _, hasta, dias = _rango(request)
    evs = evaluar_supervisores(hasta, dias)
    nombres = [e.supervisor.apellido for e in evs]
    g = grafico("bar", nombres, [
        {"nombre": "Imagen / trato", "datos": [e.score_imagen for e in evs], "serie": 1},
        {"nombre": "Control en calle", "datos": [e.score_control for e in evs], "serie": 2},
        {"nombre": "Gestión de desvíos", "datos": [e.score_desvios for e in evs], "serie": 3},
        {"nombre": "Objetivos", "datos": [e.score_objetivos for e in evs], "serie": 4},
    ], max=100)
    # evolución semanal de la nota de encuesta (promedio de toda la supervisión)
    desde = hasta - timedelta(weeks=16)
    sem = (EncuestaSupervisor.objects.filter(fecha__range=(desde, hasta), respondida__isnull=False)
           .annotate(s=TruncWeek("fecha")).values("s").annotate(t=Avg("trato"), c=Avg("claridad")).order_by("s"))
    g_sem = grafico("line", [r["s"].strftime("%d/%m") for r in sem], [
        {"nombre": "Trato y respeto", "datos": [r["t"] for r in sem], "serie": 1},
        {"nombre": "Claridad de indicaciones", "datos": [r["c"] for r in sem], "serie": 2},
    ], max=5)
    comentarios = (EncuestaSupervisor.objects.filter(fecha__range=(hasta - timedelta(days=dias), hasta))
                   .exclude(comentario="").select_related("supervisor").order_by("-fecha")[:15])
    return render(request, "tablero/supervisores.html", {"evs": evs, "g": g, "g_sem": g_sem, "dias": dias,
                                                        "comentarios": comentarios})


# ---------------------------------------------------------------- 3. incidentes
@requiere_rol(*TODOS)
def incidentes(request):
    hoy = timezone.localdate()
    desde = (hoy.replace(day=1) - timedelta(days=330)).replace(day=1)
    qs = Siniestro.objects.all()
    if rol_de(request.user) == SUPERVISOR:
        qs = qs.filter(tecnico__in=_equipo(request))
    mensual = defaultdict(lambda: defaultdict(int))
    costo = defaultdict(Decimal)
    for r in (qs.filter(fecha__gte=desde).annotate(m=TruncMonth("fecha"))
              .values("m", "gravedad").annotate(n=Count("id"), c=Sum("costo_real"), e=Sum("costo_estimado"))):
        mensual[r["m"]][r["gravedad"]] = r["n"]
        costo[r["m"]] += r["c"] or r["e"] or 0
    meses = sorted(mensual)
    et = [m.strftime("%m/%Y") for m in meses]
    g_mes = grafico("bar", et, [
        {"nombre": "Leve", "datos": [mensual[m]["leve"] for m in meses], "estado": "aviso"},
        {"nombre": "Grave", "datos": [mensual[m]["grave"] for m in meses], "estado": "serio"},
        {"nombre": "Crítica", "datos": [mensual[m]["critica"] for m in meses], "estado": "critico"},
    ], apilado=True)
    g_costo = grafico("bar", et, [{"nombre": "Costo de siniestros", "datos": [costo[m] for m in meses], "serie": 2}],
                      formato="pesos")
    tipos = qs.filter(fecha__gte=desde).values("tipo").annotate(n=Count("id"), c=Sum("costo_real")).order_by("-n")
    nombres_tipo = dict(Siniestro.Tipo.choices)
    tipos = [{**t, "nombre": nombres_tipo.get(t["tipo"], t["tipo"])} for t in tipos]
    abiertos = qs.exclude(estado=Siniestro.Estado.CERRADO).select_related("tecnico").order_by("fecha")
    reincidentes = (qs.filter(fecha__gte=hoy - timedelta(days=180), tecnico__isnull=False)
                    .values("tecnico__id", "tecnico__apellido", "tecnico__nombre").annotate(n=Count("id"))
                    .filter(n__gte=2).order_by("-n"))
    mes = hoy.replace(day=1)
    return render(request, "tablero/incidentes.html", {
        "g_mes": g_mes, "g_costo": g_costo, "tipos": tipos, "abiertos": abiertos, "reincidentes": reincidentes,
        "mes_total": qs.filter(fecha__gte=mes).count(),
        "mes_rc": qs.filter(fecha__gte=mes, responsabilidad_civil=True).exclude(gravedad="leve").count(),
        "costo_anual": sum(costo.values()),
        "recuperado": qs.filter(fecha__gte=desde).aggregate(t=Sum("monto_recuperado"))["t"] or 0,
    })


# ---------------------------------------------------------------- 4. herramientas / EPP
@requiere_rol(*TODOS)
def herramientas(request):
    hoy = timezone.localdate()
    obligatorios = list(Elemento.objects.filter(obligatorio_tecnicos=True))
    equipo = list(_equipo(request))
    vigentes = defaultdict(set)
    for pid, eid in Asignacion.objects.filter(
            persona__in=equipo, estado="en_uso", elemento__in=obligatorios
    ).filter(Q(fecha_vencimiento__isnull=True) | Q(fecha_vencimiento__gte=hoy)).values_list("persona_id", "elemento_id"):
        vigentes[pid].add(eid)
    filas = []
    for t in equipo:
        falta = [e for e in obligatorios if e.id not in vigentes[t.id]]
        filas.append({"t": t, "falta": falta, "ok": len(obligatorios) - len(falta)})
    filas.sort(key=lambda f: -len(f["falta"]))
    completos = sum(1 for f in filas if not f["falta"])
    proximos = (Asignacion.objects.filter(persona__in=equipo, estado="en_uso",
                                          fecha_vencimiento__range=(hoy - timedelta(days=60), hoy + timedelta(days=30)))
                .select_related("persona", "elemento").order_by("fecha_vencimiento"))
    perdidas = (Asignacion.objects.filter(estado__in=["perdido", "danado"], fecha_entrega__gte=hoy - timedelta(days=180))
                .values("persona__apellido", "persona__nombre").annotate(n=Count("id")).order_by("-n")[:10])
    return render(request, "tablero/herramientas.html", {
        "filas": filas, "obligatorios": obligatorios, "completos": completos, "total": len(filas),
        "proximos": proximos, "elementos": Elemento.objects.all(), "perdidas": perdidas, "hoy": hoy})


# ---------------------------------------------------------------- 6. flota
@requiere_rol(*TODOS)
def flota(request):
    hoy = timezone.localdate()
    filas = []
    for v in Vehiculo.objects.select_related("asignado_a"):
        prox = proximos_services(v, hoy)
        peor = min((p for p in prox if p["dias"] is not None), key=lambda p: p["dias"], default=None)
        filas.append({"v": v, "prox": prox, "peor": peor})
    filas.sort(key=lambda f: f["peor"]["dias"] if f["peor"] else 9999)
    costos = (ServiceRealizado.objects.filter(fecha__gte=hoy - timedelta(days=365))
              .values("vehiculo__patente").annotate(t=Sum("costo"), n=Count("id")).order_by("-t"))
    g = grafico("bar", [c["vehiculo__patente"] for c in costos],
                [{"nombre": "Costo de services (12 meses)", "datos": [c["t"] for c in costos], "serie": 1}],
                formato="pesos")
    estados = Counter(f["v"].estado for f in filas)
    dia = ultimo_dia_con_datos(hoy)
    usados = Jornada.objects.filter(fecha=dia, vehiculo__isnull=False).values("vehiculo").distinct().count()
    return render(request, "tablero/flota.html", {
        "filas": filas, "g": g, "operativos": estados.get("operativo", 0), "taller": estados.get("taller", 0),
        "fuera": estados.get("fuera", 0), "total": len(filas), "usados": usados, "dia": dia,
        "vencidos": sum(1 for f in filas if f["peor"] and f["peor"]["estado"] == "critico")})


# ---------------------------------------------------------------- 7. finanzas
@requiere_rol(GERENCIA)
def finanzas(request):
    hoy = timezone.localdate()
    hist = historico_mensual(6, hoy)
    cats = sorted({c for v in hist.values() for c in v})
    meses = list(hist)
    g_hist = grafico("bar", [m.strftime("%m/%Y") for m in meses], [
        {"nombre": c, "datos": [hist[m].get(c, 0) for m in meses], "serie": i + 1} for i, c in enumerate(cats[:8])
    ], apilado=True, formato="pesos")
    proy = proyectar(3, hoy)
    g_proy = grafico("bar", [p["mes"].strftime("%m/%Y") for p in proy], [
        {"nombre": "Materiales", "datos": [p["materiales"] for p in proy], "serie": 1},
        {"nombre": "Costos fijos", "datos": [p["fijos"] for p in proy], "serie": 2},
        {"nombre": "Flota", "datos": [p["flota"] for p in proy], "serie": 3},
        {"nombre": "EPP / herramientas", "datos": [p["epp"] for p in proy], "serie": 4},
        {"nombre": "Siniestros", "datos": [p["siniestros"] for p in proy], "serie": 5},
    ], apilado=True, formato="pesos")
    mes = hoy.replace(day=1)
    return render(request, "tablero/finanzas.html", {
        "g_hist": g_hist, "g_proy": g_proy, "proy": proy,
        "mes_actual": Egreso.objects.filter(fecha__gte=mes).aggregate(t=Sum("monto"))["t"] or 0,
        "por_cat": Egreso.objects.filter(fecha__gte=mes).values("categoria__nombre").annotate(t=Sum("monto")).order_by("-t"),
        "fijos": CostoFijo.objects.filter(activo=True),
        "ultimos": Egreso.objects.select_related("categoria")[:15]})


# ---------------------------------------------------------------- 8. stock
@requiere_rol(*TODOS)
def stock(request):
    hoy = timezone.localdate()
    sd = stock_diario(hoy)
    lotes = lotes_envejecidos(hoy)
    p = Parametros.actual()
    tramos = [(0, 30, "0–30 días"), (31, p.dias_aviso_stock - 1, f"31–{p.dias_aviso_stock - 1} días"),
              (p.dias_aviso_stock, p.dias_max_stock - 1, f"{p.dias_aviso_stock}–{p.dias_max_stock - 1} días"),
              (p.dias_max_stock, 10 ** 6, f"{p.dias_max_stock}+ días")]
    valores = [sum(f["valor"] for f in lotes if a <= f["dias"] <= b) for a, b, _ in tramos]
    g_aging = grafico("bar", [t[2] for t in tramos], [
        {"nombre": "Valor inmovilizado", "datos": valores, "colores": ["--s1", "--s1", "--aviso", "--critico"]}],
        formato="pesos")
    try:
        horizonte = max(1, min(60, int(request.GET.get("horizonte", 14))))
    except ValueError:
        horizonte = 14
    prev = prevision_materiales(hoy, hoy + timedelta(days=horizonte - 1))
    criticos = [f for f in lotes if f["estado"] != "ok"]
    consumo = (Salida.objects.filter(fecha__gte=hoy - timedelta(days=29), motivo="consumo")
               .annotate(s=TruncWeek("fecha")).values("s").annotate(t=Sum("costo_total")).order_by("s"))
    return render(request, "tablero/stock.html", {
        "sd": sd, "criticos": criticos, "g_aging": g_aging, "prev": prev, "horizonte": horizonte, "p": p,
        "valor_total": sum(f["valor"] for f in lotes), "valor_parado": valores[-1],
        "faltantes": [f for f in sd["filas"] if f["estado"] != "ok"],
        "compra_total": sum(f["costo_compra"] for f in prev), "consumo": consumo})


# ---------------------------------------------------------------- 9. planificación
@requiere_rol(*TODOS)
def planificacion(request):
    hoy = timezone.localdate()
    p = Parametros.actual()
    dia = ultimo_dia_con_datos(hoy)

    def num(nombre, defecto, tipo=float):
        try:
            return tipo(request.GET.get(nombre, "").replace(",", ".")) if request.GET.get(nombre) else defecto
        except ValueError:
            return defecto

    prob = probabilidad_decodificador(hoy)
    ha_real = hectareas_reales_por_cuadrilla(hoy)
    zonas = Zona.objects.filter(activa=True)
    zona_id = request.GET.get("zona")
    zona = zonas.filter(pk=zona_id).first() if zona_id else None
    entradas = {
        "tecnicos": num("tecnicos", tecnicos_en_calle(dia), int),
        "ha_min": num("ha_min", float(p.hectareas_dia_min)),
        "ha_max": num("ha_max", float(p.hectareas_dia_max)),
        "densidad": num("densidad", float(zona.densidad_clientes_ha) if zona else None),
        "prob_min": num("prob_min", float(p.prob_decodificador_min) * 100) / 100,
        "prob_max": num("prob_max", float(p.prob_decodificador_max) * 100) / 100,
        "dias": num("dias", 14, int),
    }
    cap = capacidad(entradas["tecnicos"], entradas["ha_min"], entradas["ha_max"], entradas["densidad"],
                    entradas["prob_min"], entradas["prob_max"], prob.media)
    dias = max(1, min(60, entradas["dias"]))
    filas = demanda_vs_capacidad(hoy, dias, entradas["tecnicos"])
    g = grafico("bar", [f["fecha"].strftime("%d/%m") for f in filas], [
        {"nombre": "Demanda comercial (clientes)", "datos": [f["demanda"] for f in filas], "serie": 1},
        {"nombre": "Capacidad (clientes)", "datos": [f["capacidad"] for f in filas], "serie": 2, "tipo": "line"},
    ])
    fin = hoy + timedelta(days=dias - 1)
    stock_deco = stock_decodificadores()
    deco = {"bajo": decodificadores_necesarios(hoy, fin, entradas["prob_min"]),
            "alto": decodificadores_necesarios(hoy, fin, entradas["prob_max"]),
            "estimado": decodificadores_necesarios(hoy, fin, prob.media)}
    g_prob = grafico("bar", ["Supuesto bajo", "Supuesto alto", "Estimado con datos reales"], [
        {"nombre": "Probabilidad de pedir decodificador",
         "datos": [entradas["prob_min"] * 100, entradas["prob_max"] * 100, prob.media * 100], "serie": 1}],
        formato="pct", max=100)
    return render(request, "tablero/planificacion.html", {
        "e": entradas, "cap": cap, "prob": prob, "ha_real": ha_real, "filas": filas, "g": g, "g_prob": g_prob,
        "deficit": [f for f in filas if not f["ok"]], "deco": deco, "stock_deco": stock_deco, "zonas": zonas,
        "zona": zona, "p": p, "dia": dia, "dias": dias,
        "deco_faltante": max(0.0, deco["estimado"] - float(stock_deco)),
        "prev": prevision_materiales(hoy, fin)})


# ---------------------------------------------------------------- envío de encuestas
def link_whatsapp(telefono: str, texto: str) -> str | None:
    """Enlace wa.me con el mensaje precargado (formato argentino: 54 9 + área + número)."""
    from urllib.parse import quote
    digitos = "".join(ch for ch in telefono or "" if ch.isdigit())
    if not digitos:
        return None
    if digitos.startswith("0"):
        digitos = digitos[1:]
    if not digitos.startswith("54"):
        digitos = "549" + digitos
    return f"https://wa.me/{digitos}?text={quote(texto)}"


@requiere_rol(*TODOS)
def encuestas(request):
    """Encuestas del día con link para enviar por WhatsApp (sin proveedor pago)."""
    hoy = timezone.localdate()
    try:
        fecha = date.fromisoformat(request.GET.get("fecha", ""))
    except ValueError:
        fecha = hoy
    qs = (EncuestaSupervisor.objects.filter(fecha=fecha, tecnico__in=_equipo(request))
          .select_related("tecnico", "supervisor").order_by("respondida", "tecnico__apellido"))
    filas = []
    for e in qs:
        url = request.build_absolute_uri(reverse("encuesta", args=[e.token]))
        texto = (f"Hola {e.tecnico.nombre}, ¿cómo te fue hoy? Contanos cómo te trató tu supervisor "
                 f"(20 segundos, confidencial): {url}")
        filas.append({"e": e, "url": url, "wa": link_whatsapp(e.tecnico.telefono, texto)})
    respondidas = sum(1 for f in filas if f["e"].respondida)
    return render(request, "tablero/encuestas.html", {"filas": filas, "fecha": fecha, "respondidas": respondidas,
                                                       "pendientes": len(filas) - respondidas})


# ---------------------------------------------------------------- alertas
@requiere_rol(*TODOS)
def alertas(request):
    qs = Alerta.objects.filter(resuelta=request.GET.get("resueltas") == "1")
    modulo = request.GET.get("modulo")
    if modulo:
        qs = qs.filter(modulo=modulo)
    lista = sorted(qs[:500], key=lambda a: ({"critica": 0, "aviso": 1, "info": 2}[a.nivel], -a.id))
    return render(request, "tablero/alertas.html", {"alertas": lista, "modulos": Alerta.Modulo.choices,
                                                    "modulo": modulo})


@require_POST
@requiere_rol(GERENCIA)
def resolver_alerta(request, pk):
    a = get_object_or_404(Alerta, pk=pk)
    a.resuelta = True
    a.save()
    messages.success(request, "Alerta marcada como resuelta. Si la condición persiste, volverá a abrirse.")
    destino = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
        destino = reverse("tablero:alertas")
    return redirect(destino)
