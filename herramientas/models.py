from datetime import timedelta
from decimal import Decimal

from django.db import models
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


class Asignacion(models.Model):
    class Estado(models.TextChoices):
        EN_USO = "en_uso", "En uso"
        DEVUELTO = "devuelto", "Devuelto"
        PERDIDO = "perdido", "Perdido"
        DANADO = "danado", "Dañado / reemplazado"

    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="asignaciones")
    elemento = models.ForeignKey(Elemento, on_delete=models.PROTECT, related_name="asignaciones")
    fecha_entrega = models.DateField(default=timezone.localdate)
    cantidad = models.PositiveSmallIntegerField(default=1)
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
        super().save(*args, **kwargs)

    @property
    def vencida(self) -> bool:
        return bool(self.fecha_vencimiento and self.fecha_vencimiento < timezone.localdate())
