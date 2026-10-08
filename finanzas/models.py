from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class CategoriaEgreso(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    codigo = models.SlugField(max_length=30, unique=True)
    tolerancia_presupuesto = models.PositiveSmallIntegerField(
        "Tolerancia sobre el presupuesto (%)", default=10,
        help_text="Verde hasta el presupuesto; amarillo hasta presupuesto + tolerancia; rojo después.")

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Categoría de egreso"
        verbose_name_plural = "Categorías de egreso"

    def __str__(self):
        return self.nombre


class Egreso(models.Model):
    """Gasto real. Los de compras de stock, services, EPP y siniestros se
    generan automáticamente; el resto se carga a mano."""

    fecha = models.DateField(default=timezone.localdate, db_index=True)
    categoria = models.ForeignKey(CategoriaEgreso, on_delete=models.PROTECT, related_name="egresos")
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    descripcion = models.CharField(max_length=200)
    proveedor = models.CharField(max_length=120, blank=True)
    numero_comprobante = models.CharField("N° de factura / comprobante", max_length=40, blank=True)
    comprobante = models.FileField("Archivo del comprobante", upload_to="egresos/%Y/%m/", blank=True)
    cargado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    editable=False)
    automatico = models.BooleanField(default=False, editable=False)
    origen = models.CharField(max_length=60, blank=True, editable=False,
                              help_text="Referencia al registro que lo originó (modelo:id).")

    class Meta:
        ordering = ["-fecha"]
        constraints = [
            models.UniqueConstraint(fields=["origen"], condition=~models.Q(origen=""),
                                    name="egreso_origen_unico"),
        ]

    def __str__(self):
        return f"{self.fecha} {self.categoria}: ${self.monto}"


class Presupuesto(models.Model):
    """Monto previsto por categoría y mes; se compara contra lo gastado (semáforo)."""

    categoria = models.ForeignKey(CategoriaEgreso, on_delete=models.CASCADE, related_name="presupuestos")
    mes = models.DateField(help_text="Primer día del mes.")
    monto = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["mes", "categoria__nombre"]
        unique_together = [("categoria", "mes")]

    def __str__(self):
        return f"{self.categoria} {self.mes:%m/%Y}: ${self.monto}"


class CostoFijo(models.Model):
    """Egreso recurrente mensual (sueldos, alquileres, seguros) para la proyección."""

    categoria = models.ForeignKey(CategoriaEgreso, on_delete=models.PROTECT)
    descripcion = models.CharField(max_length=150)
    monto_mensual = models.DecimalField(max_digits=14, decimal_places=2)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Costo fijo mensual"
        verbose_name_plural = "Costos fijos mensuales"

    def __str__(self):
        return f"{self.descripcion} (${self.monto_mensual}/mes)"


def registrar_egreso_automatico(origen: str, categoria_codigo: str, fecha, monto, descripcion):
    """Crea o actualiza el egreso asociado a un registro operativo."""
    monto = Decimal(monto or 0)
    if monto <= 0:
        Egreso.objects.filter(origen=origen).delete()
        return None
    cat, _ = CategoriaEgreso.objects.get_or_create(
        codigo=categoria_codigo, defaults={"nombre": categoria_codigo.replace("-", " ").capitalize()})
    obj, _ = Egreso.objects.update_or_create(
        origen=origen, defaults={"fecha": fecha, "categoria": cat, "monto": monto,
                                 "descripcion": descripcion[:200], "automatico": True})
    return obj
