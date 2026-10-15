"""Metas efectivas: la del equipo (si su supervisor o gerencia la fijó) o, si no, la general."""
import copy

from .models import Indicador, MetaEquipo


def indicadores_efectivos(rol: str, supervisor=None, al=None) -> list[Indicador]:
    """Indicadores activos del rol con meta/límite ajustados al equipo del supervisor indicado.
    Con `al` (fecha), el criterio general es el vigente en esa fecha (Indicador.en)."""
    if al is None:
        lista = list(Indicador.objects.filter(rol=rol, activo=True))
    else:
        lista = [i for i in (x.en(al) for x in Indicador.objects.filter(rol=rol)) if i.activo]
    if supervisor is None:
        return lista
    propias = {m.indicador_id: m for m in MetaEquipo.objects.filter(supervisor=supervisor, indicador__rol=rol)}
    res = []
    for i in lista:
        m = propias.get(i.id)
        if m:
            i = copy.copy(i)
            i.meta, i.minimo, i.ajustada_por_equipo = m.meta, m.minimo, True
        res.append(i)
    return res


def mapa(rol: str, supervisor=None) -> dict:
    return {i.codigo: i for i in indicadores_efectivos(rol, supervisor)}
