from .models import Alerta


def alertas(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    abiertas = Alerta.objects.filter(resuelta=False)
    return {
        "alertas_abiertas": abiertas.count(),
        "alertas_criticas": abiertas.filter(nivel=Alerta.Nivel.CRITICA).count(),
    }


def rol(request):
    from .roles import GERENCIA, SUPERVISOR, rol_de
    r = rol_de(request.user) if hasattr(request, "user") else None
    return {"rol": r, "es_gerencia": r == GERENCIA, "es_supervisor": r == SUPERVISOR}
