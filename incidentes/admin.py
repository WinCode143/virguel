from django.contrib import admin

from .models import Siniestro


@admin.register(Siniestro)
class SiniestroAdmin(admin.ModelAdmin):
    list_display = ["numero", "fecha", "tipo", "gravedad", "responsabilidad_civil", "tecnico", "estado",
                    "resolucion", "costo_estimado", "costo_real", "monto_recuperado"]
    list_filter = ["estado", "gravedad", "tipo", "responsabilidad_civil", "resolucion", "zona"]
    search_fields = ["numero", "descripcion", "direccion", "tecnico__apellido"]
    date_hierarchy = "fecha"
    autocomplete_fields = ["tecnico", "supervisor", "orden", "cliente", "reportado_por"]
    readonly_fields = ["recomendacion"]
    fieldsets = [
        (None, {"fields": ["numero", "fecha", "tipo", "gravedad", "responsabilidad_civil", "zona", "direccion"]}),
        ("Personas y orden", {"fields": ["tecnico", "supervisor", "orden", "cliente", "reportado_por"]}),
        ("Análisis", {"fields": ["descripcion", "causa_raiz", "plan_accion"]}),
        ("Costos y resolución", {"fields": ["recomendacion", "costo_estimado", "costo_real", "monto_recuperado",
                                            "estado", "resolucion", "fecha_cierre"]}),
    ]

    @admin.display(description="Recomendación de acción")
    def recomendacion(self, obj):
        return obj.recomendacion_legal() if obj.pk else "Se calcula al guardar."
