"""¿Las acciones correctivas funcionaron?

Se separan cuatro cosas que antes se mezclaban:
  indicada  → se registró la acción;
  cumplida  → se ejecutó (cumplida=True, con fecha);
  verificada→ después hubo controles suficientes del mismo tipo de problema;
  resultado → efectiva (no se repitió el desvío) / no efectiva (se repitió).

Sin controles posteriores suficientes la acción queda "no verificada": dejar de
controlar ya no mejora el indicador. Una acción no cumplida no entra al cálculo.
"""
from dataclasses import dataclass
from datetime import date, timedelta

from core.models import Parametros

from .models import InformeControl

PENDIENTE = "pendiente"            # indicada, no cumplida
EN_SEGUIMIENTO = "en_seguimiento"  # cumplida, todavía dentro del plazo de seguimiento
EFECTIVA = "efectiva"
NO_EFECTIVA = "no_efectiva"
NO_VERIFICADA = "no_verificada"

NOMBRES = {PENDIENTE: "Sin cumplir", EN_SEGUIMIENTO: "En seguimiento", EFECTIVA: "Efectiva",
           NO_EFECTIVA: "No efectiva (se repitió)", NO_VERIFICADA: "No verificada (faltan controles)"}


def clasificar(accion, hasta: date, p: Parametros | None = None) -> str:
    p = p or Parametros.actual()
    if not accion.cumplida:
        return PENDIENTE
    inicio = accion.fecha_cumplida or accion.fecha
    fin = inicio + timedelta(days=p.dias_verificacion_accion)
    controles = InformeControl.objects.filter(tecnico_id=accion.tecnico_id, fecha__gt=inicio,
                                              fecha__lte=min(fin, hasta))
    if accion.informe_id:  # recurrencia del mismo tipo de problema
        controles = controles.filter(tipo=accion.informe.tipo)
    if controles.filter(desvio_detectado=True).exists():
        return NO_EFECTIVA
    if controles.count() >= p.controles_verificacion_accion:
        return EFECTIVA
    return EN_SEGUIMIENTO if fin > hasta else NO_VERIFICADA


@dataclass
class Resumen:
    indicadas: int = 0
    cumplidas: int = 0
    verificadas: int = 0
    efectivas: int = 0
    no_efectivas: int = 0
    no_verificadas: int = 0
    en_seguimiento: int = 0

    @property
    def efectividad(self) -> float | None:
        """% de acciones verificadas que fueron efectivas (None con menos de 3 verificadas)."""
        return self.efectivas / self.verificadas * 100 if self.verificadas >= 3 else None


def resumir(acciones, hasta: date) -> Resumen:
    p = Parametros.actual()
    r = Resumen()
    for a in acciones:
        r.indicadas += 1
        c = clasificar(a, hasta, p)
        if c == PENDIENTE:
            continue
        r.cumplidas += 1
        if c == EFECTIVA:
            r.efectivas += 1
            r.verificadas += 1
        elif c == NO_EFECTIVA:
            r.no_efectivas += 1
            r.verificadas += 1
        elif c == NO_VERIFICADA:
            r.no_verificadas += 1
        else:
            r.en_seguimiento += 1
    return r
