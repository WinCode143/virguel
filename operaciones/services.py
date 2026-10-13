"""Operaciones sobre órdenes que deben quedar auditadas."""
from django.db import transaction

from .models import NotaOrden, OrdenTrabajo


class NoSePuedeReabrir(Exception):
    pass


@transaction.atomic
def reabrir_orden(orden: OrdenTrabajo, motivo: str, autor=None, usuario=None) -> OrdenTrabajo:
    """Corrección administrativa explícita: devuelve una orden cerrada a la agenda.

    Deja una nota con quién, por qué y el cierre anterior, para que el cambio sea auditable.
    Los materiales consumidos y los gastos del cierre anterior se conservan."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise NoSePuedeReabrir("Indicar el motivo de la reapertura.")
    orden = OrdenTrabajo.objects.select_for_update().get(pk=orden.pk)
    if orden.estado not in (OrdenTrabajo.Estado.COMPLETADA, OrdenTrabajo.Estado.FALLIDA):
        raise NoSePuedeReabrir("La orden no está cerrada.")
    anterior = (f"{orden.get_estado_display()}"
                + (f" el {orden.fecha_ejecucion:%d/%m/%Y}" if orden.fecha_ejecucion else "")
                + (f" por {orden.tecnico.nombre_completo}" if orden.tecnico_id else "")
                + (f", motivo: {orden.get_motivo_no_resuelto_display()}" if orden.motivo_no_resuelto else ""))
    quien = autor.nombre_completo if autor else (usuario.get_username() if usuario else "sistema")
    NotaOrden.objects.create(orden=orden, autor=autor, tipo=NotaOrden.Tipo.CORRECCION,
                             texto=f"Reabierta por {quien}. Cierre anterior: {anterior}. Motivo: {motivo}")
    orden.estado = OrdenTrabajo.Estado.ASIGNADA if orden.tecnico_id else OrdenTrabajo.Estado.PENDIENTE
    orden.fecha_ejecucion = None
    orden.inicio_trabajo = orden.fin_trabajo = None
    orden.minutos_reales = None
    orden.motivo_no_resuelto = ""
    orden.save()
    return orden
