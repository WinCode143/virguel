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
    motivo = models.CharField("Motivo / objetivo", max_length=200, blank=True,
                              help_text="Defecto o necesidad que la origina (p. ej. hallazgo de control, plan de mejora).")
    accion_correctiva = models.ForeignKey("supervision.AccionCorrectiva", null=True, blank=True,
                                          on_delete=models.SET_NULL, related_name="capacitaciones",
                                          help_text="Si la capacitación es una acción correctiva.")
    participantes = models.ManyToManyField(Persona, through="Participacion", through_fields=("capacitacion", "persona"),
                                           related_name="capacitaciones")

    class Meta:
        ordering = ["-fecha"]
        verbose_name_plural = "Capacitaciones"

    def __str__(self):
        return f"{self.curso} ({self.fecha})"


class Participacion(models.Model):
    """Asistencia, evaluación y habilitación son cosas distintas: asistir no aprueba; la aprobación
    queda PENDIENTE hasta que alguien evalúa (práctica, evaluador, resultado)."""

    capacitacion = models.ForeignKey(Capacitacion, on_delete=models.CASCADE)
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="participaciones")
    asistio = models.BooleanField(default=True)
    aprobado = models.BooleanField(null=True, blank=True, default=None,
                                   help_text="Vacío = pendiente de evaluación (asistir no aprueba).")
    nota = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    evaluador = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    fecha_evaluacion = models.DateField(null=True, blank=True)
    evidencia = models.CharField("Evidencia de la evaluación", max_length=200, blank=True,
                                 help_text="Práctica observada, examen, trabajo controlado...")

    @property
    def resultado(self) -> str:
        if not self.asistio:
            return "No asistió"
        return {None: "Pendiente de evaluación", True: "Aprobado", False: "No aprobado"}[self.aprobado]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.aprobado is not None and not (self.evaluador_id and self.evidencia):
            raise ValidationError("Aprobar o desaprobar requiere evaluador y evidencia.")

    class Meta:
        unique_together = [("capacitacion", "persona")]
        verbose_name = "Participación"
        verbose_name_plural = "Participaciones"


class EvaluacionCompetencia(models.Model):
    """Habilitación: nivel comprobado de una competencia, con evaluador, evidencia y vigencia."""

    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="evaluaciones")
    competencia = models.ForeignKey(Competencia, on_delete=models.CASCADE)
    fecha = models.DateField(default=timezone.localdate)
    vence = models.DateField(null=True, blank=True, help_text="Vacío = sin vencimiento.")
    nivel = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    evaluador = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="evaluaciones_realizadas")
    comentario = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Evaluación de competencia"
        verbose_name_plural = "Evaluaciones de competencias"


class RequisitoCompetencia(models.Model):
    """Competencia que exige un tipo de tarea. Sin habilitación vigente la asignación se bloquea (o se
    permite en modalidad tutelada, si la empresa la admite para esa tarea)."""

    tipo_tarea = models.ForeignKey("operaciones.TipoTarea", on_delete=models.CASCADE, related_name="requisitos")
    competencia = models.ForeignKey(Competencia, on_delete=models.CASCADE)
    nivel_minimo = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(5)])
    permite_tutelada = models.BooleanField("Permite ejecución tutelada", default=False,
                                           help_text="Con nivel menor pero acompañado por alguien habilitado.")

    class Meta:
        unique_together = [("tipo_tarea", "competencia")]
        verbose_name = "Competencia requerida por tarea"
        verbose_name_plural = "Competencias requeridas por tarea"

    def __str__(self):
        return f"{self.tipo_tarea}: {self.competencia} ≥ {self.nivel_minimo}"


