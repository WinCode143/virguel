from django.contrib import admin

from .models import (Capacitacion, Competencia, Curso, EvaluacionCompetencia, EvaluacionHistorica, Participacion,
                     ObjetivoPlan, PlanMejora, RequisitoCompetencia)


@admin.register(Competencia)
class CompetenciaAdmin(admin.ModelAdmin):
    search_fields = ["nombre"]


@admin.register(Curso)
class CursoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "competencia", "horas", "obligatorio"]


class ParticipacionInline(admin.TabularInline):
    model = Participacion
    fk_name = "capacitacion"
    extra = 3
    fields = ["persona", "asistio", "aprobado", "nota", "evaluador", "evidencia", "fecha_evaluacion"]
    autocomplete_fields = ["persona", "evaluador"]


@admin.register(Capacitacion)
class CapacitacionAdmin(admin.ModelAdmin):
    list_display = ["curso", "fecha", "instructor", "en_produccion", "asistentes"]
    list_filter = ["en_produccion", "curso"]
    date_hierarchy = "fecha"
    inlines = [ParticipacionInline]

    @admin.display(description="Asistentes")
    def asistentes(self, obj):
        return obj.participacion_set.filter(asistio=True).count()


@admin.register(EvaluacionCompetencia)
class EvaluacionAdmin(admin.ModelAdmin):
    list_display = ["fecha", "persona", "competencia", "nivel", "evaluador"]
    list_filter = ["competencia", "nivel"]
    autocomplete_fields = ["persona", "evaluador"]


@admin.register(EvaluacionHistorica)
class HistorialAdmin(admin.ModelAdmin):
    list_display = ["fecha", "persona", "productividad", "riesgo", "diagnostico"]
    list_filter = ["diagnostico", "fecha"]
    search_fields = ["persona__apellido", "persona__legajo"]
    date_hierarchy = "fecha"

    def has_add_permission(self, request):
        return False  # lo genera la tarea diaria


@admin.register(RequisitoCompetencia)
class RequisitoCompetenciaAdmin(admin.ModelAdmin):
    list_display = ["tipo_tarea", "competencia", "nivel_minimo", "permite_tutelada"]
    list_filter = ["tipo_tarea", "competencia"]


class ObjetivoPlanInline(admin.TabularInline):
    model = ObjetivoPlan
    extra = 2


@admin.register(PlanMejora)
class PlanMejoraAdmin(admin.ModelAdmin):
    list_display = ["persona", "tipo", "desde", "revisar_el", "responsable", "estado", "decision"]
    list_filter = ["tipo", "estado", "decision"]
    autocomplete_fields = ["persona", "responsable", "decidido_por"]
    inlines = [ObjetivoPlanInline]
