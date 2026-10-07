from django.urls import path

from . import exportar, views

app_name = "tablero"
urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("operacion/", views.operacion, name="operacion"),
    path("tecnicos/", views.tecnicos, name="tecnicos"),
    path("tecnicos/<int:pk>/", views.tecnico_detalle, name="tecnico"),
    path("capacitacion/", views.capacitacion, name="capacitacion"),
    path("supervisores/", views.supervisores, name="supervisores"),
    path("incidentes/", views.incidentes, name="incidentes"),
    path("herramientas/", views.herramientas, name="herramientas"),
    path("flota/", views.flota, name="flota"),
    path("finanzas/", views.finanzas, name="finanzas"),
    path("stock/", views.stock, name="stock"),
    path("planificacion/", views.planificacion, name="planificacion"),
    path("alertas/", views.alertas, name="alertas"),
    path("alertas/<int:pk>/resolver/", views.resolver_alerta, name="resolver_alerta"),
    path("powerbi/", exportar.indice, name="powerbi"),
]
