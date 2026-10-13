from django.conf import settings
from django.db import models
from django.utils import timezone


class Importacion(models.Model):
    """Registro de cada archivo importado (quién, cuándo, qué y con qué resultado)."""

    tipo = models.CharField(max_length=20)
    archivo = models.CharField("Nombre del archivo", max_length=200, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    fecha = models.DateTimeField(default=timezone.now)
    total = models.PositiveIntegerField(default=0)
    creados = models.PositiveIntegerField(default=0)
    actualizados = models.PositiveIntegerField(default=0)
    omitidos = models.PositiveIntegerField(default=0, help_text="Filas no aplicadas (duplicadas u órdenes cerradas).")

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Importación"
        verbose_name_plural = "Importaciones"

    def __str__(self):
        return f"{self.tipo} {self.fecha:%d/%m/%Y %H:%M}"


class ConflictoImportacion(models.Model):
    """Fila que el archivo quería cambiar pero el sistema protegió (p. ej. una orden ya cerrada)."""

    importacion = models.ForeignKey(Importacion, on_delete=models.CASCADE, related_name="conflictos")
    fila = models.PositiveIntegerField()
    clave = models.CharField("Registro", max_length=60)
    campo = models.CharField(max_length=40)
    valor_actual = models.CharField(max_length=200, blank=True)
    valor_importado = models.CharField(max_length=200, blank=True)
    motivo = models.CharField(max_length=200)

    class Meta:
        ordering = ["importacion", "fila"]
        verbose_name = "Conflicto de importación"
        verbose_name_plural = "Conflictos de importación"

    def __str__(self):
        return f"Fila {self.fila} {self.clave}: {self.campo}"
