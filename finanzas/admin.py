from django.contrib import admin

from .models import CategoriaEgreso, CostoFijo, Egreso


@admin.register(CategoriaEgreso)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "codigo"]
    prepopulated_fields = {"codigo": ["nombre"]}


@admin.register(Egreso)
class EgresoAdmin(admin.ModelAdmin):
    list_display = ["fecha", "categoria", "descripcion", "monto", "automatico"]
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
