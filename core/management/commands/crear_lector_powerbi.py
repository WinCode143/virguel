"""Crea (o actualiza) un usuario de PostgreSQL de sólo lectura para Power BI.

    python manage.py crear_lector_powerbi --password <clave>

Sólo puede leer las vistas del esquema `powerbi`, no las tablas internas.
"""
from django.core.management.base import BaseCommand
from django.db import connection
from psycopg import sql


class Command(BaseCommand):
    help = "Crea el usuario de sólo lectura 'powerbi_lector' para conectar Power BI a PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument("--usuario", default="powerbi_lector")
        parser.add_argument("--password", required=True)

    def handle(self, *args, usuario, password, **opts):
        u = sql.Identifier(usuario)
        with connection.cursor() as c:
            c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [usuario])
            if c.fetchone():
                c.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(u, sql.Literal(password)))
            else:
                c.execute(sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {}").format(u, sql.Literal(password)))
            c.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(connection.settings_dict["NAME"]), u))
            c.execute(sql.SQL("GRANT USAGE ON SCHEMA powerbi TO {}").format(u))
            c.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA powerbi TO {}").format(u))
            # Las vistas leen tablas de 'public' con permisos del dueño: el lector no necesita acceso a 'public'.
            c.execute(sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(u))
        self.stdout.write(self.style.SUCCESS(f"Usuario '{usuario}' listo: sólo lectura sobre el esquema powerbi."))
