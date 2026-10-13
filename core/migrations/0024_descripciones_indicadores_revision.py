"""Descripciones de indicadores según los criterios corregidos en la revisión del 12/10/2026."""
from django.db import migrations

TEXTOS = {
    "no_resueltas_evitables": "Visitas no resueltas atribuidas al técnico ÷ visitas ejecutadas. Usa el catálogo "
                              "común de motivos: cliente ausente, clima o red no cuentan; falta de material, "
                              "rechazo u otro cuentan sólo si el supervisor confirma que fue por el técnico.",
    "efectividad_correccion": "Acciones correctivas cumplidas y verificadas (con controles posteriores suficientes) "
                              "en las que no se repitió el mismo problema en el seguimiento. Sin controles "
                              "suficientes la acción queda 'no verificada' y no suma.",
}


def actualizar(apps, schema_editor):
    Indicador = apps.get_model("core", "Indicador")
    for codigo, texto in TEXTOS.items():
        Indicador.objects.filter(codigo=codigo).update(descripcion=texto)


class Migration(migrations.Migration):
    dependencies = [("core", "0023_historial_supervisores")]
    operations = [migrations.RunPython(actualizar, migrations.RunPython.noop)]
