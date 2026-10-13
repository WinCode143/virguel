from django.contrib import admin

from .models import Asignacion, CompraElemento, Elemento


@admin.register(Elemento)
class ElementoAdmin(admin.ModelAdmin):
    list_display = ["codigo", "nombre", "tipo", "vida_util_dias", "obligatorio_tecnicos", "costo", "stock"]
    list_filter = ["tipo", "obligatorio_tecnicos"]
    search_fields = ["codigo", "nombre"]


@admin.register(Asignacion)
class AsignacionAdmin(admin.ModelAdmin):
    list_display = ["persona", "elemento", "fecha_entrega", "origen", "fecha_vencimiento", "estado",
                    "conformidad_firmada"]
    list_filter = ["estado", "origen", "elemento__tipo", "elemento", "conformidad_firmada"]
    search_fields = ["persona__apellido", "elemento__nombre"]
    autocomplete_fields = ["persona", "elemento"]


@admin.register(CompraElemento)
class CompraElementoAdmin(admin.ModelAdmin):
    list_display = ["fecha", "elemento", "cantidad", "costo_unitario", "proveedor", "comprobante"]
    list_filter = ["elemento__tipo"]
    search_fields = ["elemento__nombre", "proveedor", "comprobante"]
    autocomplete_fields = ["elemento"]
