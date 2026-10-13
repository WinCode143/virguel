"""Historia de las órdenes: un Intento por cada cierre (ver Intento)."""
from django.db.models import Max
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Intento, OrdenTrabajo

RESULTADOS = set(Intento.Resultado.values)


@receiver(pre_save, sender=OrdenTrabajo)
def _estado_anterior(sender, instance, raw=False, **kwargs):
    instance._cierre_anterior = (OrdenTrabajo.objects.filter(pk=instance.pk).values_list("estado", "fecha_ejecucion")
                                 .first() if instance.pk and not raw else None)


@receiver(post_save, sender=OrdenTrabajo)
def _registrar_intento(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    registrar_intento(instance, getattr(instance, "_cierre_anterior", None))


def _datos(orden) -> dict:
    tecnico = orden.tecnico
    return {"tecnico": tecnico, "supervisor_id": tecnico.supervisor_id if tecnico else None,
            "fecha": orden.fecha_ejecucion, "resultado": orden.estado,
            "motivo_no_resuelto": "" if orden.estado == "completada" else orden.motivo_no_resuelto,
            "minutos_reales": orden.minutos_reales, "inicio_trabajo": orden.inicio_trabajo,
            "fin_trabajo": orden.fin_trabajo}


def registrar_intento(orden: OrdenTrabajo, anterior=None):
    """Crea el intento cuando la orden pasa a un resultado (o cambia de fecha de ejecución);
    si sólo se corrigen datos del mismo cierre, actualiza el último intento."""
    if orden.estado not in RESULTADOS or not orden.fecha_ejecucion:
        return None
    ultimo = orden.intentos.order_by("-numero").first()
    estado_ant, fecha_ant = anterior or (None, None)
    nuevo_cierre = (ultimo is None or estado_ant not in RESULTADOS or fecha_ant != orden.fecha_ejecucion)
    if nuevo_cierre:
        numero = (orden.intentos.aggregate(n=Max("numero"))["n"] or 0) + 1
        return Intento.objects.create(orden=orden, numero=numero, **_datos(orden))
    for campo, valor in _datos(orden).items():
        setattr(ultimo, campo, valor)
    ultimo.save()
    return ultimo


def completar_intentos_faltantes(ordenes=None) -> int:
    """Crea el intento de las órdenes cerradas que no tienen ninguno (cargas en bloque o datos previos)."""
    qs = (ordenes if ordenes is not None else OrdenTrabajo.objects.all()).filter(
        estado__in=RESULTADOS, fecha_ejecucion__isnull=False, intentos__isnull=True).select_related("tecnico")
    nuevos = [Intento(orden=o, numero=1, **_datos(o)) for o in qs]
    Intento.objects.bulk_create(nuevos, batch_size=2000)
    return len(nuevos)
