import uuid
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import Persona
from operaciones.models import OrdenTrabajo

ESCALA_1_5 = [MinValueValidator(1), MaxValueValidator(5)]


class InformeQuerySet(models.QuerySet):
    def representativos(self):
        """Controles que sirven para medir la calidad general (no los dirigidos por sospecha o reclamo)."""
        return self.exclude(motivo_seleccion__in=NO_REPRESENTATIVOS)


NO_REPRESENTATIVOS = ("sospecha", "reclamo")


class InformeControl(models.Model):
    """Informe que el supervisor sube desde la app móvil al controlar en calle."""

    objects = InformeQuerySet.as_manager()

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
    motivo_seleccion = models.CharField(
        "Por qué se controló", max_length=12, default="programado", choices=[
            ("programado", "Programado / plan de control"), ("aleatorio", "Muestra aleatoria"),
            ("sospecha", "Por sospecha o antecedente"), ("reclamo", "Por reclamo del cliente")],
        help_text="Los controles por sospecha o reclamo no representan la calidad de toda la operación.")
    plantilla = models.ForeignKey("PlantillaInspeccion", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="informes")
    revision_visita = models.CharField(
        "Resultado de la revisión de la visita", max_length=12, blank=True,
        choices=[("aprobada", "Trabajo aprobado"), ("rechazada", "Trabajo rechazado")],
        help_text="Si se controló una orden: queda como revisión técnica de esa visita (no depende del puntaje).")
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ["-creado"]
        verbose_name = "Informe de control"
        verbose_name_plural = "Informes de control"

    def __str__(self):
        return f"{self.fecha} {self.supervisor.apellido} → {self.tecnico.apellido}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.orden_id and self.revision_visita:
            # Revisión técnica de la última visita de esa orden (estado propio, distinto del cierre)
            from operaciones.models import Intento
            it = Intento.objects.filter(orden_id=self.orden_id).order_by("-numero").first()
            if it:
                Intento.objects.filter(pk=it.pk).update(revision_tecnica=self.revision_visita,
                                                        revisado_por_id=self.supervisor_id)

    @property
    def hallazgos(self):
        """Defectos tipificados de los puntos que no cumplieron."""
        return [r for r in self.resultados.select_related("item") if r.resultado == "no_cumple"]

    @property
    def calidad_informe(self) -> int:
        """COMPLETITUD DOCUMENTAL del informe (no calidad técnica del control ni del trabajo), 0-100:
        texto, foto, ubicación, orden y, si se usó plantilla, puntos completados."""
        pts = 0
        largo = len(self.descripcion.strip())
        pts += 40 if largo >= 80 else 25 if largo >= 30 else 10 if largo else 0
        pts += 30 if self.foto else 0
        pts += 15 if self.latitud is not None else 0
        pts += 15 if self.orden_id else 0
        if self.plantilla_id:
            total = self.plantilla.items.count()
            hechos = self.resultados.count()
            if total and hechos < total:
                pts = int(pts * hechos / total)
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
                                help_text="Sólo para multas. Ojo: no se descuentan del sueldo (art. 131 LCT).")
    dias_suspension = models.PositiveSmallIntegerField(default=0, help_text="Sólo para suspensiones: días sin goce.")
    descripcion = models.TextField(blank=True)
    cumplida = models.BooleanField(default=False, help_text="La acción se ejecutó (no implica que haya funcionado).")
    fecha_cumplida = models.DateField(null=True, blank=True,
                                      help_text="Desde acá se cuenta el seguimiento para verificar si fue efectiva.")

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Acción correctiva"
        verbose_name_plural = "Acciones correctivas"

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.tecnico} ({self.fecha})"

    def save(self, *args, **kwargs):
        if self.cumplida and not self.fecha_cumplida:
            self.fecha_cumplida = max(self.fecha, timezone.localdate()) if self.pk else self.fecha
        elif not self.cumplida:
            self.fecha_cumplida = None
        super().save(*args, **kwargs)

    @property
    def dias_respuesta(self):
        """Días entre que se detectó el desvío y se aplicó la acción."""
        if self.informe_id:
            return (self.fecha - self.informe.fecha).days
        return None


class PlantillaInspeccion(models.Model):
    """Plantilla versionada de control: qué puntos observar y con qué criterio de aceptación."""

    nombre = models.CharField(max_length=120)
    tipo = models.CharField(max_length=20, default="calidad")
    version = models.PositiveIntegerField(default=1)
    vigente = models.BooleanField(default=True)
    creada = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["nombre", "-version"]
        unique_together = [("nombre", "version")]
        verbose_name = "Plantilla de inspección"
        verbose_name_plural = "Plantillas de inspección"

    def __str__(self):
        return f"{self.nombre} v{self.version}"


