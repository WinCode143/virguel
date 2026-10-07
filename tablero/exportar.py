"""Exportaciones para Power BI / Excel.

* CSV por dataset: /api/powerbi/<dataset>.csv  (sesión de gerencia o ?token=<POWERBI_TOKEN>)
* Indicadores calculados (evaluación de técnicos y supervisores) también se
  exportan, porque no viven en tablas sino que se calculan en Python.
"""
import csv
import hmac
import os

from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone

from capacitacion.evaluacion import evaluar_tecnicos
from core.roles import GERENCIA, requiere_rol, rol_de
from supervision.evaluacion import evaluar_supervisores


def _sql(consulta):
    def f():
        from django.db import connection
        with connection.cursor() as c:
            c.execute(consulta)
            cols = [d[0] for d in c.description]
            yield cols
            yield from c.fetchall()
    return f


def _tecnicos():
    yield ["legajo", "tecnico", "supervisor", "dias_calle", "ot_completadas", "ot_fallidas", "retrabajos_causados",
           "productividad_ot_dia", "indice_vs_mediana", "tendencia_pct", "puntaje_controles", "score_productividad",
           "score_calidad", "score_disciplina", "score_seguridad", "riesgo", "nivel_riesgo", "diagnostico", "motivos"]
    for e in evaluar_tecnicos():
        t = e.tecnico
        yield [t.legajo, t.nombre_completo, t.supervisor.nombre_completo if t.supervisor else "", e.dias_calle,
               e.completadas, e.fallidas, e.retrabajos_causados, round(e.productividad, 3),
               round(e.indice_productividad, 3), round(e.tendencia, 1),
               round(e.puntaje_controles, 2) if e.puntaje_controles else "", round(e.score_productividad, 1),
               round(e.score_calidad, 1), round(e.score_disciplina, 1), round(e.score_seguridad, 1), e.riesgo,
               e.nivel_riesgo, e.diagnostico, " | ".join(e.motivos)]


def _supervisores():
    yield ["legajo", "supervisor", "tecnicos_a_cargo", "informes", "informes_por_dia", "calidad_documentacion",
           "desvios", "desvios_con_accion", "dias_respuesta_prom", "encuestas_enviadas", "encuestas_respondidas",
           "nota_trato", "nota_claridad", "nota_apoyo", "nota_presencia", "cumplimiento_tareas", "score_imagen",
           "score_control", "score_desvios", "score_objetivos", "score_total"]
    r = lambda v, n=2: round(v, n) if v is not None else ""
    for e in evaluar_supervisores():
        s = e.supervisor
        yield [s.legajo, s.nombre_completo, e.tecnicos_a_cargo, e.informes, r(e.informes_por_dia),
               r(e.calidad_documentacion, 1), e.desvios, e.desvios_con_accion, r(e.dias_respuesta_prom, 1),
               e.encuestas_enviadas, e.encuestas_respondidas, r(e.nota_trato), r(e.nota_claridad), r(e.nota_apoyo),
               r(e.nota_presencia), r(e.cumplimiento_tareas), r(e.score_imagen, 1), r(e.score_control, 1),
               r(e.score_desvios, 1), r(e.score_objetivos, 1), e.score_total]


DATASETS = {
    "personal": ("Padrón de personal", _sql("SELECT * FROM powerbi.personal")),
    "asistencia": ("Asistencia (fichadas)", _sql("SELECT * FROM powerbi.asistencia")),
    "novedades": ("Novedades y licencias", _sql("SELECT * FROM powerbi.novedades")),
    "ordenes": ("Órdenes de trabajo", _sql("SELECT * FROM powerbi.ordenes")),
    "jornadas": ("Jornadas (personal en calle)", _sql("SELECT * FROM powerbi.jornadas")),
    "stock_lotes": ("Stock por lote con antigüedad", _sql("SELECT * FROM powerbi.stock_lotes")),
    "salidas": ("Salidas / consumos de material", _sql("SELECT * FROM powerbi.salidas")),
    "demanda": ("Demanda comercial prevista", _sql("SELECT * FROM powerbi.demanda")),
    "informes": ("Informes de control de supervisores", _sql("SELECT * FROM powerbi.informes")),
    "acciones": ("Acciones correctivas", _sql("SELECT * FROM powerbi.acciones")),
    "encuestas": ("Encuestas diarias a supervisores", _sql("SELECT * FROM powerbi.encuestas")),
    "siniestros": ("Siniestros / incidentes", _sql("SELECT * FROM powerbi.siniestros")),
    "egresos": ("Egresos", _sql("SELECT * FROM powerbi.egresos")),
    "services": ("Services de flota", _sql("SELECT * FROM powerbi.services")),
    "epp": ("Asignaciones de EPP / herramientas", _sql("SELECT * FROM powerbi.epp")),
    "evaluacion_historica": ("Historial semanal de evaluación de técnicos", _sql("SELECT * FROM powerbi.evaluacion_historica")),
    "evaluacion_tecnicos": ("Evaluación de técnicos (calculada)", _tecnicos),
    "evaluacion_supervisores": ("Evaluación de supervisores (calculada)", _supervisores),
}


def _autorizado(request):
    token = os.environ.get("POWERBI_TOKEN", "")
    if token and hmac.compare_digest(request.GET.get("token", ""), token):
        return True
    return rol_de(request.user) == GERENCIA


def exportar_csv(request, dataset):
    if dataset not in DATASETS:
        raise Http404
    if not _autorizado(request):
        return HttpResponseForbidden("Requiere sesión de gerencia o token de Power BI.")
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="virguel_{dataset}_{timezone.localdate():%Y%m%d}.csv"'
    resp.write("﻿")  # BOM: Excel abre bien los acentos
    w = csv.writer(resp)
    for fila in DATASETS[dataset][1]():
        w.writerow(fila)
    return resp


@requiere_rol(GERENCIA)
def indice(request):
    base = request.build_absolute_uri("/api/powerbi/")
    return render(request, "tablero/powerbi.html", {
        "datasets": [(k, v[0]) for k, v in DATASETS.items()], "base": base,
        "hay_token": bool(os.environ.get("POWERBI_TOKEN"))})
