"""Pre-liquidación de sueldos: arma las novedades del mes con los datos que el sistema ya tiene.

Por persona y mes:
  * básico (de su ficha)
  * horas extra: de las fichadas. Las de domingo o feriado van al 100 %, el resto al 50 %.
    Valor hora = básico ÷ horas mensuales.
  * presentismo: % del básico si no tuvo faltas sin justificar y no superó las llegadas tarde toleradas.
  * días no trabajados: faltas sin justificar + días de suspensión → se descuenta básico ÷ 30 por día.
  * multas: se informan pero NO se descuentan (art. 131 Ley de Contrato de Trabajo).
  * cargas sociales del empleador → costo total para la empresa.

No reemplaza la liquidación legal (aguinaldo, retenciones, F.931): es control de costos y la
planilla de novedades para el estudio contable.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from core.models import Parametros, Persona
from personal.indicadores import resumen
from personal.models import Asistencia, Feriado
from supervision.models import AccionCorrectiva

from .models import Liquidacion

D2 = Decimal("0.01")


def _r(x) -> Decimal:
    return Decimal(x).quantize(D2, rounding=ROUND_HALF_UP)


def fin_de_mes(periodo: date) -> date:
    return (periodo.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def calcular(persona: Persona, periodo: date, liq: Liquidacion | None = None, par: Parametros | None = None) -> Liquidacion:
    par = par or Parametros.actual()
    liq = liq or Liquidacion(persona=persona, periodo=periodo)
    fin = min(fin_de_mes(periodo), timezone.localdate())
    basico = Decimal(persona.sueldo_basico or 0)
    liq.basico = basico
    feriados = set(Feriado.objects.filter(fecha__range=(periodo, fin)).values_list("fecha", flat=True))
    he50 = he100 = Decimal("0")
    for f, h in Asistencia.objects.filter(persona=persona, fecha__range=(periodo, fin), horas_extra__gt=0).values_list(
            "fecha", "horas_extra"):
        if f.weekday() == 6 or f in feriados:
            he100 += h
        else:
            he50 += h
    valor_hora = basico / par.horas_mensuales if par.horas_mensuales else Decimal("0")
    liq.horas_extra_50, liq.horas_extra_100 = he50, he100
    liq.monto_horas_extra = _r(he50 * valor_hora * (1 + Decimal(par.recargo_extra_50) / 100)
                               + he100 * valor_hora * (1 + Decimal(par.recargo_extra_100) / 100))
    asis = resumen(periodo, fin, [persona])[0]
    liq.dias_trabajados, liq.faltas_injustificadas, liq.tardanzas = asis.presentes, asis.injustificadas, asis.tardanzas
    cobra = asis.injustificadas == 0 and asis.tardanzas <= par.presentismo_tardanzas_max
    liq.presentismo = _r(basico * par.adicional_presentismo / 100) if cobra else Decimal("0")
    acciones = AccionCorrectiva.objects.filter(tecnico=persona, fecha__range=(periodo, fin))
    liq.multas = acciones.filter(tipo="multa").aggregate(t=Sum("monto"))["t"] or Decimal("0")
    dias_susp = acciones.filter(tipo="suspension").aggregate(t=Sum("dias_suspension"))["t"] or 0
    liq.dias_descuento = Decimal(asis.injustificadas + dias_susp)
    liq.descuento_dias = _r(basico / 30 * liq.dias_descuento)
    liq.bruto = _r(basico + liq.monto_horas_extra + liq.presentismo + liq.otros_adicionales
                   - liq.descuento_dias - liq.otros_descuentos)
    liq.cargas_sociales = _r(liq.bruto * par.cargas_sociales / 100)
    liq.costo_total = liq.bruto + liq.cargas_sociales
    return liq


def generar(periodo: date) -> tuple[int, int]:
    """Crea o recalcula las liquidaciones en borrador del mes. Las aprobadas o pagadas no se tocan."""
    par = Parametros.actual()
    fin = fin_de_mes(periodo)
    personas = (Persona.objects.exclude(rol="gerencia").filter(sueldo_basico__gt=0, fecha_ingreso__lte=fin)
                .filter(Q(fecha_egreso__isnull=True) | Q(fecha_egreso__gte=periodo)))
    creadas = recalculadas = 0
    for p in personas:
        liq = Liquidacion.objects.filter(persona=p, periodo=periodo).first()
        if liq and liq.estado != Liquidacion.Estado.BORRADOR:
            continue
        nueva = liq is None
        liq = calcular(p, periodo, liq, par)
        liq.save()
        creadas += nueva
        recalculadas += not nueva
    return creadas, recalculadas
