import uuid
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import Persona
from operaciones.models import OrdenTrabajo

ESCALA_1_5 = [MinValueValidator(1), MaxValueValidator(5)]


class InformeControl(models.Model):
    """Informe que el supervisor sube desde la app móvil al controlar en calle."""

    class Tipo(models.TextChoices):
        CALIDAD = "calidad", "Calidad de instalación"
        SEGURIDAD = "seguridad", "Seguridad / uso de EPP"
        VEHICULO = "vehiculo", "Estado de vehículo"
        CONDUCTA = "conducta", "Conducta / trato al cliente"

    supervisor = models.ForeignKey(Persona, on_delete=models.PROTECT, related_name="informes_realizados",
                                   limit_choices_to={"rol": "supervisor"})
    tecnico = models.ForeignKey(Persona, on_delete=models.PROTECT, related_name="informes_recibidos",
                                limit_choices_to={"rol": "tecnico"})
    orden = models.ForeignKey(OrdenTrabajo, null=True, blank=True, on_delete=models.SET_NULL)
    fecha = models.DateField(default=timezone.localdate, db_index=True)
    creado = models.DateTimeField(default=timezone.now)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.CALIDAD)
    puntaje = models.PositiveSmallIntegerField(
        "Puntaje del trabajo controlado (1-5)", validators=ESCALA_1_5)
    desvio_detectado = models.BooleanField(default=False)
    descripcion = models.TextField(blank=True)
    foto = models.FileField(upload_to="informes/%Y/%m/", blank=True)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ["-creado"]
        verbose_name = "Informe de control"
        verbose_name_plural = "Informes de control"

    def __str__(self):
        return f"{self.fecha} {self.supervisor.apellido} → {self.tecnico.apellido}"

    @property
    def calidad_informe(self) -> int:
        """Calidad del *informe* (no del trabajo), 0-100: ¿está bien documentado?"""
        pts = 0
        largo = len(self.descripcion.strip())
        pts += 40 if largo >= 80 else 25 if largo >= 30 else 10 if largo else 0
        pts += 30 if self.foto else 0
        pts += 15 if self.latitud is not None else 0
        pts += 15 if self.orden_id else 0
        return pts


class AccionCorrectiva(models.Model):
    class Tipo(models.TextChoices):
        RECAPACITACION = "recapacitacion", "Recapacitación"
        APERCIBIMIENTO = "apercibimiento", "Apercibimiento"
        MULTA = "multa", "Multa / descuento"
        SUSPENSION = "suspension", "Suspensión"
        CHARLA = "charla", "Charla / corrección en el momento"

    informe = models.ForeignKey(InformeControl, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="acciones")
    tecnico = models.ForeignKey(Persona, on_delete=models.PROTECT, related_name="acciones_correctivas",
                                limit_choices_to={"rol": "tecnico"})
    aplicada_por = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="acciones_aplicadas")
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    fecha = models.DateField(default=timezone.localdate)
    monto = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"),
                                help_text="Solo para multas.")
    descripcion = models.TextField(blank=True)
    cumplida = models.BooleanField(default=False)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Acción correctiva"
        verbose_name_plural = "Acciones correctivas"

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.tecnico} ({self.fecha})"

    @property
    def dias_respuesta(self):
        """Días entre que se detectó el desvío y se aplicó la acción."""
        if self.informe_id:
            return (self.fecha - self.informe.fecha).days
        return None


class TareaSupervisor(models.Model):
    """Objetivo asignado diariamente al supervisor por gerencia."""

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        CUMPLIDA = "cumplida", "Cumplida"
        PARCIAL = "parcial", "Parcial"
        NO_CUMPLIDA = "no_cumplida", "No cumplida"

    supervisor = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="tareas_supervisor",
                                   limit_choices_to={"rol": "supervisor"})
    fecha = models.DateField(default=timezone.localdate, db_index=True)
    descripcion = models.CharField(max_length=250)
    meta = models.PositiveIntegerField(null=True, blank=True,
                                       help_text="Valor objetivo si es medible (ej: 8 controles).")
    resultado = models.PositiveIntegerField(null=True, blank=True)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    comentario = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Tarea / objetivo de supervisor"
        verbose_name_plural = "Tareas / objetivos de supervisores"

    def __str__(self):
        return f"{self.fecha} {self.supervisor.apellido}: {self.descripcion}"

    @property
    def cumplimiento(self) -> float | None:
        if self.meta:
            return min(1.0, (self.resultado or 0) / self.meta)
        return {"cumplida": 1.0, "parcial": 0.5, "no_cumplida": 0.0}.get(self.estado)


class EncuestaSupervisor(models.Model):
    """Encuesta de cierre de jornada: el técnico califica el trato de su supervisor.

    Se genera automáticamente cada día para cada técnico que estuvo en calle.
    Las respuestas individuales solo las ve gerencia; el supervisor ve promedios.
    """

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    fecha = models.DateField(db_index=True)
    tecnico = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="encuestas_respondidas")
    supervisor = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="encuestas_recibidas")
    respondida = models.DateTimeField(null=True, blank=True)
    trato = models.PositiveSmallIntegerField("Trato y respeto", null=True, blank=True, validators=ESCALA_1_5)
    claridad = models.PositiveSmallIntegerField("Claridad de las indicaciones", null=True, blank=True,
                                                validators=ESCALA_1_5)
    apoyo = models.PositiveSmallIntegerField("Apoyo ante problemas", null=True, blank=True,
                                             validators=ESCALA_1_5)
    presencia = models.PositiveSmallIntegerField("Presencia / disponibilidad", null=True, blank=True,
                                                 validators=ESCALA_1_5)
    comentario = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha"]
        unique_together = [("fecha", "tecnico")]
        verbose_name = "Encuesta diaria al supervisor"
        verbose_name_plural = "Encuestas diarias a supervisores"

    def __str__(self):
        return f"{self.fecha} {self.tecnico.apellido} → {self.supervisor.apellido}"

    @property
    def promedio(self) -> float | None:
        notas = [n for n in (self.trato, self.claridad, self.apoyo, self.presencia) if n]
        return sum(notas) / len(notas) if notas else None
