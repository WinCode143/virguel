"""Tareas automáticas diarias (las ejecuta `manage.py tareas_diarias`)."""
from datetime import timedelta

from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from capacitacion.evaluacion import Diagnostico, evaluar_tecnicos, guardar_historial
from capacitacion.models import EvaluacionHistorica
from core.models import Alerta
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
    fecha = fecha or timezone.localdate()
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


def ejecutar(hoy=None, log=print):
    hoy = hoy or timezone.localdate()
    log(f"Encuestas generadas: {generar_encuestas(hoy)}")
    log(f"Tareas de supervisor vencidas cerradas: {cerrar_tareas_vencidas(hoy)}")
    ultima = EvaluacionHistorica.objects.order_by("-fecha").values_list("fecha", flat=True).first()
    if ultima is None or (hoy - ultima).days >= 7:
        log(f"Historial semanal de evaluación guardado: {guardar_historial(hoy)} técnicos")
    for nombre, f in (("stock", alertas_stock), ("flota", alertas_flota), ("EPP", alertas_epp),
                      ("personas", alertas_personas), ("incidentes", alertas_incidentes)):
        f(hoy)
        log(f"Alertas de {nombre} actualizadas")
    abiertas = Alerta.objects.filter(resuelta=False).values("nivel").annotate(n=Count("id"))
    log("Alertas abiertas: " + ", ".join(f"{r['nivel']}={r['n']}" for r in abiertas))
