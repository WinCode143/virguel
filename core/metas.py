"""Metas efectivas: la del equipo (si su supervisor o gerencia la fijó) o, si no, la general."""
import copy

from .models import Indicador, MetaEquipo


def indicadores_efectivos(rol: str, supervisor=None) -> list[Indicador]:
    """Indicadores activos del rol con meta/límite ajustados al equipo del supervisor indicado."""
    lista = list(Indicador.objects.filter(rol=rol, activo=True))
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
