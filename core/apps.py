from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = "Configuración, personas y clientes"

    def ready(self):
        from . import autenticacion, signals  # noqa: F401
        from .numeros import instalar_en_admin
        instalar_en_admin()
