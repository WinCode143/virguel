from datetime import date

from django.core.management.base import BaseCommand

from tablero.automatizacion import ejecutar


class Command(BaseCommand):
    help = "Genera encuestas del día, cierra tareas vencidas y recalcula todas las alertas."

    def add_arguments(self, parser):
        parser.add_argument("--fecha", type=date.fromisoformat, help="Fecha a procesar (AAAA-MM-DD).")

    def handle(self, *args, fecha=None, **opts):
        ejecutar(fecha, log=self.stdout.write)
