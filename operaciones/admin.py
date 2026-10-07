from django.contrib import admin

from inventario.models import Salida

from .models import Jornada, OrdenTrabajo, TipoTarea


@admin.register(TipoTarea)
class TipoTareaAdmin(admin.ModelAdmin):
    list_display = ["codigo", "nombre", "minutos_estandar", "puede_requerir_decodificador", "activo"]


@admin.register(Jornada)
class JornadaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "tecnico", "en_calle", "zona", "vehiculo", "hectareas_cubiertas", "horas_trabajadas"]
    list_filter = ["en_calle", "zona", "fecha"]
    search_fields = ["tecnico__apellido", "tecnico__legajo"]
    date_hierarchy = "fecha"
    autocomplete_fields = ["tecnico"]


class ConsumoInline(admin.TabularInline):
    model = Salida
    fields = ["material", "cantidad", "fecha", "costo_total"]
    readonly_fields = ["costo_total"]
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False  # los consumos se registran por la app o por Salidas (FIFO)


@admin.register(OrdenTrabajo)
class OrdenTrabajoAdmin(admin.ModelAdmin):
    list_display = ["numero", "tipo", "tecnico", "cliente", "fecha_programada", "fecha_ejecucion", "estado",
                    "decodificador_solicitado", "es_retrabajo"]
    list_filter = ["estado", "tipo", "es_retrabajo", "decodificador_solicitado", "zona"]
    search_fields = ["numero", "cliente__numero", "cliente__nombre", "tecnico__apellido"]
    date_hierarchy = "fecha_programada"
    autocomplete_fields = ["tecnico", "cliente", "orden_original"]
    inlines = [ConsumoInline]
