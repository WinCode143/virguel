"""Vistas de Power BI de control de personal (asistencia y novedades)."""
from django.db import migrations

SQL = """
CREATE OR REPLACE VIEW powerbi.asistencia AS
SELECT a.id, a.fecha, p.legajo, p.apellido || ', ' || p.nombre AS persona, p.rol,
       s.apellido || ', ' || s.nombre AS supervisor, a.entrada, a.salida, a.minutos_tarde,
       a.horas_trabajadas, a.horas_extra, a.origen,
       (a.lat_entrada IS NOT NULL) AS con_ubicacion
FROM personal_asistencia a
JOIN core_persona p ON p.id = a.persona_id
LEFT JOIN core_persona s ON s.id = p.supervisor_id;

CREATE OR REPLACE VIEW powerbi.novedades AS
SELECT n.id, p.legajo, p.apellido || ', ' || p.nombre AS persona, p.rol,
       s.apellido || ', ' || s.nombre AS supervisor, n.tipo, n.estado, n.desde, n.hasta,
       (n.hasta - n.desde + 1) AS dias, (n.certificado <> '') AS con_certificado
FROM personal_novedad n
JOIN core_persona p ON p.id = n.persona_id
LEFT JOIN core_persona s ON s.id = p.supervisor_id;

CREATE OR REPLACE VIEW powerbi.personal AS
SELECT p.id, p.legajo, p.apellido, p.nombre, p.rol, s.apellido || ', ' || s.nombre AS supervisor,
       z.nombre AS zona, p.fecha_ingreso, p.fecha_egreso, p.motivo_egreso, p.activo,
       p.hora_entrada, p.hora_salida
FROM core_persona p
LEFT JOIN core_persona s ON s.id = p.supervisor_id
LEFT JOIN core_zona z ON z.id = p.zona_id;
"""


class Migration(migrations.Migration):
    dependencies = [("tablero", "0002_vista_powerbi_historial"), ("personal", "0001_initial"),
                    ("core", "0005_alerta_modulo_personal")]
    operations = [migrations.RunSQL(SQL, "DROP VIEW IF EXISTS powerbi.asistencia; DROP VIEW IF EXISTS powerbi.novedades; "
                                         "DROP VIEW IF EXISTS powerbi.personal;")]
