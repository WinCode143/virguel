"""Partes a cargo de cada técnico (stock en la camioneta).

Flujo:  depósito --entrega--> técnico --consumo en orden--> cliente
                                    \\--devolución--> depósito

Las entregas guardan de qué lotes salieron las unidades (ConsumoLote). Una devolución
reingresa esas mismas unidades: con la fecha de ingreso y el costo de su lote de origen,
y sin generar un gasto (no es una compra).
"""
from collections import defaultdict, deque
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.models import Parametros

from .models import ConsumoLote, LoteIngreso, MovimientoStockTecnico, RecetaMaterial, Salida
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
    salida = registrar_salida(Salida(material=material, cantidad=cantidad, fecha=fecha, tecnico=tecnico,
                                     motivo=Salida.Motivo.ENTREGA, observaciones=f"Pedido {pedido.id}" if pedido else ""),
                              permitir_negativo=permitir_negativo)
    if pedido is not None and pedido.orden_id:
        # lo reservado para esa orden ya salió del depósito: la reserva queda consumida (no se descuenta dos veces)
        from .models import ReservaMaterial
        ReservaMaterial.objects.filter(orden_id=pedido.orden_id, material=material, estado="activa").update(
            estado="consumida")
    return MovimientoStockTecnico.objects.create(tecnico=tecnico, material=material, fecha=fecha, tipo=T.ENTREGA,
                                                 cantidad=Decimal(cantidad), pedido=pedido, salida=salida)


@transaction.atomic
def consumir(tecnico, orden, material, cantidad, fecha: date | None = None, intento=None) -> bool:
    """Material usado en una orden: se descuenta del stock del técnico.

    Devuelve False si el técnico no tenía suficiente (queda saldo negativo y se avisa:
    significa que usó partes que no figuraban a su cargo)."""
    fecha = fecha or timezone.localdate()
    cantidad = Decimal(cantidad)
    alcanzaba = saldo(tecnico, material) >= cantidad
    MovimientoStockTecnico.objects.create(tecnico=tecnico, material=material, fecha=fecha, tipo=T.CONSUMO,
                                          cantidad=-cantidad, orden=orden, intento=intento)
    # Registro del consumo para los indicadores (no toca los lotes del depósito: ya salieron en la entrega)
    Salida.objects.create(material=material, fecha=fecha, cantidad=cantidad, tecnico=tecnico, orden=orden, intento=intento,
                          motivo=Salida.Motivo.CONSUMO, costo_total=cantidad * material.costo_unitario,
                          observaciones="Del stock del técnico")
    return alcanzaba


def unidades_a_cargo(tecnico, material) -> list:
    """Unidades que tiene el técnico, con su origen: [[lote | None, fecha_ingreso, costo_unitario, cantidad], ...].

    Se reconstruye en orden FIFO: cada salida del técnico (consumo, devolución, ajuste negativo)
    se descuenta de lo que recibió primero. `lote` es None cuando no se conoce (entregas
    anteriores al registro por lote, ajustes positivos o partes entregadas sin stock en depósito):
    en ese caso la fecha es la de la entrega."""
    cola = deque()
    movs = (MovimientoStockTecnico.objects.filter(tecnico=tecnico, material=material)
            .select_related("salida").order_by("fecha", "id"))
    for m in movs:
        if m.cantidad > 0:
            pendiente = m.cantidad
            if m.tipo == T.ENTREGA and m.salida_id:
                for c in ConsumoLote.objects.filter(salida_id=m.salida_id).select_related("lote"):
                    tomado = min(c.cantidad, pendiente)
                    if tomado > 0:
                        cola.append([c.lote, c.lote.fecha, c.costo_unitario, tomado])
                        pendiente -= tomado
            if pendiente > 0:
                costo = (m.salida.costo_total / m.salida.cantidad) if m.salida_id and m.salida.cantidad else \
                    material.costo_unitario
                cola.append([None, m.fecha, costo, pendiente])
        else:
            resto = -m.cantidad
            while resto > 0 and cola:
                tomado = min(cola[0][3], resto)
                cola[0][3] -= tomado
                resto -= tomado
                if cola[0][3] <= 0:
                    cola.popleft()
    return list(cola)


