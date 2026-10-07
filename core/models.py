from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Parametros(models.Model):
    """Parámetros de negocio editables desde el admin (registro único).

    Todos los cálculos del sistema leen de aquí, así gerencia puede ajustar
    supuestos (p. ej. 50% vs 60% de decodificadores) sin tocar código.
    """

    dias_max_stock = models.PositiveIntegerField(
        "Días máximos de stock parado", default=60,
        help_text="Un lote con más días que esto sin consumirse genera alerta crítica.")
    dias_aviso_stock = models.PositiveIntegerField(
        "Días de aviso previo", default=45,
        help_text="A partir de estos días el lote aparece como 'por vencer'.")
    hectareas_dia_min = models.DecimalField(
        "Hectáreas por cuadrilla/día (mín.)", max_digits=5, decimal_places=2, default=Decimal("5"))
    hectareas_dia_max = models.DecimalField(
        "Hectáreas por cuadrilla/día (máx.)", max_digits=5, decimal_places=2, default=Decimal("6"))
    tecnicos_por_cuadrilla = models.PositiveSmallIntegerField(
        "Técnicos por cuadrilla", default=2,
        help_text="Las hectáreas/día se miden por cuadrilla; esto convierte técnicos en cuadrillas.")
    clientes_por_tecnico_dia = models.DecimalField(
        "Clientes atendibles por técnico/día", max_digits=5, decimal_places=2, default=Decimal("6"),
        help_text="Tope operativo de visitas diarias por técnico.")
    prob_decodificador_min = models.DecimalField(
        "Prob. de pedido de decodificador (escenario bajo)", max_digits=4, decimal_places=3,
        default=Decimal("0.50"), validators=[MinValueValidator(0), MaxValueValidator(1)])
    prob_decodificador_max = models.DecimalField(
        "Prob. de pedido de decodificador (escenario alto)", max_digits=4, decimal_places=3,
        default=Decimal("0.60"), validators=[MinValueValidator(0), MaxValueValidator(1)])
    dias_ventana_evaluacion = models.PositiveIntegerField(
        "Ventana de evaluación de técnicos (días)", default=90)
    dias_cobertura_stock_min = models.PositiveIntegerField(
        "Días mínimos de cobertura de stock", default=7,
        help_text="Si el stock alcanza para menos días que esto, se alerta faltante.")

    class Meta:
        verbose_name = "Parámetros del sistema"
        verbose_name_plural = "Parámetros del sistema"

    def __str__(self):
        return "Parámetros del sistema"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def actual(cls) -> "Parametros":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Zona(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    densidad_clientes_ha = models.DecimalField(
        "Clientes por hectárea", max_digits=6, decimal_places=2, default=Decimal("1.0"),
        help_text="Densidad promedio usada para traducir hectáreas cubiertas en clientes.")
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Persona(models.Model):
    class Rol(models.TextChoices):
        TECNICO = "tecnico", "Técnico"
        SUPERVISOR = "supervisor", "Supervisor"
        ADMINISTRATIVO = "administrativo", "Administrativo"
        GERENCIA = "gerencia", "Gerencia"

    legajo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=80)
    apellido = models.CharField(max_length=80)
    dni = models.CharField(max_length=15, blank=True)
    rol = models.CharField(max_length=20, choices=Rol.choices, default=Rol.TECNICO)
    supervisor = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="a_cargo",
        limit_choices_to={"rol": "supervisor"})
    zona = models.ForeignKey(Zona, null=True, blank=True, on_delete=models.SET_NULL, related_name="personas")
    telefono = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    fecha_ingreso = models.DateField(default=timezone.localdate)
    fecha_egreso = models.DateField(null=True, blank=True)
    activo = models.BooleanField(default=True)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="persona")

    class Meta:
        ordering = ["apellido", "nombre"]

    def __str__(self):
        return f"{self.apellido}, {self.nombre} ({self.legajo})"

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"


class TecnicoManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(rol=Persona.Rol.TECNICO)


class SupervisorManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(rol=Persona.Rol.SUPERVISOR)


class Tecnico(Persona):
    objects = TecnicoManager()

    class Meta:
        proxy = True
        verbose_name = "Técnico"
        verbose_name_plural = "Técnicos"


class Supervisor(Persona):
    objects = SupervisorManager()

    class Meta:
        proxy = True
        verbose_name = "Supervisor"
        verbose_name_plural = "Supervisores"


class Cliente(models.Model):
    class Tipo(models.TextChoices):
        RESIDENCIAL = "residencial", "Residencial"
        MODERNO = "moderno", "Moderno (fibra/smart)"
        COMERCIAL = "comercial", "Comercial"

    numero = models.CharField("N° de cliente", max_length=30, unique=True)
    nombre = models.CharField(max_length=150)
    direccion = models.CharField(max_length=200, blank=True)
    zona = models.ForeignKey(Zona, null=True, blank=True, on_delete=models.SET_NULL, related_name="clientes")
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.RESIDENCIAL)
    cantidad_televisores = models.PositiveSmallIntegerField(default=1)

    class Meta:
        ordering = ["numero"]

    def __str__(self):
        return f"{self.numero} - {self.nombre}"


class Alerta(models.Model):
    """Alerta generada automáticamente por las tareas diarias."""

    class Nivel(models.TextChoices):
        INFO = "info", "Info"
        AVISO = "aviso", "Aviso"
        CRITICA = "critica", "Crítica"

    class Modulo(models.TextChoices):
        STOCK = "stock", "Inventario / stock"
        FLOTA = "flota", "Flota"
        EPP = "epp", "Herramientas / EPP"
        TECNICOS = "tecnicos", "Técnicos"
        SUPERVISION = "supervision", "Supervisión"
        INCIDENTES = "incidentes", "Incidentes"
        FINANZAS = "finanzas", "Finanzas"

    modulo = models.CharField(max_length=20, choices=Modulo.choices)
    nivel = models.CharField(max_length=10, choices=Nivel.choices, default=Nivel.AVISO)
    clave = models.CharField(
        max_length=120, help_text="Identificador estable para no duplicar la misma alerta.")
    titulo = models.CharField(max_length=200)
    detalle = models.TextField(blank=True)
    url = models.CharField(max_length=300, blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)
    resuelta = models.BooleanField(default=False)

    class Meta:
        ordering = ["resuelta", "-nivel", "-actualizada"]
        constraints = [
            models.UniqueConstraint(fields=["clave"], condition=models.Q(resuelta=False),
                                    name="alerta_abierta_unica"),
        ]

    def __str__(self):
        return f"[{self.get_nivel_display()}] {self.titulo}"
