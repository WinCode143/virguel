from django.urls import path

from . import views

app_name = "finanzas"
urlpatterns = [
    path("", views.panel, name="panel"),
    path("comprobantes/", views.comprobantes, name="comprobantes"),
    path("comprobantes/nuevo/", views.comprobante_form, name="comprobante_nuevo"),
    path("comprobantes/<int:pk>/", views.comprobante_form, name="comprobante"),
    path("sueldos/", views.sueldos, name="sueldos"),
    path("materiales/", views.materiales, name="materiales"),
    path("reintegros/", views.gastos_campo, name="gastos_campo"),
    path("presupuesto/", views.presupuestos, name="presupuestos"),
    path("configuracion/", views.configuracion, name="configuracion"),
]
