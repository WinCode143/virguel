"""Pantallas de escritorio de control de personal."""
import csv
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin

from core.models import Parametros, Persona
from core.roles import GERENCIA, SUPERVISOR, persona_de, requiere_rol, rol_de
from tablero.views import grafico

from .indicadores import (documentos_faltantes_o_vencidos, dotacion_mensual, es_laborable, estado_del_dia,
                          ranking_tardanzas, resumen)
from .models import Asistencia, DocumentoPersonal, Feriado, Novedad

TODOS = (GERENCIA, SUPERVISOR)


def personal_visible(request, incluir_inactivos=False):
    """Gerencia ve a todos (menos gerencia); el supervisor, a su equipo y a sí mismo."""
    qs = Persona.objects.exclude(rol=Persona.Rol.GERENCIA)
    if not incluir_inactivos:
        qs = qs.filter(activo=True)
    if rol_de(request.user) == SUPERVISOR:
        yo = persona_de(request.user)
        qs = qs.filter(Q(supervisor=yo) | Q(pk=yo.pk))
    return qs.select_related("supervisor", "zona")


def _fecha(request, nombre, defecto):
    try:
        return date.fromisoformat(request.GET.get(nombre, ""))
    except ValueError:
        return defecto


@requiere_rol(*TODOS)
def hoy(request):
    fecha = _fecha(request, "fecha", timezone.localdate())
    personas = personal_visible(request)
    sup = request.GET.get("supervisor")
    if sup:
        personas = personas.filter(Q(supervisor_id=sup) | Q(pk=sup))
    filas = estado_del_dia(fecha, personas)
    cuenta = Counter(f.situacion[0] for f in filas)
    laborables = [f for f in filas if f.laborable]
    presentes = sum(1 for f in filas if f.asistencia)
    tarde = sum(1 for f in filas if f.asistencia and f.asistencia.minutos_tarde)
    con_aviso = sum(1 for f in filas if not f.asistencia and f.novedad)
    sin_aviso = sum(1 for f in filas if f.situacion[1] == "Sin fichar y sin aviso")

    # presentismo diario de los últimos 30 días (sólo días laborables)
    desde = fecha - timedelta(days=29)
    personas_l = list(personas)
    feriados = set(Feriado.objects.filter(fecha__range=(desde, fecha)).values_list("fecha", flat=True))
    pres = dict(Asistencia.objects.filter(persona__in=personas_l, fecha__range=(desde, fecha))
                .values_list("fecha").annotate(n=Count("id")))
    dias, valores = [], []
    for i in range(30):
        d = desde + timedelta(days=i)
        esperados = sum(1 for p in personas_l if es_laborable(p, d, feriados))
        if esperados:
            dias.append(d.strftime("%d/%m"))
            valores.append(min(100, pres.get(d, 0) / esperados * 100))
    g = grafico("line", dias, [{"nombre": "Presentismo diario", "datos": valores}], formato="pct", max=100)
    supervisores = Persona.objects.filter(rol="supervisor", activo=True) if rol_de(request.user) == GERENCIA else []
    return render(request, "personal/hoy.html", {
        "fecha": fecha, "filas": filas, "cuenta": cuenta, "total": len(laborables), "presentes": presentes,
        "tarde": tarde, "con_aviso": con_aviso, "sin_aviso": sin_aviso, "g": g, "supervisores": supervisores,
        "sup": sup, "es_hoy": fecha == timezone.localdate()})