class ItemPlantilla(models.Model):
    plantilla = models.ForeignKey(PlantillaInspeccion, on_delete=models.CASCADE, related_name="items")
    orden = models.PositiveSmallIntegerField(default=0)
    punto = models.CharField("Punto a observar", max_length=200)
    criterio = models.CharField("Criterio de aceptación", max_length=200)
    defecto = models.CharField("Defecto si no cumple", max_length=120,
                               help_text="Hallazgo tipificado (p. ej. 'Conector sin protector').")
    critico = models.BooleanField(default=False)

    class Meta:
        ordering = ["plantilla", "orden"]
        verbose_name = "Punto de la plantilla"
        verbose_name_plural = "Puntos de la plantilla"

    def __str__(self):
        return self.punto


class ResultadoItem(models.Model):
    """Resultado de un punto en un control concreto: cumple / no cumple / no aplica, con su medida."""

    informe = models.ForeignKey("InformeControl", on_delete=models.CASCADE, related_name="resultados")
    item = models.ForeignKey(ItemPlantilla, on_delete=models.PROTECT)
    resultado = models.CharField(max_length=10, choices=[("cumple", "Cumple"), ("no_cumple", "No cumple"),
                                                         ("na", "No aplica")])
    medida = models.CharField("Medida / observación", max_length=120, blank=True)

    class Meta:
        unique_together = [("informe", "item")]
        verbose_name = "Resultado del punto"
        verbose_name_plural = "Resultados de los puntos"


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
    criterio_aceptacion = models.CharField(
        "Criterio de aceptación", max_length=250, blank=True,
        help_text="Qué tiene que pasar para darlo por cumplido (p. ej. 'los 3 desvíos con acción cumplida').")
    evidencia = models.CharField(max_length=250, blank=True, help_text="Lo que el supervisor aporta al reportar.")
    verificacion = models.CharField(max_length=12, default="sin_reporte", choices=[
        ("sin_reporte", "Sin reporte"), ("reportado", "Reportado (a verificar)"),
        ("verificado", "Verificado"), ("rechazado", "Rechazado")])
    verificado_por = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    fecha_verificacion = models.DateTimeField(null=True, blank=True)
    historial_meta = models.JSONField(default=list, blank=True, help_text="Cambios de la meta (fecha, antes, después).")

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Tarea / objetivo de supervisor"
        verbose_name_plural = "Tareas / objetivos de supervisores"

    def __str__(self):
        return f"{self.fecha} {self.supervisor.apellido}: {self.descripcion}"

    def save(self, *args, **kwargs):
        if self.pk:
            anterior = TareaSupervisor.objects.filter(pk=self.pk).values_list("meta", flat=True).first()
            if anterior != self.meta:
                self.historial_meta = (self.historial_meta or []) + [
                    {"fecha": timezone.now().isoformat(timespec="minutes"), "antes": anterior, "despues": self.meta}]
        super().save(*args, **kwargs)

    @property
    def cumplimiento(self) -> float | None:
        """Sólo lo VERIFICADO cuenta como cumplido (lo reportado espera verificación; rechazado = 0)."""
        if self.verificacion == "rechazado":
            return 0.0
        if self.verificacion == "sin_reporte" and self.estado == self.Estado.NO_CUMPLIDA:
            return 0.0  # venció sin que el supervisor lo reportara
        if self.verificacion != "verificado":
            return None
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


class EncuestaSemanal(models.Model):
    """Evaluación semanal, más completa, que el técnico hace de su supervisor.

    Una por técnico y semana (la semana se identifica por su lunes). Confidencial:
    el supervisor sólo ve promedios."""

    semana = models.DateField(db_index=True, help_text="Lunes de la semana evaluada.")
    tecnico = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="encuestas_semanales")
    supervisor = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="encuestas_semanales_recibidas")
    respondida = models.DateTimeField(auto_now_add=True)
    general = models.PositiveSmallIntegerField("Calificación general de la semana", validators=ESCALA_1_5)
    trato = models.PositiveSmallIntegerField("Trato y respeto", validators=ESCALA_1_5)
    organizacion = models.PositiveSmallIntegerField("Organización y reparto del trabajo", validators=ESCALA_1_5)
    apoyo = models.PositiveSmallIntegerField("Apoyo cuando hubo problemas", validators=ESCALA_1_5)
    ensenanza = models.PositiveSmallIntegerField("Te ayudó a mejorar / te enseñó", validators=ESCALA_1_5)
    justicia = models.PositiveSmallIntegerField("Fue justo con el equipo", validators=ESCALA_1_5)
    lo_mejor = models.TextField("Lo mejor de la semana", blank=True)
    a_mejorar = models.TextField("Qué debería mejorar", blank=True)

    class Meta:
        ordering = ["-semana"]
        unique_together = [("semana", "tecnico")]
        verbose_name = "Evaluación semanal al supervisor"
        verbose_name_plural = "Evaluaciones semanales a supervisores"

    def __str__(self):
        return f"Semana {self.semana:%d/%m} {self.tecnico.apellido} → {self.supervisor.apellido}"

    @property
    def promedio(self) -> float:
        notas = [self.general, self.trato, self.organizacion, self.apoyo, self.ensenanza, self.justicia]
        return sum(notas) / len(notas)
