"""Partes adeudadas por los técnicos: qué deben regularizar y hace cuántos días.

Tres tipos:
  * equipo_retirado: equipo retirado a un cliente que todavía no entregó al depósito.
  * uso_sin_cargo:   usó partes que no figuraban a su cargo (saldo negativo): falta registrar de dónde salieron.
  * parte_parada:    partes a su cargo sin usar hace más del máximo de días: debe devolverlas.

Semáforo por días sin regularizar (Parámetros): verde hasta `deuda_dias_aviso`, amarillo hasta
`deuda_dias_critico`, rojo después.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from core.models import Parametros, Persona

from .models import EquipoRetirado, MovimientoStockTecnico
from .stock_tecnico import partes_paradas

QUE_HACER = {
    "equipo_retirado": "Entregalo en el depósito.",
    "uso_sin_cargo": "Avisá a tu supervisor de dónde salió para regularizarlo.",
    "parte_parada": "Devolvé al depósito lo que no vas a usar.",
}
TITULO = {
    "equipo_retirado": "Equipo retirado sin devolver",
    "uso_sin_cargo": "Parte usada sin estar a tu cargo",
    "parte_parada": "Parte sin usar hace mucho",
}


@dataclass
class Deuda:
    tipo: str
    tecnico: Persona
    descripcion: str
    desde: date
    referencia: object = None
    cantidad: Decimal | None = None

    @property
    def dias(self) -> int:
        return max(0, (timezone.localdate() - self.desde).days)

    @property
    def estado(self) -> str:
        p = Parametros.actual()
        return "critico" if self.dias > p.deuda_dias_critico else "aviso" if self.dias > p.deuda_dias_aviso else "ok"

    @property
    def titulo(self):
        return TITULO[self.tipo]

    @property
    def que_hacer(self):
        return QUE_HACER[self.tipo]


def _usos_sin_cargo(tecnicos) -> list[Deuda]:
    """Material con saldo negativo y desde qué día está en negativo (recorriendo sus movimientos)."""
    deudas = []
    corrido = defaultdict(Decimal)
    negativo_desde = {}
    for m in (MovimientoStockTecnico.objects.filter(tecnico__in=tecnicos).select_related("material", "tecnico")
              .order_by("fecha", "id")):
        k = (m.tecnico, m.material)
        corrido[k] += m.cantidad
        if corrido[k] < 0 and k not in negativo_desde:
            negativo_desde[k] = m.fecha
        elif corrido[k] >= 0:
            negativo_desde.pop(k, None)
    for (t, mat), desde in negativo_desde.items():
        deudas.append(Deuda("uso_sin_cargo", t, f"{(-corrido[(t, mat)]).normalize():f} {mat.unidad} de {mat.nombre}",
                            desde, referencia=mat, cantidad=-corrido[(t, mat)]))
    return deudas


def deudas(tecnicos=None) -> list[Deuda]:
    if tecnicos is None:
        tecnicos = Persona.objects.filter(rol="tecnico", activo=True)
    tecnicos = list(tecnicos)
    lista = [Deuda("equipo_retirado", e.tecnico,
                   f"Serie {e.numero_serie}" + (f" ({e.material.nombre})" if e.material else "")
                   + (f" · orden {e.orden.numero}" if e.orden else ""), e.fecha_retiro, referencia=e)
             for e in EquipoRetirado.objects.filter(tecnico__in=tecnicos, estado="en_tecnico")
             .select_related("material", "orden", "tecnico")]
    lista += _usos_sin_cargo(tecnicos)
    dias_max = Parametros.actual().dias_max_stock
    for f in partes_paradas(tecnicos):
        lista.append(Deuda("parte_parada", f["tecnico"], f"{f['cantidad'].normalize():f} {f['material'].unidad} de "
                           f"{f['material'].nombre} (sin usar desde el {f['desde']:%d/%m})",
                           f["desde"] + timedelta(days=dias_max), referencia=f["material"], cantidad=f["cantidad"]))
    return sorted(lista, key=lambda d: -d.dias)


def resumen_por_tecnico(lista: list[Deuda]) -> dict:
    """{tecnico: {"n": total, "rojas": n, "mas_vieja": días, "estado": peor}}"""
    res = {}
    orden = {"ok": 0, "aviso": 1, "critico": 2}
    for d in lista:
        r = res.setdefault(d.tecnico, {"n": 0, "rojas": 0, "mas_vieja": 0, "estado": "ok", "items": []})
        r["n"] += 1
        r["rojas"] += d.estado == "critico"
        r["mas_vieja"] = max(r["mas_vieja"], d.dias)
        r["items"].append(d)
        if orden[d.estado] > orden[r["estado"]]:
            r["estado"] = d.estado
    return res


def notificar_deudas(log=print) -> int:
    """Aviso diario: a cada técnico con partes adeudadas y a cada supervisor con el resumen de su equipo."""
    from core.notificaciones import notificar
    por_tec = resumen_por_tecnico(deudas())
    por_sup = defaultdict(lambda: {"tecnicos": 0, "rojas": 0, "n": 0})
    for t, r in por_tec.items():
        notificar(t, f"Tenés {r['n']} parte{'s' if r['n'] > 1 else ''} por regularizar",
                  f"La más antigua lleva {r['mas_vieja']} día{'s' if r['mas_vieja'] != 1 else ''} sin regularizar.",
                  "/app/stock/#deudas")
        if t.supervisor_id:
            s = por_sup[t.supervisor]
            s["tecnicos"] += 1
            s["n"] += r["n"]
            s["rojas"] += r["rojas"]
    for sup, s in por_sup.items():
        notificar(sup, f"Tu equipo tiene {s['n']} partes por regularizar",
                  f"{s['tecnicos']} técnico(s) · {s['rojas']} en rojo.", "/app/deudas/")
    log(f"Avisos de partes adeudadas: {len(por_tec)} técnicos, {len(por_sup)} supervisores")
    return len(por_tec)
