"""Partes a cargo de cada técnico (stock en la camioneta).

Flujo:  depósito --entrega--> técnico --consumo en orden--> cliente
                                    \\--devolución--> depósito
"""
from collections import defaultdict, deque
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.models import Parametros

from .models import LoteIngreso, MovimientoStockTecnico, RecetaMaterial, Salida
from .services import StockInsuficiente, registrar_salida

T = MovimientoStockTecnico.Tipo


def saldos(tecnico) -> dict:
    """{material: cantidad} de lo que tiene el técnico (sólo saldos distintos de cero)."""
    filas = (MovimientoStockTecnico.objects.filter(tecnico=tecnico).values("material")
             .annotate(t=Sum("cantidad")))
    from .models import Material
    mats = Material.objects.in_bulk([f["material"] for f in filas])
    return {mats[f["material"]]: f["t"] for f in filas if f["t"]}


def saldo(tecnico, material) -> Decimal:
    return (MovimientoStockTecnico.objects.filter(tecnico=tecnico, material=material)
            .aggregate(t=Sum("cantidad"))["t"] or Decimal("0"))


def total_en_tecnicos() -> dict:
    """{material_id: cantidad} en manos de todos los técnicos."""
    return {r["material"]: r["t"] for r in MovimientoStockTecnico.objects.values("material")
            .annotate(t=Sum("cantidad")) if r["t"]}


@transaction.atomic
def entregar(tecnico, material, cantidad, fecha: date | None = None, pedido=None, permitir_negativo=False):
    """El depósito entrega partes al técnico: salen de los lotes (FIFO) y pasan a su stock."""
    fecha = fecha or timezone.localdate()
    registrar_salida(Salida(material=material, cantidad=cantidad, fecha=fecha, tecnico=tecnico,
                            motivo=Salida.Motivo.ENTREGA, observaciones=f"Pedido {pedido.id}" if pedido else ""),
                     permitir_negativo=permitir_negativo)
    return MovimientoStockTecnico.objects.create(tecnico=tecnico, material=material, fecha=fecha, tipo=T.ENTREGA,
                                                 cantidad=Decimal(cantidad), pedido=pedido)


@transaction.atomic
def consumir(tecnico, orden, material, cantidad, fecha: date | None = None) -> bool:
    """Material usado en una orden: se descuenta del stock del técnico.

    Devuelve False si el técnico no tenía suficiente (queda saldo negativo y se avisa:
    significa que usó partes que no figuraban a su cargo)."""
    fecha = fecha or timezone.localdate()
    cantidad = Decimal(cantidad)
    alcanzaba = saldo(tecnico, material) >= cantidad
    MovimientoStockTecnico.objects.create(tecnico=tecnico, material=material, fecha=fecha, tipo=T.CONSUMO,
                                          cantidad=-cantidad, orden=orden)
    # Registro del consumo para los indicadores (no toca los lotes del depósito: ya salieron en la entrega)
    Salida.objects.create(material=material, fecha=fecha, cantidad=cantidad, tecnico=tecnico, orden=orden,
                          motivo=Salida.Motivo.CONSUMO, costo_total=cantidad * material.costo_unitario,
                          observaciones="Del stock del técnico")
    return alcanzaba


@transaction.atomic
def devolver(tecnico, material, cantidad, fecha: date | None = None, observaciones=""):
    """El técnico devuelve partes al depósito: vuelven como un lote nuevo."""
    fecha = fecha or timezone.localdate()
    cantidad = Decimal(cantidad)
    if saldo(tecnico, material) < cantidad:
        raise StockInsuficiente(f"{tecnico} no tiene {cantidad} {material.unidad} de {material.nombre}")
    MovimientoStockTecnico.objects.create(tecnico=tecnico, material=material, fecha=fecha, tipo=T.DEVOLUCION,
                                          cantidad=-cantidad, observaciones=observaciones)
    LoteIngreso.objects.create(material=material, fecha=fecha, cantidad=cantidad,
                               costo_unitario=material.costo_unitario, proveedor=f"Devolución {tecnico.legajo}")


def partes_paradas(tecnicos=None, hoy: date | None = None, dias: int | None = None):
    """Partes en manos de técnicos hace más de N días sin usarse (FIFO sobre sus movimientos)."""
    hoy = hoy or timezone.localdate()
    dias = dias or Parametros.actual().dias_max_stock
    qs = MovimientoStockTecnico.objects.select_related("material", "tecnico").order_by("fecha", "id")
    if tecnicos is not None:
        qs = qs.filter(tecnico__in=tecnicos)
    colas = defaultdict(deque)  # (tecnico, material) -> [[fecha, cantidad]]
    for m in qs:
        cola = colas[(m.tecnico, m.material)]
        if m.cantidad > 0:
            cola.append([m.fecha, m.cantidad])
        else:
            resto = -m.cantidad
            while resto > 0 and cola:
                tomado = min(cola[0][1], resto)
                cola[0][1] -= tomado
                resto -= tomado
                if cola[0][1] <= 0:
                    cola.popleft()
    filas = []
    for (tec, mat), cola in colas.items():
        viejas = [(f, c) for f, c in cola if (hoy - f).days >= dias]
        if viejas:
            cant = sum(c for _, c in viejas)
            filas.append({"tecnico": tec, "material": mat, "cantidad": cant, "desde": viejas[0][0],
                          "dias": (hoy - viejas[0][0]).days, "valor": cant * mat.costo_unitario})
    return sorted(filas, key=lambda f: -f["dias"])


def faltante_para_ordenes(tecnico, hasta: date | None = None):
    """Lo que el técnico necesita para sus órdenes pendientes, menos lo que ya tiene."""
    from operaciones.models import OrdenTrabajo
    hasta = hasta or timezone.localdate() + timedelta(days=2)
    pendientes = OrdenTrabajo.objects.filter(tecnico=tecnico, estado__in=["asignada", "pendiente"],
                                             fecha_programada__lte=hasta)
    necesidad = defaultdict(Decimal)
    recetas = defaultdict(list)
    for r in RecetaMaterial.objects.select_related("material"):
        recetas[r.tipo_tarea_id].append(r)
    for o in pendientes:
        for r in recetas[o.tipo_id]:
            necesidad[r.material] += r.cantidad
    tengo = saldos(tecnico)
    filas = []
    for m, q in sorted(necesidad.items(), key=lambda kv: kv[0].nombre):
        q = q.quantize(Decimal("1")) if q >= 1 else q
        falta = max(Decimal("0"), q - tengo.get(m, Decimal("0")))
        filas.append({"material": m, "necesito": q, "tengo": tengo.get(m, Decimal("0")), "falta": falta})
    return filas, pendientes.count()
