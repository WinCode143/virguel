from django.contrib import admin

from .models import Alerta, Cliente, Parametros, Persona, Zona

admin.site.site_header = "Virguel — ERP operativo"
admin.site.site_title = "Virguel ERP"
admin.site.index_title = "Administración de datos"


@admin.register(Parametros)
class ParametrosAdmin(admin.ModelAdmin):
    fieldsets = [
        ("Control de personal", {"fields": ["tolerancia_tarde_minutos", "horas_jornada", "destinatarios_parte"]}),
        ("Stock", {"fields": ["dias_max_stock", "dias_aviso_stock", "dias_cobertura_stock_min"]}),
        ("Capacidad", {"fields": ["clientes_por_tecnico_dia", "usar_hectareas", "hectareas_dia_min",
                                  "hectareas_dia_max", "tecnicos_por_cuadrilla"]}),
        ("Decodificadores", {"fields": ["prob_decodificador_min", "prob_decodificador_max"]}),
        ("Evaluación", {"fields": ["dias_ventana_evaluacion"]}),
    ]

    def has_add_permission(self, request):
        return not Parametros.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Zona)
class ZonaAdmin(admin.ModelAdmin):
    list_display = ["nombre", "densidad_clientes_ha", "activa"]


@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    list_display = ["legajo", "apellido", "nombre", "rol", "supervisor", "zona", "hora_entrada", "fecha_ingreso", "activo"]
    list_filter = ["rol", "activo", "zona", "supervisor"]
    search_fields = ["legajo", "apellido", "nombre", "dni"]
    autocomplete_fields = ["supervisor", "usuario"]
    fieldsets = [
        (None, {"fields": ["legajo", "nombre", "apellido", "dni", "rol", "supervisor", "zona", "usuario"]}),
        ("Contacto", {"fields": ["telefono", "email"]}),
        ("Horario", {"fields": ["hora_entrada", "hora_salida", "trabaja_sabados"]}),
        ("Relación laboral", {"fields": ["fecha_ingreso", "activo", "fecha_egreso", "motivo_egreso"]}),
    ]


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ["numero", "nombre", "zona", "tipo", "cantidad_televisores"]
    list_filter = ["tipo", "zona"]
    search_fields = ["numero", "nombre", "direccion"]


@admin.register(Alerta)
class AlertaAdmin(admin.ModelAdmin):
    list_display = ["titulo", "modulo", "nivel", "actualizada", "resuelta"]
    list_filter = ["resuelta", "nivel", "modulo"]
    search_fields = ["titulo", "detalle"]
