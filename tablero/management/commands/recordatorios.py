"""Recordatorios de la mañana: partes adeudadas (técnicos y supervisores)."""
from django.core.management.base import BaseCommand

from inventario.deudas import notificar_deudas


class Command(BaseCommand):
    help = "Avisa a cada técnico qué partes debe regularizar y a cada supervisor el resumen de su equipo."

    def handle(self, *args, **opts):
        notificar_deudas(log=self.stdout.write)
