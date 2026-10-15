"""Compromisos de material (ReservaMaterial): un único lugar para reservar, entregar, liberar y reasignar.

* Lo comprometido es la cantidad PENDIENTE (reservada − entregada) de las reservas activas.
* Ninguna salida del depósito puede tomar unidades comprometidas para OTRA orden: hace falta una
  reasignación explícita (`reasignar`) o la autorización `usar_reservado` con su motivo.
* Una entrega para la orden descuenta su reserva en forma parcial; la reserva se cierra cuando se
  entregó todo.
* Cerrar una visita sin resolverla (ausente, reprogramada) no toca la reserva: el trabajo sigue
  pendiente. Completar la orden libera lo que no se llegó a entregar (no crea consumo ni entradas).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Sum

from .models import LoteIngreso, Material, ReservaMaterial

ACTIVA = ReservaMaterial.Estado.ACTIVA
PENDIENTE = ExpressionWrapper(F("cantidad") - F("cantidad_entregada"),
                              output_field=DecimalField(max_digits=12, decimal_places=2))


class ReservadoParaOtra(Exception):
    """La salida tomaría unidades comprometidas para otra orden."""


def comprometido(material_id, excepto_orden_id=None) -> Decimal:
    qs = ReservaMaterial.objects.filter(material_id=material_id, estado=ACTIVA)
    if excepto_orden_id:
        qs = qs.exclude(orden_id=excepto_orden_id)
    return qs.aggregate(t=Sum(PENDIENTE))["t"] or Decimal("0")


def comprometido_por_material() -> dict:
    return dict(ReservaMaterial.objects.filter(estado=ACTIVA).values_list("material")
                .annotate(t=Sum(PENDIENTE)))


def comprometido_por_orden() -> dict:
    """{(orden_id, material_id): pendiente}."""
    res = {}
    for oid, mid, q in (ReservaMaterial.objects.filter(estado=ACTIVA).values_list("orden_id", "material_id")
                        .annotate(t=Sum(PENDIENTE))):
        res[(oid, mid)] = q or Decimal("0")
    return res


def _stock(material_id) -> Decimal:
    return (LoteIngreso.objects.filter(material_id=material_id).aggregate(t=Sum("cantidad_disponible"))["t"]
            or Decimal("0"))


def validar_salida(material, cantidad, orden_id=None, usar_reservado=False):
    """Debe llamarse dentro de la transacción de la salida (bloquea el material)."""
    Material.objects.select_for_update().filter(pk=material.pk).first()
    if usar_reservado:
        return
    ajeno = comprometido(material.pk, excepto_orden_id=orden_id)
    if not ajeno:
        return
    libre = max(Decimal("0"), _stock(material.pk) - ajeno)
    if Decimal(cantidad) > libre:
        raise ReservadoParaOtra(
            f"{material.nombre}: sin comprometer quedan {libre:g} {material.unidad}; {ajeno:g} están reservados "
            f"para otras órdenes. Reasigná la reserva si corresponde.")


def aplicar_entrega(orden_id, material, cantidad):
    """Descuenta lo entregado de las reservas de esa orden (parcial, la más antigua primero)."""
    resto = Decimal(cantidad)
    for r in (ReservaMaterial.objects.select_for_update()
              .filter(orden_id=orden_id, material=material, estado=ACTIVA).order_by("necesaria_para", "id")):
        if resto <= 0:
            break
        toma = min(resto, r.cantidad - r.cantidad_entregada)
        r.cantidad_entregada += toma
        resto -= toma
        if r.cantidad_entregada >= r.cantidad:
            r.estado = ReservaMaterial.Estado.CONSUMIDA
        r.save(update_fields=["cantidad_entregada", "estado"])


@transaction.atomic
def reservar(orden, material, cantidad, responsable="") -> ReservaMaterial:
    """No se puede comprometer lo que ya está comprometido."""
    Material.objects.select_for_update().filter(pk=material.pk).first()
    libre = _stock(material.pk) - comprometido(material.pk)
    if libre < Decimal(cantidad):
        raise ValidationError(f"No alcanza: disponible sin reservar {libre:g} {material.unidad}.")
    return ReservaMaterial.objects.create(material=material, cantidad=cantidad, orden=orden,
                                          necesaria_para=orden.fecha_programada, responsable=responsable)


@transaction.atomic
def liberar(orden, motivo: str):
    """Libera lo pendiente de las reservas de la orden (no crea entradas: nunca salió del depósito)."""
    for r in ReservaMaterial.objects.select_for_update().filter(orden=orden, estado=ACTIVA):
        if r.cantidad_entregada:
            r.cantidad, r.estado = r.cantidad_entregada, ReservaMaterial.Estado.CONSUMIDA
        else:
            r.estado = ReservaMaterial.Estado.CANCELADA
        r.nota = motivo[:200]
        r.save(update_fields=["cantidad", "estado", "nota"])


@transaction.atomic
def reasignar(reserva: ReservaMaterial, orden_nueva, motivo: str, responsable="") -> ReservaMaterial:
    """Pasa lo pendiente de una reserva a otra orden, dejando constancia (reasignación explícita)."""
    r = ReservaMaterial.objects.select_for_update().get(pk=reserva.pk)
    pendiente = r.cantidad - r.cantidad_entregada
    if r.estado != ACTIVA or pendiente <= 0:
        raise ValidationError("La reserva no tiene cantidad pendiente para reasignar.")
    liberar_nota = f"Reasignada a {orden_nueva.numero}: {motivo}"[:200]
    if r.cantidad_entregada:
        r.cantidad, r.estado = r.cantidad_entregada, ReservaMaterial.Estado.CONSUMIDA
    else:
        r.estado = ReservaMaterial.Estado.CANCELADA
    r.nota = liberar_nota
    r.save(update_fields=["cantidad", "estado", "nota"])
    return ReservaMaterial.objects.create(material=r.material, cantidad=pendiente, orden=orden_nueva,
                                          necesaria_para=orden_nueva.fecha_programada, responsable=responsable,
                                          nota=f"Reasignada desde {r.orden.numero}: {motivo}"[:200])
