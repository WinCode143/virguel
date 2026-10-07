"""Catálogo inicial de indicadores de productividad (editable desde el admin)."""
from django.db import migrations

# (codigo, nombre, unidad, meta, minimo, mayor_es_mejor, peso, descripcion)
TECNICO = [
    ("eficiencia_jornada", "Eficiencia de la jornada", "%", 70, 40, True, 25,
     "Horas estándar de trabajo producidas ÷ horas trabajadas (fichadas). Cada orden completada suma su "
     "tiempo estándar: así una instalación vale más que un retiro y no conviene elegir trabajos fáciles."),
    ("primera_visita", "Resuelto en la primera visita", "%", 95, 80, True, 20,
     "Órdenes completadas que NO necesitaron una visita de corrección (retrabajo) después."),
    ("cumplimiento_agenda", "Cumplimiento de la agenda", "%", 90, 70, True, 10,
     "Órdenes asignadas para los días trabajados que quedaron resueltas ese mismo día."),
    ("calidad_controles", "Calidad en los controles", "%", 90, 60, True, 10,
     "Puntaje promedio que le dio el supervisor en los controles en calle (5/5 = 100 %)."),
    ("no_resueltas_evitables", "No resueltas por causa propia", "%", 2, 10, False, 5,
     "Órdenes no resueltas por motivos que dependen del técnico (faltó material, otro) ÷ ejecutadas. "
     "Cliente ausente, clima o problema de red NO cuentan."),
    ("ot_por_dia", "Órdenes por día vs. el equipo", "%", 100, 60, True, 5,
     "Órdenes completadas por día en calle, como % de la mediana de todo el plantel."),
    ("documentacion_cierre", "Cierres documentados", "%", 90, 50, True, 5,
     "Órdenes completadas cerradas con foto del trabajo y conformidad del cliente (nombre o firma)."),
    ("cierre_en_sitio", "Cierres en el domicilio", "%", 95, 70, True, 5,
     "Cierres cuya ubicación GPS está a menos de 300 m del domicilio del cliente."),
    ("consumo_vs_estandar", "Consumo de materiales vs. estándar", "%", 100, 130, False, 5,
     "Costo de materiales usados ÷ costo estándar según el tipo de trabajo. Más de 100 % = usa de más."),
    ("puntualidad", "Puntualidad", "%", 97, 85, True, 5,
     "Días fichados sin llegada tarde (fuera de la tolerancia)."),
    ("presentismo", "Presentismo", "%", 97, 85, True, 5,
     "Días trabajados ÷ días que debía trabajar (sin contar vacaciones ni francos)."),
    ("arranque", "Demora en arrancar", "min", 30, 75, False, 0,
     "Minutos promedio entre la fichada de entrada y el inicio del primer trabajo. Informativo."),
    ("minutos_vs_estandar", "Tiempo por orden vs. estándar", "%", 100, 140, False, 0,
     "Minutos reales ÷ minutos estándar de las órdenes completadas. Informativo (ya está en la eficiencia)."),
]
SUPERVISOR = [
    ("eficiencia_equipo", "Eficiencia de su equipo", "%", 70, 45, True, 10,
     "Promedio de la eficiencia de la jornada de los técnicos a cargo."),
    ("primera_visita_equipo", "Resuelto en primera visita (equipo)", "%", 95, 80, True, 10,
     "Promedio del indicador de primera visita de los técnicos a cargo."),
    ("mejora_equipo", "Mejora del equipo", "%", 5, -10, True, 5,
     "Variación de las órdenes por día del equipo: últimas 4 semanas vs. las 4 anteriores."),
    ("cobertura_control", "Cobertura de control", "%", 100, 60, True, 15,
     "Semanas-técnico con al menos un control en calle ÷ semanas-técnico trabajadas."),
    ("respuesta_desvios", "Desvíos resueltos en 2 días", "%", 90, 50, True, 10,
     "Desvíos detectados que tuvieron acción correctiva dentro de los 2 días (se calcula con 3 o más desvíos)."),
    ("efectividad_correccion", "Efectividad de las correcciones", "%", 80, 40, True, 10,
     "Técnicos corregidos que NO repitieron un desvío en los 30 días siguientes."),
    ("clima_equipo", "Clima del equipo", "%", 80, 50, True, 15,
     "Encuesta diaria y evaluación semanal de los técnicos, llevadas a 0-100 %."),
    ("presentismo_equipo", "Presentismo del equipo", "%", 96, 88, True, 0,
     "Presentismo promedio de los técnicos a cargo. Informativo (lo que depende del supervisor se mide en "
     "las faltas sin aviso)."),
    ("faltas_sin_aviso", "Faltas sin aviso del equipo", "c/100 jornadas", 0.5, 3, False, 5,
     "Faltas injustificadas cada 100 jornadas esperadas del equipo."),
    ("seguridad_equipo", "Siniestros del equipo", "c/1000 jornadas", 2, 10, False, 5,
     "Siniestros cada 1000 jornadas en calle del equipo."),
    ("objetivos", "Objetivos cumplidos", "%", 90, 50, True, 10,
     "Cumplimiento de los objetivos diarios asignados por gerencia."),
    ("tiempo_respuesta", "Tiempo de respuesta a su equipo", "h", 4, 48, False, 5,
     "Horas promedio en aprobar o rechazar avisos de ausencia y pedidos de partes."),
    ("puntualidad_propia", "Su propia puntualidad", "%", 97, 85, True, 0,
     "Días fichados sin llegada tarde del propio supervisor. Informativo."),
]


def cargar(apps, schema_editor):
    Indicador = apps.get_model("core", "Indicador")
    for rol, lista in (("tecnico", TECNICO), ("supervisor", SUPERVISOR)):
        for orden, (codigo, nombre, unidad, meta, minimo, mayor, peso, desc) in enumerate(lista):
            Indicador.objects.update_or_create(codigo=codigo, defaults=dict(
                rol=rol, nombre=nombre, unidad=unidad, meta=meta, minimo=minimo, mayor_es_mejor=mayor,
                peso=peso, descripcion=desc, orden=orden))


class Migration(migrations.Migration):
    dependencies = [("core", "0008_indicador")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
