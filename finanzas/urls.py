from django.urls import path

from . import views

app_name = "finanzas"
urlpatterns = [
    path("", views.panel, name="panel"),
    path("egresos/", views.egresos, name="egresos"),
    path("egresos/nuevo/", views.egreso_form, name="egreso_nuevo"),
    path("egresos/<int:pk>/", views.egreso_form, name="egreso"),
    path("reintegros/", views.gastos_campo, name="gastos_campo"),
    path("presupuestos/", views.presupuestos, name="presupuestos"),
    path("configuracion/", views.configuracion, name="configuracion"),
]
