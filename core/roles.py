"""Roles de acceso. Cada persona ve una 'cara' distinta del sistema:

* técnico      → app móvil (/app/): su día, órdenes, materiales, EPP, encuesta.
* supervisor   → app móvil en modo supervisor + tableros de su equipo en PC.
* gerencia / administración / superusuario → aplicación de escritorio completa.
* depósito     → sólo inventario, partes de técnicos, pedidos y herramientas.
* contabilidad → finanzas: egresos, comprobantes, reintegros, presupuestos y costos fijos.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

TECNICO, SUPERVISOR, GERENCIA, DEPOSITO, CONTABILIDAD = "tecnico", "supervisor", "gerencia", "deposito", "contabilidad"


def rol_de(user) -> str | None:
    if not user.is_authenticated:
        return None
    grupos = set(user.groups.values_list("name", flat=True))
    if user.is_superuser or grupos & {"Gerencia", "Administración"}:
        return GERENCIA
    if "Contabilidad" in grupos:
        return CONTABILIDAD
    if "Depósito" in grupos:
        return DEPOSITO
    persona = getattr(user, "persona", None)
    if persona is None:
        return GERENCIA if user.is_staff else None
    if persona.rol in ("gerencia", "administrativo"):
        return GERENCIA
    return persona.rol


def persona_de(user):
    return getattr(user, "persona", None) if user.is_authenticated else None


def requiere_rol(*roles):
    def deco(vista):
        @login_required
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if rol_de(request.user) not in roles:
                raise PermissionDenied("No tiene acceso a esta sección.")
            return vista(request, *args, **kwargs)
        return envoltura
    return deco
