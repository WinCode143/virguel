from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.models import Cliente, Persona, Zona
from operaciones.models import OrdenTrabajo


class Siniestro(models.Model):
    """Falla grave en terreno que puede comprometer la responsabilidad civil."""

    class Tipo(models.TextChoices):
        ROTURA_VIVIENDA = "rotura_vivienda", "Rotura en vivienda"
        CANO_PINCHADO = "cano_pinchado", "Caño pinchado (agua/gas)"
        CABLEADO_TERCEROS = "cableado", "Daño a cableado de terceros"
        VEHICULO = "vehiculo", "Accidente de vehículo"
        LESION = "lesion", "Lesión de persona"
        OTRO = "otro", "Otro"

    class Gravedad(models.TextChoices):
        LEVE = "leve", "Leve"
        GRAVE = "grave", "Grave"
        CRITICA = "critica", "Crítica"

    class Estado(models.TextChoices):
        ABIERTO = "abierto", "Abierto"
        EN_GESTION = "en_gestion", "En gestión / negociación"
        RECLAMO_LEGAL = "legal", "Reclamo legal en curso"
        CERRADO = "cerrado", "Cerrado"

    class Resolucion(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        REPARACION_PROPIA = "reparacion", "Reparación a cargo de la empresa"
        ACUERDO = "acuerdo", "Acuerdo económico con el damnificado"
        SEGURO = "seguro", "Cubierto por seguro"
        JUICIO = "juicio", "Juicio"
        RECHAZADO = "rechazado", "Reclamo rechazado (sin responsabilidad)"

    class Investigacion(models.TextChoices):
        SIN_INICIAR = "sin_iniciar", "Sin iniciar"
        EN_CURSO = "en_curso", "En curso"
        CONCLUIDA = "concluida", "Concluida"

    class Atribucion(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de investigación"
        CONFIRMADA = "confirmada", "Conducta del técnico confirmada"
        DESCARTADA = "descartada", "Descartada (no atribuible al técnico)"

    numero = models.CharField(max_length=20, unique=True)
    fecha = models.DateField(default=timezone.localdate, db_index=True)
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    gravedad = models.CharField(max_length=10, choices=Gravedad.choices, default=Gravedad.GRAVE)
    responsabilidad_civil = models.BooleanField(
        default=True, help_text="¿Involucra responsabilidad civil de la empresa frente a terceros?")
    tecnico = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="siniestros", limit_choices_to={"rol": "tecnico"})
    supervisor = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="siniestros_supervisados", limit_choices_to={"rol": "supervisor"})
    orden = models.ForeignKey(OrdenTrabajo, null=True, blank=True, on_delete=models.SET_NULL)
    cliente = models.ForeignKey(Cliente, null=True, blank=True, on_delete=models.SET_NULL)
    zona = models.ForeignKey(Zona, null=True, blank=True, on_delete=models.SET_NULL)
    direccion = models.CharField(max_length=200, blank=True)
    descripcion = models.TextField()
    causa_raiz = models.TextField(blank=True, help_text="Por qué ocurrió (falta de capacitación, apuro, herramienta, etc.)")
    plan_accion = models.TextField(blank=True, help_text="Cómo se mitiga y cómo se evita que se repita.")
    costo_estimado = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    costo_real = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    monto_recuperado = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0"),
        help_text="Recuperado por seguro, descuento al responsable, etc.")
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.ABIERTO, db_index=True)
    resolucion = models.CharField(max_length=15, choices=Resolucion.choices, default=Resolucion.PENDIENTE)
    fecha_cierre = models.DateField(null=True, blank=True)
    reportado_por = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="siniestros_reportados")
    # Investigación y atribución: estar vinculado no acredita haberlo causado
    investigacion = models.CharField(max_length=12, choices=Investigacion.choices, default=Investigacion.SIN_INICIAR)
    hechos = models.TextField("Hechos comprobados", blank=True)
    atribucion = models.CharField(
        "Atribución al técnico", max_length=12, choices=Atribucion.choices, default=Atribucion.PENDIENTE,
        help_text="Sólo una atribución CONFIRMADA afecta la evaluación del técnico.")
    atribucion_fundamento = models.TextField("Fundamento de la atribución", blank=True)
    atribucion_por = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                       verbose_name="Decidió la atribución")
    atribucion_fecha = models.DateField(null=True, blank=True)
    responsable_gestion = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                            related_name="siniestros_a_cargo", verbose_name="Responsable del seguimiento")

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Siniestro / incidente"
        verbose_name_plural = "Siniestros / incidentes"

    def __str__(self):
        return f"{self.numero} {self.get_tipo_display()} ({self.fecha})"

    @property
    def costo_neto(self) -> Decimal:
        base = self.costo_real or self.costo_estimado
        return base - self.monto_recuperado

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.atribucion != self.Atribucion.PENDIENTE and not (self.atribucion_fundamento or "").strip():
            raise ValidationError({"atribucion_fundamento": "Confirmar o descartar la atribución requiere fundamento."})

    def save(self, *args, **kwargs):
        if self.atribucion != self.Atribucion.PENDIENTE and not self.atribucion_fecha:
            self.atribucion_fecha = timezone.localdate()
        super().save(*args, **kwargs)

    def recomendacion_legal(self) -> str:
        """Próximo paso del expediente según el procedimiento (no es una conclusión jurídica)."""
        if self.investigacion != self.Investigacion.CONCLUIDA:
            pasos = "Completar la investigación (hechos, evidencia y causa)"
            if self.gravedad == self.Gravedad.CRITICA or self.tipo == self.Tipo.LESION:
                return pasos + " y dar aviso inmediato a legales y aseguradora según el procedimiento."
            return pasos + " antes de decidir responsabilidades o acuerdos."
        if not self.responsable_gestion_id:
            return "Asignar un responsable del seguimiento."
        costo = self.costo_real or self.costo_estimado
        if self.gravedad == self.Gravedad.CRITICA or self.tipo == self.Tipo.LESION or costo >= Decimal("500000"):
            return "Derivar a legales y aseguradora según el procedimiento aprobado."
        return "Decidir reparación, acuerdo o cierre según el procedimiento aprobado y registrar la decisión."
