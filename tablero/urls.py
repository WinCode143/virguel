from django.urls import path

from . import asignacion, deposito, exportar, exportar_excel, importar, metas, productividad, views

app_name = "tablero"
urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("operacion/", views.operacion, name="operacion"),
    path("asignacion/", asignacion.vista, name="asignacion"),
    path("tecnicos/", views.tecnicos, name="tecnicos"),
    path("tecnicos/<int:pk>/", views.tecnico_detalle, name="tecnico"),
    path("capacitacion/", views.capacitacion, name="capacitacion"),
    path("productividad/general/", productividad.general, name="prod_general"),
    path("metas/", metas.metas, name="metas"),
    path("productividad/excel/", exportar_excel.exportar, name="prod_excel"),
    path("productividad/", productividad.tecnicos, name="prod_tecnicos"),
    path("productividad/supervisores/", productividad.supervisores, name="prod_supervisores"),
    path("productividad/<int:pk>/", productividad.ficha, name="prod_ficha"),
    path("supervisores/", views.supervisores, name="supervisores"),
    path("incidentes/", views.incidentes, name="incidentes"),
    path("herramientas/", views.herramientas, name="herramientas"),
    path("flota/", views.flota, name="flota"),
    path("finanzas/", views.finanzas, name="finanzas"),
    path("stock/", views.stock, name="stock"),
    path("stock/tecnicos/", deposito.stock_tecnicos, name="stock_tecnicos"),
    path("pedidos/", deposito.pedidos, name="pedidos"),
    path("partes-adeudadas/", deposito.deudas, name="deudas"),
    path("planificacion/", views.planificacion, name="planificacion"),
    path("encuestas/", views.encuestas, name="encuestas"),
    path("alertas/", views.alertas, name="alertas"),
    path("alertas/<int:pk>/resolver/", views.resolver_alerta, name="resolver_alerta"),
    path("powerbi/", exportar.indice, name="powerbi"),
    path("importar/", importar.vista, name="importar"),
    path("importar/plantilla/<slug:tipo>.csv", importar.plantilla, name="plantilla"),
]
