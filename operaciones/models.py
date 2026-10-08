from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.models import Cliente, Persona, Zona


class TipoTarea(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=100)
    minutos_estandar = models.PositiveIntegerField(
        default=60, help_text="Tiempo estándar esperado para completar la tarea.")
    puede_requerir_decodificador = models.BooleanField(
        default=False, help_text="Si en esta tarea el cliente puede pedir decodificador para TV.")
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Tipo de tarea"
        verbose_name_plural = "Tipos de tarea"

    def __str__(self):
        return self.nombre


class Jornada(models.Model):
    """Presencia diaria de cada técnico: base del cálculo de 'personal en calle'."""

    fecha = models.DateField(default=timezone.localdate, db_index=True)
    tecnico = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="jornadas",
                                limit_choices_to={"rol": "tecnico"})
    en_calle = models.BooleanField(default=True, help_text="Salió a trabajar en calle ese día.")
    motivo_ausencia = models.CharField(max_length=100, blank=True)
    zona = models.ForeignKey(Zona, null=True, blank=True, on_delete=models.SET_NULL)
    vehiculo = models.ForeignKey("flota.Vehiculo", null=True, blank=True, on_delete=models.SET_NULL)
    km_inicio = models.PositiveIntegerField(null=True, blank=True)
    km_fin = models.PositiveIntegerField(null=True, blank=True)
    hectareas_cubiertas = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0"))
    horas_trabajadas = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal("8"))

    class Meta:
        ordering = ["-fecha"]
        unique_together = [("fecha", "tecnico")]

    def __str__(self):
        return f"{self.fecha} - {self.tecnico}"


class OrdenTrabajo(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        ASIGNADA = "asignada", "Asignada"
        COMPLETADA = "completada", "Completada"
        FALLIDA = "fallida", "Fallida / no resuelta"
        REPROGRAMADA = "reprogramada", "Reprogramada"

    numero = models.CharField(max_length=30, unique=True)
    tipo = models.ForeignKey(TipoTarea, on_delete=models.PROTECT, related_name="ordenes")
    cliente = models.ForeignKey(Cliente, null=True, blank=True, on_delete=models.SET_NULL, related_name="ordenes")
    zona = models.ForeignKey(Zona, null=True, blank=True, on_delete=models.SET_NULL)
    tecnico = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="ordenes", limit_choices_to={"rol": "tecnico"})
    fecha_programada = models.DateField(default=timezone.localdate, db_index=True)
    fecha_ejecucion = models.DateField(null=True, blank=True, db_index=True)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE, db_index=True)
    minutos_reales = models.PositiveIntegerField(null=True, blank=True)
    decodificador_solicitado = models.BooleanField(default=False)
    decodificadores_instalados = models.PositiveSmallIntegerField(default=0)
    es_retrabajo = models.BooleanField(
        default=False, help_text="Visita para corregir un trabajo anterior mal hecho (indicador de calidad).")
    orden_original = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name="retrabajos")
    observaciones = models.TextField(blank=True)

    # ---- Datos del cierre en calle (los carga el técnico desde la app)
    motivo_no_resuelto = models.CharField(max_length=20, blank=True, choices=[
        ("cliente_ausente", "Cliente ausente"), ("falta_material", "Faltó material"),
        ("problema_red", "Problema de red / externo"), ("direccion", "Dirección errónea"),
        ("clima", "Clima"), ("rechazo", "Cliente rechazó el trabajo"), ("otro", "Otro")])
    minutos_viaje = models.PositiveIntegerField("Tiempo de viaje (min)", null=True, blank=True)
    minutos_retorno = models.PositiveIntegerField("Tiempo de retorno (min)", null=True, blank=True)
    inicio_trabajo = models.DateTimeField(null=True, blank=True)
    fin_trabajo = models.DateTimeField(null=True, blank=True)
    series_instaladas = models.CharField("N° de serie instalados", max_length=300, blank=True)
    series_retiradas = models.CharField("N° de serie retirados", max_length=300, blank=True)
    foto_trabajo = models.FileField(upload_to="ordenes/%Y/%m/", blank=True)
    conforme_nombre = models.CharField("Conformidad: nombre", max_length=120, blank=True)
    conforme_apellido = models.CharField("Conformidad: apellido", max_length=120, blank=True)
    conforme_dni = models.CharField("Conformidad: DNI", max_length=15, blank=True)
    firma = models.FileField(upload_to="firmas/%Y/%m/", blank=True)
    lat_cierre = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng_cierre = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ["-fecha_programada", "numero"]
        verbose_name = "Orden de trabajo"
        verbose_name_plural = "Órdenes de trabajo"

    def __str__(self):
        return f"OT {self.numero} - {self.tipo}"


class NotaOrden(models.Model):
    """Notas de una llamada: indicaciones, avances y lo que se hizo al cerrar."""

    class Tipo(models.TextChoices):
        NOTA = "nota", "Nota"
        CIERRE = "cierre", "Cierre (qué se hizo)"
        DESPACHO = "despacho", "Indicación de despacho"

    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name="notas")
    autor = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="notas_orden")
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.NOTA)
    texto = models.TextField()
    creada = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-creada"]
        verbose_name = "Nota de la orden"
        verbose_name_plural = "Notas de las órdenes"

    def __str__(self):
        return f"{self.orden.numero}: {self.texto[:40]}"


class GastoOrden(models.Model):
    """Gasto extra que el técnico pagó para resolver la llamada (con su comprobante)."""

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de revisión"
        APROBADO = "aprobado", "Aprobado para reintegro"
        RECHAZADO = "rechazado", "Rechazado"

    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name="gastos")
    tecnico = models.ForeignKey(Persona, on_delete=models.PROTECT, related_name="gastos_orden")
    fecha = models.DateField(default=timezone.localdate)
    descripcion = models.CharField("Qué se compró", max_length=200)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    comprobante = models.FileField("Factura / ticket", upload_to="gastos/%Y/%m/", blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Gasto de la orden"
        verbose_name_plural = "Gastos de las órdenes"

    def __str__(self):
        return f"{self.orden.numero}: {self.descripcion} ${self.monto}"
