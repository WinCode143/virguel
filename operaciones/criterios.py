"""Criterios comunes para leer los resultados de las visitas (intentos) de las órdenes.

Un único lugar decide qué cuenta como falla del técnico; lo usan la evaluación de técnicos
(capacitacion/evaluacion.py) y los indicadores de productividad (tablero/metricas.py).

Regla: una visita fallida o reprogramada se atribuye al técnico sólo si
  * el supervisor lo confirmó (atribucion_confirmada = "tecnico"), o
  * el catálogo de motivos dice "tecnico" para ese motivo y nadie confirmó otra cosa.
Lo que el catálogo marca "a investigar" (falta de material, rechazo, otro, sin motivo) no
penaliza hasta que se confirme: una falta de material puede venir de un pedido no atendido.

Se lee la historia (Intento), no el estado actual de la orden: si una orden fallida se reasigna
y otro la completa, la visita fallida sigue siendo de quien la hizo.
"""
from dataclasses import dataclass
from datetime import date

from django.db.models import Q

from .models import Atribucion, Intento, MotivoNoResolucion, OrdenTrabajo

NO_RESUELTAS = ("fallida", "reprogramada")


def atribuciones_por_motivo() -> dict:
    return dict(MotivoNoResolucion.objects.values_list("codigo", "atribucion"))


def atribucion(resultado: str, motivo: str, confirmada: str = "", catalogo: dict | None = None) -> str | None:
    """Atribución de una visita no resuelta (None si se completó)."""
    if resultado not in NO_RESUELTAS:
        return None
    if confirmada:
        return confirmada
    catalogo = atribuciones_por_motivo() if catalogo is None else catalogo
    return catalogo.get(motivo or "", Atribucion.A_INVESTIGAR)


def q_atribuidas(valor: str) -> Q:
    """Filtro de Intentos no resueltos con esa atribución (confirmada o por catálogo)."""
    catalogo = atribuciones_por_motivo()
    codigos = [c for c, a in catalogo.items() if a == valor]
    por_catalogo = Q(atribucion_confirmada="") & Q(motivo_no_resuelto__in=codigos)
    if valor == Atribucion.A_INVESTIGAR:  # sin motivo o con un motivo fuera del catálogo
        por_catalogo |= Q(atribucion_confirmada="") & ~Q(motivo_no_resuelto__in=list(catalogo))
    return Q(resultado__in=NO_RESUELTAS) & (Q(atribucion_confirmada=valor) | por_catalogo)


def q_falla_tecnico() -> Q:
    return q_atribuidas(Atribucion.TECNICO)


def q_a_investigar() -> Q:
    return q_atribuidas(Atribucion.A_INVESTIGAR)


@dataclass
class Visita:
    tecnico_id: int
    orden_id: int
    fecha: date
    resultado: str
    motivo: str
    confirmada: str
    minutos: int | None
    estandar: int | None


def visitas(desde: date, hasta: date, tecnico_ids) -> list[Visita]:
    """Visitas (intentos) de esos técnicos en el período.

    Las órdenes cerradas sin ningún intento registrado (cargas en bloque o datos anteriores a la
    historia de intentos) cuentan como una visita con su estado actual."""
    filas = [Visita(*v) for v in Intento.objects.filter(tecnico_id__in=tecnico_ids, fecha__range=(desde, hasta))
             .values_list("tecnico_id", "orden_id", "fecha", "resultado", "motivo_no_resuelto",
                          "atribucion_confirmada", "minutos_reales", "orden__tipo__minutos_estandar")]
    filas += [Visita(t, o, f, e, m, "", mins, est) for t, o, f, e, m, mins, est in OrdenTrabajo.objects.filter(
        tecnico_id__in=tecnico_ids, fecha_ejecucion__range=(desde, hasta), intentos__isnull=True,
        estado__in=("completada",) + NO_RESUELTAS).values_list(
        "tecnico_id", "id", "fecha_ejecucion", "estado", "motivo_no_resuelto", "minutos_reales",
        "tipo__minutos_estandar")]
    return filas
