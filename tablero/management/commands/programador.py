"""Programador de tareas automáticas (para el servicio 'tareas' de producción).

    python manage.py programador

Horarios configurables con variables de entorno:
    HORA_RECORDATORIOS=07:30   (partes adeudadas)
    HORA_TAREAS=21:00          (encuestas, alertas, parte diario por mail)
"""
import os
import time
from datetime import datetime, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone


def proxima(hhmm: str, ahora: datetime) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    cuando = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
    return cuando if cuando > ahora else cuando + timedelta(days=1)


class Command(BaseCommand):
    help = "Corre las tareas automáticas todos los días a su hora."

    def handle(self, *args, **opts):
        tareas = [(os.environ.get("HORA_RECORDATORIOS", "07:30"), "recordatorios"),
                  (os.environ.get("HORA_TAREAS", "21:00"), "tareas_diarias")]
        self.stdout.write("Programador iniciado: " + ", ".join(f"{c} a las {h}" for h, c in tareas))
        while True:
            ahora = timezone.localtime()
            hora, comando = min(((proxima(h, ahora), c) for h, c in tareas), key=lambda x: x[0])
            time.sleep(max(1, (hora - ahora).total_seconds()))
            self.stdout.write(f"[{timezone.localtime():%d/%m %H:%M}] {comando}")
            try:
                call_command(comando, stdout=self.stdout)
            except Exception as e:  # noqa: BLE001 — una falla no debe detener al programador
                self.stderr.write(f"Error en {comando}: {e}")
            time.sleep(61)
