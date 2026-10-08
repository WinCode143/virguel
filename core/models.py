from datetime import time
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

    # ---- Control de personal
    tolerancia_tarde_minutos = models.PositiveIntegerField(
        "Tolerancia de llegada tarde (minutos)", default=10)
    horas_jornada = models.DecimalField("Horas de una jornada normal (incluye almuerzo)", max_digits=4,
                                        decimal_places=1, default=Decimal("9"),
                                        help_text="Lo que exceda esto entre entrada y salida cuenta como hora extra.")
    destinatarios_parte = models.TextField(
        "Mails que reciben el parte diario completo", blank=True,
        help_text="Uno por línea. Los supervisores reciben además el parte de su equipo en su propio mail.")
    encuesta_diaria = models.BooleanField(
        "Encuesta diaria al supervisor", default=True,
        help_text="La encuesta corta de cada día. La evaluación semanal está siempre disponible.")
    usar_hectareas = models.BooleanField(
        "Medir hectáreas cubiertas", default=False,
        help_text="Opcional. Si está apagado, la capacidad se calcula sólo por clientes por técnico.")

    # ---- Semáforo de los índices (IPT / IGS)
    indice_verde = models.PositiveSmallIntegerField("Índice: verde desde", default=75)
    indice_rojo = models.PositiveSmallIntegerField("Índice: rojo por debajo de", default=55)

    # ---- Partes adeudadas por los técnicos
    deuda_dias_aviso = models.PositiveIntegerField(
        "Días para pasar a amarillo (partes adeudadas)", default=2,
        help_text="Una parte sin regularizar pasa a amarillo después de estos días.")
    deuda_dias_critico = models.PositiveIntegerField(
        "Días para pasar a rojo (partes adeudadas)", default=5,
        help_text="Y a rojo después de estos días (además se avisa al supervisor).")

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
    motivo_egreso = models.CharField(max_length=20, blank=True, choices=[
        ("renuncia", "Renuncia"), ("despido", "Despido"), ("despido_causa", "Despido con causa"),
        ("fin_contrato", "Fin de contrato"), ("jubilacion", "Jubilación"), ("otro", "Otro")])
    activo = models.BooleanField(default=True)
    hora_entrada = models.TimeField("Horario de entrada", default=time(8, 0))
    hora_salida = models.TimeField("Horario de salida", default=time(17, 0))
    trabaja_sabados = models.BooleanField(default=True)
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
    telefono = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

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
        PERSONAL = "personal", "Personal / asistencia"
        STOCK = "stock", "Inventario / stock"
        PARTES = "partes", "Partes en manos de técnicos"
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


class Notificacion(models.Model):
    """Aviso para una persona: se ve en la app (campanita) y, si autorizó, llega al celular."""

    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="notificaciones")
    titulo = models.CharField(max_length=120)
    texto = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=300, blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    leida = models.BooleanField(default=False)

    class Meta:
        ordering = ["-creada"]
        verbose_name_plural = "Notificaciones"

    def __str__(self):
        return f"{self.persona}: {self.titulo}"


