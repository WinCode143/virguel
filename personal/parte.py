"""Parte diario por mail: resumen del día para gerencia y para cada supervisor (su equipo)."""
from datetime import date, timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Count
from django.template.loader import render_to_string
from django.utils import timezone

from core.models import Alerta, Parametros, Persona
from incidentes.models import Siniestro
from operaciones.models import OrdenTrabajo
from supervision.models import InformeControl

from .indicadores import documentos_faltantes_o_vencidos, estado_del_dia
from .models import Novedad


def armar(fecha: date, supervisor: Persona | None = None) -> dict:
    """Datos del parte. Con supervisor: sólo su equipo."""
    personas = Persona.objects.filter(activo=True).exclude(rol=Persona.Rol.GERENCIA)
    if supervisor:
        personas = personas.filter(supervisor=supervisor)
    personas = list(personas.select_related("supervisor"))
    estado = estado_del_dia(fecha, personas)
    laborables = [e for e in estado if e.laborable]
    sin_aviso = [e for e in estado if e.situacion[1] == "Sin fichar y sin aviso"]
    tarde = [e for e in estado if e.asistencia and e.asistencia.minutos_tarde]
    con_aviso = [e for e in estado if not e.asistencia and e.novedad]
    sin_salida = [e for e in estado if e.asistencia and not e.asistencia.salida]

    ots = OrdenTrabajo.objects.filter(fecha_ejecucion=fecha, tecnico__in=personas)
    por_estado = dict(ots.values_list("estado").annotate(n=Count("id")))
    completadas = por_estado.get("completada", 0)
    ejecutadas = sum(por_estado.values())
    informes = InformeControl.objects.filter(fecha=fecha, tecnico__in=personas)
    desvios_sin_accion = informes.filter(desvio_detectado=True, acciones__isnull=True).count()
    siniestros = Siniestro.objects.filter(fecha=fecha, tecnico__in=personas)
    novedades_pend = Novedad.objects.filter(persona__in=personas, estado="pendiente").count()
    docs = [d for d in documentos_faltantes_o_vencidos(personas)
            if d["doc"] and d["doc"].vencimiento and d["doc"].vencimiento <= fecha + timedelta(days=7)]
    criticas = Alerta.objects.filter(resuelta=False, nivel=Alerta.Nivel.CRITICA).order_by("-creada")[:10] \
        if supervisor is None else []
    return {
        "fecha": fecha, "supervisor": supervisor, "url": settings.URL_SISTEMA.rstrip("/"),
        "dotacion": len(laborables), "presentes": sum(1 for e in estado if e.asistencia),
        "sin_aviso": sin_aviso, "tarde": tarde, "con_aviso": con_aviso, "sin_salida": sin_salida,
        "completadas": completadas, "ejecutadas": ejecutadas,
        "efectividad": completadas / ejecutadas if ejecutadas else None,
        "informes": informes.count(), "desvios": informes.filter(desvio_detectado=True).count(),
        "desvios_sin_accion": desvios_sin_accion, "siniestros": list(siniestros),
        "novedades_pend": novedades_pend, "docs": docs, "criticas": criticas,
        "tolerancia": Parametros.actual().tolerancia_tarde_minutos,
    }


def render(ctx: dict) -> tuple[str, str, str]:
    asunto = (f"Parte diario {ctx['fecha']:%d/%m/%Y}"
              + (f" · equipo {ctx['supervisor'].apellido}" if ctx["supervisor"] else "")
              + f" · {ctx['presentes']}/{ctx['dotacion']} presentes"
              + (f" · {len(ctx['sin_aviso'])} sin aviso" if ctx["sin_aviso"] else ""))
    return asunto, render_to_string("personal/parte_mail.txt", ctx), render_to_string("personal/parte_mail.html", ctx)


def destinatarios_gerencia() -> list[str]:
    texto = Parametros.actual().destinatarios_parte or ""
    return [m.strip() for m in texto.replace(",", "\n").splitlines() if "@" in m]


def enviar(fecha: date | None = None, log=print) -> int:
    """Envía el parte general a gerencia y uno por equipo a cada supervisor con mail."""
    fecha = fecha or timezone.localdate()
    enviados = 0
    envios = []
    if destinatarios_gerencia():
        envios.append((destinatarios_gerencia(), armar(fecha)))
    for s in Persona.objects.filter(rol=Persona.Rol.SUPERVISOR, activo=True).exclude(email=""):
        envios.append(([s.email], armar(fecha, s)))
    for para, ctx in envios:
        asunto, texto, html = render(ctx)
        m = EmailMultiAlternatives(asunto, texto, settings.DEFAULT_FROM_EMAIL, para)
        m.attach_alternative(html, "text/html")
        m.send()
        enviados += 1
        log(f"Parte enviado a {', '.join(para)}")
    if not envios:
        log("Parte diario: no hay destinatarios (cargar mails en Parámetros o en los supervisores).")
    return enviados
