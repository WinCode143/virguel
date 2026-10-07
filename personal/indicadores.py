"""Indicadores de control de personal.

Por persona y período:
  * días esperados   = días laborables según su horario (lun–vie, + sábado si corresponde),
                       sin feriados, desde su ingreso y hasta su egreso.
  * presentes        = días con fichada o con jornada de trabajo registrada (técnico en calle).
  * Los días anteriores al inicio del control (primera fichada o jornada cargada en el sistema)
    no se cuentan, y el día de hoy sólo cuenta si la persona ya se presentó.
  * justificadas     = días esperados sin fichada cubiertos por una novedad justificada
                       (enfermedad, ART, vacaciones, licencia, franco).
  * injustificadas   = días esperados sin fichada y sin novedad justificada
                       (incluye novedades "ausencia injustificada" y "suspensión").
  * tardanzas        = días con entrada después del horario + tolerancia.
  * presentismo      = presentes / (esperados − vacaciones y francos).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from core.models import Persona
from operaciones.models import Jornada

from .models import Asistencia, DocumentoPersonal, Feriado, Novedad, TipoDocumento

NO_CUENTAN_PARA_PRESENTISMO = {"vacaciones", "franco"}


def inicio_control() -> date | None:
    """Desde cuándo el sistema registra asistencia (antes no se puede hablar de faltas)."""
    fechas = [f for f in (Asistencia.objects.order_by("fecha").values_list("fecha", flat=True).first(),
                          Jornada.objects.order_by("fecha").values_list("fecha", flat=True).first()) if f]
    return min(fechas) if fechas else None


def es_laborable(persona: Persona, d: date, feriados: set) -> bool:
    if d in feriados or d.weekday() == 6:
        return False
    if d.weekday() == 5 and not persona.trabaja_sabados:
        return False
    if d < persona.fecha_ingreso or (persona.fecha_egreso and d > persona.fecha_egreso):
        return False
    return True


@dataclass
class ResumenPersona:
    persona: Persona
    esperados: int = 0
    presentes: int = 0
    justificadas: int = 0
    injustificadas: int = 0
    no_computables: int = 0  # vacaciones / francos
    tardanzas: int = 0
    minutos_tarde: int = 0
    horas: Decimal = Decimal("0")
    horas_extra: Decimal = Decimal("0")
    por_tipo: dict = field(default_factory=lambda: defaultdict(int))
    sin_salida: int = 0

    @property
    def presentismo(self) -> float | None:
        base = self.esperados - self.no_computables
        return min(1.0, self.presentes / base) if base > 0 else None

    @property
    def ausentismo(self) -> float | None:
        base = self.esperados - self.no_computables
        return (self.justificadas + self.injustificadas - self.no_computables) / base if base > 0 else None

    @property
    def estado(self) -> str:
        p = self.presentismo
        if p is None:
            return "info"
        if self.injustificadas >= 3 or p < 0.85:
            return "critico"
        if self.injustificadas >= 1 or p < 0.93 or self.tardanzas >= 5:
            return "aviso"
        return "ok"


def resumen(desde: date, hasta: date, personas=None) -> list[ResumenPersona]:
    if personas is None:
        personas = Persona.objects.filter(Q(activo=True) | Q(fecha_egreso__gte=desde)).exclude(
            rol=Persona.Rol.GERENCIA)
    personas = list(personas)
    ids = [p.id for p in personas]
    feriados = set(Feriado.objects.filter(fecha__range=(desde, hasta)).values_list("fecha", flat=True))
    res = {p.id: ResumenPersona(p) for p in personas}

    fichadas = defaultdict(set)
    for a in Asistencia.objects.filter(persona_id__in=ids, fecha__range=(desde, hasta)).only(
            "persona_id", "fecha", "minutos_tarde", "horas_trabajadas", "horas_extra", "salida"):
        r = res[a.persona_id]
        fichadas[a.persona_id].add(a.fecha)
        r.presentes += 1
        if a.minutos_tarde:
            r.tardanzas += 1
            r.minutos_tarde += a.minutos_tarde
        r.horas += a.horas_trabajadas
        r.horas_extra += a.horas_extra
        if a.salida is None and a.fecha < timezone.localdate():
            r.sin_salida += 1

    # técnicos con jornada en calle cuentan como presentes aunque no hayan fichado
    for pid, f in Jornada.objects.filter(tecnico_id__in=ids, fecha__range=(desde, hasta), en_calle=True).values_list(
            "tecnico_id", "fecha"):
        if f not in fichadas[pid]:
            fichadas[pid].add(f)
            res[pid].presentes += 1
    inicio = inicio_control()
    hoy = timezone.localdate()

    cubiertos = defaultdict(dict)  # persona -> fecha -> tipo
    for n in Novedad.objects.filter(persona_id__in=ids, desde__lte=hasta, hasta__gte=desde).exclude(
            estado=Novedad.Estado.RECHAZADA):
        d = max(n.desde, desde)
        while d <= min(n.hasta, hasta):
            cubiertos[n.persona_id][d] = n.tipo
            d += timedelta(days=1)

    for p in personas:
        r = res[p.id]
        d = max(desde, inicio) if inicio else hasta + timedelta(days=1)
        while d <= hasta:
            if es_laborable(p, d, feriados) and not (d >= hoy and d not in fichadas[p.id]):
                r.esperados += 1
                if d not in fichadas[p.id]:
                    tipo = cubiertos[p.id].get(d)
                    if tipo in Novedad.JUSTIFICADAS:
                        r.justificadas += 1
                        r.por_tipo[tipo] += 1
                        if tipo in NO_CUENTAN_PARA_PRESENTISMO:
                            r.no_computables += 1
                    else:
                        r.injustificadas += 1
                        r.por_tipo[tipo or "sin_aviso"] += 1
            d += timedelta(days=1)
    return sorted(res.values(), key=lambda r: (r.presentismo if r.presentismo is not None else 2,
                                                -r.injustificadas))


@dataclass
class EstadoHoy:
    persona: Persona
    asistencia: Asistencia | None
    novedad: Novedad | None
    laborable: bool

    @property
    def situacion(self) -> tuple[str, str]:
        """(clase de estado, texto) para mostrar."""
        if self.asistencia:
            if self.asistencia.salida:
                return "ok", "Trabajó" + (f" (tarde {self.asistencia.minutos_tarde}′)" if self.asistencia.minutos_tarde else "")
            if self.asistencia.minutos_tarde:
                return "aviso", f"Presente, llegó {self.asistencia.minutos_tarde} min tarde"
            return "ok", "Presente"
        if self.novedad:
            return ("info" if self.novedad.justificada else "critico"), self.novedad.get_tipo_display()
        if not self.laborable:
            return "info", "No laborable"
        return "critico", "Sin fichar y sin aviso"


def estado_del_dia(fecha: date, personas) -> list[EstadoHoy]:
    personas = list(personas)
    feriados = set(Feriado.objects.filter(fecha=fecha).values_list("fecha", flat=True))
    asis = {a.persona_id: a for a in Asistencia.objects.filter(fecha=fecha, persona__in=personas)}
    nov = {}
    for n in Novedad.objects.filter(persona__in=personas, desde__lte=fecha, hasta__gte=fecha).exclude(
            estado=Novedad.Estado.RECHAZADA):
        nov[n.persona_id] = n
    filas = [EstadoHoy(p, asis.get(p.id), nov.get(p.id), es_laborable(p, fecha, feriados)) for p in personas]
    orden = {"critico": 0, "aviso": 1, "ok": 2, "info": 3}
    return sorted(filas, key=lambda f: (orden[f.situacion[0]], f.persona.apellido))


def dotacion_mensual(meses: int = 12, hoy: date | None = None):
    """Altas, bajas, dotación a fin de mes y rotación (bajas / dotación promedio)."""
    hoy = hoy or timezone.localdate()
    filas = []
    inicio = hoy.replace(day=1)
    for i in range(meses - 1, -1, -1):
        m = inicio.month - 1 - i
        ini = date(inicio.year + m // 12, m % 12 + 1, 1)
        fin = (date(ini.year + (ini.month // 12), ini.month % 12 + 1, 1) - timedelta(days=1))
        base = Persona.objects.exclude(rol=Persona.Rol.GERENCIA)
        altas = base.filter(fecha_ingreso__range=(ini, fin)).count()
        bajas = base.filter(fecha_egreso__range=(ini, fin)).count()
        dot = base.filter(fecha_ingreso__lte=fin).filter(Q(fecha_egreso__isnull=True) | Q(fecha_egreso__gt=fin)).count()
        filas.append({"mes": ini, "altas": altas, "bajas": bajas, "dotacion": dot,
                      "rotacion": bajas / dot if dot else 0})
    return filas


def documentos_faltantes_o_vencidos(personas):
    """Documentos obligatorios que faltan, vencieron o están por vencer."""
    personas = list(personas)
    tipos = list(TipoDocumento.objects.filter(Q(obligatorio_tecnicos=True) | Q(obligatorio_supervisores=True)))
    docs = defaultdict(dict)
    for d in DocumentoPersonal.objects.filter(persona__in=personas).select_related("tipo").order_by("vencimiento"):
        docs[d.persona_id][d.tipo_id] = d  # queda el de vencimiento más lejano
    filas = []
    for p in personas:
        for t in tipos:
            if not ((p.rol == "tecnico" and t.obligatorio_tecnicos) or (p.rol == "supervisor" and t.obligatorio_supervisores)):
                continue
            d = docs[p.id].get(t.id)
            if d is None:
                filas.append({"persona": p, "tipo": t, "doc": None, "estado": "critico", "texto": "Falta"})
            elif d.estado != "ok":
                filas.append({"persona": p, "tipo": t, "doc": d, "estado": d.estado,
                              "texto": ("Vencido el " if d.estado == "critico" else "Vence el ") + d.vencimiento.strftime("%d/%m/%Y")})
    return sorted(filas, key=lambda f: (f["estado"] != "critico", f["persona"].apellido))


def ranking_tardanzas(desde: date, hasta: date, personas, n=10):
    return (Asistencia.objects.filter(fecha__range=(desde, hasta), persona__in=personas, minutos_tarde__gt=0)
            .values("persona__id", "persona__apellido", "persona__nombre")
            .annotate(veces=Count("id")).order_by("-veces")[:n])
