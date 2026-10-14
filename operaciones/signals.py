"""Compatibilidad: registra la visita cuando una orden se cierra por un camino que no la registra
explícitamente (admin, importación, cargas en bloque).

La señal NUNCA modifica una visita existente: corregir una visita es una rectificación explícita
(operaciones/visitas.py) y reasignar una orden cerrada no cambia quién hizo la visita."""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Intento, OrdenTrabajo
from .visitas import RESULTADOS, crear_visita, datos_de_cierre


@receiver(pre_save, sender=OrdenTrabajo)
def _estado_anterior(sender, instance, raw=False, **kwargs):
    instance._cierre_anterior = (OrdenTrabajo.objects.filter(pk=instance.pk).values_list("estado", "fecha_ejecucion")
                                 .first() if instance.pk and not raw else None)


@receiver(post_save, sender=OrdenTrabajo)
def _registrar_intento(sender, instance, created, raw=False, **kwargs):
    if raw or getattr(instance, "_visita_explicita", False):
        return
    if instance.estado not in RESULTADOS or not instance.fecha_ejecucion:
        return
    estado_ant, fecha_ant = getattr(instance, "_cierre_anterior", None) or (None, None)
    if estado_ant in RESULTADOS and fecha_ant == instance.fecha_ejecucion:
        return  # edición de una orden ya cerrada: no es una visita nueva ni corrige la anterior
    crear_visita(instance)


def completar_intentos_faltantes(ordenes=None) -> int:
    """Crea el intento de las órdenes cerradas que no tienen ninguno (cargas en bloque o datos previos)."""
    qs = (ordenes if ordenes is not None else OrdenTrabajo.objects.all()).filter(
        estado__in=RESULTADOS, fecha_ejecucion__isnull=False, intentos__isnull=True).select_related("tecnico")
    nuevos = [Intento(orden=o, numero=1, **datos_de_cierre(o)) for o in qs]
    Intento.objects.bulk_create(nuevos, batch_size=2000)
    return len(nuevos)
