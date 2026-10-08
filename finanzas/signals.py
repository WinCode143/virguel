"""Generación automática de egresos a partir de la operación."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from flota.models import ServiceRealizado
from herramientas.models import Asignacion
from incidentes.models import Siniestro
from inventario.models import LoteIngreso
from operaciones.models import GastoOrden

from .models import Egreso, registrar_egreso_automatico


def egreso_de(instancia):
    """Devuelve (origen, categoria, fecha, monto, descripcion) para un registro operativo."""
    if isinstance(instancia, LoteIngreso):
        return (f"lote:{instancia.pk}", "compras-stock", instancia.fecha,
                instancia.cantidad * instancia.costo_unitario,
                f"Compra {instancia.cantidad} {instancia.material.unidad} {instancia.material.nombre}")
    if isinstance(instancia, ServiceRealizado):
        return (f"service:{instancia.pk}", "flota", instancia.fecha, instancia.costo,
                f"Service {instancia.tipo} {instancia.vehiculo.patente}")
    if isinstance(instancia, Asignacion):
        return (f"asignacion:{instancia.pk}", "epp-herramientas", instancia.fecha_entrega,
                instancia.elemento.costo * instancia.cantidad,
                f"Entrega {instancia.elemento} a {instancia.persona.nombre_completo}")
    if isinstance(instancia, GastoOrden):
        monto = instancia.monto if instancia.estado != "rechazado" else 0
        return (f"gasto_orden:{instancia.pk}", "gastos-de-campo", instancia.fecha, monto,
                f"Gasto OT {instancia.orden.numero}: {instancia.descripcion} ({instancia.tecnico.nombre_completo})")
    if isinstance(instancia, Siniestro):
        return (f"siniestro:{instancia.pk}", "siniestros", instancia.fecha_cierre or instancia.fecha,
                instancia.costo_real, f"Siniestro {instancia.numero} ({instancia.get_tipo_display()})")
    return None


def sincronizar(instancia):
    datos = egreso_de(instancia)
    if datos:
        registrar_egreso_automatico(*datos)


MODELOS = (LoteIngreso, ServiceRealizado, Asignacion, Siniestro, GastoOrden)


@receiver(post_save)
def _al_guardar(sender, instance, **kwargs):
    if sender in MODELOS and not kwargs.get("raw"):
        sincronizar(instance)


@receiver(post_delete)
def _al_borrar(sender, instance, **kwargs):
    if sender in MODELOS:
        datos = egreso_de(instance)
        if datos:
            Egreso.objects.filter(origen=datos[0]).delete()
