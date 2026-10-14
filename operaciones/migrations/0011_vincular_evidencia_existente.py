"""Vincula consumos, gastos y equipos retirados existentes con su visita cuando no hay ambigüedad
(una sola visita de esa orden, de ese técnico, ese día). Lo ambiguo queda sin vincular (origen pendiente)."""
from collections import defaultdict

from django.db import migrations


def vincular(apps, schema_editor):
    Intento = apps.get_model("operaciones", "Intento")
    Orden = apps.get_model("operaciones", "OrdenTrabajo")
    clave = defaultdict(list)
    for i in Intento.objects.values("id", "orden_id", "tecnico_id", "fecha"):
        clave[(i["orden_id"], i["tecnico_id"], i["fecha"])].append(i["id"])
    unicos = {k: v[0] for k, v in clave.items() if len(v) == 1}
    for modelo, campo_fecha in (("inventario.Salida", "fecha"), ("operaciones.GastoOrden", "fecha"),
                                ("inventario.EquipoRetirado", "fecha_retiro")):
        M = apps.get_model(*modelo.split("."))
        for obj in M.objects.filter(orden__isnull=False, intento__isnull=True).values("id", "orden_id", "tecnico_id",
                                                                                     campo_fecha):
            iid = unicos.get((obj["orden_id"], obj["tecnico_id"], obj[campo_fecha]))
            if iid:
                M.objects.filter(pk=obj["id"]).update(intento_id=iid)
    # instantánea de evidencias de la última visita de cada orden (lo que la orden tiene hoy)
    ultimos = {}
    for i in Intento.objects.order_by("orden_id", "numero").values("id", "orden_id"):
        ultimos[i["orden_id"]] = i["id"]
    for o in Orden.objects.filter(id__in=list(ultimos)).values("id", "series_instaladas", "series_retiradas",
                                                               "foto_trabajo", "firma", "lat_cierre", "lng_cierre"):
        Intento.objects.filter(pk=ultimos[o["id"]]).update(
            series_instaladas=o["series_instaladas"] or "", series_retiradas=o["series_retiradas"] or "",
            foto=o["foto_trabajo"] or "", firma=o["firma"] or "", lat=o["lat_cierre"], lng=o["lng_cierre"])


class Migration(migrations.Migration):
    dependencies = [("operaciones", "0010_evidencia_por_visita"), ("inventario", "0009_evidencia_por_visita")]
    operations = [migrations.RunPython(vincular, migrations.RunPython.noop)]
