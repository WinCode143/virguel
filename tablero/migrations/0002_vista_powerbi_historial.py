"""Vista de Power BI con el historial semanal de evaluación de técnicos."""
from django.db import migrations

SQL = """
CREATE OR REPLACE VIEW powerbi.evaluacion_historica AS
SELECT h.fecha, p.legajo, p.apellido || ', ' || p.nombre AS tecnico,
       s.apellido || ', ' || s.nombre AS supervisor, z.nombre AS zona,
       h.productividad, h.indice_productividad, h.score_productividad, h.score_calidad,
       h.score_disciplina, h.score_seguridad, h.riesgo, h.diagnostico
FROM capacitacion_evaluacionhistorica h
JOIN core_persona p ON p.id = h.persona_id
LEFT JOIN core_persona s ON s.id = p.supervisor_id
LEFT JOIN core_zona z ON z.id = p.zona_id;
"""


class Migration(migrations.Migration):
    dependencies = [("tablero", "0001_vistas_powerbi"), ("capacitacion", "0002_evaluacionhistorica")]
    operations = [migrations.RunSQL(SQL,
                                    "DROP VIEW IF EXISTS powerbi.evaluacion_historica;")]
