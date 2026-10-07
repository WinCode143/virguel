from decimal import Decimal

from django.db import models
from django.db.models import Sum
from django.utils import timezone

from core.models import Persona, Zona
from operaciones.models import OrdenTrabajo, TipoTarea


class Material(models.Model):
    class Categoria(models.TextChoices):
        MATERIAL = "material", "Material / consumible"
        EQUIPO = "equipo", "Equipo (decodificador, módem, etc.)"
        REPUESTO = "repuesto", "Repuesto"

    codigo = models.CharField(max_length=30, unique=True)
    nombre = models.CharField(max_length=150)
    categoria = models.CharField(max_length=20, choices=Categoria.choices, default=Categoria.MATERIAL)
    unidad = models.CharField(max_length=20, default="u")
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    stock_minimo = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    es_decodificador = models.BooleanField(
        default=False, help_text="Se usa para la proyección de decodificadores de TV.")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name_plural = "Materiales y equipos"

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

    @property
    def stock_actual(self) -> Decimal:
        return self.lotes.aggregate(t=Sum("cantidad_disponible"))["t"] or Decimal("0")


class LoteIngreso(models.Model):
    """Cada ingreso de mercadería es un lote. La antigüedad se mide por lote
    y las salidas se descuentan en orden FIFO (primero lo más viejo)."""

    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="lotes")
    fecha = models.DateField(default=timezone.localdate, db_index=True)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    cantidad_disponible = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    proveedor = models.CharField(max_length=120, blank=True)
    remito = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["fecha", "id"]
        verbose_name = "Ingreso de stock (lote)"
        verbose_name_plural = "Ingresos de stock (lotes)"

    def __str__(self):
        return f"{self.material.codigo} {self.cantidad} ({self.fecha})"

    def save(self, *args, **kwargs):
        if self._state.adding and self.cantidad_disponible is None:
            self.cantidad_disponible = self.cantidad
        if not self.costo_unitario:
            self.costo_unitario = self.material.costo_unitario
        super().save(*args, **kwargs)

    @property
    def dias_en_stock(self) -> int:
        return (timezone.localdate() - self.fecha).days


class Salida(models.Model):
    class Motivo(models.TextChoices):
        CONSUMO = "consumo", "Consumo en orden de trabajo"
        ENTREGA = "entrega", "Entrega a técnico (stock en mano)"
        DEVOLUCION = "devolucion", "Devolución a proveedor"
        BAJA = "baja", "Baja / rotura / pérdida"

    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="salidas")
    fecha = models.DateField(default=timezone.localdate, db_index=True)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    motivo = models.CharField(max_length=20, choices=Motivo.choices, default=Motivo.CONSUMO)
    tecnico = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="salidas_material")
    orden = models.ForeignKey(OrdenTrabajo, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="consumos")
    costo_total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"), editable=False)
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Salida de stock"
        verbose_name_plural = "Salidas de stock"

    def __str__(self):
        return f"{self.material.codigo} -{self.cantidad} ({self.fecha})"


class RecetaMaterial(models.Model):
    """Materiales que consume en promedio cada tipo de tarea (para prever compras)."""

    tipo_tarea = models.ForeignKey(TipoTarea, on_delete=models.CASCADE, related_name="receta")
    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name="en_recetas")
    cantidad = models.DecimalField(max_digits=10, decimal_places=3)

    class Meta:
        unique_together = [("tipo_tarea", "material")]
        verbose_name = "Material por tipo de tarea"
        verbose_name_plural = "Materiales por tipo de tarea"

    def __str__(self):
        return f"{self.tipo_tarea}: {self.cantidad} {self.material.unidad} {self.material.nombre}"


class DemandaComercial(models.Model):
    """Pronóstico de trabajo informado por el área comercial (clientes a atender)."""

    fecha = models.DateField(db_index=True)
    zona = models.ForeignKey(Zona, null=True, blank=True, on_delete=models.SET_NULL)
    tipo_tarea = models.ForeignKey(TipoTarea, on_delete=models.PROTECT)
    cantidad_clientes = models.PositiveIntegerField()
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["fecha"]
        verbose_name = "Demanda comercial prevista"
        verbose_name_plural = "Demanda comercial prevista"

    def __str__(self):
        return f"{self.fecha} {self.tipo_tarea} x{self.cantidad_clientes}"
