from django.apps import AppConfig


class FinanzasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finanzas"
    verbose_name = "Finanzas"

    def ready(self):
        from . import signals  # noqa: F401
