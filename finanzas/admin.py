from django.contrib import admin

from .models import CategoriaEgreso, CostoFijo, Egreso, Liquidacion, Proveedor


@admin.register(CategoriaEgreso)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "codigo"]
    prepopulated_fields = {"codigo": ["nombre"]}


@admin.register(Egreso)
class EgresoAdmin(admin.ModelAdmin):
    list_display = ["fecha", "tipo_comprobante", "proveedor", "categoria", "descripcion", "monto", "pagado", "automatico"]
    list_filter = ["categoria", "automatico"]
    search_fields = ["descripcion"]
    date_hierarchy = "fecha"

    def has_change_permission(self, request, obj=None):
        return not (obj and obj.automatico)

    def has_delete_permission(self, request, obj=None):
        return not (obj and obj.automatico)


@admin.register(CostoFijo)
class CostoFijoAdmin(admin.ModelAdmin):
    list_display = ["descripcion", "categoria", "monto_mensual", "activo"]


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ["nombre", "cuit", "categoria", "contacto"]
    search_fields = ["nombre", "cuit"]


@admin.register(Liquidacion)
class LiquidacionAdmin(admin.ModelAdmin):
    list_display = ["persona", "periodo", "basico", "monto_horas_extra", "bruto", "costo_total", "estado"]
    list_filter = ["estado", "periodo"]
    search_fields = ["persona__apellido", "persona__legajo"]
