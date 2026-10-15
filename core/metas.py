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
    if al is not None:
        # meta del equipo vigente en esa fecha (si hay historial): la última versión desde esa fecha o antes
        from .models import VersionMetaEquipo
        versiones = {}
        for v in VersionMetaEquipo.objects.filter(supervisor=supervisor, indicador__rol=rol,
                                                  vigente_desde__lte=al).order_by("vigente_desde", "creada"):
            versiones[v.indicador_id] = v
        con_historial = set(VersionMetaEquipo.objects.filter(supervisor=supervisor, indicador__rol=rol)
                            .values_list("indicador_id", flat=True))
        propias = {iid: m for iid, m in propias.items() if iid not in con_historial}
        propias.update({iid: v for iid, v in versiones.items() if v.meta is not None})
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