@requiere_rol(*TODOS)
def asistencia(request):
    hasta = _fecha(request, "hasta", timezone.localdate())
    desde = _fecha(request, "desde", hasta.replace(day=1))
    personas = personal_visible(request)
    rol = request.GET.get("rol")
    if rol:
        personas = personas.filter(rol=rol)
    filas = resumen(desde, hasta, personas)
    if request.GET.get("formato") == "csv":
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="asistencia_{desde:%Y%m%d}_{hasta:%Y%m%d}.csv"'
        resp.write("﻿")
        w = csv.writer(resp, delimiter=";")
        w.writerow(["legajo", "apellido", "nombre", "rol", "supervisor", "dias_esperados", "presentes",
                    "justificadas", "injustificadas", "vacaciones_francos", "tardanzas", "minutos_tarde",
                    "horas", "horas_extra", "presentismo"])
        for r in filas:
            p = r.persona
            w.writerow([p.legajo, p.apellido, p.nombre, p.get_rol_display(),
                        p.supervisor.nombre_completo if p.supervisor else "", r.esperados, r.presentes,
                        r.justificadas, r.injustificadas, r.no_computables, r.tardanzas, r.minutos_tarde,
                        str(r.horas).replace(".", ","), str(r.horas_extra).replace(".", ","),
                        f"{r.presentismo * 100:.1f}".replace(".", ",") if r.presentismo is not None else ""])
        return resp
    tot = defaultdict(float)
    for r in filas:
        for k in ("esperados", "presentes", "justificadas", "injustificadas", "no_computables", "tardanzas"):
            tot[k] += getattr(r, k)
        tot["horas_extra"] += float(r.horas_extra)
    base = tot["esperados"] - tot["no_computables"]
    motivos = Counter()
    for r in filas:
        motivos.update(r.por_tipo)
    nombres = dict(Novedad.Tipo.choices) | {"sin_aviso": "Sin aviso"}
    orden = sorted(motivos.items(), key=lambda kv: -kv[1])
    g_motivos = grafico("bar", [nombres.get(k, k) for k, _ in orden],
                        [{"nombre": "Días", "datos": [v for _, v in orden], "serie": 2}], horizontal=True)
    return render(request, "personal/asistencia.html", {
        "desde": desde, "hasta": hasta, "filas": filas, "rol": rol, "tot": tot,
        "presentismo": tot["presentes"] / base if base else None, "g_motivos": g_motivos,
        "tardanzas": ranking_tardanzas(desde, hasta, personas),
        "pendientes": Novedad.objects.filter(persona__in=personas, estado="pendiente").select_related("persona")})


@requiere_rol(*TODOS)
def legajo(request, pk):
    p = get_object_or_404(personal_visible(request, incluir_inactivos=True), pk=pk)
    hoy_ = timezone.localdate()
    mes = resumen(hoy_.replace(day=1), hoy_, [p])[0]
    trimestre = resumen(hoy_ - timedelta(days=89), hoy_, [p])[0]
    ev = None
    if p.rol == "tecnico":
        from capacitacion.evaluacion import evaluar_tecnicos
        ev = evaluar_tecnicos(hoy_, tecnicos=[p])[0]
    return render(request, "personal/legajo.html", {
        "p": p, "mes": mes, "trimestre": trimestre, "ev": ev,
        "fichadas": p.asistencias.all()[:20],
        "novedades": p.novedades.all()[:20],
        "documentos": p.documentos.select_related("tipo"),
        "faltantes": [f for f in documentos_faltantes_o_vencidos([p]) if f["doc"] is None],
        "acciones": p.acciones_correctivas.select_related("aplicada_por")[:15],
        "siniestros": p.siniestros.all()[:10],
        "capacitaciones": p.participaciones.select_related("capacitacion__curso").order_by("-capacitacion__fecha")[:10],
        "asignaciones": p.asignaciones.select_related("elemento").filter(estado="en_uso"),
        "vehiculos": p.vehiculos.all(), "a_cargo": p.a_cargo.filter(activo=True) if p.rol == "supervisor" else [],
        "antiguedad": (hoy_ - p.fecha_ingreso).days // 365,
    })


@requiere_rol(*TODOS)
def legajos(request):
    q = request.GET.get("q", "").strip()
    personas = personal_visible(request, incluir_inactivos=request.GET.get("inactivos") == "1")
    if q:
        personas = personas.filter(Q(apellido__icontains=q) | Q(nombre__icontains=q) | Q(legajo__icontains=q)
                                   | Q(dni__icontains=q))
    return render(request, "personal/legajos.html", {"personas": personas.order_by("rol", "apellido"), "q": q})


