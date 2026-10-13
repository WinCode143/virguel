"""Criterios comunes para leer las órdenes no resueltas.

Un único lugar decide qué cuenta como falla del técnico; lo usan la evaluación de técnicos
(capacitacion/evaluacion.py) y los indicadores de productividad (tablero/metricas.py).

Regla: una orden fallida o reprogramada se atribuye al técnico sólo si
  * el supervisor lo confirmó (atribucion_confirmada = "tecnico"), o
  * el catálogo de motivos dice "tecnico" para ese motivo y nadie confirmó otra cosa.
Lo que el catálogo marca "a investigar" (falta de material, rechazo, otro, sin motivo) no
penaliza hasta que se confirme: una falta de material puede venir de un pedido no atendido.
"""
from django.db.models import Q

from .models import Atribucion, MotivoNoResolucion

NO_RESUELTAS = ("fallida", "reprogramada")


def atribuciones_por_motivo() -> dict:
    return dict(MotivoNoResolucion.objects.values_list("codigo", "atribucion"))


def atribucion(orden, catalogo: dict | None = None) -> str | None:
    """Atribución de una orden no resuelta (None si la orden no está fallida/reprogramada)."""
    if orden.estado not in NO_RESUELTAS:
        return None
    if orden.atribucion_confirmada:
        return orden.atribucion_confirmada
    catalogo = atribuciones_por_motivo() if catalogo is None else catalogo
    return catalogo.get(orden.motivo_no_resuelto or "", Atribucion.A_INVESTIGAR)


def q_atribuidas(valor: str, prefijo: str = "") -> Q:
    """Filtro de órdenes no resueltas con esa atribución (confirmada o por catálogo)."""
    codigos = [c for c, a in atribuciones_por_motivo().items() if a == valor]
    p = prefijo
    confirmada = Q(**{f"{p}atribucion_confirmada": valor})
    por_catalogo = Q(**{f"{p}atribucion_confirmada": ""}) & Q(**{f"{p}motivo_no_resuelto__in": codigos})
    if valor == Atribucion.A_INVESTIGAR:  # sin motivo o con un motivo fuera del catálogo
        conocidos = list(atribuciones_por_motivo())
        por_catalogo |= Q(**{f"{p}atribucion_confirmada": ""}) & ~Q(**{f"{p}motivo_no_resuelto__in": conocidos})
    return Q(**{f"{p}estado__in": NO_RESUELTAS}) & (confirmada | por_catalogo)


def q_falla_tecnico(prefijo: str = "") -> Q:
    return q_atribuidas(Atribucion.TECNICO, prefijo)


def q_a_investigar(prefijo: str = "") -> Q:
    return q_atribuidas(Atribucion.A_INVESTIGAR, prefijo)
