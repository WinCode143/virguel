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


class MovimientoStockTecnico(models.Model):
    """Libro de las partes que tiene cada técnico a su cargo (en la camioneta).

    Entrega del depósito: +cantidad.  Consumo en una orden: -cantidad.
    Devolución al depósito: -cantidad.  Ajuste por inventario: +/-.
    El saldo por técnico y material es la suma de sus movimientos."""

    class Tipo(models.TextChoices):
        ENTREGA = "entrega", "Entrega del depósito"
        CONSUMO = "consumo", "Consumo en orden"
        DEVOLUCION = "devolucion", "Devolución al depósito"
        AJUSTE = "ajuste", "Ajuste de inventario"

    tecnico = models.ForeignKey(Persona, on_delete=models.PROTECT, related_name="movimientos_stock")
    material = models.ForeignKey(Material, on_delete=models.PROTECT, related_name="movimientos_tecnico")
    fecha = models.DateField(default=timezone.localdate, db_index=True)
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2, help_text="Positivo entra, negativo sale.")
    orden = models.ForeignKey(OrdenTrabajo, null=True, blank=True, on_delete=models.SET_NULL)
    pedido = models.ForeignKey("PedidoMaterial", null=True, blank=True, on_delete=models.SET_NULL)
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Movimiento de stock del técnico"
        verbose_name_plural = "Movimientos de stock de técnicos"

    def __str__(self):
        return f"{self.tecnico} {self.get_tipo_display()} {self.cantidad} {self.material.codigo}"


class PedidoMaterial(models.Model):
    """Pedido de partes del técnico: lo aprueba el supervisor y lo entrega el depósito."""

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de aprobación"
        APROBADO = "aprobado", "Aprobado (a preparar)"
        ENTREGADO = "entregado", "Entregado"
        RECHAZADO = "rechazado", "Rechazado"

    tecnico = models.ForeignKey(Persona, on_delete=models.PROTECT, related_name="pedidos_material")
    creado = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True)
    motivo = models.CharField(max_length=200, blank=True)
    respuesta = models.CharField(max_length=200, blank=True)
    aprobado_por = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="pedidos_aprobados")
    entregado = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-creado"]
        verbose_name = "Pedido de materiales"
        verbose_name_plural = "Pedidos de materiales"

    def __str__(self):
        return f"Pedido {self.id} de {self.tecnico} ({self.get_estado_display()})"


class PedidoItem(models.Model):
    pedido = models.ForeignKey(PedidoMaterial, on_delete=models.CASCADE, related_name="items")
    material = models.ForeignKey(Material, on_delete=models.PROTECT)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    cantidad_entregada = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "Ítem del pedido"
        verbose_name_plural = "Ítems del pedido"
