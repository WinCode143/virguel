"""Proyección de capacidad, clientes atendibles y probabilidad de decodificadores."""
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Avg, Sum
from django.utils import timezone

from core.models import Parametros, Zona
from inventario.models import DemandaComercial, LoteIngreso
from operaciones.models import Jornada, OrdenTrabajo

PRIOR_FUERZA = 20  # equivale a 20 "clientes virtuales" de opinión previa


@dataclass
class EstimacionProbabilidad:
    observados: int
    con_decodificador: int
    prior: float
    media: float
    inf90: float
    sup90: float

    @property
    def tasa_observada(self):
        return self.con_decodificador / self.observados if self.observados else None


def probabilidad_decodificador(hasta: date | None = None, dias: int = 90) -> EstimacionProbabilidad:
    """Combina el supuesto inicial del cliente (punto medio entre 50% y 60%) con
    lo que realmente pasa en calle (modelo Beta-Binomial). Con pocos datos
    manda el supuesto; a medida que se acumulan órdenes, manda la realidad."""
    p = Parametros.actual()
    hasta = hasta or timezone.localdate()
    qs = OrdenTrabajo.objects.filter(
        estado=OrdenTrabajo.Estado.COMPLETADA, tipo__puede_requerir_decodificador=True,
        fecha_ejecucion__range=(hasta - timedelta(days=dias), hasta))
    n = qs.count()
    k = qs.filter(decodificador_solicitado=True).count()
    prior = float(p.prob_decodificador_min + p.prob_decodificador_max) / 2
    a = prior * PRIOR_FUERZA + k
    b = (1 - prior) * PRIOR_FUERZA + (n - k)
    media = a / (a + b)
    var = a * b / ((a + b) ** 2 * (a + b + 1))
    sd = math.sqrt(var)
    return EstimacionProbabilidad(n, k, prior, media, max(0, media - 1.645 * sd), min(1, media + 1.645 * sd))


def hectareas_reales_por_cuadrilla(hasta: date | None = None, dias: int = 30):
    hasta = hasta or timezone.localdate()
    p = Parametros.actual()
    r = Jornada.objects.filter(fecha__range=(hasta - timedelta(days=dias), hasta), en_calle=True,
                               hectareas_cubiertas__gt=0).aggregate(prom=Avg("hectareas_cubiertas"))
    if r["prom"] is None:
        return None
    # La jornada guarda las ha por técnico; una cuadrilla suma las de sus integrantes.
    return float(r["prom"]) * p.tecnicos_por_cuadrilla


@dataclass
class Capacidad:
    tecnicos: int
    cuadrillas: float
    ha_min: float
    ha_max: float
    densidad: float
    clientes_por_area_min: float
    clientes_por_area_max: float
    clientes_por_tope: float
    clientes_min: float
    clientes_max: float
    deco_min: float
    deco_max: float
    deco_estimado: float


def capacidad(tecnicos: int, ha_dia_min=None, ha_dia_max=None, densidad=None,
              prob_min=None, prob_max=None, prob_estimada=None) -> Capacidad:
    """Cuántos clientes y decodificadores se cubren en un día.

    Por defecto: técnicos x clientes por técnico. Si se activa "medir hectáreas",
    además se limita por el área (hectáreas x densidad de clientes)."""
    p = Parametros.actual()
    ha_dia_min = float(ha_dia_min if ha_dia_min is not None else p.hectareas_dia_min)
    ha_dia_max = float(ha_dia_max if ha_dia_max is not None else p.hectareas_dia_max)
    if densidad is None:
        densidad = float(Zona.objects.filter(activa=True).aggregate(d=Avg("densidad_clientes_ha"))["d"] or 1)
    densidad = float(densidad)
    prob_min = float(prob_min if prob_min is not None else p.prob_decodificador_min)
    prob_max = float(prob_max if prob_max is not None else p.prob_decodificador_max)
    cuadrillas = tecnicos / p.tecnicos_por_cuadrilla
    ha_min, ha_max = cuadrillas * ha_dia_min, cuadrillas * ha_dia_max
    tope = tecnicos * float(p.clientes_por_tecnico_dia)
    c_area_min, c_area_max = ha_min * densidad, ha_max * densidad
    if p.usar_hectareas:
        c_min, c_max = min(c_area_min, tope), min(c_area_max, tope)
    else:  # sin hectáreas: la capacidad es directamente técnicos x clientes por técnico
        c_min = c_max = tope
    medio = (c_min + c_max) / 2
    return Capacidad(
        tecnicos=tecnicos, cuadrillas=cuadrillas, ha_min=ha_min, ha_max=ha_max, densidad=densidad,
        clientes_por_area_min=c_area_min, clientes_por_area_max=c_area_max, clientes_por_tope=tope,
        clientes_min=c_min, clientes_max=c_max,
        deco_min=c_min * prob_min, deco_max=c_max * prob_max,
        deco_estimado=medio * (prob_estimada if prob_estimada is not None else (prob_min + prob_max) / 2),
    )


def demanda_vs_capacidad(desde: date, dias: int, tecnicos_disponibles: int):
    """Para cada día futuro: clientes pedidos por comercial vs. capacidad."""
    p = Parametros.actual()
    hasta = desde + timedelta(days=dias - 1)
    demanda = defaultdict(int)
    for f, n in (DemandaComercial.objects.filter(fecha__range=(desde, hasta))
                 .values_list("fecha").annotate(n=Sum("cantidad_clientes"))):
        demanda[f] = n
    cap = capacidad(tecnicos_disponibles)
    cap_dia = (cap.clientes_min + cap.clientes_max) / 2
    por_tecnico = cap_dia / tecnicos_disponibles if tecnicos_disponibles else float(p.clientes_por_tecnico_dia)
    filas = []
    for i in range(dias):
        f = desde + timedelta(days=i)
        d = demanda.get(f, 0)
        necesarios = math.ceil(d / por_tecnico) if por_tecnico else 0
        filas.append({"fecha": f, "demanda": d, "capacidad": round(cap_dia), "brecha": round(cap_dia - d),
                      "tecnicos_necesarios": necesarios, "ok": d <= cap_dia})
    return filas


def stock_decodificadores() -> Decimal:
    return (LoteIngreso.objects.filter(material__es_decodificador=True)
            .aggregate(t=Sum("cantidad_disponible"))["t"] or Decimal("0"))


def decodificadores_necesarios(desde: date, hasta: date, prob: float) -> float:
    """Decodificadores que pedirán los clientes de la demanda comercial del período."""
    clientes = (DemandaComercial.objects.filter(fecha__range=(desde, hasta),
                                                tipo_tarea__puede_requerir_decodificador=True)
                .aggregate(t=Sum("cantidad_clientes"))["t"] or 0)
    return clientes * prob
