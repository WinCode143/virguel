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
    path("desempeno/", views.mi_desempeno, name="desempeno"),
    path("incidente/", views.reportar_incidente, name="incidente"),
    path("informe/", views.nuevo_informe, name="informe"),
    path("accion/", views.nueva_accion, name="accion"),
    path("tarea/<int:pk>/", views.tarea, name="tarea"),
    path("indicadores/", views.mis_indicadores, name="indicadores"),
]
