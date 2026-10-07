"""Evaluación de supervisores.

Cuatro ejes, cada uno 0-100:
  * Imagen / trato    - promedio de la encuesta diaria de sus técnicos.
  * Control en calle  - cantidad de informes por día trabajado y calidad de documentación.
  * Gestión de desvíos- % de desvíos detectados que tuvieron acción correctiva y en cuántos días.
  * Objetivos         - cumplimiento de las tareas diarias asignadas por gerencia.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Avg, Count
from django.utils import timezone

from core.models import Persona
from incidentes.models import Siniestro
from operaciones.models import Jornada

from .models import EncuestaSemanal, EncuestaSupervisor, InformeControl, TareaSupervisor

INFORMES_OBJETIVO_DIA = 4  # controles por día hábil esperados de un supervisor


@dataclass
class EvaluacionSupervisor:
    supervisor: Persona
    tecnicos_a_cargo: int = 0
    dias_habiles: int = 0
    informes: int = 0
    informes_por_dia: float = 0.0
    calidad_documentacion: float = 0.0
    desvios: int = 0
    desvios_con_accion: int = 0
    dias_respuesta_prom: float | None = None
    encuestas_enviadas: int = 0
    encuestas_respondidas: int = 0
    nota_trato: float | None = None
    nota_claridad: float | None = None
    nota_apoyo: float | None = None
    nota_presencia: float | None = None
    cumplimiento_tareas: float | None = None
    nota_semanal: float | None = None      # promedio de la evaluación semanal (1-5)
    semanales: int = 0
    siniestros_equipo: int = 0
    score_imagen: float = 0.0
    score_control: float = 0.0
    score_desvios: float = 0.0
    score_objetivos: float = 0.0
    score_total: float = 0.0

    @property
    def nota_encuesta(self):
        notas = [n for n in (self.nota_trato, self.nota_claridad, self.nota_apoyo, self.nota_presencia) if n]
        return sum(notas) / len(notas) if notas else None

    @property
    def tasa_respuesta(self):
        return self.encuestas_respondidas / self.encuestas_enviadas if self.encuestas_enviadas else None

    @property
    def color(self):
        return "ok" if self.score_total >= 70 else "aviso" if self.score_total >= 50 else "critico"


def evaluar_supervisores(hasta: date | None = None, dias: int = 30):
    hasta = hasta or timezone.localdate()
    desde = hasta - timedelta(days=dias - 1)
    sups = list(Persona.objects.filter(rol=Persona.Rol.SUPERVISOR, activo=True))
    evs = {s.id: EvaluacionSupervisor(supervisor=s) for s in sups}
    ids = list(evs)

    for r in (Persona.objects.filter(supervisor_id__in=ids, activo=True, rol=Persona.Rol.TECNICO)
              .values("supervisor_id").annotate(n=Count("id"))):
        evs[r["supervisor_id"]].tecnicos_a_cargo = r["n"]

    # Días hábiles = días en que su equipo salió a la calle
    for r in (Jornada.objects.filter(tecnico__supervisor_id__in=ids, fecha__range=(desde, hasta), en_calle=True)
              .values("tecnico__supervisor_id").annotate(n=Count("fecha", distinct=True))):
        evs[r["tecnico__supervisor_id"]].dias_habiles = r["n"]

    calidad = defaultdict(list)
    respuesta = defaultdict(list)
    for inf in (InformeControl.objects.filter(supervisor_id__in=ids, fecha__range=(desde, hasta))
                .prefetch_related("acciones")):
        e = evs[inf.supervisor_id]
        e.informes += 1
        calidad[inf.supervisor_id].append(inf.calidad_informe)
        if inf.desvio_detectado:
            e.desvios += 1
            acciones = list(inf.acciones.all())
            if acciones:
                e.desvios_con_accion += 1
                respuesta[inf.supervisor_id].append(min((a.fecha - inf.fecha).days for a in acciones))

    enc = EncuestaSupervisor.objects.filter(supervisor_id__in=ids, fecha__range=(desde, hasta))
    for r in enc.values("supervisor_id").annotate(n=Count("id")):
        evs[r["supervisor_id"]].encuestas_enviadas = r["n"]
    for r in (enc.filter(respondida__isnull=False).values("supervisor_id")
              .annotate(n=Count("id"), t=Avg("trato"), c=Avg("claridad"), a=Avg("apoyo"), p=Avg("presencia"))):
        e = evs[r["supervisor_id"]]
        e.encuestas_respondidas = r["n"]
        e.nota_trato, e.nota_claridad, e.nota_apoyo, e.nota_presencia = (
            float(r[k]) if r[k] is not None else None for k in "tcap")

    semanal = defaultdict(list)
    for e in EncuestaSemanal.objects.filter(supervisor_id__in=ids, semana__range=(desde - timedelta(days=6), hasta)):
        semanal[e.supervisor_id].append(e.promedio)
    for sid, notas in semanal.items():
        evs[sid].nota_semanal = sum(notas) / len(notas)
        evs[sid].semanales = len(notas)

    tareas = defaultdict(list)
    for t in TareaSupervisor.objects.filter(supervisor_id__in=ids, fecha__range=(desde, hasta)).exclude(
            estado=TareaSupervisor.Estado.PENDIENTE):
        if t.cumplimiento is not None:
            tareas[t.supervisor_id].append(t.cumplimiento)

    for r in (Siniestro.objects.filter(fecha__range=(desde, hasta), tecnico__supervisor_id__in=ids)
              .values("tecnico__supervisor_id").annotate(n=Count("id"))):
        evs[r["tecnico__supervisor_id"]].siniestros_equipo = r["n"]

    for sid, e in evs.items():
        e.informes_por_dia = e.informes / e.dias_habiles if e.dias_habiles else 0.0
        e.calidad_documentacion = sum(calidad[sid]) / len(calidad[sid]) if calidad[sid] else 0.0
        if respuesta[sid]:
            e.dias_respuesta_prom = sum(respuesta[sid]) / len(respuesta[sid])
        if tareas[sid]:
            e.cumplimiento_tareas = sum(tareas[sid]) / len(tareas[sid])

        # Imagen: promedio de la encuesta diaria y de la evaluación semanal (las que haya)
        notas_img = [n for n in (e.nota_encuesta, e.nota_semanal) if n]
        e.score_imagen = (sum(notas_img) / len(notas_img) - 1) / 4 * 100 if notas_img else 0.0
        cantidad = min(1.0, e.informes_por_dia / INFORMES_OBJETIVO_DIA) * 100
        e.score_control = 0.6 * cantidad + 0.4 * e.calidad_documentacion
        if e.desvios:
            cobertura = e.desvios_con_accion / e.desvios * 100
            rapidez = 100 if e.dias_respuesta_prom is None else max(0, 100 - max(0, e.dias_respuesta_prom - 1) * 25)
            e.score_desvios = 0.7 * cobertura + 0.3 * rapidez
        else:
            # Sin desvíos detectados: si casi no controla, no se le da puntaje alto
            e.score_desvios = 50.0 if e.informes_por_dia < 1 else 80.0
        e.score_objetivos = (e.cumplimiento_tareas or 0) * 100
        e.score_total = round(0.30 * e.score_imagen + 0.25 * e.score_control
                              + 0.20 * e.score_desvios + 0.25 * e.score_objetivos, 1)
    return sorted(evs.values(), key=lambda e: -e.score_total)
