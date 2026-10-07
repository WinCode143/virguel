from django.urls import path

from . import views

app_name = "personal"
urlpatterns = [
    path("", views.hoy, name="hoy"),
    path("asistencia/", views.asistencia, name="asistencia"),
    path("legajos/", views.legajos, name="legajos"),
    path("legajos/<int:pk>/", views.legajo, name="legajo"),
    path("dotacion/", views.dotacion, name="dotacion"),
    path("documentos/", views.documentos, name="documentos"),
    path("parte/", views.parte, name="parte"),
]
