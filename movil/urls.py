from django.urls import path

from . import views

app_name = "movil"
urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="sw"),
    path("jornada/<str:accion>/", views.jornada, name="jornada"),
    path("orden/<int:pk>/", views.orden, name="orden"),
    path("epp/", views.mi_epp, name="epp"),
    path("historial/", views.historial, name="historial"),
    path("stock/", views.mi_stock, name="stock"),
    path("stock/pedir/", views.pedir_partes, name="pedir"),
    path("pedidos/", views.pedidos_equipo, name="pedidos"),
    path("legajo/", views.mi_legajo, name="legajo"),
    path("yo/", views.yo, name="yo"),
    path("mi-supervisor/", views.mi_supervisor, name="mi_supervisor"),
    path("notificaciones/", views.notificaciones, name="notificaciones"),
    path("push/suscribir/", views.push_suscribir, name="push_suscribir"),
    path("asistencia/", views.mi_asistencia, name="asistencia"),
    path("ausencia/", views.novedad, name="novedad"),
    path("novedades/", views.novedades_equipo, name="novedades"),
    path("desempeno/", views.mi_desempeno, name="desempeno"),
    path("incidente/", views.reportar_incidente, name="incidente"),
    path("informe/", views.nuevo_informe, name="informe"),
    path("accion/", views.nueva_accion, name="accion"),
    path("tarea/<int:pk>/", views.tarea, name="tarea"),
    path("indicadores/", views.mis_indicadores, name="indicadores"),
]
