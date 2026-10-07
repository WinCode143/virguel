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

    def recomendacion_legal(self) -> str:
        """Sugerencia de cómo accionar, según gravedad, costo y responsabilidad."""
        if not self.responsabilidad_civil:
            return "Documentar y rechazar reclamo: sin responsabilidad de la empresa."
        costo = self.costo_real or self.costo_estimado
        if self.gravedad == self.Gravedad.CRITICA or self.tipo == self.Tipo.LESION:
            return "Dar intervención inmediata a legales y aseguradora; no negociar sin asesoramiento."
        if costo >= Decimal("500000"):
            return "Denunciar a la aseguradora; evaluar acuerdo con asesoramiento legal."
        if costo >= Decimal("100000"):
            return "Negociar acuerdo directo con el damnificado y documentar conformidad firmada."
        return "Reparación directa por cuadrilla propia para minimizar costo; registrar conformidad."
