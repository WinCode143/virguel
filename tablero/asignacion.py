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
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
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

    @property
    def libre(self):
        return self.capacidad - self.ya_asignadas - len(self.nuevas)


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


def proponer(fecha: date, tecnicos_qs):
    tecnicos = list(tecnicos_qs.select_related("zona"))
    ausentes = set(Jornada.objects.filter(fecha=fecha, en_calle=False).values_list("tecnico_id", flat=True))
    tecnicos = [t for t in tecnicos if t.id not in ausentes]
    cap = capacidad_tecnicos(tecnicos, fecha)
    ya = dict(OrdenTrabajo.objects.filter(tecnico__in=tecnicos, fecha_programada=fecha,
                                          estado__in=["asignada", "pendiente"])
              .values_list("tecnico").annotate(n=Count("id")))
    cupos = {t.id: Cupo(t, cap[t.id], ya.get(t.id, 0)) for t in tecnicos}
    por_zona = defaultdict(list)
    for c in cupos.values():
        por_zona[c.tecnico.zona_id].append(c)

    pendientes = list(OrdenTrabajo.objects.filter(
        Q(tecnico__isnull=True) | Q(tecnico__activo=False), fecha_programada__lte=fecha,
        estado__in=["pendiente", "reprogramada"]).select_related("tipo", "zona", "cliente")
        .order_by("-es_retrabajo", "fecha_programada", "id"))

    def mejor(candidatos):
        libres = [c for c in candidatos if c.libre > 0]
        # el que tiene más lugar relativo a su capacidad (reparte parejo)
        return max(libres, key=lambda c: (c.libre / c.capacidad, c.libre), default=None)

    sin_lugar = []
    for o in pendientes:
        c = mejor(por_zona.get(o.zona_id, []))
        if c is None:
            sin_lugar.append(o)
            continue
        c.nuevas.append(o)
    otra_zona = []
    for o in sin_lugar:
        c = mejor(cupos.values())
        if c is None:
            break
        c.nuevas.append(o)
        otra_zona.append(o.id)
    sin_asignar = [o for o in sin_lugar if o.id not in otra_zona]
    return {"cupos": sorted(cupos.values(), key=lambda c: (c.tecnico.zona.nombre if c.tecnico.zona else "", c.tecnico.apellido)),
            "pendientes": len(pendientes), "sin_asignar": sin_asignar, "otra_zona": set(otra_zona),
            "ausentes": len(ausentes)}


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
    propuesta = proponer(fecha, _tecnicos(request))
    if request.method == "POST":
        with transaction.atomic():
            n = 0
            for c in propuesta["cupos"]:
                for o in c.nuevas:
                    o.tecnico, o.estado, o.fecha_programada = c.tecnico, OrdenTrabajo.Estado.ASIGNADA, fecha
                    o._sin_notificar = True
                    o.save(update_fields=["tecnico", "estado", "fecha_programada"])
                    n += 1
                if c.nuevas:
                    notificar(c.tecnico, f"Tenés {len(c.nuevas)} orden{'es' if len(c.nuevas) > 1 else ''} nueva"
                              f"{'s' if len(c.nuevas) > 1 else ''} para el {fecha:%d/%m}", "", "/app/")
        messages.success(request, f"{n} órdenes asignadas para el {fecha:%d/%m/%Y}.")
        return redirect(f"{request.path}?fecha={fecha.isoformat()}")
    total_nuevas = sum(len(c.nuevas) for c in propuesta["cupos"])
    return render(request, "tablero/asignacion.html", {"fecha": fecha, "total_nuevas": total_nuevas, **propuesta})
