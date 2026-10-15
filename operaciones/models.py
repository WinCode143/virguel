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


class TarifaClaro(models.Model):
    """Precio que paga Claro por orden completada de un tipo de tarea, con vigencia.

    Cambiar una tarifa crea una nueva vigencia: el trabajo ya hecho se valoriza con la tarifa vigente
    a su fecha de ejecución (no se revaloriza en silencio)."""

    tipo_tarea = models.ForeignKey(TipoTarea, on_delete=models.CASCADE, related_name="tarifas")
    precio = models.DecimalField(max_digits=12, decimal_places=2)
    vigente_desde = models.DateField()
    provisoria = models.BooleanField(default=True, help_text="Valor provisorio / de prueba hasta confirmarlo con Claro.")
    fuente = models.CharField(max_length=120, blank=True, help_text="De dónde sale el valor (contrato, acta, prueba).")

    class Meta:
        ordering = ["tipo_tarea", "-vigente_desde"]
        unique_together = [("tipo_tarea", "vigente_desde")]
        verbose_name = "Tarifa de Claro"
        verbose_name_plural = "Tarifas de Claro"

    def __str__(self):
        return f"{self.tipo_tarea}: ${self.precio} desde {self.vigente_desde:%d/%m/%Y}"


class Atribucion(models.TextChoices):
    """A quién se atribuye que una orden no se haya resuelto."""
    TECNICO = "tecnico", "Técnico (desempeño)"
    CLIENTE = "cliente", "Cliente / datos de la orden"
    SUMINISTRO = "suministro", "Empresa / abastecimiento"
    EXTERNO = "externo", "Externo (red, clima)"
    A_INVESTIGAR = "a_investigar", "A investigar"


class MotivoNoResolucion(models.Model):
    """Catálogo común de motivos de no resolución y su atribución por defecto.

    Lo usan la evaluación de técnicos y los indicadores (IPT/IGS): una orden no resuelta sólo
    cuenta contra el técnico si la atribución es "técnico" (por catálogo o confirmada por el
    supervisor). Lo dudoso queda "a investigar" y no penaliza hasta que se confirme."""

    codigo = models.CharField(max_length=20, unique=True)
    nombre = models.CharField(max_length=80)
    atribucion = models.CharField(max_length=15, choices=Atribucion.choices, default=Atribucion.A_INVESTIGAR)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Motivo de no resolución"
        verbose_name_plural = "Motivos de no resolución"

    def __str__(self):
        return f"{self.nombre} ({self.get_atribucion_display()})"


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
    equipos_requeridos = models.PositiveSmallIntegerField(
        "Equipos que indica la orden", null=True, blank=True,
        help_text="Cantidad conocida (p. ej. televisores/decos que pide Claro). Vacío = desconocido: se estima.")
    requiere_recambio = models.BooleanField(null=True, blank=True,
                                            help_text="Si la reparación necesita reemplazar el equipo (vacío = no se sabe).")
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


MOTIVOS_NO_RESUELTO = OrdenTrabajo._meta.get_field("motivo_no_resuelto").choices


