"""Proyección de egresos: no hay ventas, así que el flujo es sólo de salida.

Para cada mes futuro se suman:
  * Materiales: demanda comercial cargada x receta de materiales x costo.
    Si comercial todavía no cargó demanda para ese mes, se usa el promedio
    de consumo real de los últimos 3 meses.
  * Flota: services que vencen en el mes x costo estimado del tipo de service.
  * EPP/herramientas: asignaciones que vencen en el mes x costo del elemento.
  * Siniestros: costo pendiente de los siniestros abiertos (mes actual) +
    promedio histórico mensual (meses siguientes).
  * Costos fijos mensuales cargados.
  * Sueldos: costo total del último mes liquidado.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from flota.models import Vehiculo, proximos_services
from herramientas.models import Asignacion
from incidentes.models import Siniestro
from inventario.models import DemandaComercial, RecetaMaterial, Salida

from .models import CostoFijo, Egreso


def inicio_mes(d: date) -> date:
    return d.replace(day=1)


def sumar_meses(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def historico_mensual(meses: int = 6, hoy: date | None = None):
    hoy = hoy or timezone.localdate()
    desde = sumar_meses(inicio_mes(hoy), -(meses - 1))
    datos = defaultdict(lambda: defaultdict(Decimal))
    for r in (Egreso.objects.filter(fecha__gte=desde).annotate(mes=TruncMonth("fecha"))
              .values("mes", "categoria__nombre").annotate(t=Sum("monto"))):
        datos[r["mes"]][r["categoria__nombre"]] += r["t"]
    return {mes: dict(cats) for mes, cats in sorted(datos.items())}


def proyectar(meses: int = 3, hoy: date | None = None):
    hoy = hoy or timezone.localdate()
    primero = inicio_mes(hoy)

    recetas = defaultdict(list)
    for r in RecetaMaterial.objects.select_related("material"):
        recetas[r.tipo_tarea_id].append(r)

    hace3 = sumar_meses(primero, -3)
    consumo_hist = (Salida.objects.filter(fecha__gte=hace3, fecha__lt=primero, motivo=Salida.Motivo.CONSUMO)
                    .aggregate(t=Sum("costo_total"))["t"] or Decimal("0")) / 3
    siniestros_hist = (Siniestro.objects.filter(fecha__gte=hace3, fecha__lt=primero)
                       .aggregate(t=Sum("costo_real"))["t"] or Decimal("0")) / 3
    fijos = CostoFijo.objects.filter(activo=True).aggregate(t=Sum("monto_mensual"))["t"] or Decimal("0")
    # sueldos: el costo del último mes con liquidaciones (si se usan)
    from .models import Liquidacion
    ultimo = Liquidacion.objects.order_by("-periodo").values_list("periodo", flat=True).first()
    sueldos = (Liquidacion.objects.filter(periodo=ultimo).aggregate(t=Sum("costo_total"))["t"] or Decimal("0")
               if ultimo else Decimal("0"))

    services = []
    for v in Vehiculo.objects.exclude(estado=Vehiculo.Estado.FUERA):
        for s in proximos_services(v, hoy):
            if s["fecha_estimada"]:
                services.append((s["fecha_estimada"], s["tipo"].costo_estimado))

    resultado = []
    for i in range(meses):
        ini = sumar_meses(primero, i)
        fin = sumar_meses(primero, i + 1) - timedelta(days=1)
        desde = max(ini, hoy)

        mat = Decimal("0")
        demanda = DemandaComercial.objects.filter(fecha__range=(desde, fin))
        for d in demanda:
            for r in recetas[d.tipo_tarea_id]:
                mat += r.cantidad * d.cantidad_clientes * r.material.costo_unitario
        origen_mat = "demanda comercial"
        if not demanda.exists():
            dias_restantes = (fin - desde).days + 1
            mat = consumo_hist * Decimal(dias_restantes) / Decimal((fin - ini).days + 1)
            origen_mat = "promedio histórico"

        flota = sum((c for f, c in services if (f <= fin and i > 0 and f >= ini) or (i == 0 and f <= fin)),
                    Decimal("0"))
        epp = sum((a.elemento.costo * a.cantidad for a in Asignacion.objects.filter(
            estado=Asignacion.Estado.EN_USO, fecha_vencimiento__range=(ini if i else date.min, fin)
        ).select_related("elemento")), Decimal("0"))
        if i == 0:
            abiertos = sum((s.costo_estimado - s.monto_recuperado for s in Siniestro.objects.exclude(
                estado=Siniestro.Estado.CERRADO) if s.costo_real == 0), Decimal("0"))
            sin = max(abiertos, Decimal("0"))
        else:
            sin = siniestros_hist
        resultado.append({
            "mes": ini, "materiales": mat, "origen_materiales": origen_mat, "flota": flota, "epp": epp,
            "siniestros": sin, "fijos": fijos, "sueldos": sueldos, "resto": flota + epp + sin + fijos, "total": mat + flota + epp + sin + fijos + sueldos,
        })
    return resultado
