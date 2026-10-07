"""Pantallas de indicadores de productividad (IPT técnicos, IGS supervisores)."""
from datetime import timedelta

from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.models import Indicador, Persona
from core.roles import GERENCIA, SUPERVISOR, persona_de, requiere_rol, rol_de

from .metricas import referencia_equipo, tableros_supervisores, tableros_tecnicos
from .views import grafico


def _dias(request):
    try:
        return max(7, min(180, int(request.GET.get("dias", 30))))
    except ValueError:
        return 30


def _tecnicos_visibles(request):
    qs = Persona.objects.filter(rol="tecnico", activo=True)
    if rol_de(request.user) == SUPERVISOR:
        qs = qs.filter(supervisor=persona_de(request.user))
    return qs


@requiere_rol(GERENCIA, SUPERVISOR)
def tecnicos(request):
    dias = _dias(request)
    tbs = tableros_tecnicos(dias=dias, tecnicos=_tecnicos_visibles(request))
    ref = referencia_equipo(tableros_tecnicos(dias=dias))  # referencia: todo el plantel
    indicadores = list(Indicador.objects.filter(rol="tecnico", activo=True))
    return render(request, "tablero/productividad_tecnicos.html", {
        "tbs": tbs, "indicadores": indicadores, "ref": ref, "dias": dias,
        "g": grafico("bar", [tb.persona.apellido for tb in tbs],
                     [{"nombre": "IPT", "datos": [tb.indice for tb in tbs], "serie": 1}], max=100)})


@requiere_rol(GERENCIA)
def supervisores(request):
    dias = _dias(request)
    tbs = tableros_supervisores(dias=dias)
    return render(request, "tablero/productividad_supervisores.html", {
        "tbs": tbs, "indicadores": list(Indicador.objects.filter(rol="supervisor", activo=True)),
        "ref": referencia_equipo(tbs), "dias": dias})


@requiere_rol(GERENCIA, SUPERVISOR)
def ficha(request, pk):
    """Tarjeta de indicadores de una persona, con referencia del grupo y evolución del índice."""
    dias = _dias(request)
    if rol_de(request.user) == SUPERVISOR:
        yo = persona_de(request.user)
        p = get_object_or_404(Persona, pk=pk, supervisor=yo) if pk != yo.pk else yo
    else:
        p = get_object_or_404(Persona, pk=pk, rol__in=["tecnico", "supervisor"])
    hoy = timezone.localdate()
    if p.rol == "tecnico":
        todos = tableros_tecnicos(dias=dias)
        calcular = lambda hasta: tableros_tecnicos(hasta=hasta, dias=dias, tecnicos=[p])[0].indice  # noqa: E731
    else:
        todos = tableros_supervisores(dias=dias)
        calcular = lambda hasta: tableros_supervisores(hasta=hasta, dias=dias, supervisores=[p])[0].indice  # noqa: E731
    tb = next(t for t in todos if t.persona.id == p.id)
    ref = referencia_equipo(todos)
    posicion = [t.persona.id for t in todos].index(p.id) + 1
    semanas = [hoy - timedelta(weeks=n) for n in range(11, -1, -1)]
    g = grafico("line", [s.strftime("%d/%m") for s in semanas],
                [{"nombre": "Índice", "datos": [calcular(s) for s in semanas], "serie": 1}], max=100)
    return render(request, "tablero/productividad_ficha.html", {
        "p": p, "tb": tb, "ref": ref, "posicion": posicion, "total": len(todos), "g": g, "dias": dias,
        "sigla": "IPT" if p.rol == "tecnico" else "IGS"})
