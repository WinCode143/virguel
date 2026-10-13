"""Evaluación retrospectiva de los diagnósticos: ¿qué pasó después con cada grupo?

Toma las fotos semanales (EvaluacionHistorica) con al menos `--horizonte` días de antigüedad y
mira qué ocurrió en los días siguientes: baja de la persona, sanciones y siniestros. Sirve para
revisar con la empresa si los pesos del criterio separan bien los casos (no prueba causalidad).

    python manage.py evaluacion_retrospectiva --horizonte 90
"""
from collections import defaultdict
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from capacitacion.models import EvaluacionHistorica
from incidentes.models import Siniestro
from supervision.models import AccionCorrectiva

SANCIONES = ("apercibimiento", "multa", "suspension")


class Command(BaseCommand):
    help = "Compara cada diagnóstico histórico con lo que pasó en los días siguientes."

    def add_arguments(self, parser):
        parser.add_argument("--horizonte", type=int, default=90, help="Días a mirar después de cada foto.")

    def handle(self, *args, horizonte=90, **opts):
        limite = timezone.localdate() - timedelta(days=horizonte)
        grupos = defaultdict(lambda: {"n": 0, "baja": 0, "sancion": 0, "siniestro": 0})
        for h in EvaluacionHistorica.objects.filter(fecha__lte=limite).select_related("persona"):
            fin = h.fecha + timedelta(days=horizonte)
            g = grupos[(h.criterio_version or 0, h.diagnostico)]
            g["n"] += 1
            p = h.persona
            g["baja"] += bool(p.fecha_egreso and h.fecha < p.fecha_egreso <= fin)
            g["sancion"] += AccionCorrectiva.objects.filter(tecnico=p, tipo__in=SANCIONES,
                                                            fecha__gt=h.fecha, fecha__lte=fin).exists()
            g["siniestro"] += Siniestro.objects.filter(tecnico=p, fecha__gt=h.fecha, fecha__lte=fin).exists()
        if not grupos:
            self.stdout.write(f"No hay evaluaciones históricas con más de {horizonte} días.")
            return
        self.stdout.write(f"{'Criterio':>8}  {'Diagnóstico':<48} {'Fotos':>6} {'Baja':>6} {'Sanción':>8} {'Siniestro':>9}")
        for (version, diag), g in sorted(grupos.items()):
            pct = lambda k: f"{g[k] / g['n']:.0%}"  # noqa: E731
            self.stdout.write(f"{('v' + str(version)) if version else '—':>8}  {diag[:48]:<48} {g['n']:>6} "
                              f"{pct('baja'):>6} {pct('sancion'):>8} {pct('siniestro'):>9}")
        self.stdout.write("Porcentaje de fotos tras las cuales hubo cada evento dentro del horizonte.")
