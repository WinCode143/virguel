from datetime import date

from django.core.management.base import BaseCommand

from personal.parte import enviar


class Command(BaseCommand):
    help = "Envía el parte diario por mail a gerencia y a cada supervisor."

    def add_arguments(self, parser):
        parser.add_argument("--fecha", type=date.fromisoformat)

    def handle(self, *args, fecha=None, **opts):
        n = enviar(fecha, log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(f"{n} parte(s) enviado(s)."))
