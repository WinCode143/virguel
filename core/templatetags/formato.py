
from django import template

register = template.Library()


def _miles(v, dec=0):
    s = f"{float(v):,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


@register.filter
def pesos(v):
    if v in (None, ""):
        return "—"
    return "$" + _miles(v)


@register.filter
def num(v, dec=0):
    if v in (None, ""):
        return "—"
    return _miles(v, int(dec))


@register.filter
def pct(v, dec=0):
    """0.55 → 55%"""
    if v in (None, ""):
        return "—"
    return _miles(float(v) * 100, int(dec)) + "%"


@register.filter
def ancho(v, maximo=100):
    """Porcentaje 0-100 para barras CSS (como texto con punto: el CSS no acepta coma)."""
    try:
        return f"{max(0.0, min(100.0, float(v) / float(maximo) * 100)):.1f}"
    except (TypeError, ValueError, ZeroDivisionError):
        return "0"


@register.filter
def nivel_score(v):
    """Score 0-100 → clase de estado."""
    if v is None:
        return "info"
    return "ok" if v >= 70 else "aviso" if v >= 50 else "critico"


@register.filter
def nivel_alerta(n):
    return {"critica": "critico", "aviso": "aviso"}.get(n, "info")


@register.filter
def get(d, k):
    return d.get(k) if hasattr(d, "get") else None


@register.filter
def idx(lista, i):
    try:
        return lista[int(i)]
    except (IndexError, TypeError, ValueError):
        return None
