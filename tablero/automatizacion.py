"""Tareas automáticas diarias (las ejecuta `manage.py tareas_diarias`)."""
from datetime import timedelta

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from capacitacion.evaluacion import Diagnostico, evaluar_tecnicos, guardar_historial
from capacitacion.models import EvaluacionHistorica
from core.models import Alerta, Persona
from core.services import SincronizadorAlertas
from flota.models import Vehiculo, proximos_services
from herramientas.models import Asignacion, Elemento
from incidentes.models import Siniestro
from inventario.services import lotes_envejecidos, stock_diario
from operaciones.models import Jornada
from supervision.evaluacion import evaluar_supervisores
from supervision.models import EncuestaSupervisor, TareaSupervisor

C, A = Alerta.Nivel.CRITICA, Alerta.Nivel.AVISO


def generar_encuestas(fecha=None):
    """Una encuesta por técnico que estuvo en calle y tiene supervisor asignado."""
    from core.models import Parametros
    fecha = fecha or timezone.localdate()
    if not Parametros.actual().encuesta_diaria:
        return 0
    creadas = 0
    for j in Jornada.objects.filter(fecha=fecha, en_calle=True, tecnico__supervisor__isnull=False
                                    ).select_related("tecnico"):
        _, nueva = EncuestaSupervisor.objects.get_or_create(
            fecha=fecha, tecnico=j.tecnico, defaults={"supervisor": j.tecnico.supervisor})
        creadas += nueva
    return creadas


def cerrar_tareas_vencidas(fecha=None):
    fecha = fecha or timezone.localdate()
    return TareaSupervisor.objects.filter(fecha__lt=fecha, estado=TareaSupervisor.Estado.PENDIENTE).update(
        estado=TareaSupervisor.Estado.NO_CUMPLIDA)


def alertas_stock(hoy):
    with SincronizadorAlertas(Alerta.Modulo.STOCK) as s:
        url = reverse("tablero:stock")
        for f in lotes_envejecidos(hoy):
            if f["estado"] == "ok":
                continue
            lote = f["lote"]
            s.alerta(f"lote-{lote.id}",
                     f"{f['material'].nombre}: {lote.cantidad_disponible:g} {f['material'].unidad} parados hace {f['dias']} días",
                     f"Lote ingresado el {lote.fecha:%d/%m/%Y}. Valor inmovilizado ${f['valor']:,.0f}.",
                     C if f["estado"] == "critico" else A, url)
        for f in stock_diario(hoy)["filas"]:
            if f["estado"] == "ok":
                continue
            m = f["material"]
            dias = f"{f['dias_cobertura']:.1f} días" if f["dias_cobertura"] is not None else "—"
            s.alerta(f"cobertura-{m.id}", f"{m.nombre}: stock para {dias} (stock {f['stock']:g} {m.unidad})",
                     f"Consumo estimado {f['consumo_dia']:.1f} {m.unidad}/día con el personal en calle.",
                     C if f["estado"] == "critico" else A, url)


def alertas_flota(hoy):
    with SincronizadorAlertas(Alerta.Modulo.FLOTA) as s:
        url = reverse("tablero:flota")
        for v in Vehiculo.objects.exclude(estado=Vehiculo.Estado.FUERA):
            for p in proximos_services(v, hoy):
                if p["estado"] != "ok":
                    s.alerta(f"service-{v.id}-{p['tipo'].id}",
                             f"{v.patente}: {p['tipo'].nombre} " + ("VENCIDO" if p["estado"] == "critico"
                                                                    else f"en {p['dias']} días"),
                             f"Km actual {v.km_actual:,}. Próximo a los {p['prox_km'] or '—'} km.",
                             C if p["estado"] == "critico" else A, url)
            for campo, nombre in (("vencimiento_vtv", "VTV"), ("vencimiento_seguro", "Seguro")):
                venc = getattr(v, campo)
                if venc and venc <= hoy + timedelta(days=15):
                    s.alerta(f"{campo}-{v.id}", f"{v.patente}: {nombre} vence el {venc:%d/%m/%Y}", "",
                             C if venc <= hoy else A, url)


