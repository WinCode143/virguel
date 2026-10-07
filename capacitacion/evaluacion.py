"""Evaluación de técnicos: productividad vs. capacidad, riesgo y diagnóstico.

Idea central (pedido del cliente): no alcanza con saber si alguien produce
hoy. Se separan cuatro dimensiones y se mira la tendencia:

  * Productividad   - órdenes completadas por día en calle, relativo a la mediana del equipo.
  * Calidad         - retrabajos que causó, órdenes fallidas y puntaje en controles.
  * Disciplina      - apercibimientos, multas y suspensiones.
  * Seguridad       - siniestros causados (ponderados por gravedad) y EPP faltante/vencido.

Diagnóstico:
  * Rinde poco pero calidad/disciplina/seguridad están bien  → necesita CAPACITACIÓN en producción.
  * Falla en dos o más de las otras dimensiones, o ya fue
    capacitado y no mejora                                   → RIESGO ALTO: evaluar desvinculación.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median

from django.db.models import Avg, Count, Q
from django.utils import timezone

from core.models import Parametros, Persona
from herramientas.models import Asignacion, Elemento
from incidentes.models import Siniestro
from operaciones.models import Jornada, OrdenTrabajo
from supervision.models import AccionCorrectiva, InformeControl

from .models import Participacion

# Charla y recapacitación son formativas: casi no penalizan. Las sanciones sí.
PESO_ACCION = {"apercibimiento": 2, "multa": 3, "suspension": 5, "recapacitacion": 0.5, "charla": 0}
PESO_SINIESTRO = {"leve": 1, "grave": 3, "critica": 6}


class Diagnostico:
    ADECUADO = "Adecuado"
    APRENDIZAJE = "En curva de aprendizaje"
    CAPACITACION = "Necesita capacitación en producción"
    MEJORANDO = "En mejora tras capacitación"
    OBSERVACION = "En observación"
    RIESGO = "Riesgo alto – evaluar desvinculación"

    COLOR = {ADECUADO: "ok", APRENDIZAJE: "info", CAPACITACION: "aviso", MEJORANDO: "info",
             OBSERVACION: "aviso", RIESGO: "critico"}


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


@dataclass
class EvaluacionTecnico:
    tecnico: Persona
    dias_calle: int = 0
    completadas: int = 0
    fallidas: int = 0
    retrabajos_causados: int = 0
    productividad: float = 0.0           # OT completadas por día en calle
    indice_productividad: float = 0.0    # relativo a la mediana del equipo (1.0 = mediana)
    tendencia: float = 0.0               # variación % último tercio vs. primer tercio
    eficiencia_tiempo: float | None = None
    puntaje_controles: float | None = None
    puntos_disciplina: float = 0.0
    puntos_siniestros: float = 0.0
    epp_faltantes: int = 0
    capacitaciones: int = 0
    capacitado_en_produccion: bool = False
    antiguedad_dias: int = 0
    score_productividad: float = 0.0
    score_calidad: float = 0.0
    score_disciplina: float = 0.0
    score_seguridad: float = 0.0
    riesgo: float = 0.0
    diagnostico: str = Diagnostico.ADECUADO
    motivos: list = field(default_factory=list)

    @property
    def color(self):
        return Diagnostico.COLOR.get(self.diagnostico, "info")

    @property
    def nivel_riesgo(self):
        return "Alto" if self.riesgo >= 50 else "Medio" if self.riesgo >= 30 else "Bajo"


def _tendencia(serie_por_dia: dict, desde: date, hasta: date) -> float:
    """Compara productividad del último tercio de la ventana contra el primero."""
    total = (hasta - desde).days + 1
    tercio = max(1, total // 3)
    inicio = [v for d, v in serie_por_dia.items() if d < desde + timedelta(days=tercio)]
    fin = [v for d, v in serie_por_dia.items() if d > hasta - timedelta(days=tercio)]
    if not inicio or not fin:
        return 0.0
    a, b = sum(inicio) / len(inicio), sum(fin) / len(fin)
    if a == 0:
        return 0.0
    return (b - a) / a * 100


def evaluar_tecnicos(hasta: date | None = None, dias: int | None = None, tecnicos=None):
    hasta = hasta or timezone.localdate()
    dias = dias or Parametros.actual().dias_ventana_evaluacion
    desde = hasta - timedelta(days=dias - 1)
    if tecnicos is None:
        tecnicos = Persona.objects.filter(rol=Persona.Rol.TECNICO, activo=True)
    tecnicos = list(tecnicos)
    ids = [t.id for t in tecnicos]
    evs = {t.id: EvaluacionTecnico(tecnico=t, antiguedad_dias=(hasta - t.fecha_ingreso).days)
           for t in tecnicos}

    # Días en calle
    for r in (Jornada.objects.filter(tecnico_id__in=ids, fecha__range=(desde, hasta), en_calle=True)
              .values("tecnico_id").annotate(n=Count("id"))):
        evs[r["tecnico_id"]].dias_calle = r["n"]

    # Órdenes: completadas, fallidas y serie diaria para la tendencia
    ots = OrdenTrabajo.objects.filter(tecnico_id__in=ids, fecha_ejecucion__range=(desde, hasta))
    serie = defaultdict(lambda: defaultdict(int))
    tiempos = defaultdict(list)
    for tid, estado, fecha, mins, estandar in ots.values_list(
            "tecnico_id", "estado", "fecha_ejecucion", "minutos_reales", "tipo__minutos_estandar"):
        if estado == OrdenTrabajo.Estado.COMPLETADA:
            evs[tid].completadas += 1
            serie[tid][fecha] += 1
            if mins:
                tiempos[tid].append(estandar / mins)
        elif estado == OrdenTrabajo.Estado.FALLIDA:
            evs[tid].fallidas += 1
    for r in (OrdenTrabajo.objects.filter(es_retrabajo=True, orden_original__tecnico_id__in=ids,
                                          fecha_programada__range=(desde, hasta))
              .values("orden_original__tecnico_id").annotate(n=Count("id"))):
        evs[r["orden_original__tecnico_id"]].retrabajos_causados = r["n"]

    # Días en calle sin órdenes cuentan como 0 en la serie
    for tid, fecha in Jornada.objects.filter(tecnico_id__in=ids, fecha__range=(desde, hasta),
                                             en_calle=True).values_list("tecnico_id", "fecha"):
        serie[tid].setdefault(fecha, 0)

    # Controles de supervisores
    for r in (InformeControl.objects.filter(tecnico_id__in=ids, fecha__range=(desde, hasta))
              .values("tecnico_id").annotate(p=Avg("puntaje"))):
        evs[r["tecnico_id"]].puntaje_controles = float(r["p"])

    # Disciplina
    for tid, tipo in AccionCorrectiva.objects.filter(
            tecnico_id__in=ids, fecha__range=(desde, hasta)).values_list("tecnico_id", "tipo"):
        evs[tid].puntos_disciplina += PESO_ACCION.get(tipo, 1)

    # Seguridad: siniestros + EPP obligatorio faltante o vencido
    for tid, grav in Siniestro.objects.filter(
            tecnico_id__in=ids, fecha__range=(desde, hasta)).values_list("tecnico_id", "gravedad"):
        evs[tid].puntos_siniestros += PESO_SINIESTRO.get(grav, 1)
    obligatorios = set(Elemento.objects.filter(obligatorio_tecnicos=True).values_list("id", flat=True))
    vigentes = defaultdict(set)
    for pid, eid in Asignacion.objects.filter(
            persona_id__in=ids, estado=Asignacion.Estado.EN_USO, elemento_id__in=obligatorios,
            fecha_entrega__lte=hasta,
    ).filter(Q(fecha_vencimiento__isnull=True) | Q(fecha_vencimiento__gte=hasta)).values_list(
            "persona_id", "elemento_id"):
        vigentes[pid].add(eid)
    for tid in ids:
        evs[tid].epp_faltantes = len(obligatorios - vigentes[tid])

    # Capacitación recibida en la ventana
    for pid, en_prod in Participacion.objects.filter(
            persona_id__in=ids, asistio=True, capacitacion__fecha__range=(desde, hasta)
    ).values_list("persona_id", "capacitacion__en_produccion"):
        evs[pid].capacitaciones += 1
        evs[pid].capacitado_en_produccion |= en_prod

    # Productividad relativa al equipo
    for e in evs.values():
        e.productividad = e.completadas / e.dias_calle if e.dias_calle else 0.0
        e.tendencia = _tendencia(serie[e.tecnico.id], desde, hasta)
        if tiempos[e.tecnico.id]:
            e.eficiencia_tiempo = sum(tiempos[e.tecnico.id]) / len(tiempos[e.tecnico.id])
    mediana = mediana_plantel(desde, hasta)

    for e in evs.values():
        _puntuar(e, mediana, dias)
    return sorted(evs.values(), key=lambda e: -e.riesgo)


def mediana_plantel(desde: date, hasta: date) -> float:
    """Productividad mediana (OT completadas por día en calle) de TODO el plantel
    activo. Es la referencia aunque se evalúe a una sola persona o a un equipo."""
    dias = dict(Jornada.objects.filter(fecha__range=(desde, hasta), en_calle=True,
                                       tecnico__activo=True, tecnico__rol=Persona.Rol.TECNICO)
                .values_list("tecnico_id").annotate(n=Count("id")))
    ots = dict(OrdenTrabajo.objects.filter(fecha_ejecucion__range=(desde, hasta),
                                           estado=OrdenTrabajo.Estado.COMPLETADA, tecnico_id__in=dias)
               .values_list("tecnico_id").annotate(n=Count("id")))
    valores = [ots.get(t, 0) / n for t, n in dias.items() if n >= 5]
    return median(valores) if valores else 0


def _puntuar(e: EvaluacionTecnico, mediana: float, dias: int = 90):
    e.indice_productividad = e.productividad / mediana if mediana else 0.0
    e.score_productividad = _clamp(e.indice_productividad * 70)

    base = max(1, e.completadas)
    tasa_retrabajo = e.retrabajos_causados / base
    tasa_fallidas = e.fallidas / max(1, e.completadas + e.fallidas)
    calidad_ots = _clamp(100 - tasa_retrabajo * 300 - tasa_fallidas * 150)
    if e.puntaje_controles is not None:
        e.score_calidad = 0.6 * calidad_ots + 0.4 * _clamp((e.puntaje_controles - 1) / 4 * 100)
    else:
        e.score_calidad = calidad_ots
    # Disciplina: puntos de sanción cada 30 días (un apercibimiento por mes ≈ 70/100)
    e.score_disciplina = _clamp(100 - e.puntos_disciplina * 30 / max(dias, 1) * 15)
    # Seguridad: un siniestro grave ≈ -36; cada EPP obligatorio faltante o vencido -10
    e.score_seguridad = _clamp(100 - e.puntos_siniestros * 12 - e.epp_faltantes * 10)

    e.riesgo = round(100 - (0.20 * e.score_productividad + 0.30 * e.score_calidad
                            + 0.25 * e.score_disciplina + 0.25 * e.score_seguridad), 1)

    dims = {"calidad": e.score_calidad, "disciplina": e.score_disciplina, "seguridad": e.score_seguridad}
    malas = [k for k, v in dims.items() if v < 50]
    flojas = [k for k, v in dims.items() if v < 60]
    baja_prod = e.score_productividad < 55
    nuevo = e.antiguedad_dias < 60

    if baja_prod:
        e.motivos.append(f"Productividad al {e.indice_productividad:.0%} de la mediana del equipo")
    for k in malas:
        e.motivos.append(f"{k.capitalize()} deficiente ({dims[k]:.0f}/100)")
    if e.capacitado_en_produccion and e.tendencia <= 0 and baja_prod:
        e.motivos.append("Ya recibió capacitación en producción y no mejoró")

    if len(malas) >= 2 or (baja_prod and malas and e.capacitado_en_produccion and e.tendencia <= 0):
        e.diagnostico = Diagnostico.RIESGO
    elif baja_prod and not flojas:
        if nuevo:
            e.diagnostico = Diagnostico.APRENDIZAJE
        elif e.capacitado_en_produccion and e.tendencia > 10:
            e.diagnostico = Diagnostico.MEJORANDO
        else:
            e.diagnostico = Diagnostico.CAPACITACION
    elif malas or (baja_prod and flojas):
        e.diagnostico = Diagnostico.OBSERVACION
    else:
        e.diagnostico = Diagnostico.ADECUADO


def guardar_historial(fecha: date | None = None) -> int:
    """Guarda la evaluación de todos los técnicos activos a la fecha indicada."""
    from decimal import Decimal

    from .models import EvaluacionHistorica

    fecha = fecha or timezone.localdate()
    tecnicos = Persona.objects.filter(rol=Persona.Rol.TECNICO, activo=True, fecha_ingreso__lte=fecha)
    n = 0
    for e in evaluar_tecnicos(fecha, tecnicos=tecnicos):
        if not e.dias_calle:
            continue
        EvaluacionHistorica.objects.update_or_create(fecha=fecha, persona=e.tecnico, defaults={
            "productividad": Decimal(f"{e.productividad:.2f}"),
            "indice_productividad": Decimal(f"{e.indice_productividad:.3f}"),
            "score_productividad": Decimal(f"{e.score_productividad:.1f}"),
            "score_calidad": Decimal(f"{e.score_calidad:.1f}"),
            "score_disciplina": Decimal(f"{e.score_disciplina:.1f}"),
            "score_seguridad": Decimal(f"{e.score_seguridad:.1f}"),
            "riesgo": Decimal(f"{e.riesgo:.1f}"), "diagnostico": e.diagnostico})
        n += 1
    return n
