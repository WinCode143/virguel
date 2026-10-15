from django.contrib import admin

from .models import Asignacion, CompraElemento, Elemento, MovimientoPanol, ReporteCondicion, RequisitoEPP


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

    def get_readonly_fields(self, request, obj=None):
        # una entrega registrada no cambia de persona/elemento/origen; la cantidad sí, con su movimiento
        return ["persona", "elemento", "origen"] if obj else []


@admin.register(CompraElemento)
class CompraElementoAdmin(admin.ModelAdmin):
    list_display = ["fecha", "elemento", "cantidad", "costo_unitario", "proveedor", "comprobante"]
    list_filter = ["elemento__tipo"]
    search_fields = ["elemento__nombre", "proveedor", "comprobante"]
    autocomplete_fields = ["elemento"]


@admin.register(MovimientoPanol)
class MovimientoPanolAdmin(admin.ModelAdmin):
    """Para ajustes por inventario físico y bajas: el resto de los movimientos los genera el sistema."""
    list_display = ["fecha", "elemento", "tipo", "cantidad", "responsable", "motivo"]
    list_filter = ["tipo", "elemento"]
    fields = ["elemento", "fecha", "tipo", "cantidad", "motivo"]
    autocomplete_fields = ["elemento"]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.responsable = request.user.get_username()
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        return False  # el libro no se edita: una corrección es otro movimiento

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReporteCondicion)
class ReporteCondicionAdmin(admin.ModelAdmin):
    list_display = ["fecha", "asignacion", "tipo", "estado", "resolucion", "responsable", "reemplazo"]
    list_filter = ["estado", "tipo", "resolucion"]
    autocomplete_fields = ["responsable", "reportado_por"]
    actions = ["reponer_del_panol"]

    @admin.action(description="Reponer del pañol (entrega sustituta)")
    def reponer_del_panol(self, request, queryset):
        from django.contrib import messages
        from django.core.exceptions import ValidationError

        from core.roles import persona_de
        n = 0
        for r in queryset.filter(estado="abierto"):
            try:
                r.reponer(responsable=persona_de(request.user))
                n += 1
            except ValidationError as e:
                self.message_user(request, f"{r}: {' '.join(e.messages)}", messages.ERROR)
        self.message_user(request, f"{n} reposición(es) entregada(s).")


@admin.register(RequisitoEPP)
class RequisitoEPPAdmin(admin.ModelAdmin):
    list_display = ["tipo_tarea", "elemento"]
    list_filter = ["tipo_tarea"]
