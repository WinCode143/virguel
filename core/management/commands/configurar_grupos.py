"""Crea los grupos de usuarios y les asigna permisos sobre la carga de datos (admin).

    python manage.py configurar_grupos

* Gerencia: todo lo del ERP + alta de usuarios.
* Administración: todo lo del ERP salvo parámetros, indicadores y usuarios.
* Depósito: inventario, partes de técnicos, pedidos y herramientas.
* Contabilidad: finanzas (egresos, presupuestos, costos fijos) y revisión de gastos de campo.
* Supervisores / Técnicos: sin acceso al admin (usan la app y los tableros).
"""
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.core.management.base import BaseCommand

APPS_ERP = ["core", "personal", "operaciones", "inventario", "supervision", "incidentes", "herramientas",
            "capacitacion", "flota", "finanzas"]


class Command(BaseCommand):
    help = "Crea los grupos (Gerencia, Administración, Supervisores, Técnicos) con sus permisos."

    def handle(self, *args, **opts):
        erp = Permission.objects.filter(content_type__app_label__in=APPS_ERP)
        usuarios = Permission.objects.filter(content_type__app_label="auth", content_type__model__in=["user", "group"])
        ger, _ = Group.objects.get_or_create(name="Gerencia")
        ger.permissions.set(list(erp) + list(usuarios))
        adm, _ = Group.objects.get_or_create(name="Administración")
        adm.permissions.set(erp.exclude(content_type__model__in=["parametros", "indicador"]))
        dep, _ = Group.objects.get_or_create(name="Depósito")
        dep.permissions.set(Permission.objects.filter(content_type__app_label__in=["inventario", "herramientas"]))
        cont, _ = Group.objects.get_or_create(name="Contabilidad")
        cont.permissions.set(Permission.objects.filter(
            Q(content_type__app_label="finanzas") | Q(content_type__model="gastoorden")))
        for nombre in ("Supervisores", "Técnicos"):
            Group.objects.get_or_create(name=nombre)
        self.stdout.write(self.style.SUCCESS(
            f"Grupos listos: Gerencia ({ger.permissions.count()} permisos), Administración ({adm.permissions.count()})."))