def alertas_epp(hoy):
    with SincronizadorAlertas(Alerta.Modulo.EPP) as s:
        url = reverse("tablero:herramientas")
        for a in Asignacion.objects.filter(estado=Asignacion.Estado.EN_USO, fecha_vencimiento__lte=hoy + timedelta(days=10),
                                           persona__activo=True).select_related("persona", "elemento"):
            s.alerta(f"asig-{a.id}", f"{a.persona.nombre_completo}: {a.elemento} "
                     + ("vencido" if a.fecha_vencimiento < hoy else f"vence {a.fecha_vencimiento:%d/%m}"),
                     "Reemplazar antes de salir a calle.", C if a.fecha_vencimiento < hoy else A, url)
        for el in Elemento.objects.all():
            if el.obligatorio_tecnicos and el.stock < 3:
                s.alerta(f"stock-{el.id}", f"Pañol: quedan {el.stock} unidades de {el}", "", A, url)


def alertas_personas(hoy):
    with SincronizadorAlertas(Alerta.Modulo.TECNICOS) as s:
        url = reverse("tablero:tecnicos")
        for e in evaluar_tecnicos(hoy):
            if e.diagnostico == Diagnostico.RIESGO:
                s.alerta(f"riesgo-{e.tecnico.id}", f"{e.tecnico.nombre_completo}: riesgo alto ({e.riesgo:.0f}/100)",
                         "; ".join(e.motivos), C, url)
            elif e.diagnostico == Diagnostico.CAPACITACION:
                s.alerta(f"capacitar-{e.tecnico.id}", f"{e.tecnico.nombre_completo}: necesita capacitación en producción",
                         "; ".join(e.motivos), A, url)
    with SincronizadorAlertas(Alerta.Modulo.SUPERVISION) as s:
        url = reverse("tablero:supervisores")
        for e in evaluar_supervisores(hoy):
            if e.nota_encuesta is not None and e.nota_encuesta < 3:
                s.alerta(f"trato-{e.supervisor.id}",
                         f"{e.supervisor.nombre_completo}: nota de trato {e.nota_encuesta:.1f}/5 en encuestas", "",
                         C if e.nota_encuesta < 2.5 else A, url)
            if e.desvios and e.desvios_con_accion / e.desvios < 0.6:
                s.alerta(f"desvios-{e.supervisor.id}",
                         f"{e.supervisor.nombre_completo}: {e.desvios - e.desvios_con_accion} desvíos sin acción correctiva",
                         "", A, url)
            if e.dias_habiles and e.informes_por_dia < 1:
                s.alerta(f"informes-{e.supervisor.id}",
                         f"{e.supervisor.nombre_completo}: sólo {e.informes_por_dia:.1f} informes de control por día", "",
                         A, url)


def alertas_incidentes(hoy):
    with SincronizadorAlertas(Alerta.Modulo.INCIDENTES) as s:
        url = reverse("tablero:incidentes")
        for sin in Siniestro.objects.exclude(estado=Siniestro.Estado.CERRADO):
            dias = (hoy - sin.fecha).days
            if sin.gravedad == Siniestro.Gravedad.CRITICA or dias > 30:
                s.alerta(f"abierto-{sin.id}", f"Siniestro {sin.numero} abierto hace {dias} días ({sin.get_gravedad_display()})",
                         sin.recomendacion_legal(), C if sin.gravedad != "leve" else A, url)
        mes = hoy.replace(day=1)
        graves = Siniestro.objects.filter(fecha__gte=mes, responsabilidad_civil=True).exclude(gravedad="leve").count()
        if graves >= 3:
            s.alerta(f"mes-{mes:%Y%m}", f"{graves} siniestros graves con responsabilidad civil en el mes",
                     "Revisar causas raíz y capacitación del personal involucrado.", C, url)


def recordar_evaluacion_semanal(hoy):
    """Jueves: recordar a los técnicos que aún no evaluaron a su supervisor esta semana."""
    from core.notificaciones import notificar
    from supervision.models import EncuestaSemanal
    if hoy.weekday() != 3:
        return 0
    lunes = hoy - timedelta(days=hoy.weekday())
    ya = set(EncuestaSemanal.objects.filter(semana=lunes).values_list("tecnico_id", flat=True))
    n = 0
    for t in Persona.objects.filter(rol="tecnico", activo=True, supervisor__isnull=False).exclude(id__in=ya):
        notificar(t, "Evaluá a tu supervisor de esta semana", "Son 6 preguntas y es confidencial.", "/app/mi-supervisor/")
        n += 1
    return n


