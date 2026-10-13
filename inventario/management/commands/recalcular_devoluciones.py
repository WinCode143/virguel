"""Corrige los egresos que generaron las devoluciones de técnicos antes de la corrección H02.

Antes, cada devolución creaba un lote nuevo que finanzas tomaba como una compra. Este comando
informa esos egresos y, con --aplicar, los elimina (las devoluciones no son compras).

    python manage.py recalcular_devoluciones            # sólo informa
    python manage.py recalcular_devoluciones --aplicar  # corrige
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from finanzas.models import Egreso
from inventario.models import LoteIngreso


class Command(BaseCommand):
    help = "Elimina los egresos generados por devoluciones de técnicos (no son compras)."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true", help="Corregir (sin esto sólo se informa).")

    def handle(self, *args, aplicar=False, **opts):
        lotes = LoteIngreso.objects.exclude(origen=LoteIngreso.Origen.COMPRA)
        egresos = Egreso.objects.filter(origen__in=[f"lote:{pk}" for pk in lotes.values_list("pk", flat=True)])
        total = sum((e.monto for e in egresos), Decimal("0"))
        for e in egresos.order_by("fecha"):
            self.stdout.write(f"{e.fecha:%d/%m/%Y}  ${e.monto:>12,.2f}  {e.descripcion}")
        self.stdout.write(f"{egresos.count()} egresos por ${total:,.2f} generados por devoluciones o ajustes.")
        sin_origen = lotes.filter(origen=LoteIngreso.Origen.DEVOLUCION, lote_origen__isnull=True).count()
        if sin_origen:
            self.stdout.write(f"{sin_origen} lotes de devolución anteriores sin lote de origen registrado: su fecha "
                              "de ingreso es la de la devolución (revisar a mano si importa su antigüedad).")
        if not aplicar:
            self.stdout.write("Sin cambios. Usar --aplicar para eliminar esos egresos.")
            return
        with transaction.atomic():
            n, _ = egresos.delete()
        self.stdout.write(self.style.SUCCESS(f"Eliminados {n} egresos."))
