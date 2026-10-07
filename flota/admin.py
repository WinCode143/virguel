from django.contrib import admin

from .models import ServiceRealizado, TipoService, Vehiculo


class ServiceInline(admin.TabularInline):
    model = ServiceRealizado
    extra = 0


@admin.register(Vehiculo)
class VehiculoAdmin(admin.ModelAdmin):
    list_display = ["patente", "marca", "modelo", "anio", "km_actual", "estado", "asignado_a",
                    "vencimiento_vtv", "vencimiento_seguro"]
    list_filter = ["estado", "marca"]
    search_fields = ["patente", "marca", "modelo"]
    autocomplete_fields = ["asignado_a"]
    inlines = [ServiceInline]


@admin.register(TipoService)
class TipoServiceAdmin(admin.ModelAdmin):
    list_display = ["nombre", "cada_km", "cada_dias", "costo_estimado"]


@admin.register(ServiceRealizado)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["vehiculo", "tipo", "fecha", "km", "costo", "taller"]
    list_filter = ["tipo", "vehiculo"]
    date_hierarchy = "fecha"
