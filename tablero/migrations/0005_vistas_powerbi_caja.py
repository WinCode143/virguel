"""Vistas de Power BI del flujo de fondos: ingresos, cobros, pagos y cuotas."""
from django.db import migrations

SQL = """
CREATE OR REPLACE VIEW powerbi.ingresos AS
SELECT i.id, i.fecha, i.periodo, i.pagador, i.concepto, i.numero_comprobante, i.monto,
       i.fecha_esperada_cobro, COALESCE(SUM(c.monto), 0) AS cobrado, i.monto - COALESCE(SUM(c.monto), 0) AS saldo
FROM finanzas_ingreso i LEFT JOIN finanzas_cobro c ON c.ingreso_id = i.id
GROUP BY i.id;

CREATE OR REPLACE VIEW powerbi.cobros AS
SELECT c.id, c.fecha, c.monto, cu.nombre AS cuenta, i.pagador, i.concepto, i.id AS ingreso_id
FROM finanzas_cobro c JOIN finanzas_ingreso i ON i.id = c.ingreso_id
LEFT JOIN finanzas_cuenta cu ON cu.id = c.cuenta_id;

CREATE OR REPLACE VIEW powerbi.pagos AS
SELECT p.id, p.fecha, p.monto, p.medio, p.automatico, cu.nombre AS cuenta, e.id AS egreso_id,
       e.descripcion, e.proveedor, cat.nombre AS categoria
FROM finanzas_pago p JOIN finanzas_egreso e ON e.id = p.egreso_id
JOIN finanzas_categoriaegreso cat ON cat.id = e.categoria_id
LEFT JOIN finanzas_cuenta cu ON cu.id = p.cuenta_id;

CREATE OR REPLACE VIEW powerbi.cuotas AS
SELECT q.id, q.egreso_id, q.numero, q.vencimiento, q.monto, e.descripcion, e.proveedor
FROM finanzas_cuota q JOIN finanzas_egreso e ON e.id = q.egreso_id;
"""
BORRAR = """
DROP VIEW IF EXISTS powerbi.cuotas; DROP VIEW IF EXISTS powerbi.pagos;
DROP VIEW IF EXISTS powerbi.cobros; DROP VIEW IF EXISTS powerbi.ingresos;
"""


class Migration(migrations.Migration):
    dependencies = [("tablero", "0004_initial"), ("finanzas", "0006_ingresos_cobros_pagos_caja")]
    operations = [migrations.RunSQL(SQL, BORRAR)]
