"""Operaciones explícitas sobre las visitas (intentos) de una orden.

* crear_visita: registra lo que pasó en un cierre (quién, bajo qué supervisor, resultado, tiempos).
* rectificar_visita: corrige una visita registrada dejando antes/después, motivo y autor.
"""
from django.db import transaction
from django.db.models import Max

from .models import Intento, OrdenTrabajo, RectificacionVisita

RESULTADOS = set(Intento.Resultado.values)
RECTIFICABLES = {"resultado", "motivo_no_resuelto", "tecnico", "minutos_reales", "fecha"}


def datos_de_cierre(orden: OrdenTrabajo) -> dict:
    tecnico = orden.tecnico
    return {"tecnico": tecnico, "supervisor_id": tecnico.supervisor_id if tecnico else None,
            "fecha": orden.fecha_ejecucion, "resultado": orden.estado,
            "motivo_no_resuelto": "" if orden.estado == "completada" else orden.motivo_no_resuelto,
            "minutos_reales": orden.minutos_reales, "inicio_trabajo": orden.inicio_trabajo,
            "fin_trabajo": orden.fin_trabajo}


@transaction.atomic
def crear_visita(orden: OrdenTrabajo) -> Intento:
    numero = (orden.intentos.select_for_update().aggregate(n=Max("numero"))["n"] or 0) + 1
    return Intento.objects.create(orden=orden, numero=numero, **datos_de_cierre(orden))


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
