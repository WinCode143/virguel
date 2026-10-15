"""Liquidación esperada de Claro a partir de las órdenes completadas.

Supuestos (configurables, a validar con la empresa):
  * Claro paga por orden completada según la tarifa VIGENTE a la fecha de ejecución (TarifaClaro);
  * las visitas de retrabajo no se pagan (Parámetros → "Claro paga las visitas de retrabajo");
  * del bruto se descuenta un % de retenciones y débitos por calidad (Parámetros);
  * se cobra N días después del fin del mes liquidado (Parámetros).

Estimación, confirmación y cobro son cosas distintas:
  * cada cálculo queda como una versión (EstimacionLiquidacion);
  * mientras el ingreso está ESTIMADO y sin cobros, la versión nueva actualiza su monto;
  * cuando se CONFIRMA la liquidación de Claro (monto aceptado y ajuste) o ya hay cobros, recalcular
    sólo agrega una versión para comparar: nunca reescribe lo aceptado ni el saldo cobrado.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from core.models import Parametros
from operaciones.models import OrdenTrabajo, TarifaClaro

from .models import EstimacionLiquidacion, Ingreso
from .proyeccion import sumar_meses

PAGADOR = "Claro"


def _concepto(mes: date) -> str:
    return f"Liquidación Claro {mes:%m/%Y}"


class Tarifario:
    """Tarifa vigente por tipo de tarea y fecha."""

    def __init__(self):
        self.por_tipo = defaultdict(list)
        for t in TarifaClaro.objects.order_by("vigente_desde"):
            self.por_tipo[t.tipo_tarea_id].append(t)

    def tarifa(self, tipo_id, fecha) -> TarifaClaro | None:
        vigente = None
        for t in self.por_tipo.get(tipo_id, ()):
            if t.vigente_desde <= fecha:
                vigente = t
        return vigente


def calcular(mes: date) -> dict:
    """Detalle por tipo de tarea y tarifa, bruto, retención y neto de las órdenes completadas en el mes."""
    p = Parametros.actual()
    fin = sumar_meses(mes, 1) - timedelta(days=1)
    qs = OrdenTrabajo.objects.filter(estado="completada", fecha_ejecucion__range=(mes, fin))
    if not p.claro_paga_retrabajos:
        qs = qs.filter(es_retrabajo=False)
    # Una visita completada con revisión técnica o aceptación de Claro rechazada no se estima como cobrable
    from operaciones.models import Intento
    rechazadas = Intento.objects.filter(resultado="completada", fecha__range=(mes, fin)).filter(
        Q(revision_tecnica=Intento.Revision.RECHAZADA) | Q(aceptacion_claro=Intento.Aceptacion.RECHAZADA))
    excluidas = qs.filter(intentos__in=rechazadas).count()
    qs = qs.exclude(intentos__in=rechazadas)
    tarifario = Tarifario()
    grupos = defaultdict(lambda: {"ordenes": 0, "importe": Decimal("0")})
    for tipo_id, codigo, nombre, fecha in qs.values_list("tipo_id", "tipo__codigo", "tipo__nombre", "fecha_ejecucion"):
        t = tarifario.tarifa(tipo_id, fecha)
        precio = t.precio if t else Decimal("0")
        g = grupos[(nombre, codigo, precio, bool(t and t.provisoria))]
        g["ordenes"] += 1
        g["importe"] += precio
    filas = [{"tipo": n, "codigo": c, "precio": pr, "provisoria": prov, **g}
             for (n, c, pr, prov), g in sorted(grupos.items())]
    bruto = sum((f["importe"] for f in filas), Decimal("0"))
    retencion = (bruto * p.claro_retencion / 100).quantize(Decimal("0.01"))
    return {"mes": mes, "filas": filas, "bruto": bruto, "retencion": retencion, "neto": bruto - retencion,
            "cobro": fin + timedelta(days=p.claro_dias_cobro),
            "sin_precio": {f["tipo"]: f["ordenes"] for f in filas if not f["precio"]},
            "provisoria": any(f["provisoria"] for f in filas), "excluidas": excluidas,
            "supuestos": {"retencion_pct": str(p.claro_retencion), "dias_cobro": p.claro_dias_cobro,
                          "paga_retrabajos": p.claro_paga_retrabajos}}


def ingreso_del_mes(mes: date) -> Ingreso | None:
    return Ingreso.objects.filter(pagador=PAGADOR, periodo=mes).order_by("id").first()


@transaction.atomic
def registrar(mes: date) -> Ingreso | None:
    """Guarda una nueva versión de la estimación (también si da cero) y actualiza el ingreso sólo si sigue
    estimado y sin cobros. Una estimación que baja a cero deja el ingreso estimado en 0 (con su versión),
    no conserva el importe anterior; si no había ingreso y da cero, no se crea uno."""
    c = calcular(mes)
    if c["neto"] <= 0 and ingreso_del_mes(mes) is None:
        return None
    version = (EstimacionLiquidacion.objects.filter(periodo=mes).aggregate(v=Max("version"))["v"] or 0) + 1
    detalle = [{**f, "precio": str(f["precio"]), "importe": str(f["importe"])} for f in c["filas"]]
    est = EstimacionLiquidacion.objects.create(periodo=mes, version=version, bruto=c["bruto"],
                                               retencion=c["retencion"], neto=c["neto"], detalle=detalle,
                                               supuestos=c["supuestos"])
    ingreso = ingreso_del_mes(mes)
    resumen = (f"Estimación v{version}: bruto {c['bruto']:.2f} − retención {c['retencion']:.2f}"
               + (" (tarifas provisorias)" if c["provisoria"] else "")
               + (" · sin órdenes cobrables" if c["neto"] <= 0 else ""))
    if ingreso is None:
        ingreso = Ingreso.objects.create(
            pagador=PAGADOR, periodo=mes, concepto=_concepto(mes), confirmacion=Ingreso.Confirmacion.ESTIMADO,
            fecha=sumar_meses(mes, 1) - timedelta(days=1), monto=c["neto"], monto_estimado=c["neto"],
            fecha_esperada_cobro=c["cobro"], observaciones=resumen[:200])
        est.aplicada = True
    elif ingreso.confirmacion == Ingreso.Confirmacion.ESTIMADO and not ingreso.cobros.exists():
        ingreso.monto = ingreso.monto_estimado = max(c["neto"], 0)
        ingreso.fecha_esperada_cobro = c["cobro"]
        ingreso.observaciones = resumen[:200]
        ingreso.save()
        est.aplicada = True
    est.ingreso = ingreso
    est.save(update_fields=["ingreso", "aplicada"])
    return ingreso


@transaction.atomic
def confirmar(ingreso: Ingreso, monto: Decimal, usuario=None, nota: str = "") -> Ingreso:
    """La liquidación aceptada por Claro reemplaza a la estimación (que queda guardada)."""
    if ingreso.monto_estimado is None:
        ingreso.monto_estimado = ingreso.monto
    ingreso.monto = monto
    ingreso.confirmacion = Ingreso.Confirmacion.CONFIRMADO
    ingreso.confirmado_por = usuario if getattr(usuario, "is_authenticated", False) else None
    ingreso.fecha_confirmacion = timezone.now()
    ingreso.nota_confirmacion = (nota or "")[:200]
    ingreso.save()
    return ingreso
