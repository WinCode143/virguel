"""Evaluación de supervisores.

Cuatro ejes, cada uno 0-100:
  * Imagen / trato    - promedio de la encuesta diaria de sus técnicos.
  * Control en calle  - cantidad de informes por día trabajado y calidad de documentación.
  * Gestión de desvíos- % de desvíos detectados que tuvieron acción correctiva y en cuántos días.
  * Objetivos         - cumplimiento de las tareas asignadas por gerencia: sólo cuenta lo VERIFICADO por
                        un tercero (lo reportado espera verificación; lo vencido sin reporte cuenta 0).
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Avg, Count
from django.utils import timezone

from core.models import Persona
from incidentes.models import Siniestro
from operaciones.models import Jornada

from .efectividad import EFECTIVA, clasificar
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
    desvios_con_accion: int = 0          # con acción INDICADA
    desvios_accion_ejecutada: int = 0    # con acción CUMPLIDA (ejecutada); no dice si funcionó
    desvios_accion_eficaz: int = 0       # con acción cumplida y VERIFICADA eficaz (supervision/efectividad.py)
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
    personas_encuesta: int = 0             # técnicos distintos que respondieron
    encuesta_suficiente: bool = False
    score_imagen: float | None = None
    score_control: float | None = None
    score_desvios: float | None = None
    score_objetivos: float | None = None
    score_total: float | None = None
    sin_datos: list = None

    @property
    def sin_evidencia(self) -> bool:
        return self.score_total is None

    @property
    def nota_encuesta(self):
        notas = [n for n in (self.nota_trato, self.nota_claridad, self.nota_apoyo, self.nota_presencia) if n]
        return sum(notas) / len(notas) if notas else None

    @property
    def tasa_respuesta(self):
        return self.encuestas_respondidas / self.encuestas_enviadas if self.encuestas_enviadas else None

    @property
    def color(self):
        if self.score_total is None:
            return "info"
        return "ok" if self.score_total >= 70 else "aviso" if self.score_total >= 50 else "critico"


def evaluar_supervisores(hasta: date | None = None, dias: int = 30):
    from core.models import Parametros
    par = Parametros.actual()
    hasta = hasta or timezone.localdate()
    desde = hasta - timedelta(days=dias - 1)
    sups = list(Persona.objects.filter(rol=Persona.Rol.SUPERVISOR, activo=True))
    evs = {s.id: EvaluacionSupervisor(supervisor=s) for s in sups}
    ids = list(evs)

    for r in (Persona.objects.filter(supervisor_id__in=ids, activo=True, rol=Persona.Rol.TECNICO)
              .values("supervisor_id").annotate(n=Count("id"))):
        evs[r["supervisor_id"]].tecnicos_a_cargo = r["n"]

    # Días hábiles = días en que su equipo (el de ESE día, según el historial) salió a la calle
    from core.historial import HistorialSupervisores
    hist = HistorialSupervisores(desde, hasta)
    dias_equipo = defaultdict(set)
    for tid, f in Jornada.objects.filter(fecha__range=(desde, hasta), en_calle=True).values_list("tecnico_id", "fecha"):
        sid = hist.supervisor(tid, f)
        if sid in evs:
            dias_equipo[sid].add(f)
    for sid, fechas in dias_equipo.items():
        evs[sid].dias_habiles = len(fechas)

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
            cumplidas = [a for a in acciones if a.cumplida]
            if cumplidas:
                # una acción EJECUTADA cuenta como gestión del desvío (una indicada pendiente no); la eficacia
                # se mide aparte, con los controles posteriores
                e.desvios_accion_ejecutada += 1
                if any(clasificar(a, hasta) == EFECTIVA for a in cumplidas):
                    e.desvios_accion_eficaz += 1
                respuesta[inf.supervisor_id].append(min(((a.fecha_cumplida or a.fecha) - inf.fecha).days
                                                        for a in cumplidas))

    enc = EncuestaSupervisor.objects.filter(supervisor_id__in=ids, fecha__range=(desde, hasta))
    for r in enc.values("supervisor_id").annotate(n=Count("id")):
        evs[r["supervisor_id"]].encuestas_enviadas = r["n"]
    for r in (enc.filter(respondida__isnull=False).values("supervisor_id")
              .annotate(n=Count("id"), t=Avg("trato"), c=Avg("claridad"), a=Avg("apoyo"), p=Avg("presencia"))):
        e = evs[r["supervisor_id"]]
        e.encuestas_respondidas = r["n"]
        e.nota_trato, e.nota_claridad, e.nota_apoyo, e.nota_presencia = (
            float(r[k]) if r[k] is not None else None for k in "tcap")
    for r in (enc.filter(respondida__isnull=False).values("supervisor_id")
              .annotate(p=Count("tecnico", distinct=True))):
        evs[r["supervisor_id"]].personas_encuesta = r["p"]

    semanal = defaultdict(list)
    personas_semanal = defaultdict(set)
    for e in EncuestaSemanal.objects.filter(supervisor_id__in=ids, semana__range=(desde - timedelta(days=6), hasta)):
        semanal[e.supervisor_id].append(e.promedio)
        personas_semanal[e.supervisor_id].add(e.tecnico_id)
    for sid, personas in personas_semanal.items():
        evs[sid].personas_encuesta = max(evs[sid].personas_encuesta, len(personas))
    for sid, notas in semanal.items():
        evs[sid].nota_semanal = sum(notas) / len(notas)
        evs[sid].semanales = len(notas)

    tareas = defaultdict(list)
    for t in TareaSupervisor.objects.filter(supervisor_id__in=ids, fecha__range=(desde, hasta)).exclude(
            estado=TareaSupervisor.Estado.PENDIENTE):
        if t.cumplimiento is not None:
            tareas[t.supervisor_id].append(t.cumplimiento)

    for tid, f in Siniestro.objects.filter(fecha__range=(desde, hasta), tecnico__isnull=False).values_list(
            "tecnico_id", "fecha"):
        sid = hist.supervisor(tid, f)
        if sid in evs:
            evs[sid].siniestros_equipo += 1

    for sid, e in evs.items():
        e.informes_por_dia = e.informes / e.dias_habiles if e.dias_habiles else 0.0
        e.calidad_documentacion = sum(calidad[sid]) / len(calidad[sid]) if calidad[sid] else 0.0
        if respuesta[sid]:
            e.dias_respuesta_prom = sum(respuesta[sid]) / len(respuesta[sid])
        if tareas[sid]:
            e.cumplimiento_tareas = sum(tareas[sid]) / len(tareas[sid])

        # Suficiencia de la encuesta: con pocas respuestas o personas no se consolida una nota de trato
        # (y se protege la confidencialidad en grupos chicos).
        e.encuesta_suficiente = (e.encuestas_respondidas + e.semanales >= par.encuesta_min_respuestas
                                 and e.personas_encuesta >= par.encuesta_min_personas)
        if not e.encuesta_suficiente:
            e.nota_trato = e.nota_claridad = e.nota_apoyo = e.nota_presencia = e.nota_semanal = None
        e.sin_datos = []
        # Imagen: promedio de la encuesta diaria y de la evaluación semanal (las que haya)
        notas_img = [n for n in (e.nota_encuesta, e.nota_semanal) if n]
        if notas_img:
            e.score_imagen = (sum(notas_img) / len(notas_img) - 1) / 4 * 100
        else:
            e.sin_datos.append("encuestas insuficientes")
        # Control: sólo evaluable si su equipo trabajó en el período
        if e.dias_habiles:
            cantidad = min(1.0, e.informes_por_dia / INFORMES_OBJETIVO_DIA) * 100
            e.score_control = 0.6 * cantidad + 0.4 * e.calidad_documentacion
        else:
            e.sin_datos.append("su equipo no tuvo jornadas")
        # Gestión de desvíos = con acción EJECUTADA (no "corregidos": la eficacia se informa aparte como
        # desvios_accion_eficaz); sin desvíos detectados no hay qué evaluar
        if e.desvios:
            cobertura = e.desvios_accion_ejecutada / e.desvios * 100
            rapidez = 0 if e.dias_respuesta_prom is None else max(0, 100 - max(0, e.dias_respuesta_prom - 1) * 25)
            e.score_desvios = 0.7 * cobertura + 0.3 * rapidez
        else:
            e.sin_datos.append("sin desvíos detectados")
        if e.cumplimiento_tareas is not None:
            e.score_objetivos = e.cumplimiento_tareas * 100
        else:
            e.sin_datos.append("sin objetivos asignados")
        pesos = {"score_imagen": .30, "score_control": .25, "score_desvios": .20, "score_objetivos": .25}
        con = {k: getattr(e, k) for k in pesos if getattr(e, k) is not None}
        total = sum(pesos[k] for k in con)
        e.score_total = round(sum(pesos[k] * v for k, v in con.items()) / total, 1) if con else None
    return sorted(evs.values(), key=lambda e: (e.score_total is None, -(e.score_total or 0)))
