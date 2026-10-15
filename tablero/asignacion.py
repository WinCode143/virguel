"""Asignación automática de órdenes pendientes según la capacidad real de cada técnico.

Reglas:
  * Capacidad del técnico para el día = su promedio de OT completadas por día en calle
    (últimos 30 días), redondeado, con mínimo 2 y tope = clientes por técnico/día.
    Si no tiene historial (ingresante), se usa la mitad del tope.
  * Se descuentan las órdenes que ya tiene asignadas para ese día.
  * Prioridad: retrabajos primero, después las más atrasadas.
  * Primero se asigna dentro de la misma zona; si en una zona sobran órdenes y en otra
    sobra capacidad, se completa con técnicos de otras zonas.
  * Técnicos con ausencia ya cargada para ese día no reciben órdenes.

Agenda ejecutable (contraste B04, B05, B17, H09):
  * cada técnico tiene minutos útiles en la jornada; cada orden ocupa su tiempo estándar + traslado
    promedio. Una tarea que llena la jornada no admite otra. El cupo de órdenes por día (su rendimiento
    histórico) se mantiene como tope adicional: rige el que se agote primero;
  * material: la orden necesita lo conocido de su receta disponible en la fecha (su reserva, el stock
    del técnico o el depósito sin comprometer + compras que llegan a tiempo); si falta, no se asigna y
    se dice qué falta. El coordinador puede asignarla igual con motivo (excepción anotada en la orden);
  * disponibilidad unificada por fecha: licencia/novedad aprobada o jornada sin salir → no disponible;
    novedad pendiente de aprobar → pendiente (no se asigna automáticamente); vehículo asignado en
    taller o fuera de servicio → no disponible;
  * competencias: si el tipo de tarea exige una competencia que el técnico no tiene habilitada,
    no se le asigna (o queda como "requiere tutela" si la tarea lo admite);
  * cada orden que no se pudo asignar indica la causa.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from core.models import Parametros, Persona
from core.notificaciones import notificar
from core.roles import GERENCIA, SUPERVISOR, persona_de, requiere_rol, rol_de
from operaciones.models import Jornada, OrdenTrabajo


@dataclass
class Cupo:
    tecnico: Persona
    capacidad: int
    ya_asignadas: int
    nuevas: list = field(default_factory=list)
    minutos_jornada: int = 480
    minutos_ocupados: int = 0

    @property
    def libre(self):
        return self.capacidad - self.ya_asignadas - len(self.nuevas)

    @property
    def minutos_libres(self):
        return self.minutos_jornada - self.minutos_ocupados

    def entra(self, minutos: int) -> bool:
        return self.libre > 0 and minutos <= self.minutos_libres


def minutos_orden(orden, p=None) -> int:
    p = p or Parametros.actual()
    return (orden.tipo.minutos_estandar or 60) + p.minutos_traslado_promedio


def disponibilidad(tecnicos, fecha: date) -> dict:
    """{tecnico_id: (estado, causa)} con estado "disponible" | "no_disponible" | "pendiente"."""
    from personal.models import Novedad
    res = {t.id: ("disponible", "") for t in tecnicos}
    for tid in Jornada.objects.filter(fecha=fecha, en_calle=False, tecnico__in=tecnicos).values_list("tecnico_id",
                                                                                                       flat=True):
        res[tid] = ("no_disponible", "jornada sin salir a la calle")
    for n in Novedad.objects.filter(persona__in=tecnicos, desde__lte=fecha, hasta__gte=fecha).exclude(
            estado=Novedad.Estado.RECHAZADA):
        if n.estado == Novedad.Estado.APROBADA:
            res[n.persona_id] = ("no_disponible", n.get_tipo_display().lower())
        elif res[n.persona_id][0] == "disponible":
            res[n.persona_id] = ("pendiente", f"{n.get_tipo_display().lower()} pendiente de aprobar")
    from flota.models import Vehiculo
    for v in Vehiculo.objects.filter(asignado_a__in=tecnicos).exclude(estado=Vehiculo.Estado.OPERATIVO):
        if res[v.asignado_a_id][0] == "disponible":
            res[v.asignado_a_id] = ("no_disponible", f"vehículo {v.patente} {v.get_estado_display().lower()}")
    return res


def capacidad_tecnicos(tecnicos, fecha: date):
    p = Parametros.actual()
    tope = int(p.clientes_por_tecnico_dia)
    desde = fecha - timedelta(days=30)
    dias = dict(Jornada.objects.filter(tecnico__in=tecnicos, en_calle=True, fecha__range=(desde, fecha - timedelta(days=1)))
                .values_list("tecnico").annotate(n=Count("id")))
    hechas = dict(OrdenTrabajo.objects.filter(tecnico__in=tecnicos, estado="completada",
                                              fecha_ejecucion__range=(desde, fecha - timedelta(days=1)))
                  .values_list("tecnico").annotate(n=Count("id")))
    res = {}
    for t in tecnicos:
        if dias.get(t.id, 0) >= 5:
            res[t.id] = max(2, min(tope, round(hechas.get(t.id, 0) / dias[t.id])))
        else:
            res[t.id] = max(2, tope // 2)
    return res


class Suministro:
    """Material disponible para la fecha, para decidir si una orden es ejecutable (contraste B04/B05/H09).

    Cubre una orden, en este orden: lo reservado para ella, el stock a cargo del técnico candidato y el
    depósito sin comprometer más las compras que llegan ese día o antes. Sólo cuenta lo conocido de la
    receta (lo estimado por condición desconocida no bloquea). Lo que toma una orden ya no está para otra."""

    def __init__(self, fecha):
        from inventario.models import CompraEnCamino, LoteIngreso, MovimientoStockTecnico
        from inventario.reservas import comprometido_por_material, comprometido_por_orden
        stock = dict(LoteIngreso.objects.values_list("material").annotate(t=Sum("cantidad_disponible")))
        comp = comprometido_por_material()
        self.pool = defaultdict(Decimal)
        for mid, q in stock.items():
            self.pool[mid] += max(Decimal("0"), (q or 0) - (comp.get(mid) or 0))
        for mid, q in (CompraEnCamino.objects.filter(recibida=False, fecha_esperada__lte=fecha)
                       .values_list("material_id").annotate(t=Sum("cantidad"))):
            self.pool[mid] += q or 0
        self.reservado = comprometido_por_orden()
        self.tecnico = defaultdict(Decimal)
        for tid, mid, q in (MovimientoStockTecnico.objects.values_list("tecnico_id", "material_id")
                            .annotate(t=Sum("cantidad"))):
            if q and q > 0:
                self.tecnico[(tid, mid)] = q
        self._cache = {}

    def necesidad(self, o):
        if o.pk not in self._cache:
            from inventario.services import necesidad_orden
            self._cache[o.pk] = [(n["material"], n["cantidad"]) for n in necesidad_orden(o) if not n["estimado"]]
        return self._cache[o.pk]

    def faltante(self, o, tecnico_id):
        """[(material, cantidad que falta)] si se asignara a ese técnico (sin descontar nada)."""
        res = []
        for m, q in self.necesidad(o):
            q -= min(q, self.reservado.get((o.pk, m.id), Decimal("0")))
            q -= min(q, self.tecnico.get((tecnico_id, m.id), Decimal("0")))
            q -= min(q, self.pool.get(m.id, Decimal("0")))
            if q > 0:
                res.append((m, q))
        return res

    def tomar(self, o, tecnico_id):
        for m, q in self.necesidad(o):
            q -= min(q, self.reservado.get((o.pk, m.id), Decimal("0")))
            t = min(q, self.tecnico.get((tecnico_id, m.id), Decimal("0")))
            self.tecnico[(tecnico_id, m.id)] -= t
            q -= t
            self.pool[m.id] -= min(q, self.pool.get(m.id, Decimal("0")))


def proponer(fecha: date, tecnicos_qs, excepciones=()):
    """excepciones: ids de órdenes que el coordinador decide asignar aunque falte material (con motivo):
    no se presentan como disponibles, quedan marcadas `o.sin_material`."""
    from capacitacion.models import habilitacion
    p = Parametros.actual()
    todos = list(tecnicos_qs.select_related("zona"))
    disp = disponibilidad(todos, fecha)
    bloqueados = [(t, disp[t.id]) for t in todos if disp[t.id][0] != "disponible"]
    tecnicos = [t for t in todos if disp[t.id][0] == "disponible"]
    cap = capacidad_tecnicos(tecnicos, fecha)
    ya = dict(OrdenTrabajo.objects.filter(tecnico__in=tecnicos, fecha_programada=fecha,
                                          estado__in=["asignada", "pendiente"])
              .values_list("tecnico").annotate(n=Count("id")))
    minutos_ya = defaultdict(int)
    for o in OrdenTrabajo.objects.filter(tecnico__in=tecnicos, fecha_programada=fecha,
                                         estado__in=["asignada", "pendiente"]).select_related("tipo"):
        minutos_ya[o.tecnico_id] += minutos_orden(o, p)
    jornada = int((float(p.horas_jornada) - 1) * 60)  # la jornada incluye el almuerzo
    cupos = {t.id: Cupo(t, cap[t.id], ya.get(t.id, 0), minutos_jornada=jornada, minutos_ocupados=minutos_ya[t.id])
             for t in tecnicos}
    habil = {}

    from herramientas.models import epp_faltante
    epp = {}

    sumin = Suministro(fecha)
    excepciones = set(excepciones)

    def puede(c, o):
        k = (c.tecnico.id, o.tipo_id)
        if k not in habil:
            habil[k] = habilitacion(c.tecnico.id, o.tipo_id, fecha)
            epp[k] = epp_faltante(c.tecnico.id, o.tipo_id, fecha)
        return habil[k]["estado"] in ("habilitado", "sin_requisitos") and not epp[k]

    def con_material(c, o):
        return o.pk in excepciones or not sumin.faltante(o, c.tecnico.id)
    por_zona = defaultdict(list)
    for c in cupos.values():
        por_zona[c.tecnico.zona_id].append(c)

    pendientes = list(OrdenTrabajo.objects.filter(
        Q(tecnico__isnull=True) | Q(tecnico__activo=False), fecha_programada__lte=fecha,
        estado__in=["pendiente", "reprogramada"]).select_related("tipo", "zona", "cliente")
        .order_by("-es_retrabajo", "fecha_programada", "id"))

    def mejor(candidatos, o):
        minutos = minutos_orden(o, p)
        libres = [c for c in candidatos if c.entra(minutos) and puede(c, o) and con_material(c, o)]
        # el que tiene más lugar relativo a su capacidad (reparte parejo)
        return max(libres, key=lambda c: (c.libre / c.capacidad, c.minutos_libres), default=None)

    def asignar(c, o):
        o.sin_material = [(m, q) for m, q in sumin.faltante(o, c.tecnico.id)] if o.pk in excepciones else []
        sumin.tomar(o, c.tecnico.id)
        c.nuevas.append(o)
        c.minutos_ocupados += minutos_orden(o, p)

    sin_lugar = []
    for o in pendientes:
        c = mejor(por_zona.get(o.zona_id, []), o)
        if c is None:
            sin_lugar.append(o)
            continue
        asignar(c, o)
    otra_zona = []
    for o in sin_lugar:
        c = mejor(cupos.values(), o)
        if c is None:
            continue
        asignar(c, o)
        otra_zona.append(o.id)
    sin_asignar = []
    for o in sin_lugar:
        if o.id in otra_zona:
            continue
        aptos = [c for c in cupos.values() if puede(c, o)]
        if aptos and all(sumin.faltante(o, c.tecnico.id) for c in aptos) and o.pk not in excepciones:
            falta = min((sumin.faltante(o, c.tecnico.id) for c in aptos), key=len)
            o.causa = ("falta material en la fecha: " + ", ".join(f"{m.nombre} ({q:g})" for m, q in falta)
                       + " · reponer, reservar o reprogramar; o asignar con excepción")
            o.falta_material = True
        elif not aptos:
            faltas = sorted({x for (tid, tipo), v in epp.items() if tipo == o.tipo_id for x in v})
            o.causa = ("bloqueo de suministro: falta entregar " + ", ".join(faltas)) if faltas and all(
                habil.get((c.tecnico.id, o.tipo_id), {}).get("estado") in ("habilitado", "sin_requisitos")
                for c in cupos.values()) else "ningún técnico disponible tiene la competencia o el EPP requerido"
        elif not any(minutos_orden(o, p) <= c.minutos_jornada for c in cupos.values()):
            o.causa = "la tarea no entra en una jornada"
        else:
            o.causa = "sin capacidad (cupo o minutos) en la fecha"
        sin_asignar.append(o)
    return {"cupos": sorted(cupos.values(), key=lambda c: (c.tecnico.zona.nombre if c.tecnico.zona else "", c.tecnico.apellido)),
            "pendientes": len(pendientes), "sin_asignar": sin_asignar, "otra_zona": set(otra_zona),
            "ausentes": len(bloqueados), "bloqueados": bloqueados}


def _tecnicos(request):
    qs = Persona.objects.filter(rol=Persona.Rol.TECNICO, activo=True)
    if rol_de(request.user) == SUPERVISOR:
        qs = qs.filter(supervisor=persona_de(request.user))
    return qs


@requiere_rol(GERENCIA, SUPERVISOR)
def vista(request):
    try:
        fecha = date.fromisoformat(request.POST.get("fecha") or request.GET.get("fecha", ""))
    except ValueError:
        fecha = timezone.localdate() + timedelta(days=1)
    # Excepción del coordinador: asignar aunque falte material, sólo con motivo (queda anotado en la orden)
    motivo = (request.POST.get("motivo_excepcion") or request.GET.get("motivo_excepcion") or "").strip()
    excepciones = set()
    if motivo:
        for v in request.POST.getlist("excepcion") or request.GET.getlist("excepcion"):
            if v.isdigit():
                excepciones.add(int(v))
    propuesta = proponer(fecha, _tecnicos(request), excepciones)
    if request.method == "POST":
        from operaciones.models import NotaOrden
        yo = persona_de(request.user)
        with transaction.atomic():
            n = 0
            for c in propuesta["cupos"]:
                for o in c.nuevas:
                    o.tecnico, o.estado, o.fecha_programada = c.tecnico, OrdenTrabajo.Estado.ASIGNADA, fecha
                    o._sin_notificar = True
                    o.save(update_fields=["tecnico", "estado", "fecha_programada"])
                    if getattr(o, "sin_material", None):
                        NotaOrden.objects.create(orden=o, autor=yo, texto=(
                            "Asignada con EXCEPCIÓN: material no confirmado ("
                            + ", ".join(f"{m.nombre} {q:g}" for m, q in o.sin_material) + f"). Motivo: {motivo}")[:1000])
                    n += 1
                if c.nuevas:
                    notificar(c.tecnico, f"Tenés {len(c.nuevas)} orden{'es' if len(c.nuevas) > 1 else ''} nueva"
                              f"{'s' if len(c.nuevas) > 1 else ''} para el {fecha:%d/%m}", "", "/app/")
        messages.success(request, f"{n} órdenes asignadas para el {fecha:%d/%m/%Y}.")
        return redirect(f"{request.path}?fecha={fecha.isoformat()}")
    total_nuevas = sum(len(c.nuevas) for c in propuesta["cupos"])
    return render(request, "tablero/asignacion.html", {"fecha": fecha, "total_nuevas": total_nuevas,
                                                       "excepciones": excepciones, "motivo": motivo, **propuesta})