@requiere_rol(GERENCIA)
def dotacion(request):
    hoy_ = timezone.localdate()
    filas = dotacion_mensual(12, hoy_)
    et = [f["mes"].strftime("%m/%Y") for f in filas]
    g_dot = grafico("line", et, [{"nombre": "Dotación a fin de mes", "datos": [f["dotacion"] for f in filas]}])
    g_mov = grafico("bar", et, [{"nombre": "Altas", "datos": [f["altas"] for f in filas], "serie": 3},
                                {"nombre": "Bajas", "datos": [f["bajas"] for f in filas], "serie": 2}])
    activos = Persona.objects.filter(activo=True).exclude(rol=Persona.Rol.GERENCIA)
    tramos = [(0, 0.5, "< 6 meses"), (0.5, 1, "6–12 meses"), (1, 3, "1–3 años"), (3, 5, "3–5 años"), (5, 99, "5+ años")]
    anios = [(hoy_ - p.fecha_ingreso).days / 365 for p in activos]
    g_ant = grafico("bar", [t[2] for t in tramos], [{"nombre": "Personas", "datos": [
        sum(1 for a in anios if lo <= a < hi) for lo, hi, _ in tramos]}])
    bajas = (Persona.objects.filter(fecha_egreso__gte=hoy_ - timedelta(days=365)).values("motivo_egreso")
             .annotate(n=Count("id")).order_by("-n"))
    nombres = dict(Persona._meta.get_field("motivo_egreso").choices)
    por_rol = activos.values("rol").annotate(n=Count("id"))
    rotacion_anual = sum(f["bajas"] for f in filas) / (sum(f["dotacion"] for f in filas) / len(filas)) if filas else 0
    return render(request, "personal/dotacion.html", {
        "g_dot": g_dot, "g_mov": g_mov, "g_ant": g_ant, "activos": activos.count(),
        "por_rol": {r["rol"]: r["n"] for r in por_rol}, "rotacion_anual": rotacion_anual,
        "bajas": [{"motivo": nombres.get(b["motivo_egreso"], "Sin dato"), "n": b["n"]} for b in bajas],
        "antiguedad_prom": sum(anios) / len(anios) if anios else 0,
        "documentos": documentos_faltantes_o_vencidos(activos),
        "egresos": Persona.objects.filter(fecha_egreso__gte=hoy_ - timedelta(days=180)).order_by("-fecha_egreso")})


@requiere_rol(*TODOS)
def documentos(request):
    personas = personal_visible(request)
    return render(request, "personal/documentos.html", {
        "filas": documentos_faltantes_o_vencidos(personas),
        "proximos": DocumentoPersonal.objects.filter(persona__in=personas, vencimiento__isnull=False)
        .select_related("persona", "tipo").order_by("vencimiento")[:50], "hoy": timezone.localdate(),
        "p": Parametros.actual()})


@xframe_options_sameorigin
@requiere_rol(*TODOS)
def parte(request):
    """Vista previa del parte diario (el mismo HTML que llega por mail) y envío manual."""
    from django.contrib import messages
    from django.http import HttpResponse as Http
    from django.shortcuts import redirect

    from .parte import armar, destinatarios_gerencia, enviar, render as render_parte
    fecha = _fecha(request, "fecha", timezone.localdate())
    sup = persona_de(request.user) if rol_de(request.user) == SUPERVISOR else None
    if request.method == "POST" and rol_de(request.user) == GERENCIA:
        n = enviar(fecha, log=lambda *_: None)
        messages.success(request, f"{n} parte(s) enviado(s).") if n else messages.warning(
            request, "No hay destinatarios: cargá mails en Parámetros del sistema o en los supervisores.")
        return redirect(f"{request.path}?fecha={fecha.isoformat()}")
    asunto, _, html = render_parte(armar(fecha, sup))
    if request.GET.get("solo") == "mail":
        return Http(html)
    from django.conf import settings
    return render(request, "personal/parte.html", {
        "fecha": fecha, "asunto": asunto, "destinatarios": destinatarios_gerencia(),
        "supervisores_con_mail": Persona.objects.filter(rol="supervisor", activo=True).exclude(email="").count(),
        "smtp": "smtp" in settings.EMAIL_BACKEND})
