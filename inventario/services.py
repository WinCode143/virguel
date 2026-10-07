"""Lógica de stock: FIFO, antigüedad, stock diario vs. personal en calle, previsión."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.models import Parametros
from operaciones.models import Jornada

from .models import DemandaComercial, LoteIngreso, Material, RecetaMaterial, Salida


class StockInsuficiente(Exception):
    pass


@transaction.atomic
def registrar_salida(salida: Salida, permitir_negativo=False) -> Salida:
    """Descuenta la cantidad de los lotes más antiguos primero (FIFO) y
    calcula el costo real de la salida."""
    restante = Decimal(salida.cantidad)
    costo = Decimal("0")
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
    if restante > 0:
        if not permitir_negativo:
            raise StockInsuficiente(
                f"Stock insuficiente de {salida.material}: faltan {restante} {salida.material.unidad}")
        costo += restante * salida.material.costo_unitario
    salida.costo_total = costo
    salida.save()
    return salida


def lotes_envejecidos(hoy: date | None = None):
    """Lotes con stock disponible, con días en depósito y semáforo."""
    hoy = hoy or timezone.localdate()
    p = Parametros.actual()
    filas = []
    for lote in (LoteIngreso.objects.filter(cantidad_disponible__gt=0)
                 .select_related("material").order_by("fecha")):
        dias = (hoy - lote.fecha).days
        if dias >= p.dias_max_stock:
            estado = "critico"
        elif dias >= p.dias_aviso_stock:
            estado = "aviso"
        else:
            estado = "ok"
        filas.append({
            "lote": lote, "material": lote.material, "dias": dias, "estado": estado,
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


def prevision_materiales(desde: date, hasta: date):
    """Materiales necesarios para la demanda comercial del período, contra stock."""
    necesidad = defaultdict(Decimal)
    recetas = defaultdict(list)
    for r in RecetaMaterial.objects.select_related("material"):
        recetas[r.tipo_tarea_id].append(r)
    for d in DemandaComercial.objects.filter(fecha__range=(desde, hasta)):
        for r in recetas[d.tipo_tarea_id]:
            necesidad[r.material] += r.cantidad * d.cantidad_clientes
    filas = []
    for material, cant in sorted(necesidad.items(), key=lambda kv: kv[0].nombre):
        stock = material.stock_actual
        faltante = max(Decimal("0"), cant - stock)
        filas.append({"material": material, "necesario": cant, "stock": stock,
                      "faltante": faltante, "costo_compra": faltante * material.costo_unitario})
    return filas
