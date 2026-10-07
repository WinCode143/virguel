from datetime import date

from django.core.management.base import BaseCommand

from tablero.automatizacion import ejecutar


class Command(BaseCommand):
    help = "Genera encuestas del día, cierra tareas vencidas y recalcula todas las alertas."

    def add_arguments(self, parser):
        parser.add_argument("--fecha", type=date.fromisoformat, help="Fecha a procesar (AAAA-MM-DD).")
        parser.add_argument("--sin-parte", action="store_true", help="No enviar el parte diario por mail.")

    def handle(self, *args, fecha=None, sin_parte=False, **opts):
        ejecutar(fecha, log=self.stdout.write, enviar_parte=not sin_parte)
