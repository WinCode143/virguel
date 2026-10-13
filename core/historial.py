"""Lectura de la composición histórica de los equipos (AsignacionSupervisor).

Para un período, a qué supervisor respondía cada técnico en cada fecha. Si un técnico no tiene
historia cargada (datos anteriores), se usa su supervisor actual.
"""
from collections import defaultdict
from datetime import date

from django.db.models import Q

from .models import AsignacionSupervisor, Persona


class HistorialSupervisores:
    def __init__(self, desde: date, hasta: date):
        self.desde, self.hasta = desde, hasta
        self.tramos = defaultdict(list)  # tecnico_id -> [(desde, hasta|None, supervisor_id)]
        for a in AsignacionSupervisor.objects.filter(desde__lte=hasta).filter(
                Q(hasta__isnull=True) | Q(hasta__gte=desde)):
            self.tramos[a.tecnico_id].append((a.desde, a.hasta, a.supervisor_id))
        self._con_historia = set(AsignacionSupervisor.objects.values_list("tecnico_id", flat=True).distinct())
        self._actual = dict(Persona.objects.filter(rol="tecnico").values_list("id", "supervisor_id"))

    def supervisor(self, tecnico_id: int, fecha: date) -> int | None:
        if tecnico_id not in self._con_historia:
            return self._actual.get(tecnico_id)
        for d, h, s in self.tramos.get(tecnico_id, ()):
            if d <= fecha and (h is None or fecha <= h):
                return s
        return None

    def equipo(self, supervisor_id: int) -> set[int]:
        """Técnicos que estuvieron a cargo del supervisor en algún momento del período."""
        ids = {t for t, tramos in self.tramos.items() if any(s == supervisor_id for _, _, s in tramos)}
        ids |= {t for t, s in self._actual.items() if s == supervisor_id and t not in self._con_historia}
        return ids
