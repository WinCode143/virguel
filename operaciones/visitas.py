"""Operaciones explícitas sobre las visitas (intentos) de una orden.

* crear_visita: registra lo que pasó en un cierre (quién, bajo qué supervisor, resultado, tiempos).
* rectificar_visita: corrige una visita registrada dejando antes/después, motivo y autor.
"""
from django.db import transaction
from django.db.models import Max, Q

from .models import Intento, MiembroCuadrilla, OrdenTrabajo, ParticipacionVisita, RectificacionVisita

RESULTADOS = set(Intento.Resultado.values)
RECTIFICABLES = {"resultado", "motivo_no_resuelto", "tecnico", "minutos_reales", "fecha"}


def datos_de_cierre(orden: OrdenTrabajo) -> dict:
    tecnico = orden.tecnico
    return {"tecnico": tecnico, "supervisor_id": tecnico.supervisor_id if tecnico else None,
            "fecha": orden.fecha_ejecucion, "resultado": orden.estado,
            "motivo_no_resuelto": "" if orden.estado == "completada" else orden.motivo_no_resuelto,
            "minutos_reales": orden.minutos_reales, "inicio_trabajo": orden.inicio_trabajo,
            "fin_trabajo": orden.fin_trabajo, "series_instaladas": orden.series_instaladas,
            "series_retiradas": orden.series_retiradas, "foto": orden.foto_trabajo.name or "",
            "firma": orden.firma.name or "", "lat": orden.lat_cierre, "lng": orden.lng_cierre,
            "conforme": " ".join(x for x in (orden.conforme_nombre, orden.conforme_apellido,
                                             f"DNI {orden.conforme_dni}" if orden.conforme_dni else "") if x)[:200]}


@transaction.atomic
def crear_visita(orden: OrdenTrabajo, ayudantes=()) -> Intento:
    """Registra la visita con su ejecutor y, si trabaja en cuadrilla, sus compañeros de ese día
    (más los ayudantes indicados). La orden no se duplica: una visita, varias participaciones."""
    numero = (orden.intentos.select_for_update().aggregate(n=Max("numero"))["n"] or 0) + 1
    it = Intento.objects.create(orden=orden, numero=numero, **datos_de_cierre(orden))
    registrar_participantes(it, ayudantes)
    return it


def registrar_participantes(it: Intento, ayudantes=()):
    if not it.tecnico_id:
        return
    ParticipacionVisita.objects.get_or_create(intento=it, persona_id=it.tecnico_id,
                                              defaults={"funcion": "ejecutor", "minutos": it.minutos_reales})
    companeros = set(a.pk if hasattr(a, "pk") else a for a in ayudantes)
    for m in MiembroCuadrilla.objects.filter(persona_id=it.tecnico_id, desde__lte=it.fecha).filter(
            Q(hasta__isnull=True) | Q(hasta__gte=it.fecha)).select_related("cuadrilla"):
        companeros |= set(m.cuadrilla.miembros_en(it.fecha).values_list("persona_id", flat=True))
    companeros.discard(it.tecnico_id)
    for pid in companeros:
        ParticipacionVisita.objects.get_or_create(intento=it, persona_id=pid,
                                                  defaults={"funcion": "ayudante", "minutos": it.minutos_reales})


def _mostrar(v):
    if v is None:
        return ""
    return str(getattr(v, "legajo", None) or v)


@transaction.atomic
def rectificar_visita(intento: Intento, cambios: dict, motivo: str, autor=None, usuario=None) -> list:
    """Aplica cambios a una visita registrada y guarda cada uno como rectificación auditada."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Indicar el motivo de la rectificación.")
    registros = []
    for campo, nuevo in cambios.items():
        if campo not in RECTIFICABLES:
            raise ValueError(f"No se puede rectificar '{campo}'.")
        actual = getattr(intento, campo)
        if actual == nuevo:
            continue
        registros.append(RectificacionVisita(intento=intento, campo=campo, antes=_mostrar(actual)[:200],
                                             despues=_mostrar(nuevo)[:200], motivo=motivo[:200], autor=autor,
                                             usuario=usuario.get_username() if usuario else ""))
        setattr(intento, campo, nuevo)
        if campo == "tecnico":
            intento.supervisor_id = nuevo.supervisor_id if nuevo else None
    if registros:
        if intento.resultado == "completada":
            intento.motivo_no_resuelto = ""
        intento.save()
        RectificacionVisita.objects.bulk_create(registros)
    return registros
