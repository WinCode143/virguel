"""Liquidación esperada de Claro a partir de las órdenes completadas.

Supuestos (configurables, a validar con la empresa):
  * Claro paga por orden completada según el precio de su tipo de tarea (TipoTarea.precio_claro);
  * las visitas de retrabajo no se pagan (Parámetros → "Claro paga las visitas de retrabajo");
  * del bruto se descuenta un % de retenciones y débitos por calidad (Parámetros);
  * se cobra N días después del fin del mes liquidado (Parámetros).

El resultado se registra como un Ingreso a cobrar (uno por mes); recalcular lo actualiza.
Si la liquidación real difiere, se corrige el monto del ingreso a mano.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count

from core.models import Parametros
from operaciones.models import OrdenTrabajo

from .models import Ingreso
from .proyeccion import sumar_meses

PAGADOR = "Claro"


def _concepto(mes: date) -> str:
    return f"Liquidación esperada {mes:%m/%Y} (órdenes completadas)"


def calcular(mes: date) -> dict:
    """Detalle por tipo de tarea, bruto, retención y neto de las órdenes completadas en el mes."""
    p = Parametros.actual()
    fin = sumar_meses(mes, 1) - timedelta(days=1)
    qs = OrdenTrabajo.objects.filter(estado="completada", fecha_ejecucion__range=(mes, fin))
    if not p.claro_paga_retrabajos:
        qs = qs.filter(es_retrabajo=False)
    filas, bruto = [], Decimal("0")
    sin_precio = defaultdict(int)
    for r in qs.values("tipo__codigo", "tipo__nombre", "tipo__precio_claro").annotate(n=Count("id")).order_by(
            "tipo__nombre"):
        precio = r["tipo__precio_claro"] or Decimal("0")
        importe = precio * r["n"]
        if not precio:
            sin_precio[r["tipo__nombre"]] += r["n"]
        filas.append({"tipo": r["tipo__nombre"], "codigo": r["tipo__codigo"], "ordenes": r["n"], "precio": precio,
                      "importe": importe})
        bruto += importe
    retencion = (bruto * p.claro_retencion / 100).quantize(Decimal("0.01"))
    return {"mes": mes, "filas": filas, "bruto": bruto, "retencion": retencion, "neto": bruto - retencion,
            "cobro": fin + timedelta(days=p.claro_dias_cobro), "sin_precio": dict(sin_precio)}


def registrar(mes: date) -> Ingreso | None:
    """Crea o actualiza el ingreso a cobrar del mes (no toca los cobros ya registrados)."""
    c = calcular(mes)
    if c["neto"] <= 0:
        return None
    detalle = ", ".join(f"{f['ordenes']} {f['codigo']}" for f in c["filas"])
    ingreso, _ = Ingreso.objects.update_or_create(
        pagador=PAGADOR, periodo=mes, concepto=_concepto(mes),
        defaults={"fecha": sumar_meses(mes, 1) - timedelta(days=1), "monto": c["neto"],
                  "fecha_esperada_cobro": c["cobro"],
                  "observaciones": f"Bruto {c['bruto']:.2f} − retención {c['retencion']:.2f}. {detalle}"[:200]})
    return ingreso
