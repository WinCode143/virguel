from django.contrib import admin

from .models import CategoriaEgreso, Cobro, CostoFijo, Cuenta, Cuota, Egreso, Ingreso, Liquidacion, Pago, Proveedor


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


@admin.register(Cuenta)
class CuentaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "tipo", "saldo_inicial", "fecha_saldo_inicial", "saldo_actual", "activa"]

    @admin.display(description="Saldo hoy")
    def saldo_actual(self, obj):
        return obj.saldo()


class CobroInline(admin.TabularInline):
    model = Cobro
    extra = 0


@admin.register(Ingreso)
class IngresoAdmin(admin.ModelAdmin):
    list_display = ["fecha", "pagador", "concepto", "monto", "fecha_esperada_cobro", "estado"]
    search_fields = ["concepto", "pagador", "numero_comprobante"]
    date_hierarchy = "fecha"
    inlines = [CobroInline]


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ["fecha", "egreso", "monto", "cuenta", "medio", "automatico"]
    list_filter = ["cuenta", "automatico"]
    date_hierarchy = "fecha"


@admin.register(Cuota)
class CuotaAdmin(admin.ModelAdmin):
    list_display = ["egreso", "numero", "vencimiento", "monto"]
    date_hierarchy = "vencimiento"
