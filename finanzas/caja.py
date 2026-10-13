"""Flujo de fondos: saldo de caja, cuentas a cobrar y a pagar, y proyección por semana.

Tres capas que no se mezclan:
  * presupuesto / estimación  → lo que se espera gastar (finanzas/proyeccion.py), marcado "estimado";
  * obligación devengada       → Egreso (a pagar) e Ingreso (a cobrar), con vencimiento o cuotas;
  * movimiento de dinero       → Pago y Cobro, imputados a una cuenta.

Saldo proyectado = saldo actual de las cuentas + cobros esperados − pagos comprometidos
                   − gasto estimado todavía no registrado.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import DecimalField, F, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Cuenta, Egreso, Ingreso
from .proyeccion import proyectar, sumar_meses

CERO = Decimal("0")
_DEC = DecimalField(max_digits=14, decimal_places=2)


def saldo_cuentas(al: date | None = None) -> Decimal:
    return sum((c.saldo(al) for c in Cuenta.objects.filter(activa=True)), CERO)


def egresos_a_pagar():
    """Egresos con saldo pendiente (monto − pagos), con el saldo anotado."""
    return (Egreso.objects.annotate(pagos_total=Coalesce(Sum("pagos__monto"), Value(CERO), output_field=_DEC))
            .annotate(saldo_pendiente=F("monto") - F("pagos_total"))
            .filter(monto__gt=0, saldo_pendiente__gt=0))


def ingresos_a_cobrar():
    return (Ingreso.objects.annotate(cobros_total=Coalesce(Sum("cobros__monto"), Value(CERO), output_field=_DEC))
            .annotate(saldo_pendiente=F("monto") - F("cobros_total"))
            .filter(saldo_pendiente__gt=0))


def vencimientos(egreso) -> list[tuple[date, Decimal]]:
    """Lo que falta pagar de un egreso, por fecha. Con cuotas, los pagos se imputan en orden."""
    pagado = egreso.pagado_monto
    cuotas = list(egreso.cuotas.all())
    if not cuotas:
        saldo = egreso.monto - pagado
        return [(egreso.vencimiento or egreso.fecha, saldo)] if saldo > 0 else []
    filas = []
    for c in cuotas:
        cubre = min(c.monto, pagado)
        pagado -= cubre
        if c.monto - cubre > 0:
            filas.append((c.vencimiento, c.monto - cubre))
    return filas


def _lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def proyeccion_caja(semanas: int = 12, hoy: date | None = None, estimados: bool = True) -> dict:
    hoy = hoy or timezone.localdate()
    inicio = _lunes(hoy)
    periodos = [(inicio + timedelta(weeks=i), inicio + timedelta(weeks=i, days=6)) for i in range(semanas)]
    fin_total = periodos[-1][1]

    def periodo_de(f: date) -> int | None:
        if f <= periodos[0][1]:
            return 0  # vencido o de esta semana
        if f > fin_total:
            return None
        return (f - inicio).days // 7

    cobros, pagos, estimado = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    atrasado_cobrar = atrasado_pagar = CERO
    for i in ingresos_a_cobrar():
        f = i.fecha_esperada_cobro or i.fecha
        k = periodo_de(f)
        if k is not None:
            cobros[k] += i.saldo_pendiente
        if f < hoy:
            atrasado_cobrar += i.saldo_pendiente
    for e in egresos_a_pagar().prefetch_related("cuotas"):
        for f, monto in vencimientos(e):
            k = periodo_de(f)
            if k is not None:
                pagos[k] += monto
            if f < hoy:
                atrasado_pagar += monto

    if estimados:
        # Gasto estimado del mes que todavía no está registrado como egreso, repartido por día.
        meses = (fin_total.year - hoy.year) * 12 + fin_total.month - hoy.month + 1
        for m in proyectar(meses, hoy):
            ini_m, fin_m = m["mes"], sumar_meses(m["mes"], 1) - timedelta(days=1)
            registrado = (Egreso.objects.filter(fecha__range=(ini_m, fin_m))
                          .aggregate(t=Sum("monto"))["t"] or CERO)
            falta = max(CERO, Decimal(m["total"]) - registrado)
            desde = max(ini_m, hoy)
            dias = (fin_m - desde).days + 1
            if falta <= 0 or dias <= 0:
                continue
            por_dia = falta / dias
            d = desde
            while d <= fin_m:
                k = periodo_de(d)
                if k is not None:
                    estimado[k] += por_dia
                d += timedelta(days=1)

    saldo = saldo_cuentas(hoy)
    filas = []
    for k, (ini, fin) in enumerate(periodos):
        neto = cobros[k] - pagos[k] - estimado[k]
        saldo += neto
        filas.append({"desde": ini, "hasta": fin, "cobros": cobros[k], "pagos": pagos[k],
                      "estimado": estimado[k].quantize(Decimal("0.01")), "neto": neto.quantize(Decimal("0.01")),
                      "saldo": saldo.quantize(Decimal("0.01")), "negativo": saldo < 0})
    return {"saldo_inicial": saldo_cuentas(hoy), "filas": filas, "atrasado_cobrar": atrasado_cobrar,
            "atrasado_pagar": atrasado_pagar, "hay_cuentas": Cuenta.objects.filter(activa=True).exists()}


def generar_cuotas(egreso, cantidad: int, primer_vencimiento: date, cada_dias: int | None = None):
    """Arma un plan de `cantidad` cuotas iguales (la última ajusta el redondeo). Mensuales por defecto."""
    from .models import Cuota
    egreso.cuotas.all().delete()
    base = (egreso.monto / cantidad).quantize(Decimal("0.01"))
    cuotas = []
    for n in range(cantidad):
        if cada_dias:
            venc = primer_vencimiento + timedelta(days=cada_dias * n)
        else:
            m = sumar_meses(primer_vencimiento.replace(day=1), n)
            ultimo = (sumar_meses(m, 1) - timedelta(days=1)).day
            venc = m.replace(day=min(primer_vencimiento.day, ultimo))
        monto = base if n < cantidad - 1 else egreso.monto - base * (cantidad - 1)
        cuotas.append(Cuota(egreso=egreso, numero=n + 1, vencimiento=venc, monto=monto))
    Cuota.objects.bulk_create(cuotas)
    egreso.vencimiento = cuotas[-1].vencimiento
    if egreso.pagado and not egreso.pagos.filter(automatico=False).exists():
        egreso.pagado = False
        egreso.fecha_pago = None
    egreso.save()
    return cuotas
