from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import Persona


class Competencia(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Curso(models.Model):
    nombre = models.CharField(max_length=150)
    competencia = models.ForeignKey(Competencia, null=True, blank=True, on_delete=models.SET_NULL)
    horas = models.DecimalField(max_digits=5, decimal_places=1, default=4)
    obligatorio = models.BooleanField(default=False)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Capacitacion(models.Model):
    """Dictado concreto de un curso (fecha, instructor, asistentes)."""

    curso = models.ForeignKey(Curso, on_delete=models.PROTECT, related_name="dictados")
    fecha = models.DateField(default=timezone.localdate)
    instructor = models.CharField(max_length=120, blank=True)
    en_produccion = models.BooleanField(
        default=False, help_text="Capacitación en campo, acompañando al técnico en producción.")
    participantes = models.ManyToManyField(Persona, through="Participacion", related_name="capacitaciones")

    class Meta:
        ordering = ["-fecha"]
        verbose_name_plural = "Capacitaciones"

    def __str__(self):
        return f"{self.curso} ({self.fecha})"


class Participacion(models.Model):
    capacitacion = models.ForeignKey(Capacitacion, on_delete=models.CASCADE)
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="participaciones")
    asistio = models.BooleanField(default=True)
    aprobado = models.BooleanField(default=True)
    nota = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)

    class Meta:
        unique_together = [("capacitacion", "persona")]
        verbose_name = "Participación"
        verbose_name_plural = "Participaciones"


class EvaluacionCompetencia(models.Model):
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="evaluaciones")
    competencia = models.ForeignKey(Competencia, on_delete=models.CASCADE)
    fecha = models.DateField(default=timezone.localdate)
    nivel = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    evaluador = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="evaluaciones_realizadas")
    comentario = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Evaluación de competencia"
        verbose_name_plural = "Evaluaciones de competencias"
