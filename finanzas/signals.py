"""Generación automática de egresos a partir de la operación."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from flota.models import ServiceRealizado
from herramientas.models import Asignacion, CompraElemento
from incidentes.models import Siniestro
from inventario.models import LoteIngreso
from operaciones.models import GastoOrden

from .models import Liquidacion

from .models import Egreso, registrar_egreso_automatico


def egreso_de(instancia):
    """Devuelve (origen, categoria, fecha, monto, descripcion) para un registro operativo."""
    if isinstance(instancia, LoteIngreso):
        if instancia.origen != LoteIngreso.Origen.COMPRA:
            # Devoluciones y ajustes son movimientos internos: no son una compra.
            return (f"lote:{instancia.pk}", "compras-stock", instancia.fecha, 0, "")
        return (f"lote:{instancia.pk}", "compras-stock", instancia.fecha,
                instancia.cantidad * instancia.costo_unitario,
                f"Compra {instancia.cantidad} {instancia.material.unidad} {instancia.material.nombre}")
    if isinstance(instancia, ServiceRealizado):
        return (f"service:{instancia.pk}", "flota", instancia.fecha, instancia.costo,
                f"Service {instancia.tipo} {instancia.vehiculo.patente}")
    if isinstance(instancia, CompraElemento):
        return (f"compra_elemento:{instancia.pk}", "epp-herramientas", instancia.fecha,
                instancia.costo_unitario * instancia.cantidad,
                f"Compra {instancia.cantidad} × {instancia.elemento}")
    if isinstance(instancia, Asignacion):
        # Entregar algo del pañol o reasignarlo es custodia: el gasto fue la compra.
        monto = instancia.elemento.costo * instancia.cantidad if instancia.es_gasto else 0
        return (f"asignacion:{instancia.pk}", "epp-herramientas", instancia.fecha_entrega, monto,
                f"Entrega {instancia.elemento} a {instancia.persona.nombre_completo}")
    if isinstance(instancia, Liquidacion):
        from .sueldos import fin_de_mes
        monto = instancia.costo_total if instancia.estado != "borrador" else 0
        return (f"liquidacion:{instancia.pk}", "sueldos", fin_de_mes(instancia.periodo), monto,
                f"Sueldo {instancia.periodo:%m/%Y} {instancia.persona.nombre_completo} (con cargas)")
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
        egreso = registrar_egreso_automatico(*datos)
        # Marcar un sueldo como "pagado" es la acción explícita de pago: se registra el pago del saldo
        # (sin cuenta si no se indicó: queda como diferencia a imputar en la caja).
        if egreso and isinstance(instancia, Liquidacion) and instancia.estado == "pagada" and egreso.saldo > 0:
            from .models import Pago
            Pago.objects.create(egreso=egreso, monto=egreso.saldo, fecha=egreso.fecha,
                                observaciones="Sueldo marcado como pagado")


MODELOS = (LoteIngreso, ServiceRealizado, Asignacion, CompraElemento, Siniestro, GastoOrden, Liquidacion)


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
