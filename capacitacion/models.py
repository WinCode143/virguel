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


class CriterioEvaluacion(models.Model):
    """Versión de los pesos y reglas de la evaluación de técnicos.

    Cambiar pesos crea una versión nueva (vigente desde una fecha): cada foto histórica guarda la
    versión con la que se calculó, para poder comparar y revisar los criterios con la empresa.
    Los pesos son una convención de gestión, no una probabilidad validada de riesgo."""

    version = models.PositiveIntegerField(unique=True)
    vigente_desde = models.DateField()
    descripcion = models.CharField(max_length=200, blank=True)
    parametros = models.JSONField(help_text="Pesos: dimensiones, acciones, siniestros, faltas y tardanzas.")

    class Meta:
        ordering = ["-vigente_desde", "-version"]
        verbose_name = "Criterio de evaluación (versión)"
        verbose_name_plural = "Criterios de evaluación (versiones)"

    def __str__(self):
        return f"v{self.version} desde {self.vigente_desde:%d/%m/%Y}"


class EvaluacionHistorica(models.Model):
    """Foto semanal de la evaluación automática de cada técnico (capacidad a largo plazo)."""

    fecha = models.DateField(db_index=True)
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="historial_evaluacion")
    productividad = models.DecimalField(max_digits=6, decimal_places=2)
    indice_productividad = models.DecimalField(max_digits=6, decimal_places=3)
    score_productividad = models.DecimalField(max_digits=5, decimal_places=1)
    score_calidad = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    score_disciplina = models.DecimalField(max_digits=5, decimal_places=1)
    score_seguridad = models.DecimalField(max_digits=5, decimal_places=1)
    riesgo = models.DecimalField(max_digits=5, decimal_places=1)
    diagnostico = models.CharField(max_length=60)
    criterio_version = models.PositiveIntegerField(null=True, blank=True,
                                                   help_text="Versión del criterio con que se calculó.")

    class Meta:
        ordering = ["-fecha"]
        unique_together = [("fecha", "persona")]
        verbose_name = "Evaluación histórica (semanal)"
        verbose_name_plural = "Evaluaciones históricas (semanales)"

    def __str__(self):
        return f"{self.fecha} {self.persona}: {self.diagnostico}"
