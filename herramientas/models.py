from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.db.models.functions import Greatest
from django.utils import timezone

from core.models import Persona


class Elemento(models.Model):
    """EPP, herramienta o material crítico que se asigna a una persona."""

    class Tipo(models.TextChoices):
        EPP = "epp", "Elemento de protección personal"
        HERRAMIENTA = "herramienta", "Herramienta"
        CRITICO = "critico", "Material crítico de seguridad"

    codigo = models.CharField(max_length=30, unique=True)
    nombre = models.CharField(max_length=120)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.EPP)
    vida_util_dias = models.PositiveIntegerField(
        null=True, blank=True, help_text="Días hasta reemplazo obligatorio (vacío = sin vencimiento).")
    obligatorio_tecnicos = models.BooleanField(
        default=False, help_text="Todo técnico en calle debe tenerlo asignado y vigente.")
    costo = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    stock = models.PositiveIntegerField(default=0, help_text="Unidades en pañol para entregar.")

    class Meta:
        ordering = ["tipo", "nombre"]
        verbose_name = "Herramienta / EPP"
        verbose_name_plural = "Herramientas / EPP"

    def __str__(self):
        return self.nombre


class CompraElemento(models.Model):
    """Compra de herramientas/EPP para el pañol: es el gasto (egreso). Asignarlas después a una
    persona es custodia y no vuelve a contar como gasto."""

    elemento = models.ForeignKey(Elemento, on_delete=models.PROTECT, related_name="compras")
    fecha = models.DateField(default=timezone.localdate)
    cantidad = models.PositiveIntegerField()
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    proveedor = models.CharField(max_length=120, blank=True)
    comprobante = models.CharField("N° de factura / remito", max_length=50, blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Compra de herramientas / EPP"
        verbose_name_plural = "Compras de herramientas / EPP"

    def __str__(self):
        return f"{self.cantidad} × {self.elemento} ({self.fecha:%d/%m/%Y})"

    def save(self, *args, **kwargs):
        nueva = self._state.adding
        super().save(*args, **kwargs)
        if nueva:
            Elemento.objects.filter(pk=self.elemento_id).update(stock=models.F("stock") + self.cantidad)


class Asignacion(models.Model):
    class Origen(models.TextChoices):
        PANOL = "panol", "Del pañol (ya comprado)"
        COMPRA = "compra", "Comprado para esta entrega"
        REASIGNACION = "reasignacion", "Reasignado (lo tenía otra persona)"

    class Estado(models.TextChoices):
        EN_USO = "en_uso", "En uso"
        DEVUELTO = "devuelto", "Devuelto"
        PERDIDO = "perdido", "Perdido"
        DANADO = "danado", "Dañado / reemplazado"

    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="asignaciones")
    elemento = models.ForeignKey(Elemento, on_delete=models.PROTECT, related_name="asignaciones")
    fecha_entrega = models.DateField(default=timezone.localdate)
    cantidad = models.PositiveSmallIntegerField(default=1)
    origen = models.CharField(
        max_length=12, choices=Origen.choices, default=Origen.PANOL,
        help_text="Sólo 'Comprado para esta entrega' es un gasto nuevo; del pañol o reasignado es custodia.")
    fecha_vencimiento = models.DateField(null=True, blank=True, editable=False)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.EN_USO)
    conformidad_firmada = models.BooleanField(
        default=False, help_text="El técnico firmó/confirmó la recepción (en la app).")
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-fecha_entrega"]
        verbose_name = "Asignación de herramienta / EPP"
        verbose_name_plural = "Asignaciones de herramientas / EPP"

    def __str__(self):
        return f"{self.elemento} → {self.persona}"

    def save(self, *args, **kwargs):
        if self.elemento.vida_util_dias:
            self.fecha_vencimiento = self.fecha_entrega + timedelta(days=self.elemento.vida_util_dias)
        else:
            self.fecha_vencimiento = None
        nueva = self._state.adding
        estado_anterior = None if nueva else (
            Asignacion.objects.filter(pk=self.pk).values_list("estado", flat=True).first())
        super().save(*args, **kwargs)
        # Custodia del pañol: lo entregado sale del pañol; lo devuelto en uso vuelve.
        if nueva and self.origen == self.Origen.PANOL:
            Elemento.objects.filter(pk=self.elemento_id).update(
                stock=Greatest(models.F("stock") - self.cantidad, 0))
        elif (estado_anterior == self.Estado.EN_USO and self.estado == self.Estado.DEVUELTO):
            Elemento.objects.filter(pk=self.elemento_id).update(stock=models.F("stock") + self.cantidad)

    @property
    def es_gasto(self) -> bool:
        return self.origen == self.Origen.COMPRA

    @property
    def vencida(self) -> bool:
        return bool(self.fecha_vencimiento and self.fecha_vencimiento < timezone.localdate())
