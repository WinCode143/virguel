from django.db import migrations


def convertir(apps, schema_editor):
    Egreso = apps.get_model("finanzas", "Egreso")
    Proveedor = apps.get_model("finanzas", "Proveedor")
    for nombre in Egreso.objects.exclude(proveedor="").values_list("proveedor", flat=True).distinct():
        p, _ = Proveedor.objects.get_or_create(nombre=nombre.strip()[:120])
        Egreso.objects.filter(proveedor=nombre, proveedor_ref__isnull=True).update(proveedor_ref=p)


class Migration(migrations.Migration):
    dependencies = [("finanzas", "0003_egreso_fecha_pago_egreso_medio_pago_egreso_pagado_and_more")]
    operations = [migrations.RunPython(convertir, migrations.RunPython.noop)]
