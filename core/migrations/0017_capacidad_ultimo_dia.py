from django.db import migrations


def renombrar(apps, schema_editor):
    apps.get_model("core", "Indicador").objects.filter(codigo="cumplimiento_capacidad").update(
        nombre="Órdenes vs. capacidad (último día)",
        descripcion="Órdenes completadas el último día completo ÷ capacidad estimada del personal en calle ese día.")


class Migration(migrations.Migration):
    dependencies = [("core", "0016_indicadores_mando")]
    operations = [migrations.RunPython(renombrar, migrations.RunPython.noop)]
