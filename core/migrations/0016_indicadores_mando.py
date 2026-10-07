"""Indicadores del tablero de mando (Resumen de gerencia y de cada supervisor)."""
from django.db import migrations

# (codigo, nombre, unidad, meta, limite_rojo, mayor_es_mejor, descripcion)
MANDO = [
    ("presentismo_hoy", "Presentes hoy", "%", 95, 85, True, "Personas presentes ÷ personas que debían trabajar hoy."),
    ("sin_aviso_hoy", "Sin fichar y sin aviso hoy", "personas", 0, 3, False, "Personas que debían trabajar, no ficharon y no avisaron."),
    ("tarde_hoy", "Llegadas tarde hoy", "personas", 1, 5, False, "Personas que ficharon después del horario más la tolerancia."),
    ("presentismo_mes", "Presentismo del mes", "%", 97, 90, True, "Días trabajados ÷ días que debían trabajar en el mes."),
    ("cumplimiento_capacidad", "Órdenes vs. capacidad (hoy)", "%", 90, 70, True,
     "Órdenes completadas hoy ÷ capacidad estimada del personal en calle."),
    ("ipt_promedio", "Productividad de técnicos (IPT)", "pts", 75, 55, True, "Promedio del Índice de Productividad del Técnico."),
    ("igs_promedio", "Gestión de supervisores (IGS)", "pts", 75, 55, True, "Promedio del Índice de Gestión del Supervisor."),
    ("tecnicos_riesgo", "Técnicos en riesgo alto", "personas", 0, 3, False, "Técnicos con diagnóstico 'Riesgo alto – evaluar desvinculación'."),
    ("partes_adeudadas", "Partes adeudadas en rojo", "casos", 0, 5, False,
     "Equipos o partes que los técnicos deben regularizar hace más días que lo tolerado."),
    ("siniestros_mes", "Siniestros del mes", "casos", 0, 3, False, "Incidentes y daños registrados en el mes."),
    ("docs_vencidos", "Documentación vencida o faltante", "casos", 0, 5, False, "Documentos obligatorios del personal vencidos o sin presentar."),
    ("stock_parado", "Stock parado +60 días", "$", 0, 5000000, False, "Valor de los lotes del depósito con más días que el máximo."),
    ("alertas_criticas", "Alertas críticas abiertas", "alertas", 0, 10, False, "Alertas críticas sin resolver."),
]


def cargar(apps, schema_editor):
    Indicador = apps.get_model("core", "Indicador")
    for orden, (codigo, nombre, unidad, meta, lim, mayor, desc) in enumerate(MANDO):
        Indicador.objects.update_or_create(codigo=codigo, defaults=dict(
            rol="mando", nombre=nombre, unidad=unidad, meta=meta, minimo=lim, mayor_es_mejor=mayor, peso=0,
            descripcion=desc, orden=orden))


class Migration(migrations.Migration):
    dependencies = [("core", "0015_indicador_valores_grandes")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
