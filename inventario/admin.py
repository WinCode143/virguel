from django.contrib import admin, messages

from .models import (CompraEnCamino, DemandaComercial, EquipoRetirado, LoteIngreso, Material, MovimientoStockTecnico,
                     MovimientoUnidad, PedidoItem, PedidoMaterial, RecetaMaterial, ReservaMaterial, Salida, UnidadEquipo)
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
    list_display = ["material", "fecha", "cantidad", "cantidad_disponible", "dias", "costo_unitario", "proveedor",
                    "origen"]
    list_filter = ["origen", "material__categoria", "fecha"]
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
    list_display = ["tipo_tarea", "material", "cantidad", "condicion"]
    list_filter = ["tipo_tarea"]


@admin.register(DemandaComercial)
class DemandaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "zona", "tipo_tarea", "cantidad_clientes", "observaciones"]
    list_filter = ["zona", "tipo_tarea"]
    date_hierarchy = "fecha"


@admin.register(MovimientoStockTecnico)
class MovimientoTecnicoAdmin(admin.ModelAdmin):
    list_display = ["fecha", "tecnico", "material", "tipo", "cantidad", "orden", "pedido"]
    list_filter = ["tipo", "material"]
    search_fields = ["tecnico__apellido", "tecnico__legajo", "material__nombre"]
    date_hierarchy = "fecha"

    def has_change_permission(self, request, obj=None):
        return False  # se registran desde la app y el depósito; se corrigen con un ajuste

    def has_add_permission(self, request):
        return request.user.is_superuser  # ajustes de inventario


class PedidoItemInline(admin.TabularInline):
    model = PedidoItem
    extra = 0


@admin.register(PedidoMaterial)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ["id", "tecnico", "creado", "estado", "aprobado_por", "entregado"]
    list_filter = ["estado"]
    inlines = [PedidoItemInline]


@admin.register(EquipoRetirado)
class EquipoRetiradoAdmin(admin.ModelAdmin):
    list_display = ["numero_serie", "tecnico", "fecha_retiro", "estado", "devuelto", "recibido_por", "orden"]
    list_filter = ["estado"]
    search_fields = ["numero_serie", "tecnico__apellido", "orden__numero"]
    date_hierarchy = "fecha_retiro"


@admin.register(CompraEnCamino)
class CompraEnCaminoAdmin(admin.ModelAdmin):
    list_display = ["material", "cantidad", "fecha_esperada", "proveedor", "recibida"]
    list_filter = ["recibida"]
    list_editable = ["recibida"]
    autocomplete_fields = ["material"]


class MovimientoUnidadInline(admin.TabularInline):
    model = MovimientoUnidad
    extra = 0
    can_delete = False
    readonly_fields = ["fecha", "desde", "hacia", "custodio", "intento", "condicion", "motivo"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(UnidadEquipo)
class UnidadEquipoAdmin(admin.ModelAdmin):
    """Alta y consulta de equipos por serie. Los cambios de ubicación se registran como movimientos."""
    list_display = ["numero_serie", "material", "propietario", "condicion", "ubicacion", "custodio", "cliente"]
    list_filter = ["propietario", "condicion", "ubicacion", "material"]
    search_fields = ["numero_serie"]
    autocomplete_fields = ["material", "custodio"]
    inlines = [MovimientoUnidadInline]
    actions = ["marcar_funciona", "marcar_defectuoso"]

    @admin.action(description="Revisado: funciona (vuelve al suministro)")
    def marcar_funciona(self, request, queryset):
        from .equipos import revisar
        for u in queryset:
            revisar(u, True, f"Revisado por {request.user}")

    @admin.action(description="Revisado: defectuoso (fuera del suministro)")
    def marcar_defectuoso(self, request, queryset):
        from .equipos import revisar
        for u in queryset:
            revisar(u, False, f"Revisado por {request.user}")


@admin.register(ReservaMaterial)
class ReservaMaterialAdmin(admin.ModelAdmin):
    list_display = ["material", "cantidad", "orden", "necesaria_para", "estado", "responsable"]
    list_filter = ["estado"]
    list_editable = ["estado"]
    autocomplete_fields = ["material"]
    raw_id_fields = ["orden"]

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        from django.core.exceptions import ValidationError

        from .services import reservar
        try:
            nueva = reservar(obj.orden, obj.material, obj.cantidad, responsable=request.user.get_username())
            obj.pk = nueva.pk
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