def alertas_partes(hoy):
    from inventario.stock_tecnico import partes_paradas
    with SincronizadorAlertas(Alerta.Modulo.PARTES) as s:
        url = reverse("tablero:stock_tecnicos")
        for f in partes_paradas(hoy=hoy):
            s.alerta(f"parada-{f['tecnico'].id}-{f['material'].id}",
                     f"{f['tecnico'].nombre_completo}: {f['cantidad'].normalize():f} {f['material'].unidad} de {f['material'].nombre} sin usar hace {f['dias']} días",
                     f"Valor ${f['valor']:,.0f}. Pedir devolución al depósito.", C if f["dias"] >= 90 else A, url)
        from inventario.deudas import deudas
        for d in deudas():
            if d.tipo == "parte_parada":
                continue  # ya alertada arriba
            if d.estado != "ok":
                s.alerta(f"deuda-{d.tipo}-{d.tecnico.id}-{getattr(d.referencia, 'id', '')}",
                         f"{d.tecnico.nombre_completo}: {d.titulo.lower()} hace {d.dias} días",
                         d.descripcion, C if d.estado == "critico" else A, reverse("tablero:deudas"))


def alertas_personal(hoy):
    from personal.indicadores import documentos_faltantes_o_vencidos, resumen
    from personal.models import Novedad
    with SincronizadorAlertas(Alerta.Modulo.PERSONAL) as s:
        url = reverse("personal:asistencia")
        activos = Persona.objects.filter(activo=True).exclude(rol="gerencia")
        for r in resumen(hoy - timedelta(days=29), hoy, activos):
            if r.injustificadas >= 3:
                s.alerta(f"faltas-{r.persona.id}", f"{r.persona.nombre_completo}: {r.injustificadas} faltas sin justificar en 30 días",
                         "Evaluar sanción según reglamento interno.", C, url)
            elif r.tardanzas >= 6:
                s.alerta(f"tarde-{r.persona.id}", f"{r.persona.nombre_completo}: {r.tardanzas} llegadas tarde en 30 días", "", A, url)
        for n in Novedad.objects.filter(estado="pendiente", creada__lte=timezone.now() - timedelta(days=2)).select_related("persona"):
            s.alerta(f"novedad-{n.id}", f"Aviso de {n.persona.nombre_completo} ({n.get_tipo_display()}) sin aprobar hace más de 2 días",
                     "", A, reverse("personal:legajo", args=[n.persona_id]))
        for d in documentos_faltantes_o_vencidos(activos):
            if d["estado"] == "critico":
                s.alerta(f"doc-{d['persona'].id}-{d['tipo'].id}", f"{d['persona'].nombre_completo}: {d['tipo']} — {d['texto'].lower()}",
                         "", C, reverse("personal:documentos"))


def ejecutar(hoy=None, log=print, enviar_parte=True):
    hoy = hoy or timezone.localdate()
    log(f"Encuestas generadas: {generar_encuestas(hoy)}")
    log(f"Tareas de supervisor vencidas cerradas: {cerrar_tareas_vencidas(hoy)}")
    ultima = EvaluacionHistorica.objects.order_by("-fecha").values_list("fecha", flat=True).first()
    if ultima is None or (hoy - ultima).days >= 7:
        log(f"Historial semanal de evaluación guardado: {guardar_historial(hoy)} técnicos")
    log(f"Recordatorios de evaluación semanal: {recordar_evaluacion_semanal(hoy)}")
    for nombre, f in (("personal", alertas_personal), ("stock", alertas_stock), ("partes de técnicos", alertas_partes), ("flota", alertas_flota), ("EPP", alertas_epp),
                      ("personas", alertas_personas), ("incidentes", alertas_incidentes)):
        f(hoy)
        log(f"Alertas de {nombre} actualizadas")
    abiertas = Alerta.objects.filter(resuelta=False).values("nivel").annotate(n=Count("id"))
    log("Alertas abiertas: " + ", ".join(f"{r['nivel']}={r['n']}" for r in abiertas))
    if enviar_parte:
        from personal.parte import enviar
        enviar(hoy, log=log)
