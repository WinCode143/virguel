"""Vistas SQL planas (esquema `powerbi`) para conectar Power BI directo a PostgreSQL.

Cada vista ya trae los nombres legibles (técnico, supervisor, zona, tipo...)
para que en Power BI no haga falta armar relaciones complejas.
"""
from django.db import migrations

VISTAS = {
    "ordenes": """
        SELECT o.id, o.numero, tt.nombre AS tipo_tarea, tt.minutos_estandar, o.estado,
               o.fecha_programada, o.fecha_ejecucion, o.minutos_reales,
               o.decodificador_solicitado, o.decodificadores_instalados, o.es_retrabajo,
               t.legajo AS tecnico_legajo, t.apellido || ', ' || t.nombre AS tecnico,
               s.apellido || ', ' || s.nombre AS supervisor, z.nombre AS zona,
               c.numero AS cliente_numero, c.tipo AS cliente_tipo
        FROM operaciones_ordentrabajo o
        JOIN operaciones_tipotarea tt ON tt.id = o.tipo_id
        LEFT JOIN core_persona t ON t.id = o.tecnico_id
        LEFT JOIN core_persona s ON s.id = t.supervisor_id
        LEFT JOIN core_zona z ON z.id = o.zona_id
        LEFT JOIN core_cliente c ON c.id = o.cliente_id""",
    "jornadas": """
        SELECT j.id, j.fecha, j.en_calle, j.motivo_ausencia, j.hectareas_cubiertas, j.horas_trabajadas,
               j.km_fin - j.km_inicio AS km_recorridos,
               t.legajo AS tecnico_legajo, t.apellido || ', ' || t.nombre AS tecnico,
               s.apellido || ', ' || s.nombre AS supervisor, z.nombre AS zona, v.patente AS vehiculo
        FROM operaciones_jornada j
        JOIN core_persona t ON t.id = j.tecnico_id
        LEFT JOIN core_persona s ON s.id = t.supervisor_id
        LEFT JOIN core_zona z ON z.id = j.zona_id
        LEFT JOIN flota_vehiculo v ON v.id = j.vehiculo_id""",
    "stock_lotes": """
        SELECT l.id, m.codigo, m.nombre AS material, m.categoria, m.unidad, l.fecha AS fecha_ingreso,
               l.cantidad, l.cantidad_disponible, l.costo_unitario,
               l.cantidad_disponible * l.costo_unitario AS valor_disponible,
               (CURRENT_DATE - l.fecha) AS dias_en_stock, l.proveedor, l.remito
        FROM inventario_loteingreso l JOIN inventario_material m ON m.id = l.material_id""",
    "salidas": """
        SELECT sa.id, sa.fecha, m.codigo, m.nombre AS material, m.categoria, sa.cantidad, sa.motivo,
               sa.costo_total, t.apellido || ', ' || t.nombre AS tecnico, o.numero AS orden
        FROM inventario_salida sa
        JOIN inventario_material m ON m.id = sa.material_id
        LEFT JOIN core_persona t ON t.id = sa.tecnico_id
        LEFT JOIN operaciones_ordentrabajo o ON o.id = sa.orden_id""",
    "demanda": """
        SELECT d.id, d.fecha, z.nombre AS zona, tt.nombre AS tipo_tarea, d.cantidad_clientes
        FROM inventario_demandacomercial d
        JOIN operaciones_tipotarea tt ON tt.id = d.tipo_tarea_id
        LEFT JOIN core_zona z ON z.id = d.zona_id""",
    "informes": """
        SELECT i.id, i.fecha, i.tipo, i.puntaje, i.desvio_detectado, length(i.descripcion) AS largo_descripcion,
               (i.foto <> '') AS tiene_foto, (i.latitud IS NOT NULL) AS tiene_ubicacion,
               s.apellido || ', ' || s.nombre AS supervisor, t.apellido || ', ' || t.nombre AS tecnico,
               (SELECT count(*) FROM supervision_accioncorrectiva a WHERE a.informe_id = i.id) AS acciones
        FROM supervision_informecontrol i
        JOIN core_persona s ON s.id = i.supervisor_id
        JOIN core_persona t ON t.id = i.tecnico_id""",
    "acciones": """
        SELECT a.id, a.fecha, a.tipo, a.monto, a.cumplida, t.apellido || ', ' || t.nombre AS tecnico,
               p.apellido || ', ' || p.nombre AS aplicada_por, i.fecha AS fecha_desvio,
               a.fecha - i.fecha AS dias_respuesta
        FROM supervision_accioncorrectiva a
        JOIN core_persona t ON t.id = a.tecnico_id
        LEFT JOIN core_persona p ON p.id = a.aplicada_por_id
        LEFT JOIN supervision_informecontrol i ON i.id = a.informe_id""",
    "encuestas": """
        SELECT e.id, e.fecha, e.respondida IS NOT NULL AS respondida, e.trato, e.claridad, e.apoyo, e.presencia,
               s.apellido || ', ' || s.nombre AS supervisor, t.legajo AS tecnico_legajo
        FROM supervision_encuestasupervisor e
        JOIN core_persona s ON s.id = e.supervisor_id
        JOIN core_persona t ON t.id = e.tecnico_id""",
    "siniestros": """
        SELECT x.id, x.numero, x.fecha, x.tipo, x.gravedad, x.responsabilidad_civil, x.estado, x.resolucion,
               x.costo_estimado, x.costo_real, x.monto_recuperado, x.fecha_cierre,
               t.apellido || ', ' || t.nombre AS tecnico, s.apellido || ', ' || s.nombre AS supervisor,
               z.nombre AS zona
        FROM incidentes_siniestro x
        LEFT JOIN core_persona t ON t.id = x.tecnico_id
        LEFT JOIN core_persona s ON s.id = x.supervisor_id
        LEFT JOIN core_zona z ON z.id = x.zona_id""",
    "egresos": """
        SELECT e.id, e.fecha, c.nombre AS categoria, e.monto, e.descripcion, e.automatico, e.origen
        FROM finanzas_egreso e JOIN finanzas_categoriaegreso c ON c.id = e.categoria_id""",
    "services": """
        SELECT sr.id, sr.fecha, v.patente, v.marca, v.modelo, ts.nombre AS tipo_service, sr.km, sr.costo, sr.taller
        FROM flota_servicerealizado sr
        JOIN flota_vehiculo v ON v.id = sr.vehiculo_id
        JOIN flota_tiposervice ts ON ts.id = sr.tipo_id""",
    "epp": """
        SELECT a.id, a.fecha_entrega, a.fecha_vencimiento, a.estado, a.cantidad, a.conformidad_firmada,
               el.nombre AS elemento, el.tipo, el.obligatorio_tecnicos, el.costo,
               p.apellido || ', ' || p.nombre AS persona, p.rol
        FROM herramientas_asignacion a
        JOIN herramientas_elemento el ON el.id = a.elemento_id
        JOIN core_persona p ON p.id = a.persona_id""",
}

CREAR = "CREATE SCHEMA IF NOT EXISTS powerbi;\n" + "\n".join(
    f"CREATE OR REPLACE VIEW powerbi.{nombre} AS {sql};" for nombre, sql in VISTAS.items())
BORRAR = "DROP SCHEMA IF EXISTS powerbi CASCADE;"


class Migration(migrations.Migration):
    dependencies = [
        ("core", "__latest__"), ("operaciones", "__latest__"), ("inventario", "__latest__"),
        ("supervision", "__latest__"), ("incidentes", "__latest__"), ("finanzas", "__latest__"),
        ("flota", "__latest__"), ("herramientas", "__latest__"),
    ]
    operations = [migrations.RunSQL(CREAR, BORRAR)]
