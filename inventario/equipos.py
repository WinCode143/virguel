"""Equipos identificables por serie (UnidadEquipo): cada movimiento cambia su única ubicación.

* instalar: del técnico al cliente (deja de ser stock utilizable);
* retirar: del cliente al técnico, "a revisar" (no vuelve a ser utilizable hasta revisarla);
* recibir_en_deposito: el técnico entrega el equipo; sigue "a revisar" hasta la revisión;
* revisar: usado en condiciones (vuelve al suministro) o defectuoso (fuera del suministro).
La propiedad no se presume: una serie desconocida queda con propietario "sin confirmar".

Suministro único: una unidad que cuenta en el stock del depósito (en_stock) y deja de ser utilizable
en el depósito sale de los lotes (baja); una unidad recuperada que se revisa en condiciones entra a
los lotes. Así la previsión, las reservas y las entregas leen las mismas cantidades que las series.
Una serie instalada en un cliente no se instala en otro sin registrar antes su retiro (InstalacionIncompatible).
"""
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import LoteIngreso, MovimientoUnidad, Salida, UnidadEquipo

U = UnidadEquipo
UTILES = (U.Condicion.NUEVO, U.Condicion.USADO_OK)


class InstalacionIncompatible(Exception):
    pass


def _sincronizar_stock(unidad: UnidadEquipo, motivo: str):
    """Alinea los lotes del depósito con la condición de la unidad que está en el depósito."""
    from .services import registrar_salida
    if unidad.ubicacion != U.Ubicacion.DEPOSITO:
        return
    util = unidad.condicion in UTILES
    if unidad.en_stock and not util:
        registrar_salida(Salida(material=unidad.material, cantidad=Decimal(1), motivo=Salida.Motivo.BAJA,
                                observaciones=f"Serie {unidad.numero_serie}: {unidad.get_condicion_display()} "
                                              f"({motivo})"[:200]),
                         permitir_negativo=True, usar_reservado=True)
        unidad.en_stock = False
        UnidadEquipo.objects.filter(pk=unidad.pk).update(en_stock=False)
    elif not unidad.en_stock and util:
        LoteIngreso.objects.create(material=unidad.material, cantidad=1, costo_unitario=unidad.material.costo_unitario,
                                   origen=LoteIngreso.Origen.AJUSTE,
                                   proveedor=f"Equipo recuperado {unidad.numero_serie}"[:120])
        unidad.en_stock = True
        UnidadEquipo.objects.filter(pk=unidad.pk).update(en_stock=True)


@transaction.atomic
def mover(unidad: UnidadEquipo, hacia: str, custodio=None, cliente=None, intento=None, condicion=None,
          motivo="") -> UnidadEquipo:
    unidad = UnidadEquipo.objects.select_for_update().get(pk=unidad.pk)
    desde = unidad.ubicacion
    if desde == U.Ubicacion.DEPOSITO and hacia != U.Ubicacion.DEPOSITO:
        unidad.en_stock = False  # sale del depósito: la salida de los lotes la registra la entrega
    unidad.ubicacion = hacia
    unidad.custodio = custodio if hacia == U.Ubicacion.TECNICO else None
    unidad.cliente = cliente if hacia == U.Ubicacion.CLIENTE else None
    if condicion:
        unidad.condicion = condicion
    unidad.actualizado = timezone.now()
    unidad._motivo = motivo
    unidad.save()  # el modelo sincroniza los lotes del depósito con la condición
    MovimientoUnidad.objects.create(unidad=unidad, desde=desde, hacia=hacia, custodio=custodio, intento=intento,
                                    condicion=unidad.condicion, motivo=motivo[:200])
    return unidad


def _por_serie(serie: str):
    return UnidadEquipo.objects.filter(numero_serie=serie.strip()).first()


def validar_instalacion(serie: str, cliente) -> None:
    """Una serie instalada en otro cliente, dada de baja, devuelta o defectuosa no se instala."""
    u = _por_serie(serie)
    if u is None:
        return
    if u.ubicacion == U.Ubicacion.CLIENTE and u.cliente_id != (cliente.pk if cliente else None):
        raise InstalacionIncompatible(
            f"La serie {serie} figura instalada en el cliente {u.cliente}: registrá su retiro (o la rectificación) "
            f"antes de instalarla en otro cliente.")
    if u.ubicacion == U.Ubicacion.DEVUELTO or u.condicion in (U.Condicion.DEFECTUOSO, U.Condicion.BAJA):
        raise InstalacionIncompatible(f"La serie {serie} está {u.get_condicion_display().lower()} / "
                                      f"{u.get_ubicacion_display().lower()}: no se puede instalar.")


def registrar_cierre(intento, series_instaladas: list, series_retiradas: list) -> list:
    """Actualiza las unidades conocidas de un cierre; devuelve avisos (series desconocidas).
    Una instalación incompatible lanza InstalacionIncompatible antes de mover nada."""
    avisos = []
    orden = intento.orden
    retiradas = {s.strip() for s in series_retiradas}
    for serie in series_instaladas:
        if serie.strip() not in retiradas:
            validar_instalacion(serie, orden.cliente)
    for serie in series_instaladas:
        u = _por_serie(serie)
        if u is None:
            avisos.append(f"Serie instalada {serie} no registrada en equipos (cargarla para su trazabilidad).")
            continue
        if u.ubicacion == U.Ubicacion.CLIENTE and u.cliente_id == orden.cliente_id:
            continue  # ya estaba en este cliente (p. ej. reparación): no hay movimiento
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
        u = UnidadEquipo.objects.create(material=material, numero_serie=serie.strip(), en_stock=False,
                                        condicion=U.Condicion.A_REVISAR, ubicacion=U.Ubicacion.TECNICO)
    return mover(u, U.Ubicacion.DEPOSITO, condicion=U.Condicion.A_REVISAR,
                 motivo=f"Recibido por {recibido_por}" if recibido_por else "Recibido en depósito")


def revisar(unidad: UnidadEquipo, funciona: bool, motivo="") -> UnidadEquipo:
    return mover(unidad, unidad.ubicacion, custodio=unidad.custodio, cliente=unidad.cliente,
                 condicion=U.Condicion.USADO_OK if funciona else U.Condicion.DEFECTUOSO, motivo=motivo or "Revisión")
