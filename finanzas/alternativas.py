"""Comparar alternativas de pago a valor presente (contado vs. cuotas).

Con un costo del dinero mensual (Parámetros → tasa_descuento_mensual), cada cuota futura vale menos
hoy. La alternativa más barata es la de menor valor presente. Es una ayuda para decidir, no
considera inflación por separado ni beneficios impositivos.
"""
from decimal import Decimal


def valor_presente(cuotas: int, monto_cuota: Decimal, tasa_mensual: Decimal, anticipo: Decimal = Decimal("0"),
                   primera_en_meses: int = 1) -> Decimal:
    i = Decimal(tasa_mensual) / 100
    vp = Decimal(anticipo)
    for n in range(cuotas):
        vp += Decimal(monto_cuota) / (1 + i) ** (primera_en_meses + n)
    return vp.quantize(Decimal("0.01"))


def comparar(alternativas: list[dict], tasa_mensual: Decimal) -> list[dict]:
    """alternativas: [{"nombre", "anticipo", "cuotas", "monto_cuota", "primera_en_meses"}] → ordenadas por VP."""
    filas = []
    for a in alternativas:
        cuotas = int(a.get("cuotas") or 0)
        total = Decimal(a.get("anticipo") or 0) + Decimal(a.get("monto_cuota") or 0) * cuotas
        vp = valor_presente(cuotas, Decimal(a.get("monto_cuota") or 0), tasa_mensual, Decimal(a.get("anticipo") or 0),
                            int(a.get("primera_en_meses") or 1))
        filas.append({**a, "total": total, "valor_presente": vp})
    filas.sort(key=lambda f: f["valor_presente"])
    if filas:
        mejor = filas[0]["valor_presente"]
        for f in filas:
            f["diferencia"] = f["valor_presente"] - mejor
            f["mejor"] = f is filas[0]
    return filas
