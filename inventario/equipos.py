"""Equipos identificables por serie (UnidadEquipo): cada movimiento cambia su única ubicación.

* instalar: del técnico al cliente (deja de ser stock utilizable);
* retirar: del cliente al técnico, "a revisar" (no vuelve a ser utilizable hasta revisarla);
* recibir_en_deposito: el técnico entrega el equipo; sigue "a revisar" hasta la revisión;
* revisar: usado en condiciones (vuelve al suministro) o defectuoso (fuera del suministro).
La propiedad no se presume: una serie desconocida queda con propietario "sin confirmar".
"""
from django.db import transaction
from django.utils import timezone

from .models import MovimientoUnidad, UnidadEquipo

U = UnidadEquipo


@transaction.atomic
def mover(unidad: UnidadEquipo, hacia: str, custodio=None, cliente=None, intento=None, condicion=None,
          motivo="") -> UnidadEquipo:
    unidad = UnidadEquipo.objects.select_for_update().get(pk=unidad.pk)
    desde = unidad.ubicacion
    unidad.ubicacion = hacia
    unidad.custodio = custodio if hacia == U.Ubicacion.TECNICO else None
    unidad.cliente = cliente if hacia == U.Ubicacion.CLIENTE else None
    if condicion:
        unidad.condicion = condicion
    unidad.actualizado = timezone.now()
    unidad.save()
    MovimientoUnidad.objects.create(unidad=unidad, desde=desde, hacia=hacia, custodio=custodio, intento=intento,
                                    condicion=unidad.condicion, motivo=motivo[:200])
    return unidad


def _por_serie(serie: str):
    return UnidadEquipo.objects.filter(numero_serie=serie.strip()).first()


def registrar_cierre(intento, series_instaladas: list, series_retiradas: list) -> list:
    """Actualiza las unidades conocidas de un cierre; devuelve avisos (series desconocidas o inconsistentes)."""
    avisos = []
    orden = intento.orden
    for serie in series_instaladas:
        u = _por_serie(serie)
        if u is None:
            avisos.append(f"Serie instalada {serie} no registrada en equipos (cargarla para su trazabilidad).")
            continue
        if u.ubicacion == U.Ubicacion.CLIENTE:
            avisos.append(f"La serie {serie} ya figuraba instalada en otro cliente: revisar.")
        mover(u, U.Ubicacion.CLIENTE, cliente=orden.cliente, intento=intento, motivo=f"Instalada en {orden.numero}")
    for serie in series_retiradas:
        u = _por_serie(serie)
        if u is None:
            continue  # queda como EquipoRetirado; la unidad se da de alta al recibirla con su material
        mover(u, U.Ubicacion.TECNICO, custodio=intento.tecnico, intento=intento, condicion=U.Condicion.A_REVISAR,
              motivo=f"Retirada en {orden.numero}")
    return avisos


def recibir_en_deposito(serie: str, material=None, recibido_por=None) -> UnidadEquipo | None:
    u = _por_serie(serie)
    if u is None:
        if material is None:
            return None
        u = UnidadEquipo.objects.create(material=material, numero_serie=serie.strip(),
                                        condicion=U.Condicion.A_REVISAR, ubicacion=U.Ubicacion.TECNICO)
    return mover(u, U.Ubicacion.DEPOSITO, condicion=U.Condicion.A_REVISAR,
                 motivo=f"Recibido por {recibido_por}" if recibido_por else "Recibido en depósito")


def revisar(unidad: UnidadEquipo, funciona: bool, motivo="") -> UnidadEquipo:
    return mover(unidad, unidad.ubicacion, custodio=unidad.custodio, cliente=unidad.cliente,
                 condicion=U.Condicion.USADO_OK if funciona else U.Condicion.DEFECTUOSO, motivo=motivo or "Revisión")
