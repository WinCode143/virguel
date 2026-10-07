"""Indicadores de productividad de técnicos (IPT) y supervisores (IGS).

Las definiciones, metas, mínimos y pesos viven en `core.Indicador` (editables).
Ver docs/METRICAS.md para la explicación de cada uno.
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, median

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from core.models import Indicador, Parametros, Persona
from incidentes.models import Siniestro
from inventario.models import PedidoMaterial, RecetaMaterial, Salida
from operaciones.models import Jornada, OrdenTrabajo
from personal.indicadores import resumen as resumen_asistencia
from personal.models import Asistencia, Novedad
from supervision.models import AccionCorrectiva, InformeControl

EVITABLES = ("falta_material", "otro")


@dataclass
class Medicion:
    indicador: Indicador
    valor: float | None
    detalle: str = ""

    @property
    def puntos(self):
        return self.indicador.puntos(self.valor)

    @property
    def estado(self):
        p = self.puntos
        if p is None:
            return "info"
        return "ok" if p >= 80 else "aviso" if p >= 50 else "critico"


@dataclass
class Tablero:
    persona: Persona
    mediciones: list = field(default_factory=list)

    @property
    def indice(self) -> float | None:
        con = [(m.puntos, m.indicador.peso) for m in self.mediciones if m.puntos is not None and m.indicador.peso]
        total = sum(p for _, p in con)
        return round(sum(v * p for v, p in con) / total, 1) if total else None

    @property
    def estado(self):
        i = self.indice
        return "info" if i is None else "ok" if i >= 75 else "aviso" if i >= 55 else "critico"

    def get(self, codigo):
        return next((m for m in self.mediciones if m.indicador.codigo == codigo), None)

    @property
    def fuertes(self):
        return [m for m in self.mediciones if m.indicador.peso and m.puntos is not None and m.puntos >= 90][:3]

    @property
    def debiles(self):
        return sorted([m for m in self.mediciones if m.indicador.peso and m.puntos is not None and m.puntos < 50],
                      key=lambda m: m.puntos)[:3]


def _pct(a, b):
    return a / b * 100 if b else None


def _distancia_m(lat1, lng1, lat2, lng2):
    r = 6371000
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ------------------------------------------------------------------ técnicos
def valores_tecnicos(desde: date, hasta: date, tecnicos) -> dict:
    """{tecnico_id: {codigo: valor}} con los valores crudos de cada indicador."""
    tecnicos = list(tecnicos)
    ids = [t.id for t in tecnicos]
    par = Parametros.actual()
    hoy = timezone.localdate()
    v = {t.id: {} for t in tecnicos}

    # Horas trabajadas: fichada con salida; si el día no tiene fichada, la jornada normal
    horas = defaultdict(float)
    dias_fichados = defaultdict(set)
    entradas = {}
    for pid, f, h, ent in Asistencia.objects.filter(persona_id__in=ids, fecha__range=(desde, hasta),
                                                    salida__isnull=False).values_list(
            "persona_id", "fecha", "horas_trabajadas", "entrada"):
        horas[pid] += float(h)
        dias_fichados[pid].add(f)
        entradas[(pid, f)] = ent
    dias_calle = defaultdict(int)
    for pid, f in Jornada.objects.filter(tecnico_id__in=ids, fecha__range=(desde, hasta), en_calle=True).values_list(
            "tecnico_id", "fecha"):
        dias_calle[pid] += 1
        if f not in dias_fichados[pid] and f < hoy:
            horas[pid] += float(par.horas_jornada)

    completadas = OrdenTrabajo.objects.filter(tecnico_id__in=ids, estado="completada",
                                              fecha_ejecucion__range=(desde, hasta))
    est = defaultdict(float)
    n_comp = defaultdict(int)
    reales, estandar_con_real = defaultdict(list), defaultdict(list)
    doc = defaultdict(int)
    en_sitio, con_gps = defaultdict(int), defaultdict(int)
    primeros_inicios = {}
    ordenes_por_tec = defaultdict(list)
    for o in completadas.values("id", "tecnico_id", "tipo_id", "tipo__minutos_estandar", "minutos_reales",
                                "foto_trabajo", "conforme_nombre", "firma", "lat_cierre", "lng_cierre",
                                "cliente__latitud", "cliente__longitud", "inicio_trabajo", "fecha_ejecucion"):
        t = o["tecnico_id"]
        n_comp[t] += 1
        est[t] += o["tipo__minutos_estandar"] / 60
        ordenes_por_tec[t].append((o["id"], o["tipo_id"]))
        if o["minutos_reales"]:
            reales[t].append(o["minutos_reales"])
            estandar_con_real[t].append(o["tipo__minutos_estandar"])
        if o["foto_trabajo"] and (o["conforme_nombre"] or o["firma"]):
            doc[t] += 1
        if o["lat_cierre"] is not None and o["cliente__latitud"] is not None:
            con_gps[t] += 1
            if _distancia_m(o["lat_cierre"], o["lng_cierre"], o["cliente__latitud"], o["cliente__longitud"]) <= 300:
                en_sitio[t] += 1
        if o["inicio_trabajo"]:
            k = (t, o["fecha_ejecucion"])
            primeros_inicios[k] = min(primeros_inicios.get(k, o["inicio_trabajo"]), o["inicio_trabajo"])

    con_retrabajo = defaultdict(int)
    for t, n in (OrdenTrabajo.objects.filter(es_retrabajo=True, orden_original__in=completadas)
                 .values_list("orden_original__tecnico_id").annotate(n=Count("orden_original", distinct=True))):
        con_retrabajo[t] = n

    # Agenda: órdenes asignadas para días ya terminados, resueltas o intentadas ese mismo día
    agenda = defaultdict(lambda: [0, 0])
    for t, fp, fe, estado in OrdenTrabajo.objects.filter(
            tecnico_id__in=ids, fecha_programada__range=(desde, min(hasta, hoy - timedelta(days=1)))).values_list(
            "tecnico_id", "fecha_programada", "fecha_ejecucion", "estado"):
        agenda[t][0] += 1
        if fe == fp and estado in ("completada", "fallida"):
            agenda[t][1] += 1

    ejecutadas = dict(OrdenTrabajo.objects.filter(tecnico_id__in=ids, fecha_ejecucion__range=(desde, hasta))
                      .values_list("tecnico_id").annotate(n=Count("id")))
    evitables = dict(OrdenTrabajo.objects.filter(tecnico_id__in=ids, fecha_ejecucion__range=(desde, hasta),
                                                 estado__in=["fallida", "reprogramada"],
                                                 motivo_no_resuelto__in=EVITABLES)
                     .values_list("tecnico_id").annotate(n=Count("id")))
    controles = dict(InformeControl.objects.filter(tecnico_id__in=ids, fecha__range=(desde, hasta))
                     .values_list("tecnico_id").annotate(p=Avg("puntaje")))

    # Consumo de materiales vs. estándar (sin decodificadores: dependen del cliente)
    costo_std_tipo = defaultdict(Decimal)
    for r in RecetaMaterial.objects.select_related("material"):
        if not r.material.es_decodificador:
            costo_std_tipo[r.tipo_tarea_id] += r.cantidad * r.material.costo_unitario
    consumo_real = dict(Salida.objects.filter(motivo="consumo", orden__in=completadas, tecnico_id__in=ids,
                                              material__es_decodificador=False)
                        .values_list("tecnico_id").annotate(t=Sum("costo_total")))

    puntual = {r["persona_id"]: (r["n"], r["ok"]) for r in Asistencia.objects.filter(
        persona_id__in=ids, fecha__range=(desde, hasta)).values("persona_id").annotate(
        n=Count("id"), ok=Count("id", filter=Q(minutos_tarde=0)))}
    asistencia = {r.persona.id: r for r in resumen_asistencia(desde, hasta, tecnicos)}
    from capacitacion.evaluacion import mediana_plantel
    med = mediana_plantel(desde, hasta)

    for t in tecnicos:
        x = v[t.id]
        x["eficiencia_jornada"] = _pct(est[t.id], horas[t.id]) if horas[t.id] >= 8 else None
        x["primera_visita"] = 100 - _pct(con_retrabajo[t.id], n_comp[t.id]) if n_comp[t.id] else None
        tot, ok = agenda[t.id]
        x["cumplimiento_agenda"] = _pct(ok, tot)
        x["calidad_controles"] = float(controles[t.id]) * 20 if t.id in controles else None
        x["no_resueltas_evitables"] = _pct(evitables.get(t.id, 0), ejecutadas.get(t.id, 0))
        x["ot_por_dia"] = _pct(n_comp[t.id] / dias_calle[t.id], med) if dias_calle[t.id] and med else None
        x["documentacion_cierre"] = _pct(doc[t.id], n_comp[t.id])
        x["cierre_en_sitio"] = _pct(en_sitio[t.id], con_gps[t.id]) if con_gps[t.id] >= 5 else None
        std = sum((costo_std_tipo[tipo] for _, tipo in ordenes_por_tec[t.id]), Decimal("0"))
        x["consumo_vs_estandar"] = _pct(float(consumo_real.get(t.id) or 0), float(std)) if std else None
        n, ok = puntual.get(t.id, (0, 0))
        x["puntualidad"] = _pct(ok, n)
        pr = asistencia.get(t.id)
        x["presentismo"] = pr.presentismo * 100 if pr and pr.presentismo is not None else None
        demoras = [(primeros_inicios[k] - entradas[k]).total_seconds() / 60
                   for k in primeros_inicios if k[0] == t.id and k in entradas]
        x["arranque"] = mean(demoras) if len(demoras) >= 3 else None
        x["minutos_vs_estandar"] = (_pct(mean(reales[t.id]), mean(estandar_con_real[t.id]))
                                    if reales[t.id] else None)
    return v


def tableros_tecnicos(desde=None, hasta=None, tecnicos=None, dias=30) -> list[Tablero]:
    hasta = hasta or timezone.localdate()
    desde = desde or hasta - timedelta(days=dias - 1)
    if tecnicos is None:
        tecnicos = Persona.objects.filter(rol="tecnico", activo=True)
    tecnicos = list(tecnicos)
    indicadores = list(Indicador.objects.filter(rol="tecnico", activo=True))
    valores = valores_tecnicos(desde, hasta, tecnicos)
    res = [Tablero(t, [Medicion(i, valores[t.id].get(i.codigo)) for i in indicadores]) for t in tecnicos]
    return sorted(res, key=lambda tb: -(tb.indice or -1))


# ------------------------------------------------------------------ supervisores
def tableros_supervisores(desde=None, hasta=None, dias=30, supervisores=None) -> list[Tablero]:
    from supervision.evaluacion import evaluar_supervisores
    hasta = hasta or timezone.localdate()
    desde = desde or hasta - timedelta(days=dias - 1)
    sups = list(supervisores if supervisores is not None else Persona.objects.filter(rol="supervisor", activo=True))
    indicadores = list(Indicador.objects.filter(rol="supervisor", activo=True))
    equipos = defaultdict(list)
    for t in Persona.objects.filter(rol="tecnico", activo=True, supervisor__in=sups):
        equipos[t.supervisor_id].append(t)
    todos = [t for ts in equipos.values() for t in ts]
    vt = valores_tecnicos(desde, hasta, todos)
    asis = {r.persona.id: r for r in resumen_asistencia(desde, hasta, todos)}
    evs = {e.supervisor.id: e for e in evaluar_supervisores(hasta, (hasta - desde).days + 1)}
    puntual_sup = {r["persona_id"]: (r["n"], r["ok"]) for r in Asistencia.objects.filter(
        persona__in=sups, fecha__range=(desde, hasta)).values("persona_id").annotate(
        n=Count("id"), ok=Count("id", filter=Q(minutos_tarde=0)))}

    def media(ids, codigo):
        xs = [vt[i][codigo] for i in ids if vt[i].get(codigo) is not None]
        return mean(xs) if xs else None

    def ot_dia(ids, a, b):
        d = Jornada.objects.filter(tecnico_id__in=ids, en_calle=True, fecha__range=(a, b)).count()
        o = OrdenTrabajo.objects.filter(tecnico_id__in=ids, estado="completada", fecha_ejecucion__range=(a, b)).count()
        return o / d if d else None

    res = []
    for s in sups:
        ids = [t.id for t in equipos[s.id]]
        x = {}
        x["eficiencia_equipo"] = media(ids, "eficiencia_jornada")
        x["primera_visita_equipo"] = media(ids, "primera_visita")
        reciente = ot_dia(ids, hasta - timedelta(days=27), hasta)
        anterior = ot_dia(ids, hasta - timedelta(days=55), hasta - timedelta(days=28))
        x["mejora_equipo"] = (reciente - anterior) / anterior * 100 if reciente and anterior else None

        # Cobertura: semanas-técnico trabajadas que tuvieron al menos un control
        trabajadas, controladas = set(), set()
        for tid, f in Jornada.objects.filter(tecnico_id__in=ids, en_calle=True, fecha__range=(desde, hasta)).values_list(
                "tecnico_id", "fecha"):
            trabajadas.add((tid, f.isocalendar()[:2]))
        for tid, f in InformeControl.objects.filter(tecnico_id__in=ids, fecha__range=(desde, hasta)).values_list(
                "tecnico_id", "fecha"):
            controladas.add((tid, f.isocalendar()[:2]))
        x["cobertura_control"] = _pct(len(trabajadas & controladas), len(trabajadas))

        desvios = list(InformeControl.objects.filter(supervisor=s, desvio_detectado=True, fecha__range=(desde, hasta))
                       .prefetch_related("acciones"))
        rapidos = sum(1 for i in desvios if any((a.fecha - i.fecha).days <= 2 for a in i.acciones.all()))
        x["respuesta_desvios"] = _pct(rapidos, len(desvios)) if len(desvios) >= 3 else None

        # Efectividad: acciones de hace 30-60 días; ¿el técnico volvió a tener un desvío en los 30 días siguientes?
        acciones = AccionCorrectiva.objects.filter(tecnico_id__in=ids, fecha__range=(hasta - timedelta(days=60),
                                                                                    hasta - timedelta(days=30)))
        total = sin_repetir = 0
        for a in acciones:
            total += 1
            repite = InformeControl.objects.filter(tecnico_id=a.tecnico_id, desvio_detectado=True,
                                                   fecha__gt=a.fecha, fecha__lte=a.fecha + timedelta(days=30)).exists()
            sin_repetir += not repite
        x["efectividad_correccion"] = _pct(sin_repetir, total) if total >= 3 else None

        ev = evs.get(s.id)
        notas = [n for n in ((ev.nota_encuesta, ev.nota_semanal) if ev else ()) if n]
        x["clima_equipo"] = (mean(notas) - 1) / 4 * 100 if notas else None
        pres = [asis[i].presentismo for i in ids if i in asis and asis[i].presentismo is not None]
        x["presentismo_equipo"] = mean(pres) * 100 if pres else None
        esperados = sum(asis[i].esperados for i in ids if i in asis)
        injust = sum(asis[i].injustificadas for i in ids if i in asis)
        x["faltas_sin_aviso"] = injust / esperados * 100 if esperados else None
        jornadas = Jornada.objects.filter(tecnico_id__in=ids, en_calle=True, fecha__range=(desde, hasta)).count()
        sin = Siniestro.objects.filter(tecnico_id__in=ids, fecha__range=(desde, hasta)).count()
        x["seguridad_equipo"] = sin / jornadas * 1000 if jornadas else None
        x["objetivos"] = ev.cumplimiento_tareas * 100 if ev and ev.cumplimiento_tareas is not None else None
        demoras = [(n.resuelta - n.creada).total_seconds() / 3600 for n in Novedad.objects.filter(
            persona_id__in=ids, resuelta__isnull=False, creada__date__range=(desde, hasta))]
        demoras += [(p.resuelto - p.creado).total_seconds() / 3600 for p in PedidoMaterial.objects.filter(
            tecnico_id__in=ids, resuelto__isnull=False, creado__date__range=(desde, hasta))]
        x["tiempo_respuesta"] = median(demoras) if demoras else None
        n, ok = puntual_sup.get(s.id, (0, 0))
        x["puntualidad_propia"] = _pct(ok, n)
        res.append(Tablero(s, [Medicion(i, x.get(i.codigo)) for i in indicadores]))
    return sorted(res, key=lambda tb: -(tb.indice or -1))


def referencia_equipo(tableros: list[Tablero]) -> dict:
    """Mediana de cada indicador en el grupo (para comparar a cada persona)."""
    vals = defaultdict(list)
    for tb in tableros:
        for m in tb.mediciones:
            if m.valor is not None:
                vals[m.indicador.codigo].append(m.valor)
    return {k: median(v) for k, v in vals.items()}