@transaction.atomic
def devolver(tecnico, material, cantidad, fecha: date | None = None, observaciones=""):
    """El técnico devuelve partes al depósito.

    Vuelven como lotes de origen "devolución" con la fecha de ingreso y el costo del lote del que
    habían salido (no reinicia la antigüedad ni cuenta como compra)."""
    fecha = fecha or timezone.localdate()
    cantidad = Decimal(cantidad)
    if saldo(tecnico, material) < cantidad:
        raise StockInsuficiente(f"{tecnico} no tiene {cantidad} {material.unidad} de {material.nombre}")
    a_devolver = cantidad
    por_origen = {}  # (lote_id, fecha, costo) -> [lote, cantidad]
    for lote, f_ingreso, costo, q in unidades_a_cargo(tecnico, material):
        if a_devolver <= 0:
            break
        tomado = min(q, a_devolver)
        clave = (lote.pk if lote else None, f_ingreso, costo)
        por_origen.setdefault(clave, [lote, Decimal("0")])[1] += tomado
        a_devolver -= tomado
    if a_devolver > 0:  # sin origen conocido (no debería pasar si el saldo alcanza)
        por_origen.setdefault((None, fecha, material.costo_unitario), [None, Decimal("0")])[1] += a_devolver
    MovimientoStockTecnico.objects.create(tecnico=tecnico, material=material, fecha=fecha, tipo=T.DEVOLUCION,
                                          cantidad=-cantidad, observaciones=observaciones)
    lotes = []
    for (_, f_ingreso, costo), (lote, q) in por_origen.items():
        lotes.append(LoteIngreso.objects.create(
            material=material, fecha=f_ingreso, cantidad=q, costo_unitario=costo,
            origen=LoteIngreso.Origen.DEVOLUCION, lote_origen=lote, recibido=fecha,
            proveedor=f"Devolución {tecnico.legajo}", remito=f"Dev. {fecha:%d/%m/%Y}"))
    return lotes


def partes_paradas(tecnicos=None, hoy: date | None = None, dias: int | None = None):
    """Partes en manos de técnicos que superan los días máximos (FIFO sobre sus movimientos).

    Cada unidad tiene dos relojes: la edad original (ingreso a la empresa, según su lote) y la
    permanencia en el técnico (desde que se la entregaron). Parámetros → reloj_antiguedad decide cuál
    activa la alerta; ambos se informan."""
    p = Parametros.actual()
    hoy = hoy or timezone.localdate()
    dias = dias or p.dias_max_stock
    qs = MovimientoStockTecnico.objects.order_by("fecha", "id")
    if tecnicos is not None:
        qs = qs.filter(tecnico__in=tecnicos)
    movs = list(qs.values_list("tecnico_id", "material_id", "fecha", "cantidad", "salida_id"))
    origen = defaultdict(list)  # salida_id -> [(fecha_lote, cantidad)]
    for sid, f, c in ConsumoLote.objects.filter(salida_id__in={m[4] for m in movs if m[4]}).order_by(
            "lote__fecha", "lote_id").values_list("salida_id", "lote__fecha", "cantidad"):
        origen[sid].append((f, c))
    colas = defaultdict(deque)  # (tecnico_id, material_id) -> [[fecha_entrega, fecha_original, cantidad]]
    for tid, mid, fecha, cantidad, sid in movs:
        cola = colas[(tid, mid)]
        if cantidad > 0:
            pendiente = cantidad
            for f_orig, c in origen.get(sid, ()):
                tomado = min(c, pendiente)
                if tomado > 0:  # una unidad no puede ser más nueva en la empresa que su entrega
                    cola.append([fecha, min(f_orig, fecha), tomado])
                    pendiente -= tomado
            if pendiente > 0:
                cola.append([fecha, fecha, pendiente])
        else:
            resto = -cantidad
            while resto > 0 and cola:
                tomado = min(cola[0][2], resto)
                cola[0][2] -= tomado
                resto -= tomado
                if cola[0][2] <= 0:
                    cola.popleft()
    usar_original = p.reloj_antiguedad == "original"
    viejas_por_par = {}
    for k, cola in colas.items():
        viejas = [(fe, fo, c) for fe, fo, c in cola if (hoy - (fo if usar_original else fe)).days >= dias]
        if viejas:
            viejas_por_par[k] = viejas
    from core.models import Persona

    from .models import Material
    personas = Persona.objects.in_bulk({t for t, _ in viejas_por_par})
    mats = Material.objects.in_bulk({m for _, m in viejas_por_par})
    filas = []
    for (tid, mid), viejas in viejas_por_par.items():
        tec, mat = personas[tid], mats[mid]
        cant = sum(c for _, _, c in viejas)
        entrega = min(fe for fe, _, _ in viejas)
        original = min(fo for _, fo, _ in viejas)
        filas.append({"tecnico": tec, "material": mat, "cantidad": cant, "desde": entrega,
                      "dias_custodia": (hoy - entrega).days, "dias_original": (hoy - original).days,
                      "reloj": "edad original" if usar_original else "permanencia en el técnico",
                      "dias": (hoy - (original if usar_original else entrega)).days,
                      "valor": cant * mat.costo_unitario})
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
