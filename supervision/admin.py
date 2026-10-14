from django.contrib import admin

from django.utils import timezone

from core.roles import persona_de

from .models import (AccionCorrectiva, EncuestaSemanal, EncuestaSupervisor, InformeControl, ItemPlantilla,
                     PlantillaInspeccion, ResultadoItem, TareaSupervisor)


class ItemInline(admin.TabularInline):
    model = ItemPlantilla
    extra = 1


@admin.register(PlantillaInspeccion)
class PlantillaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "version", "tipo", "vigente", "creada"]
    list_filter = ["vigente", "tipo"]
    inlines = [ItemInline]
    actions = ["nueva_version"]

    @admin.action(description="Crear nueva versión (la actual deja de estar vigente)")
    def nueva_version(self, request, queryset):
        for pl in queryset:
            items = list(pl.items.all())
            ultima = PlantillaInspeccion.objects.filter(nombre=pl.nombre).order_by("-version").first()
            PlantillaInspeccion.objects.filter(nombre=pl.nombre).update(vigente=False)
            nueva = PlantillaInspeccion.objects.create(nombre=pl.nombre, tipo=pl.tipo, version=ultima.version + 1)
            for i in items:
                i.pk, i.plantilla = None, nueva
                i.save()
        self.message_user(request, "Versión nueva creada: editá sus puntos; los controles anteriores conservan la suya.")


class ResultadoInline(admin.TabularInline):
    model = ResultadoItem
    extra = 0


class AccionInline(admin.TabularInline):
    model = AccionCorrectiva
    fk_name = "informe"
    extra = 0
    autocomplete_fields = ["tecnico", "aplicada_por"]


@admin.register(InformeControl)
class InformeAdmin(admin.ModelAdmin):
    list_display = ["fecha", "supervisor", "tecnico", "tipo", "motivo_seleccion", "puntaje", "desvio_detectado",
                    "calidad"]
    list_filter = ["tipo", "motivo_seleccion", "desvio_detectado", "supervisor", "fecha"]
    search_fields = ["tecnico__apellido", "supervisor__apellido", "descripcion"]
    date_hierarchy = "fecha"
    autocomplete_fields = ["supervisor", "tecnico", "orden"]
    inlines = [ResultadoInline, AccionInline]

    @admin.display(description="Completitud documental")
    def calidad(self, obj):
        return f"{obj.calidad_informe}/100"


@admin.register(AccionCorrectiva)
class AccionAdmin(admin.ModelAdmin):
    list_display = ["fecha", "tecnico", "tipo", "monto", "aplicada_por", "cumplida", "dias_respuesta"]
    list_filter = ["tipo", "cumplida", "fecha"]
    search_fields = ["tecnico__apellido"]
    autocomplete_fields = ["tecnico", "aplicada_por", "informe"]


@admin.register(TareaSupervisor)
class TareaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "supervisor", "descripcion", "criterio_aceptacion", "meta", "resultado", "estado",
                    "verificacion", "evidencia"]
    list_filter = ["verificacion", "estado", "supervisor", "fecha"]
    date_hierarchy = "fecha"
    readonly_fields = ["verificado_por", "fecha_verificacion", "historial_meta"]
    actions = ["verificar", "rechazar"]

    def _verificar(self, request, queryset, estado):
        n = 0
        for t in queryset.exclude(verificacion="sin_reporte"):
            if t.supervisor_id and persona_de(request.user) and persona_de(request.user).pk == t.supervisor_id:
                continue  # nadie verifica su propio objetivo
            t.verificacion, t.verificado_por, t.fecha_verificacion = estado, persona_de(request.user), timezone.now()
            t.save()
            n += 1
        self.message_user(request, f"{n} objetivo(s) marcados como {estado}. Los sin reporte no se tocan.")

    @admin.action(description="Verificar lo reportado (cuenta para el puntaje)")
    def verificar(self, request, queryset):
        self._verificar(request, queryset, "verificado")

    @admin.action(description="Rechazar lo reportado (cuenta 0)")
    def rechazar(self, request, queryset):
        self._verificar(request, queryset, "rechazado")


@admin.register(EncuestaSupervisor)
class EncuestaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "supervisor", "tecnico", "respondida", "trato", "claridad", "apoyo", "presencia"]
    list_filter = ["supervisor", "fecha"]
    date_hierarchy = "fecha"
    readonly_fields = ["token", "fecha", "tecnico", "supervisor", "respondida", "trato", "claridad", "apoyo",
                       "presencia", "comentario"]

    def has_add_permission(self, request):
        return False  # las genera el sistema automáticamente


@admin.register(EncuestaSemanal)
class EncuestaSemanalAdmin(admin.ModelAdmin):
    list_display = ["semana", "supervisor", "tecnico", "general", "trato", "organizacion", "apoyo", "ensenanza", "justicia"]
    list_filter = ["supervisor", "semana"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