class Intento(models.Model):
    """Cada vez que se cierra una orden (completada, fallida o reprogramada) queda un intento con
    quién la trabajó, bajo qué supervisor y con qué resultado. La orden guarda sólo el estado actual:
    reasignarla o reabrirla no cambia la historia de quién hizo cada visita.

    Se crea solo (operaciones/signals.py) cuando la orden pasa a un estado de resultado."""

    class Resultado(models.TextChoices):
        COMPLETADA = "completada", "Completada"
        FALLIDA = "fallida", "Fallida / no resuelta"
        REPROGRAMADA = "reprogramada", "Reprogramada"

    class Revision(models.TextChoices):
        SIN_REVISAR = "sin_revisar", "Sin revisión técnica"
        APROBADA = "aprobada", "Revisión aprobada"
        RECHAZADA = "rechazada", "Revisión rechazada"

    class Aceptacion(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        ACEPTADA = "aceptada", "Aceptada por Claro"
        RECHAZADA = "rechazada", "Rechazada por Claro"

    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name="intentos")
    numero = models.PositiveSmallIntegerField(default=1)
    tecnico = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="intentos")
    supervisor = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                   help_text="Supervisor del técnico en ese momento.")
    fecha = models.DateField(db_index=True)
    resultado = models.CharField(max_length=15, choices=Resultado.choices)
    motivo_no_resuelto = models.CharField(max_length=20, blank=True, choices=MOTIVOS_NO_RESUELTO)
    minutos_reales = models.PositiveIntegerField(null=True, blank=True)
    inicio_trabajo = models.DateTimeField(null=True, blank=True)
    fin_trabajo = models.DateTimeField(null=True, blank=True)
    atribucion_confirmada = models.CharField(
        "Atribución confirmada", max_length=15, choices=Atribucion.choices, blank=True,
        help_text="La confirma el supervisor; si está vacía vale la del catálogo de motivos.")
    atribucion_confirmada_por = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                                  related_name="+")
    # Evidencias del cierre (instantánea de esta visita)
    series_instaladas = models.CharField(max_length=300, blank=True)
    series_retiradas = models.CharField(max_length=300, blank=True)
    foto = models.CharField(max_length=200, blank=True, help_text="Archivo de la foto del trabajo de esta visita.")
    firma = models.CharField(max_length=200, blank=True)
    conforme = models.CharField("Conformidad del cliente", max_length=200, blank=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # Estados separados: finalizar la visita ≠ revisión técnica ≠ aceptación para liquidar
    revision_tecnica = models.CharField(max_length=12, choices=Revision.choices, default=Revision.SIN_REVISAR)
    revisado_por = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    aceptacion_claro = models.CharField("Aceptación de Claro", max_length=12, choices=Aceptacion.choices,
                                        default=Aceptacion.PENDIENTE)
    creado = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["orden", "numero"]
        unique_together = [("orden", "numero")]
        verbose_name = "Intento (visita) de una orden"
        verbose_name_plural = "Intentos (visitas) de órdenes"

    def __str__(self):
        return f"{self.orden.numero} #{self.numero} {self.get_resultado_display()} ({self.fecha:%d/%m/%Y})"


class Cuadrilla(models.Model):
    """Equipo de trabajo de campo. Su composición cambia por período (MiembroCuadrilla); una visita
    conserva quiénes participaron ese día aunque después cambie el equipo. Unipersonal es válido."""

    nombre = models.CharField(max_length=80, unique=True)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name_plural = "Cuadrillas"

    def __str__(self):
        return self.nombre

    def miembros_en(self, fecha):
        from django.db.models import Q
        return self.miembros.filter(desde__lte=fecha).filter(Q(hasta__isnull=True) | Q(hasta__gte=fecha))


class MiembroCuadrilla(models.Model):
    class Funcion(models.TextChoices):
        RESPONSABLE = "responsable", "Responsable"
        AYUDANTE = "ayudante", "Ayudante"

    cuadrilla = models.ForeignKey(Cuadrilla, on_delete=models.CASCADE, related_name="miembros")
    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="cuadrillas")
    funcion = models.CharField(max_length=12, choices=Funcion.choices, default=Funcion.RESPONSABLE)
    desde = models.DateField(default=timezone.localdate)
    hasta = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["cuadrilla", "-desde"]
        verbose_name = "Integrante de cuadrilla (por período)"
        verbose_name_plural = "Integrantes de cuadrillas (por período)"

    def __str__(self):
        return f"{self.persona} en {self.cuadrilla} ({self.get_funcion_display()})"


class ParticipacionVisita(models.Model):
    """Quiénes trabajaron en una visita y con qué función: una orden, varias contribuciones."""

    class Funcion(models.TextChoices):
        EJECUTOR = "ejecutor", "Ejecutor (responsable de la visita)"
        AYUDANTE = "ayudante", "Ayudante"
        TUTOR = "tutor", "Tutor (ejecución tutelada)"

    intento = models.ForeignKey("Intento", on_delete=models.CASCADE, related_name="participantes")
    persona = models.ForeignKey(Persona, on_delete=models.PROTECT, related_name="participaciones_visita")
    funcion = models.CharField(max_length=10, choices=Funcion.choices, default=Funcion.EJECUTOR)
    minutos = models.PositiveIntegerField(null=True, blank=True)
    confirmada = models.BooleanField(
        default=True, help_text="Falso = inferida sólo por pertenecer a la cuadrilla ese día (asistencia no "
                                "confirmada): no cuenta como trabajo efectivo hasta confirmarla.")

    class Meta:
        unique_together = [("intento", "persona")]
        verbose_name = "Participante de la visita"
        verbose_name_plural = "Participantes de las visitas"

    def __str__(self):
        return f"{self.persona} · {self.get_funcion_display()}"


class RectificacionVisita(models.Model):
    """Corrección explícita de una visita ya registrada: conserva antes, después, motivo y autor."""

    intento = models.ForeignKey("Intento", on_delete=models.CASCADE, related_name="rectificaciones")
    campo = models.CharField(max_length=40)
    antes = models.CharField(max_length=200, blank=True)
    despues = models.CharField(max_length=200, blank=True)
    motivo = models.CharField(max_length=200)
    autor = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    usuario = models.CharField(max_length=150, blank=True)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Rectificación de visita"
        verbose_name_plural = "Rectificaciones de visitas"

    def __str__(self):
        return f"{self.intento}: {self.campo} {self.antes} → {self.despues}"


class NotaOrden(models.Model):
    """Notas de una llamada: indicaciones, avances y lo que se hizo al cerrar."""

    class Tipo(models.TextChoices):
        NOTA = "nota", "Nota"
        CIERRE = "cierre", "Cierre (qué se hizo)"
        DESPACHO = "despacho", "Indicación de despacho"
        CORRECCION = "correccion", "Corrección administrativa"

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
    intento = models.ForeignKey("Intento", null=True, blank=True, on_delete=models.SET_NULL, related_name="gastos")
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
