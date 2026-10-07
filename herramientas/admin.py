from django.contrib import admin

from .models import Asignacion, Elemento


@admin.register(Elemento)
class ElementoAdmin(admin.ModelAdmin):
    list_display = ["codigo", "nombre", "tipo", "vida_util_dias", "obligatorio_tecnicos", "costo", "stock"]
    list_filter = ["tipo", "obligatorio_tecnicos"]
    search_fields = ["codigo", "nombre"]


@admin.register(Asignacion)
class AsignacionAdmin(admin.ModelAdmin):
    list_display = ["persona", "elemento", "fecha_entrega", "fecha_vencimiento", "estado", "conformidad_firmada"]
    list_filter = ["estado", "elemento__tipo", "elemento", "conformidad_firmada"]
    search_fields = ["persona__apellido", "elemento__nombre"]
    autocomplete_fields = ["persona", "elemento"]
