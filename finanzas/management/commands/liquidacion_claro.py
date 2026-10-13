"""Registra la liquidación esperada de Claro como ingreso a cobrar.

    python manage.py liquidacion_claro               # mes anterior
    python manage.py liquidacion_claro --mes 2026-09
    python manage.py liquidacion_claro --desde 2026-05   # todos los meses hasta el anterior
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from finanzas.liquidacion_claro import registrar
from finanzas.proyeccion import sumar_meses


def _mes(texto):
    try:
        return date.fromisoformat(f"{texto}-01")
    except ValueError:
        raise CommandError(f"Mes inválido: {texto} (usar AAAA-MM)")


class Command(BaseCommand):
    help = "Calcula y registra la liquidación esperada de Claro (ingreso a cobrar)."

    def add_arguments(self, parser):
        parser.add_argument("--mes")
        parser.add_argument("--desde")

    def handle(self, *args, mes=None, desde=None, **opts):
        anterior = sumar_meses(timezone.localdate().replace(day=1), -1)
        meses = [_mes(mes)] if mes else []
        if desde:
            m = _mes(desde)
            while m <= anterior:
                meses.append(m)
                m = sumar_meses(m, 1)
        for m in meses or [anterior]:
            i = registrar(m)
            self.stdout.write(f"{m:%m/%Y}: " + (f"${i.monto:,.2f} a cobrar el {i.fecha_esperada_cobro:%d/%m/%Y}" if i
                                                 else "sin órdenes con precio"))
