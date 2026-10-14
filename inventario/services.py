"""Lógica de stock: FIFO, antigüedad, stock diario vs. personal en calle, previsión."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.models import Parametros
from operaciones.models import Jornada

from .models import ConsumoLote, DemandaComercial, LoteIngreso, Material, RecetaMaterial, Salida


class StockInsuficiente(Exception):
    pass


@transaction.atomic
def registrar_salida(salida: Salida, permitir_negativo=False) -> Salida:
    """Descuenta la cantidad de los lotes más antiguos primero (FIFO) y
    calcula el costo real de la salida."""
    restante = Decimal(salida.cantidad)
    costo = Decimal("0")
    tomados = []
    lotes = (LoteIngreso.objects.select_for_update()
             .filter(material=salida.material, cantidad_disponible__gt=0).order_by("fecha", "id"))
    for lote in lotes:
        if restante <= 0:
            break
        tomado = min(lote.cantidad_disponible, restante)
        lote.cantidad_disponible -= tomado
        lote.save(update_fields=["cantidad_disponible"])
        costo += tomado * lote.costo_unitario
        restante -= tomado
        tomados.append((lote, tomado))
    if restante > 0:
        if not permitir_negativo:
            raise StockInsuficiente(
                f"Stock insuficiente de {salida.material}: faltan {restante} {salida.material.unidad}")
        costo += restante * salida.material.costo_unitario
    salida.costo_total = costo
    salida.save()
    ConsumoLote.objects.bulk_create(ConsumoLote(salida=salida, lote=lote, cantidad=q, costo_unitario=lote.costo_unitario)
                                    for lote, q in tomados)
    return salida


def lotes_envejecidos(hoy: date | None = None):
    """Lotes con stock disponible, con edad original, permanencia en depósito y semáforo según el reloj
    elegido en Parámetros (por defecto la edad original: una devolución no rejuvenece la unidad)."""
    hoy = hoy or timezone.localdate()
    p = Parametros.actual()
    filas = []
    for lote in (LoteIngreso.objects.filter(cantidad_disponible__gt=0)
                 .select_related("material").order_by("fecha")):
        original = (hoy - lote.fecha).days
        permanencia = (hoy - (lote.recibido or lote.fecha)).days
        dias = original if p.reloj_antiguedad == "original" else permanencia
        if dias >= p.dias_max_stock:
            estado = "critico"
        elif dias >= p.dias_aviso_stock:
            estado = "aviso"
        else:
            estado = "ok"
        filas.append({
            "lote": lote, "material": lote.material, "dias": dias, "dias_original": original,
            "dias_permanencia": permanencia, "estado": estado,
            "valor": lote.cantidad_disponible * lote.costo_unitario,
        })
    return filas


def tecnicos_en_calle(fecha: date) -> int:
    return Jornada.objects.filter(fecha=fecha, en_calle=True).count()


def consumo_promedio_por_tecnico_dia(material: Material, hasta: date, dias=30) -> Decimal:
    """Consumo histórico del material dividido por jornadas-técnico en calle.

    Sólo días completos (anteriores a `hasta`): el día en curso todavía no
    registró todo su consumo y bajaría artificialmente el promedio."""
    desde = hasta - timedelta(days=dias)
    consumo = (Salida.objects.filter(material=material, fecha__gte=desde, fecha__lt=hasta,
                                     motivo=Salida.Motivo.CONSUMO)
               .aggregate(t=Sum("cantidad"))["t"] or Decimal("0"))
    jornadas = Jornada.objects.filter(fecha__gte=desde, fecha__lt=hasta, en_calle=True).count()
    if not jornadas:
        return Decimal("0")
    return consumo / jornadas


def stock_diario(fecha: date | None = None):
    """Cruza stock disponible con técnicos en calle: cuánto stock hay por técnico
    y para cuántos días alcanza al ritmo de consumo actual."""
    fecha = fecha or timezone.localdate()
    p = Parametros.actual()
    en_calle = tecnicos_en_calle(fecha)
    if not en_calle:  # si aún no se cargaron las jornadas de hoy, usar el último día con datos
        ultima = Jornada.objects.filter(fecha__lte=fecha, en_calle=True).order_by("-fecha").first()
        en_calle = tecnicos_en_calle(ultima.fecha) if ultima else 0
    stock_por_material = dict(
        LoteIngreso.objects.values_list("material").annotate(t=Sum("cantidad_disponible")))
    from .stock_tecnico import total_en_tecnicos
    en_tecnicos = total_en_tecnicos()
    filas = []
    for m in Material.objects.filter(activo=True):
        deposito = stock_por_material.get(m.id) or Decimal("0")
        tecnicos = max(Decimal("0"), en_tecnicos.get(m.id) or Decimal("0"))
        stock = deposito + tecnicos
        cons_tec = consumo_promedio_por_tecnico_dia(m, fecha)
        consumo_dia = cons_tec * en_calle
        dias_cobertura = (stock / consumo_dia) if consumo_dia else None
        if stock <= 0 and consumo_dia > 0:
            estado = "critico"
        elif dias_cobertura is not None and dias_cobertura < p.dias_cobertura_stock_min:
            estado = "critico" if dias_cobertura < p.dias_cobertura_stock_min / 2 else "aviso"
        elif stock < m.stock_minimo:
            estado = "aviso"
        else:
            estado = "ok"
        filas.append({
            "material": m, "stock": stock, "deposito": deposito, "en_tecnicos": tecnicos,
            "por_tecnico": (stock / en_calle) if en_calle else None,
            "consumo_tecnico_dia": cons_tec, "consumo_dia": consumo_dia,
            "dias_cobertura": dias_cobertura, "estado": estado,
        })
    return {"fecha": fecha, "tecnicos_en_calle": en_calle, "filas": filas}


def _factor(receta, orden_equipos, orden_recambio, p) -> tuple[Decimal, bool]:
    """(multiplicador, estimado?) de una receta para una orden. Usa lo conocido y estima lo desconocido."""
    C = RecetaMaterial.Condicion
    if receta.condicion == C.POR_EQUIPO:
        if orden_equipos is not None:
            return Decimal(orden_equipos), False
        return (p.prob_decodificador_min + p.prob_decodificador_max) / 2, True
    if receta.condicion == C.SI_RECAMBIO:
        if orden_recambio is not None:
            return Decimal(1 if orden_recambio else 0), False
        return p.prob_recambio, True
    return Decimal(1), False


def necesidades(desde: date, hasta: date) -> list[dict]:
    """Una fila por material y origen de la necesidad (sin contar dos veces):

    * órdenes abiertas programadas hasta `hasta` (incluidas las atrasadas), descontando lo ya reservado;
    * demanda comercial sólo por lo que excede a las órdenes ya creadas para ese día y tipo.
    Cada fila dice si es inmediata (orden asignada dentro de los días de necesidad inmediata) o backlog,
    y si la cantidad es estimada (condición desconocida)."""
    from operaciones.models import OrdenTrabajo

    from .models import ReservaMaterial
    p = Parametros.actual()
    limite_inmediato = desde + timedelta(days=p.dias_necesidad_inmediata)
    recetas = defaultdict(list)
    for r in RecetaMaterial.objects.select_related("material"):
        recetas[r.tipo_tarea_id].append(r)
    reservado = defaultdict(Decimal)
    for oid, mid, q in ReservaMaterial.objects.filter(estado="activa").values_list("orden_id", "material_id",
                                                                                   "cantidad"):
        reservado[(oid, mid)] += q
    filas = []
    ordenes_dia = defaultdict(int)
    for oid, tec, tipo, fecha, equipos, recambio in OrdenTrabajo.objects.filter(
            estado__in=("pendiente", "asignada", "reprogramada"), fecha_programada__lte=hasta).values_list(
            "id", "tecnico_id", "tipo_id", "fecha_programada", "equipos_requeridos", "requiere_recambio"):
        if fecha >= desde:
            ordenes_dia[(fecha, tipo)] += 1
        inmediata = bool(tec) and fecha <= limite_inmediato
        for r in recetas[tipo]:
            f, est = _factor(r, equipos, recambio, p)
            q = r.cantidad * f - reservado.get((oid, r.material_id), Decimal("0"))
            if q > 0:
                filas.append({"material": r.material, "cantidad": q, "tecnico_id": tec, "fecha": fecha,
                              "inmediata": inmediata, "estimado": est, "fuente": "orden"})
    pronostico = defaultdict(int)
    for d in DemandaComercial.objects.filter(fecha__range=(desde, hasta)):
        pronostico[(d.fecha, d.tipo_tarea_id)] += d.cantidad_clientes
    for (fecha, tipo), clientes in pronostico.items():
        extra = max(0, clientes - ordenes_dia.get((fecha, tipo), 0))
        for r in recetas[tipo]:
            f, est = _factor(r, None, None, p)
            if extra and f:
                filas.append({"material": r.material, "cantidad": r.cantidad * f * extra, "tecnico_id": None,
                              "fecha": fecha, "inmediata": False, "estimado": est or r.condicion != "siempre",
                              "fuente": "pronóstico"})
    return filas


def demanda_materiales(desde: date, hasta: date):
    """Compatibilidad: ({(tecnico_id, material): cantidad}, {material: cantidad sin técnico})."""
    por_tecnico, sin_tecnico = defaultdict(Decimal), defaultdict(Decimal)
    for n in necesidades(desde, hasta):
        if n["tecnico_id"]:
            por_tecnico[(n["tecnico_id"], n["material"])] += n["cantidad"]
        else:
            sin_tecnico[n["material"]] += n["cantidad"]
    return por_tecnico, sin_tecnico


def prevision_materiales(desde: date, hasta: date):
    """Materiales necesarios para el período contra un suministro reconciliado (sugerencia de compra).

    Suministro, sin contar dos veces ni dar por libre lo que ya está comprometido:
      * lo reservado para una orden ya está cubierto y no queda disponible para otra;
      * lo que cada técnico tiene a cargo cubre primero sus propias órdenes asignadas;
      * lo que le sobra queda "libre en técnicos" (disponible devolviéndolo o transfiriéndolo);
      * depósito disponible + libre en técnicos + compras en camino cubren el resto; para la necesidad
        inmediata sólo cuenta lo que llega a tiempo (una entrega posterior no la destraba).
    Separa necesidad inmediata y backlog; con "abastecer backlog" apagado sólo sugiere lo inmediato.
    Es una sugerencia: requiere revisión antes de emitir una orden de compra."""
    from .models import CompraEnCamino, MovimientoStockTecnico, ReservaMaterial
    p = Parametros.actual()
    limite_inmediato = desde + timedelta(days=p.dias_necesidad_inmediata)
    filas_nec = necesidades(desde, hasta)
    tiene = defaultdict(Decimal)
    for tec, mat_id, q in (MovimientoStockTecnico.objects.values_list("tecnico_id", "material_id")
                           .annotate(t=Sum("cantidad")).values_list("tecnico_id", "material_id", "t")):
        if q and q > 0:
            tiene[(tec, mat_id)] = q
    deposito = dict(LoteIngreso.objects.exclude(origen=LoteIngreso.Origen.CUSTODIA).values_list("material")
                    .annotate(t=Sum("cantidad_disponible")))
    reservas = dict(ReservaMaterial.objects.filter(estado="activa").values_list("material")
                    .annotate(t=Sum("cantidad")))
    camino, camino_inm = defaultdict(Decimal), defaultdict(Decimal)
    for mid, q, f in CompraEnCamino.objects.filter(recibida=False, fecha_esperada__lte=hasta).values_list(
            "material_id", "cantidad", "fecha_esperada"):
        camino[mid] += q
        if f <= limite_inmediato:
            camino_inm[mid] += q

    por_material = defaultdict(list)
    for n in filas_nec:
        por_material[n["material"]].append(n)
    filas = []
    for material in sorted(por_material, key=lambda m: m.nombre):
        ns = por_material[material]
        necesario = sum((n["cantidad"] for n in ns), Decimal("0"))
        inmediato = sum((n["cantidad"] for n in ns if n["inmediata"]), Decimal("0"))
        # stock propio de cada técnico cubre sus órdenes (primero las inmediatas)
        disponible_tec = {k: v for k, v in tiene.items() if k[1] == material.id}
        propio = Decimal("0")
        resto_inm = resto_backlog = Decimal("0")
        for n in sorted(ns, key=lambda n: (not n["inmediata"], n["fecha"])):
            q = n["cantidad"]
            if n["tecnico_id"]:
                k = (n["tecnico_id"], material.id)
                cubre = min(q, disponible_tec.get(k, Decimal("0")))
                if cubre:
                    disponible_tec[k] -= cubre
                    propio += cubre
                    q -= cubre
            if n["inmediata"]:
                resto_inm += q
            else:
                resto_backlog += q
        libre = sum(disponible_tec.values(), Decimal("0"))
        dep = max(Decimal("0"), (deposito.get(material.id) or Decimal("0")) - (reservas.get(material.id) or 0))
        # necesidad inmediata: sólo con lo que está o llega a tiempo
        suministro_inm = dep + libre + camino_inm.get(material.id, Decimal("0"))
        faltante_inm = max(Decimal("0"), resto_inm - suministro_inm)
        sobrante = max(Decimal("0"), suministro_inm - resto_inm) + (camino.get(material.id, Decimal("0"))
                                                                   - camino_inm.get(material.id, Decimal("0")))
        faltante_backlog = max(Decimal("0"), resto_backlog - sobrante)
        faltante = faltante_inm + (faltante_backlog if p.abastecer_backlog else Decimal("0"))
        filas.append({"material": material, "necesario": necesario, "inmediato": inmediato,
                      "backlog": necesario - inmediato, "estimado": any(n["estimado"] for n in ns),
                      "stock": propio + dep + libre + camino.get(material.id, Decimal("0")),
                      "propio_tecnicos": propio, "deposito": dep, "reservado": reservas.get(material.id) or Decimal("0"),
                      "libre_tecnicos": libre, "en_camino": camino.get(material.id, Decimal("0")),
                      "faltante_inmediato": faltante_inm, "faltante_backlog": faltante_backlog,
                      "faltante": faltante, "costo_compra": faltante * material.costo_unitario})
    return filas


def reservar(orden, material, cantidad, responsable="") -> "ReservaMaterial":
    """Reserva material del depósito para una orden. No se puede comprometer lo que ya está reservado."""
    from django.core.exceptions import ValidationError

    from .models import ReservaMaterial
    with transaction.atomic():
        Material.objects.select_for_update().filter(pk=material.pk).first()
        stock = (LoteIngreso.objects.filter(material=material).exclude(origen=LoteIngreso.Origen.CUSTODIA)
                 .aggregate(t=Sum("cantidad_disponible"))["t"] or Decimal("0"))
        ya = (ReservaMaterial.objects.filter(material=material, estado="activa").aggregate(t=Sum("cantidad"))["t"]
              or Decimal("0"))
        if stock - ya < Decimal(cantidad):
            raise ValidationError(f"No alcanza: disponible sin reservar {stock - ya} {material.unidad}.")
        return ReservaMaterial.objects.create(material=material, cantidad=cantidad, orden=orden,
                                              necesaria_para=orden.fecha_programada, responsable=responsable)
