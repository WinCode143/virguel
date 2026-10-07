"""Control de personal: asistencia (fichadas), novedades/licencias y legajo digital."""
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.models import Parametros, Persona


class Feriado(models.Model):
    fecha = models.DateField(unique=True)
    nombre = models.CharField(max_length=100)

    class Meta:
        ordering = ["fecha"]

    def __str__(self):
        return f"{self.fecha:%d/%m/%Y} {self.nombre}"


class Asistencia(models.Model):
    """Fichada diaria de entrada y salida (desde el celular con GPS, o cargada a mano)."""

    class Origen(models.TextChoices):
        APP = "app", "App (celular)"
        MANUAL = "manual", "Carga manual"
        IMPORTADO = "importado", "Importado / reloj"

    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="asistencias")
    fecha = models.DateField(db_index=True)
    entrada = models.DateTimeField()
    salida = models.DateTimeField(null=True, blank=True)
    lat_entrada = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng_entrada = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lat_salida = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng_salida = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    origen = models.CharField(max_length=10, choices=Origen.choices, default=Origen.APP)
    minutos_tarde = models.PositiveIntegerField(default=0, editable=False)
    horas_trabajadas = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"), editable=False)
    horas_extra = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"), editable=False)
    observacion = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-fecha", "persona__apellido"]
        unique_together = [("persona", "fecha")]
        verbose_name = "Asistencia (fichada)"
        verbose_name_plural = "Asistencias (fichadas)"

    def __str__(self):
        return f"{self.fecha} {self.persona}"

    def calcular(self, parametros=None):
        p = parametros or Parametros.actual()
        tz = timezone.get_current_timezone()
        esperada = timezone.make_aware(datetime.combine(self.fecha, self.persona.hora_entrada), tz)
        tarde = (timezone.localtime(self.entrada, tz) - esperada).total_seconds() / 60
        self.minutos_tarde = int(tarde) if tarde > p.tolerancia_tarde_minutos else 0
        if self.salida:
            horas = Decimal(str(round((self.salida - self.entrada).total_seconds() / 3600, 2)))
            self.horas_trabajadas = max(Decimal("0"), horas)
            self.horas_extra = max(Decimal("0"), self.horas_trabajadas - p.horas_jornada)
        else:
            self.horas_trabajadas = self.horas_extra = Decimal("0")

    def save(self, *args, **kwargs):
        self.calcular()
        super().save(*args, **kwargs)


class Novedad(models.Model):
    """Ausencia, licencia o sanción que explica por qué alguien no trabajó."""

    class Tipo(models.TextChoices):
        ENFERMEDAD = "enfermedad", "Enfermedad"
        ACCIDENTE = "accidente", "Accidente laboral (ART)"
        VACACIONES = "vacaciones", "Vacaciones"
        LICENCIA = "licencia", "Licencia especial (examen, mudanza, familiar…)"
        FRANCO = "franco", "Franco compensatorio"
        INJUSTIFICADA = "injustificada", "Ausencia injustificada"
        SUSPENSION = "suspension", "Suspensión"

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de aprobar"
        APROBADA = "aprobada", "Aprobada"
        RECHAZADA = "rechazada", "Rechazada"

    JUSTIFICADAS = {"enfermedad", "accidente", "vacaciones", "licencia", "franco"}

    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="novedades")
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    desde = models.DateField(default=timezone.localdate)
    hasta = models.DateField(default=timezone.localdate)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    certificado = models.FileField(upload_to="certificados/%Y/%m/", blank=True)
    observaciones = models.TextField(blank=True)
    cargada_por = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="novedades_cargadas")
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-desde"]
        verbose_name = "Novedad / licencia"
        verbose_name_plural = "Novedades / licencias"

    def __str__(self):
        return f"{self.persona} · {self.get_tipo_display()} {self.desde:%d/%m}–{self.hasta:%d/%m}"

    @property
    def justificada(self) -> bool:
        return self.tipo in self.JUSTIFICADAS and self.estado != self.Estado.RECHAZADA

    @property
    def dias(self) -> int:
        return (self.hasta - self.desde).days + 1


class TipoDocumento(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    obligatorio_tecnicos = models.BooleanField(default=False)
    obligatorio_supervisores = models.BooleanField(default=False)
    dias_aviso = models.PositiveIntegerField(default=30, help_text="Avisar con esta anticipación al vencimiento.")

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Tipo de documento"
        verbose_name_plural = "Tipos de documento"

    def __str__(self):
        return self.nombre


class DocumentoPersonal(models.Model):
    """Documentación del legajo con vencimiento (registro de conducir, apto médico, etc.)."""

    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="documentos")
    tipo = models.ForeignKey(TipoDocumento, on_delete=models.PROTECT)
    numero = models.CharField(max_length=50, blank=True)
    emision = models.DateField(null=True, blank=True)
    vencimiento = models.DateField(null=True, blank=True)
    archivo = models.FileField(upload_to="legajos/%Y/", blank=True)

    class Meta:
        ordering = ["vencimiento"]
        verbose_name = "Documento del legajo"
        verbose_name_plural = "Documentos del legajo"

    def __str__(self):
        return f"{self.tipo} · {self.persona}"

    @property
    def estado(self) -> str:
        if not self.vencimiento:
            return "ok"
        hoy = timezone.localdate()
        if self.vencimiento < hoy:
            return "critico"
        if self.vencimiento <= hoy + timedelta(days=self.tipo.dias_aviso):
            return "aviso"
        return "ok"
