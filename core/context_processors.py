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
    from .roles import DEPOSITO, GERENCIA, SUPERVISOR, rol_de
    r = rol_de(request.user) if hasattr(request, "user") else None
    return {"rol": r, "es_gerencia": r == GERENCIA, "es_supervisor": r == SUPERVISOR, "es_deposito": r == DEPOSITO}


def movil(request):
    """Datos del encabezado de la app: notificaciones sin leer y evaluación semanal pendiente."""
    if not request.path.startswith("/app/") or not request.user.is_authenticated:
        return {}
    p = getattr(request.user, "persona", None)
    if p is None:
        return {}
    from datetime import timedelta

    from django.utils import timezone

    from supervision.models import EncuestaSemanal
    hoy = timezone.localdate()
    lunes = hoy - timedelta(days=hoy.weekday())
    pendiente = (p.rol == "tecnico" and p.supervisor_id is not None
                 and not EncuestaSemanal.objects.filter(tecnico=p, semana=lunes).exists())
    return {"notificaciones_sin_leer": p.notificaciones.filter(leida=False).count(),
            "encuesta_semanal_pendiente": pendiente}
