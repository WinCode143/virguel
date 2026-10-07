from django.contrib import admin

from .models import Capacitacion, Competencia, Curso, EvaluacionCompetencia, Participacion


@admin.register(Competencia)
class CompetenciaAdmin(admin.ModelAdmin):
    search_fields = ["nombre"]


@admin.register(Curso)
class CursoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "competencia", "horas", "obligatorio"]


class ParticipacionInline(admin.TabularInline):
    model = Participacion
    extra = 3
    autocomplete_fields = ["persona"]


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