def habilitacion(persona_id, tipo_tarea_id, fecha=None) -> dict:
    """{"estado": "habilitado"|"tutelada"|"bloqueado"|"sin_requisitos", "faltan": [...]}."""
    fecha = fecha or timezone.localdate()
    reqs = list(RequisitoCompetencia.objects.filter(tipo_tarea_id=tipo_tarea_id).select_related("competencia"))
    if not reqs:
        return {"estado": "sin_requisitos", "faltan": []}
    niveles = {}
    for e in EvaluacionCompetencia.objects.filter(persona_id=persona_id, competencia__in=[r.competencia for r in reqs]
                                                  ).order_by("fecha"):
        if e.vence is None or e.vence >= fecha:
            niveles[e.competencia_id] = e.nivel
    faltan, tutelada = [], False
    for r in reqs:
        nivel = niveles.get(r.competencia_id, 0)
        if nivel >= r.nivel_minimo:
            continue
        if r.permite_tutelada and nivel >= 1:
            tutelada = True
            faltan.append(f"{r.competencia} (nivel {nivel}/{r.nivel_minimo}, tutelada)")
        else:
            faltan.append(f"{r.competencia} (nivel {nivel}/{r.nivel_minimo})")
    if not faltan:
        return {"estado": "habilitado", "faltan": []}
    bloqueado = any("tutelada" not in f for f in faltan)
    return {"estado": "bloqueado" if bloqueado else ("tutelada" if tutelada else "habilitado"), "faltan": faltan}


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


class PlanMejora(models.Model):
    """Plan individual de mejora o expediente de período de prueba: objetivos, apoyos, plazos,
    evidencia y decisión con fundamento. Las recomendaciones automáticas del diagnóstico son una
    hipótesis para abrirlo, no una conclusión."""

    class Tipo(models.TextChoices):
        MEJORA = "mejora", "Plan de mejora"
        PRUEBA = "prueba", "Período de prueba"

    class Estado(models.TextChoices):
        ABIERTO = "abierto", "Abierto"
        CERRADO = "cerrado", "Cerrado con decisión"
        CANCELADO = "cancelado", "Cancelado"

    class Decision(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        CUMPLIDO = "cumplido", "Objetivos cumplidos / confirma"
        EXTENDER = "extender", "Extender el plan"
        NO_CUMPLIDO = "no_cumplido", "No cumplido"

    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="planes_mejora")
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.MEJORA)
    responsable = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    desde = models.DateField(default=timezone.localdate)
    revisar_el = models.DateField("Revisar el")
    motivo = models.TextField(help_text="Qué se observó (con datos de origen: producción, calidad, controles...).")
    contexto = models.TextField("Contexto y trabajo disponible", blank=True,
                                help_text="Oportunidades reales: órdenes asignadas, recursos, ausencias, apoyos recibidos.")
    apoyos = models.TextField("Apoyos comprometidos", blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ABIERTO)
    decision = models.CharField(max_length=12, choices=Decision.choices, default=Decision.PENDIENTE)
    fundamento = models.TextField("Fundamento de la decisión", blank=True)
    decidido_por = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    fecha_decision = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-desde"]
        verbose_name = "Plan de mejora / período de prueba"
        verbose_name_plural = "Planes de mejora / períodos de prueba"

    def __str__(self):
        return f"{self.get_tipo_display()} de {self.persona} ({self.desde:%d/%m/%Y})"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.decision != self.Decision.PENDIENTE and not ((self.fundamento or "").strip() and self.decidido_por_id):
            raise ValidationError("Una decisión requiere fundamento y quién decidió.")


class ObjetivoPlan(models.Model):
    plan = models.ForeignKey(PlanMejora, on_delete=models.CASCADE, related_name="objetivos")
    descripcion = models.CharField(max_length=200)
    criterio = models.CharField("Criterio de aceptación", max_length=200,
                                help_text="Cómo se comprueba (p. ej. 'calidad en controles ≥ 4 en 3 controles').")
    plazo = models.DateField(null=True, blank=True)
    resultado = models.CharField(max_length=200, blank=True)
    verificado = models.BooleanField(null=True, blank=True, help_text="Vacío = sin verificar.")
    evidencia = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "Objetivo del plan"
        verbose_name_plural = "Objetivos del plan"