class SuscripcionPush(models.Model):
    """Permiso del navegador del celular para recibir notificaciones (Web Push)."""

    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="suscripciones_push")
    endpoint = models.URLField(max_length=600, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Suscripción a notificaciones"
        verbose_name_plural = "Suscripciones a notificaciones"


class Indicador(models.Model):
    """Definición configurable de un indicador de productividad (meta, mínimo y peso).

    El valor medido se convierte en puntos 0-100: el mínimo vale 0, la meta vale 100
    (lineal entre ambos). El índice de cada persona es el promedio ponderado por `peso`
    de los indicadores con datos."""

    class Rol(models.TextChoices):
        MANDO = "mando", "Tablero de mando"
        TECNICO = "tecnico", "Técnico"
        SUPERVISOR = "supervisor", "Supervisor"

    codigo = models.SlugField(max_length=40, unique=True)
    rol = models.CharField(max_length=12, choices=Rol.choices)
    nombre = models.CharField(max_length=80)
    descripcion = models.TextField(help_text="Qué mide y cómo se calcula.")
    unidad = models.CharField(max_length=20, default="%")
    meta = models.DecimalField(max_digits=14, decimal_places=2)
    minimo = models.DecimalField("Límite (rojo)", max_digits=14, decimal_places=2,
                                 help_text="Más allá de este valor el indicador está en rojo (y vale 0 puntos).")
    mayor_es_mejor = models.BooleanField(default=True)
    peso = models.PositiveSmallIntegerField(default=10, help_text="Peso en el índice (0 = sólo informativo).")
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["rol", "orden"]
        verbose_name = "Indicador de productividad"
        verbose_name_plural = "Indicadores de productividad"

    def __str__(self):
        return f"{self.get_rol_display()}: {self.nombre}"

    def estado(self, valor) -> str:
        """verde = cumple la meta · amarillo = no la cumple pero no pasó el límite · rojo = pasó el límite."""
        if valor is None:
            return "info"
        v, meta, lim = float(valor), float(self.meta), float(self.minimo)
        if (v >= meta) if self.mayor_es_mejor else (v <= meta):
            return "ok"
        if (v <= lim) if self.mayor_es_mejor else (v >= lim):
            return "critico"
        return "aviso"

    def regla(self) -> str:
        """Explicación legible del semáforo."""
        def f(x):
            x = float(x)
            return f"{x:,.0f}".replace(",", ".") if x == int(x) else f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
        u = "" if self.unidad in ("%",) else f" {self.unidad}"
        p = "%" if self.unidad == "%" else ""
        if self.mayor_es_mejor:
            return f"Verde ≥ {f(self.meta)}{p}{u} · Amarillo entre {f(self.minimo)} y {f(self.meta)}{p} · Rojo ≤ {f(self.minimo)}{p}{u}"
        return f"Verde ≤ {f(self.meta)}{p}{u} · Amarillo entre {f(self.meta)} y {f(self.minimo)}{p} · Rojo ≥ {f(self.minimo)}{p}{u}"

    def puntos(self, valor) -> float | None:
        if valor is None:
            return None
        meta, minimo, v = float(self.meta), float(self.minimo), float(valor)
        if meta == minimo:
            return 100.0 if (v >= meta if self.mayor_es_mejor else v <= meta) else 0.0
        frac = (v - minimo) / (meta - minimo)
        return max(0.0, min(100.0, frac * 100))


class CuentaUsuario(models.Model):
    """Estado de seguridad de cada acceso al sistema (complementa al usuario de Django)."""

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cuenta")
    debe_cambiar_clave = models.BooleanField(
        default=False, help_text="Al ingresar se le pide elegir una clave propia (primer ingreso o tras un blanqueo).")
    ultimo_cambio_clave = models.DateTimeField(null=True, blank=True)
    intentos_fallidos = models.PositiveSmallIntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)
    acepto_privacidad = models.DateTimeField(null=True, blank=True,
                                             help_text="Cuándo aceptó el aviso de privacidad (uso de ubicación y datos).")

    class Meta:
        verbose_name = "Cuenta de usuario"
        verbose_name_plural = "Cuentas de usuario"

    def __str__(self):
        return str(self.usuario)

    @property
    def bloqueada(self) -> bool:
        return bool(self.bloqueado_hasta and self.bloqueado_hasta > timezone.now())

    @classmethod
    def de(cls, user):
        return cls.objects.get_or_create(usuario=user)[0]


class RegistroAcceso(models.Model):
    """Auditoría de ingresos, salidas e intentos fallidos."""

    class Evento(models.TextChoices):
        INGRESO = "ingreso", "Ingreso"
        SALIDA = "salida", "Salida"
        FALLIDO = "fallido", "Intento fallido"
        BLOQUEO = "bloqueo", "Cuenta bloqueada"
        CAMBIO_CLAVE = "cambio_clave", "Cambio de clave"
        BLANQUEO = "blanqueo", "Blanqueo de clave (gerencia)"
        ADMIN = "admin", "Cambio de acceso (gerencia)"

    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="accesos")
    usuario_ingresado = models.CharField(max_length=150, blank=True, help_text="Lo que se escribió en 'usuario'.")
    evento = models.CharField(max_length=15, choices=Evento.choices)
    ip = models.GenericIPAddressField(null=True, blank=True)
    dispositivo = models.CharField(max_length=200, blank=True)
    detalle = models.CharField(max_length=200, blank=True)
    hecho_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name="acciones_sobre_accesos")

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Registro de acceso"
        verbose_name_plural = "Registro de accesos"


class MetaEquipo(models.Model):
    """Meta y límite propios de un equipo (los fija su supervisor o gerencia); reemplazan a los generales."""

    supervisor = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="metas_equipo",
                                   limit_choices_to={"rol": "supervisor"})
    indicador = models.ForeignKey(Indicador, on_delete=models.CASCADE, related_name="metas_equipo")
    meta = models.DecimalField(max_digits=12, decimal_places=2)
    minimo = models.DecimalField("Límite (rojo)", max_digits=12, decimal_places=2)

    class Meta:
        unique_together = [("supervisor", "indicador")]
        verbose_name = "Meta de equipo"
        verbose_name_plural = "Metas de equipo"

    def __str__(self):
        return f"{self.indicador.nombre} · equipo {self.supervisor.apellido}"


class CambioMeta(models.Model):
    """Registro de quién cambió una meta o un límite, cuándo y de qué valor a cuál."""

    fecha = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    indicador = models.ForeignKey(Indicador, on_delete=models.CASCADE)
    alcance = models.CharField(max_length=80, help_text="General o equipo de …")
    antes = models.CharField(max_length=80)
    despues = models.CharField(max_length=80)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Cambio de meta"
        verbose_name_plural = "Cambios de metas"
