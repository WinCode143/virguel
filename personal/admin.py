from django.contrib import admin

from .models import Asistencia, DocumentoPersonal, Feriado, Novedad, TipoDocumento


@admin.register(Asistencia)
class AsistenciaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "persona", "entrada", "salida", "minutos_tarde", "horas_trabajadas", "horas_extra", "origen"]
    list_filter = ["origen", "fecha", "persona__rol", "persona__supervisor"]
    search_fields = ["persona__apellido", "persona__legajo"]
    date_hierarchy = "fecha"
    autocomplete_fields = ["persona"]
    readonly_fields = ["minutos_tarde", "horas_trabajadas", "horas_extra"]


@admin.register(Novedad)
class NovedadAdmin(admin.ModelAdmin):
    list_display = ["persona", "tipo", "desde", "hasta", "estado", "certificado", "cargada_por"]
    list_filter = ["estado", "tipo", "persona__supervisor"]
    list_editable = ["estado"]
    search_fields = ["persona__apellido", "persona__legajo"]
    date_hierarchy = "desde"
    autocomplete_fields = ["persona", "cargada_por"]


@admin.register(Feriado)
class FeriadoAdmin(admin.ModelAdmin):
    list_display = ["fecha", "nombre"]


@admin.register(TipoDocumento)
class TipoDocumentoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "obligatorio_tecnicos", "obligatorio_supervisores", "dias_aviso"]


@admin.register(DocumentoPersonal)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ["persona", "tipo", "numero", "vencimiento", "archivo"]
    list_filter = ["tipo"]
    search_fields = ["persona__apellido", "persona__legajo", "numero"]
    autocomplete_fields = ["persona"]
