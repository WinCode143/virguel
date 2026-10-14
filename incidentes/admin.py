from django.contrib import admin

from .models import Siniestro


@admin.register(Siniestro)
class SiniestroAdmin(admin.ModelAdmin):
    list_display = ["numero", "fecha", "tipo", "gravedad", "tecnico", "investigacion", "atribucion", "estado",
                    "resolucion", "costo_estimado", "costo_real", "monto_recuperado"]
    list_filter = ["estado", "investigacion", "atribucion", "gravedad", "tipo", "responsabilidad_civil", "resolucion",
                   "zona"]
    search_fields = ["numero", "descripcion", "direccion", "tecnico__apellido"]
    date_hierarchy = "fecha"
    autocomplete_fields = ["tecnico", "supervisor", "orden", "cliente", "reportado_por", "atribucion_por",
                           "responsable_gestion"]
    readonly_fields = ["recomendacion"]
    fieldsets = [
        (None, {"fields": ["numero", "fecha", "tipo", "gravedad", "responsabilidad_civil", "zona", "direccion"]}),
        ("Personas y orden", {"fields": ["tecnico", "supervisor", "orden", "cliente", "reportado_por"]}),
        ("Análisis", {"fields": ["descripcion", "causa_raiz", "plan_accion"]}),
        ("Investigación y atribución", {
            "fields": ["investigacion", "hechos", "responsable_gestion", "atribucion", "atribucion_fundamento",
                       "atribucion_por", "atribucion_fecha"],
            "description": "Estar vinculado a un incidente no acredita haberlo causado: sólo una atribución "
                           "CONFIRMADA, con fundamento, afecta la evaluación del técnico."}),
        ("Costos y resolución", {"fields": ["recomendacion", "costo_estimado", "costo_real", "monto_recuperado",
                                            "estado", "resolucion", "fecha_cierre"]}),
    ]

    @admin.display(description="Próximo paso del expediente")
    def recomendacion(self, obj):
        return obj.recomendacion_legal() if obj.pk else "Se calcula al guardar."
