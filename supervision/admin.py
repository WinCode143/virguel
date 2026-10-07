from django.contrib import admin

from .models import AccionCorrectiva, EncuestaSemanal, EncuestaSupervisor, InformeControl, TareaSupervisor


class AccionInline(admin.TabularInline):
    model = AccionCorrectiva
    fk_name = "informe"
    extra = 0
    autocomplete_fields = ["tecnico", "aplicada_por"]


@admin.register(InformeControl)
class InformeAdmin(admin.ModelAdmin):
    list_display = ["fecha", "supervisor", "tecnico", "tipo", "puntaje", "desvio_detectado", "calidad"]
    list_filter = ["tipo", "desvio_detectado", "supervisor", "fecha"]
    search_fields = ["tecnico__apellido", "supervisor__apellido", "descripcion"]
    date_hierarchy = "fecha"
    autocomplete_fields = ["supervisor", "tecnico", "orden"]
    inlines = [AccionInline]

    @admin.display(description="Calidad del informe")
    def calidad(self, obj):
        return f"{obj.calidad_informe}/100"


@admin.register(AccionCorrectiva)
class AccionAdmin(admin.ModelAdmin):
    list_display = ["fecha", "tecnico", "tipo", "monto", "aplicada_por", "cumplida", "dias_respuesta"]
    list_filter = ["tipo", "cumplida", "fecha"]
    search_fields = ["tecnico__apellido"]
    autocomplete_fields = ["tecnico", "aplicada_por", "informe"]


@admin.register(TareaSupervisor)
class TareaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "supervisor", "descripcion", "meta", "resultado", "estado"]
    list_filter = ["estado", "supervisor", "fecha"]
    list_editable = ["resultado", "estado"]
    date_hierarchy = "fecha"


@admin.register(EncuestaSupervisor)
class EncuestaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "supervisor", "tecnico", "respondida", "trato", "claridad", "apoyo", "presencia"]
    list_filter = ["supervisor", "fecha"]
    date_hierarchy = "fecha"
    readonly_fields = ["token", "fecha", "tecnico", "supervisor", "respondida", "trato", "claridad", "apoyo",
                       "presencia", "comentario"]

    def has_add_permission(self, request):
        return False  # las genera el sistema automáticamente


@admin.register(EncuestaSemanal)
class EncuestaSemanalAdmin(admin.ModelAdmin):
    list_display = ["semana", "supervisor", "tecnico", "general", "trato", "organizacion", "apoyo", "ensenanza", "justicia"]
    list_filter = ["supervisor", "semana"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
