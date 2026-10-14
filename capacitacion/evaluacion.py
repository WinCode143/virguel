"""Evaluación de técnicos: productividad vs. capacidad, riesgo y diagnóstico.

Idea central (pedido del cliente): no alcanza con saber si alguien produce
hoy. Se separan cuatro dimensiones y se mira la tendencia:

  * Productividad   - órdenes completadas por día en calle, relativo a la mediana del equipo.
  * Calidad         - retrabajos que causó, órdenes no resueltas ATRIBUIDAS al técnico
                      (catálogo común de motivos, operaciones/criterios.py) y puntaje en controles.
                      Un cliente ausente o un problema de red no cuentan; lo dudoso queda
                      "a investigar" y no penaliza hasta que el supervisor lo confirme.
  * Disciplina      - apercibimientos, multas y suspensiones.
  * Seguridad       - siniestros causados (ponderados por gravedad) y EPP faltante/vencido.

Diagnóstico:
  * Rinde poco pero calidad/disciplina/seguridad están bien  → necesita CAPACITACIÓN en producción.
  * Falla en dos o más de las otras dimensiones, o ya fue
    capacitado y no mejora                                   → REQUIERE REVISIÓN del supervisor.
  * Pocos datos en la ventana                                → SIN EVIDENCIA SUFICIENTE (sin puntajes).

Es un índice orientativo para priorizar la supervisión, no una probabilidad validada de riesgo
ni una decisión laboral: los pesos están versionados (CriterioEvaluacion) y deben revisarse con
la empresa. Una dimensión sin datos suficientes queda sin puntaje y no entra al índice.
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
from operaciones.criterios import NO_RESUELTAS, atribucion, atribuciones_por_motivo, visitas
from operaciones.models import Atribucion, Jornada, OrdenTrabajo
from supervision.models import AccionCorrectiva, InformeControl

from .models import Participacion

# Criterio por defecto (si no hay versiones cargadas). Charla y recapacitación son formación: no restan.
CRITERIO_POR_DEFECTO = {
    "dimensiones": {"productividad": 0.20, "calidad": 0.30, "disciplina": 0.25, "seguridad": 0.25},
    "peso_accion": {"apercibimiento": 2, "multa": 3, "suspension": 5, "recapacitacion": 0, "charla": 0},
    "peso_siniestro": {"leve": 1, "grave": 3, "critica": 6},
    "peso_injustificada": 2,   # cada falta sin aviso ni justificación
    "peso_tardanza": 0.3,      # cada llegada tarde (fuera de la tolerancia)
}


def criterio_vigente(fecha: date) -> tuple[int | None, dict]:
    """(versión, parámetros) del criterio vigente a esa fecha."""
    from .models import CriterioEvaluacion
    c = CriterioEvaluacion.objects.filter(vigente_desde__lte=fecha).order_by("-vigente_desde", "-version").first()
    if c is None:
        return None, CRITERIO_POR_DEFECTO
    datos = {**CRITERIO_POR_DEFECTO, **c.parametros}
    return c.version, datos


class Diagnostico:
    ADECUADO = "Adecuado"
    APRENDIZAJE = "En curva de aprendizaje"
    CAPACITACION = "Necesita capacitación en producción"
    MEJORANDO = "En mejora tras capacitación"
    OBSERVACION = "En observación"
    RIESGO = "Requiere revisión del supervisor (riesgo alto)"
    SIN_EVIDENCIA = "Sin evidencia suficiente"

    COLOR = {ADECUADO: "ok", APRENDIZAJE: "info", CAPACITACION: "aviso", MEJORANDO: "info",
             OBSERVACION: "aviso", RIESGO: "critico", SIN_EVIDENCIA: "info"}


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


@dataclass
class EvaluacionTecnico:
    tecnico: Persona
    dias_calle: int = 0
    completadas: int = 0
    fallidas: int = 0                    # no resueltas atribuidas al técnico
    fallidas_a_investigar: int = 0       # no resueltas cuya atribución falta confirmar
    no_resueltas_ajenas: int = 0         # cliente ausente, red, clima, abastecimiento
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
    injustificadas: int = 0
    tardanzas: int = 0
    presentismo: float | None = None
    capacitado_en_produccion: bool = False
    antiguedad_dias: int = 0
    controles: int = 0
    score_productividad: float | None = 0.0
    score_calidad: float | None = 0.0
    score_disciplina: float | None = 0.0
    score_seguridad: float | None = 0.0
    riesgo: float | None = 0.0
    diagnostico: str = Diagnostico.ADECUADO
    motivos: list = field(default_factory=list)
    criterio_version: int | None = None

    @property
    def sin_evidencia(self) -> bool:
        return self.diagnostico == Diagnostico.SIN_EVIDENCIA

    @property
    def color(self):
        return Diagnostico.COLOR.get(self.diagnostico, "info")

    @property
    def nivel_riesgo(self):
        if self.riesgo is None:
            return "Sin dato"
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
    # Visitas (historia de intentos): una fallida queda con quien la hizo aunque la orden se reasigne
    serie = defaultdict(lambda: defaultdict(int))
    tiempos = defaultdict(list)
    catalogo = atribuciones_por_motivo()
    for v in visitas(desde, hasta, ids):
        e = evs[v.tecnico_id]
        if v.resultado == OrdenTrabajo.Estado.COMPLETADA:
            e.completadas += 1
            serie[v.tecnico_id][v.fecha] += 1
            if v.minutos and v.estandar:
                tiempos[v.tecnico_id].append(v.estandar / v.minutos)
        elif v.resultado in NO_RESUELTAS:
            a = atribucion(v.resultado, v.motivo, v.confirmada, catalogo)
            if a == Atribucion.TECNICO:
                e.fallidas += 1
            elif a == Atribucion.A_INVESTIGAR:
                e.fallidas_a_investigar += 1
            else:
                e.no_resueltas_ajenas += 1
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
              .values("tecnico_id").annotate(p=Avg("puntaje"), n=Count("id"))):
        evs[r["tecnico_id"]].puntaje_controles = float(r["p"])
        evs[r["tecnico_id"]].controles = r["n"]

    version, criterio = criterio_vigente(hasta)
    peso_accion, peso_siniestro = criterio["peso_accion"], criterio["peso_siniestro"]

    # Disciplina
    for tid, tipo in AccionCorrectiva.objects.filter(
            tecnico_id__in=ids, fecha__range=(desde, hasta)).values_list("tecnico_id", "tipo"):
        evs[tid].puntos_disciplina += peso_accion.get(tipo, 1)

    # Seguridad: siniestros + EPP obligatorio faltante o vencido
    # Sólo siniestros con conducta del técnico CONFIRMADA (estar vinculado no acredita haberlo causado)
    for tid, grav in Siniestro.objects.filter(
            tecnico_id__in=ids, fecha__range=(desde, hasta), atribucion=Siniestro.Atribucion.CONFIRMADA
    ).values_list("tecnico_id", "gravedad"):
        evs[tid].puntos_siniestros += peso_siniestro.get(grav, 1)
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

    # Asistencia: faltas injustificadas y llegadas tarde suman a disciplina
    from personal.indicadores import resumen as resumen_asistencia
    for r in resumen_asistencia(desde, hasta, tecnicos):
        e = evs[r.persona.id]
        e.injustificadas, e.tardanzas, e.presentismo = r.injustificadas, r.tardanzas, r.presentismo
        e.puntos_disciplina += r.injustificadas * criterio["peso_injustificada"] + r.tardanzas * criterio["peso_tardanza"]

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

    p = Parametros.actual()
    for e in evs.values():
        e.criterio_version = version
        _puntuar(e, mediana, dias, criterio, p)
    # Primero los de mayor riesgo; los "sin evidencia" al final
    return sorted(evs.values(), key=lambda e: (e.riesgo is None, -(e.riesgo or 0)))


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


def _puntuar(e: EvaluacionTecnico, mediana: float, dias: int = 90, criterio: dict | None = None,
             p: Parametros | None = None):
    criterio = criterio or CRITERIO_POR_DEFECTO
    p = p or Parametros.actual()
    e.indice_productividad = e.productividad / mediana if mediana else 0.0

    # Sin jornadas suficientes no se puede evaluar: se dice, en vez de inventar puntajes.
    if e.dias_calle < p.evidencia_min_jornadas:
        e.score_productividad = e.score_calidad = e.score_disciplina = e.score_seguridad = None
        e.riesgo = None
        e.diagnostico = Diagnostico.SIN_EVIDENCIA
        e.motivos.append(f"{e.dias_calle} jornada{'s' if e.dias_calle != 1 else ''} en calle en la ventana "
                         f"(mínimo {p.evidencia_min_jornadas})")
        return

    e.score_productividad = _clamp(e.indice_productividad * 70)

    base = max(1, e.completadas)
    tasa_retrabajo = e.retrabajos_causados / base
    tasa_fallidas = e.fallidas / max(1, e.completadas + e.fallidas)
    calidad_ots = _clamp(100 - tasa_retrabajo * 300 - tasa_fallidas * 150)
    ejecutadas = e.completadas + e.fallidas + e.fallidas_a_investigar + e.no_resueltas_ajenas
    hay_ordenes = ejecutadas >= p.evidencia_min_ordenes
    hay_controles = e.puntaje_controles is not None and e.controles >= p.evidencia_min_controles
    if hay_ordenes and hay_controles:
        e.score_calidad = 0.6 * calidad_ots + 0.4 * _clamp((e.puntaje_controles - 1) / 4 * 100)
    elif hay_ordenes:
        e.score_calidad = calidad_ots
    elif hay_controles:
        e.score_calidad = _clamp((e.puntaje_controles - 1) / 4 * 100)
    else:
        e.score_calidad = None
        e.motivos.append(f"Calidad sin dato: {ejecutadas} órdenes y {e.controles} controles en la ventana")
    # Disciplina: puntos de sanción cada 30 días (un apercibimiento por mes ≈ 70/100)
    e.score_disciplina = _clamp(100 - e.puntos_disciplina * 30 / max(dias, 1) * 15)
    # Seguridad: un siniestro grave confirmado ≈ -36. El EPP faltante o vencido NO resta: que la empresa
    # no lo haya entregado es un bloqueo de suministro (alerta), no una conducta del técnico; el
    # incumplimiento de uso se registra en los controles.
    e.score_seguridad = _clamp(100 - e.puntos_siniestros * 12)

    # Índice ponderado sobre las dimensiones con dato (los pesos se reparten entre las disponibles)
    pesos = criterio["dimensiones"]
    valores = {"productividad": e.score_productividad, "calidad": e.score_calidad,
               "disciplina": e.score_disciplina, "seguridad": e.score_seguridad}
    con_dato = {k: v for k, v in valores.items() if v is not None}
    total_peso = sum(pesos[k] for k in con_dato)
    e.riesgo = round(100 - sum(pesos[k] * v for k, v in con_dato.items()) / total_peso, 1)

    dims = {k: v for k, v in (("calidad", e.score_calidad), ("disciplina", e.score_disciplina),
                              ("seguridad", e.score_seguridad)) if v is not None}
    malas = [k for k, v in dims.items() if v < 50]
    flojas = [k for k, v in dims.items() if v < 60]
    baja_prod = e.score_productividad < 55
    nuevo = e.antiguedad_dias < 60

    if e.injustificadas >= 2:
        e.motivos.append(f"{e.injustificadas} faltas sin justificar")
    if e.tardanzas >= 5:
        e.motivos.append(f"{e.tardanzas} llegadas tarde")
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
        if e.sin_evidencia:
            continue
        EvaluacionHistorica.objects.update_or_create(fecha=fecha, persona=e.tecnico, defaults={
            "productividad": Decimal(f"{e.productividad:.2f}"),
            "indice_productividad": Decimal(f"{e.indice_productividad:.3f}"),
            "score_productividad": Decimal(f"{e.score_productividad:.1f}"),
            "score_calidad": Decimal(f"{e.score_calidad:.1f}") if e.score_calidad is not None else None,
            "criterio_version": e.criterio_version,
            "score_disciplina": Decimal(f"{e.score_disciplina:.1f}"),
            "score_seguridad": Decimal(f"{e.score_seguridad:.1f}"),
            "riesgo": Decimal(f"{e.riesgo:.1f}"), "diagnostico": e.diagnostico})
        n += 1
    return n
