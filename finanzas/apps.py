from django.apps import AppConfig


class FinanzasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finanzas"
    verbose_name = "7. Finanzas y flujo de fondos"

    def ready(self):
        from . import signals  # noqa: F401
