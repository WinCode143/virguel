from django.contrib import admin, messages

from .models import DemandaComercial, LoteIngreso, Material, RecetaMaterial, Salida
from .services import StockInsuficiente, registrar_salida


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ["codigo", "nombre", "categoria", "unidad", "costo_unitario", "stock_minimo", "stock",
                    "es_decodificador", "activo"]
    list_filter = ["categoria", "es_decodificador", "activo"]
    search_fields = ["codigo", "nombre"]

    @admin.display(description="Stock actual")
    def stock(self, obj):
        return obj.stock_actual


@admin.register(LoteIngreso)
class LoteIngresoAdmin(admin.ModelAdmin):
    list_display = ["material", "fecha", "cantidad", "cantidad_disponible", "dias", "costo_unitario", "proveedor"]
    list_filter = ["material__categoria", "fecha"]
    search_fields = ["material__nombre", "material__codigo", "remito", "proveedor"]
    date_hierarchy = "fecha"
    autocomplete_fields = ["material"]

    @admin.display(description="Días en stock")
    def dias(self, obj):
        return obj.dias_en_stock if obj.cantidad_disponible > 0 else "—"


@admin.register(Salida)
class SalidaAdmin(admin.ModelAdmin):
    list_display = ["material", "fecha", "cantidad", "motivo", "tecnico", "orden", "costo_total"]
    list_filter = ["motivo", "fecha", "material__categoria"]
    search_fields = ["material__nombre", "tecnico__apellido", "orden__numero"]
    date_hierarchy = "fecha"
    autocomplete_fields = ["material", "tecnico", "orden"]

    def has_change_permission(self, request, obj=None):
        return obj is None  # las salidas no se editan: se anulan con un ingreso/ajuste

    def save_model(self, request, obj, form, change):
        try:
            registrar_salida(obj)
        except StockInsuficiente as e:
            registrar_salida(obj, permitir_negativo=True)
            messages.warning(request, f"{e}. Se registró igual; revisar inventario.")


@admin.register(RecetaMaterial)
class RecetaAdmin(admin.ModelAdmin):
    list_display = ["tipo_tarea", "material", "cantidad"]
    list_filter = ["tipo_tarea"]


@admin.register(DemandaComercial)
class DemandaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "zona", "tipo_tarea", "cantidad_clientes", "observaciones"]
    list_filter = ["zona", "tipo_tarea"]
    date_hierarchy = "fecha"
