from decimal import Decimal
from datetime import date

from django.conf import settings
from django.db import models
from django.utils import timezone


class CategoriaEgreso(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    codigo = models.SlugField(max_length=30, unique=True)
    tolerancia_presupuesto = models.PositiveSmallIntegerField(
        "Tolerancia sobre el presupuesto (%)", default=10,
        help_text="Verde hasta el presupuesto; amarillo hasta presupuesto + tolerancia; rojo después.")

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Categoría de egreso"
        verbose_name_plural = "Categorías de egreso"

    def __str__(self):
        return self.nombre


class Proveedor(models.Model):
    nombre = models.CharField(max_length=120, unique=True)
    cuit = models.CharField("CUIT", max_length=13, blank=True)
    contacto = models.CharField(max_length=120, blank=True)
    categoria = models.ForeignKey(CategoriaEgreso, null=True, blank=True, on_delete=models.SET_NULL,
                                  help_text="Categoría habitual de sus comprobantes (se propone al cargar).")

    class Meta:
        ordering = ["nombre"]
        verbose_name_plural = "Proveedores"

    def __str__(self):
        return self.nombre


class Cuenta(models.Model):
    """Dónde está el dinero (banco, efectivo, billetera). Con su saldo inicial y los cobros y pagos
    registrados se calcula el saldo y se proyecta la caja."""

    class Tipo(models.TextChoices):
        BANCO = "banco", "Cuenta bancaria"
        EFECTIVO = "efectivo", "Efectivo / caja chica"
        BILLETERA = "billetera", "Billetera virtual"

    nombre = models.CharField(max_length=80, unique=True)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.BANCO)
    saldo_inicial = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    fecha_saldo_inicial = models.DateField(default=timezone.localdate,
                                           help_text="Fecha del saldo inicial: se suman los movimientos posteriores.")
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name_plural = "Cuentas"

    def __str__(self):
        return self.nombre

    def saldo(self, al: date | None = None) -> Decimal:
        al = al or timezone.localdate()
        f = {"fecha__gt": self.fecha_saldo_inicial, "fecha__lte": al}
        entra = self.cobros.filter(**f).aggregate(t=models.Sum("monto"))["t"] or Decimal("0")
        sale = self.pagos.filter(**f).aggregate(t=models.Sum("monto"))["t"] or Decimal("0")
        return self.saldo_inicial + entra - sale


class Egreso(models.Model):
    """Obligación de pago (gasto devengado). Los de compras de stock, services, EPP y siniestros se
    generan automáticamente; el resto se carga a mano.

    El dinero que efectivamente sale está en `Pago` (uno o varios, parciales). `pagado` y `fecha_pago`
    se mantienen a partir de los pagos; marcar "pagado" sin cargar pagos registra un pago por el saldo."""

    fecha = models.DateField(default=timezone.localdate, db_index=True)
    categoria = models.ForeignKey(CategoriaEgreso, on_delete=models.PROTECT, related_name="egresos")
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    descripcion = models.CharField(max_length=200)
    class TipoComprobante(models.TextChoices):
        FACTURA = "factura", "Factura"
        TICKET = "ticket", "Ticket"
        RECIBO = "recibo", "Recibo"
        NOTA_CREDITO = "nota_credito", "Nota de crédito"
        OTRO = "otro", "Otro"

    class Medio(models.TextChoices):
        TRANSFERENCIA = "transferencia", "Transferencia"
        EFECTIVO = "efectivo", "Efectivo"
        CHEQUE = "cheque", "Cheque / e-cheq"
        TARJETA = "tarjeta", "Tarjeta"
        DEBITO = "debito", "Débito automático"

    tipo_comprobante = models.CharField("Tipo", max_length=15, choices=TipoComprobante.choices,
                                        default=TipoComprobante.FACTURA)
    proveedor_ref = models.ForeignKey(Proveedor, verbose_name="Proveedor (ficha)", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="comprobantes")
    proveedor = models.CharField(max_length=120, blank=True)
    numero_comprobante = models.CharField("N° de factura / comprobante", max_length=40, blank=True)
    vencimiento = models.DateField("Vence el", null=True, blank=True)
    pagado = models.BooleanField(default=True)
    fecha_pago = models.DateField(null=True, blank=True)
    medio_pago = models.CharField(max_length=15, choices=Medio.choices, blank=True)
    comprobante = models.FileField("Archivo del comprobante", upload_to="egresos/%Y/%m/", blank=True)
    cargado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    editable=False)
    automatico = models.BooleanField(default=False, editable=False)
    origen = models.CharField(max_length=60, blank=True, editable=False,
                              help_text="Referencia al registro que lo originó (modelo:id).")

    class Meta:
        ordering = ["-fecha"]
        constraints = [
            models.UniqueConstraint(fields=["origen"], condition=~models.Q(origen=""),
                                    name="egreso_origen_unico"),
        ]

    def __str__(self):
        return f"{self.fecha} {self.categoria}: ${self.monto}"

    # ---- pagos (parciales) y saldo
    @property
    def pagado_monto(self) -> Decimal:
        return self.pagos.aggregate(t=models.Sum("monto"))["t"] or Decimal("0")

    @property
    def saldo(self) -> Decimal:
        return self.monto - self.pagado_monto

    @property
    def estado_pago(self) -> str:
        pagado = self.pagado_monto
        if self.monto <= 0 or pagado >= self.monto:
            return "pagado"
        return "parcial" if pagado > 0 else "pendiente"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._sincronizar_pago_total()

    def _sincronizar_pago_total(self):
        """Compatibilidad con el tilde "pagado": si no hay pagos cargados a mano, un pago automático
        representa el pago total (y se borra si se destilda)."""
        if self.monto <= 0:
            return
        manuales = self.pagos.filter(automatico=False)
        if manuales.exists():
            saldo = self.saldo
            if self.pagado and saldo > 0:  # se marcó pagado con pagos parciales: se registra el resto
                Pago.objects.create(egreso=self, fecha=self.fecha_pago or timezone.localdate(), monto=saldo,
                                    medio=self.medio_pago, observaciones="Saldo (marcado como pagado)")
            else:
                self.actualizar_estado_pago()
            return
        if self.pagado:
            Pago.objects.update_or_create(egreso=self, automatico=True, defaults={
                "fecha": self.fecha_pago or self.fecha, "monto": self.monto, "medio": self.medio_pago})
        else:
            self.pagos.filter(automatico=True).delete()

    def actualizar_estado_pago(self):
        """Recalcula `pagado` y `fecha_pago` a partir de los pagos (sin disparar save)."""
        ultimo = self.pagos.order_by("-fecha").values_list("fecha", flat=True).first()
        pagado = self.monto <= 0 or self.pagado_monto >= self.monto
        Egreso.objects.filter(pk=self.pk).update(pagado=pagado, fecha_pago=ultimo if pagado else None)
        self.pagado, self.fecha_pago = pagado, (ultimo if pagado else None)


class Pago(models.Model):
    """Salida de dinero que cancela (total o parcialmente) un egreso."""

    egreso = models.ForeignKey(Egreso, on_delete=models.CASCADE, related_name="pagos")
    fecha = models.DateField(default=timezone.localdate, db_index=True)
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    cuenta = models.ForeignKey(Cuenta, null=True, blank=True, on_delete=models.PROTECT, related_name="pagos")
    medio = models.CharField(max_length=15, choices=Egreso.Medio.choices, blank=True)
    observaciones = models.CharField(max_length=200, blank=True)
    automatico = models.BooleanField(default=False, editable=False,
                                     help_text="Generado por el tilde 'pagado' (pago total sin detalle).")

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"

    def __str__(self):
        return f"{self.fecha} ${self.monto} → {self.egreso.descripcion}"

    def save(self, *args, **kwargs):
        if not self.automatico:
            # Un pago detallado reemplaza al pago total automático
            Pago.objects.filter(egreso_id=self.egreso_id, automatico=True).delete()
        super().save(*args, **kwargs)
        self.egreso.actualizar_estado_pago()

    def delete(self, *args, **kwargs):
        egreso = self.egreso
        r = super().delete(*args, **kwargs)
        egreso.actualizar_estado_pago()
        return r


class Cuota(models.Model):
    """Plan de pago de un egreso (deuda en cuotas). Los pagos se imputan a las cuotas en orden."""

    egreso = models.ForeignKey(Egreso, on_delete=models.CASCADE, related_name="cuotas")
    numero = models.PositiveSmallIntegerField()
    vencimiento = models.DateField()
    monto = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["egreso", "numero"]
        unique_together = [("egreso", "numero")]
        verbose_name_plural = "Cuotas"

    def __str__(self):
        return f"Cuota {self.numero} de {self.egreso.descripcion} ({self.vencimiento:%d/%m/%Y})"


class Ingreso(models.Model):
    """Ingreso devengado de la empresa (p. ej. la liquidación de Claro por los trabajos realizados).

    La empresa no vende al público, pero cobra por su trabajo: esto es lo que se espera cobrar.
    Lo que efectivamente entra está en `Cobro` (uno o varios, parciales)."""

    fecha = models.DateField("Fecha (devengado)", default=timezone.localdate, db_index=True)
    periodo = models.DateField("Período liquidado", null=True, blank=True, help_text="Primer día del mes.")
    pagador = models.CharField(max_length=120, default="Claro")
    concepto = models.CharField(max_length=200)
    numero_comprobante = models.CharField("N° de factura / liquidación", max_length=40, blank=True)
    monto = models.DecimalField(max_digits=14, decimal_places=2,
                                help_text="Neto a cobrar (después de retenciones y débitos conocidos).")
    fecha_esperada_cobro = models.DateField("Se espera cobrar el", null=True, blank=True)
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Ingreso (a cobrar)"
        verbose_name_plural = "Ingresos (a cobrar)"

    def __str__(self):
        return f"{self.fecha} {self.pagador}: {self.concepto} ${self.monto}"

    @property
    def cobrado(self) -> Decimal:
        return self.cobros.aggregate(t=models.Sum("monto"))["t"] or Decimal("0")

    @property
    def saldo(self) -> Decimal:
        return self.monto - self.cobrado

    @property
    def estado(self) -> str:
        c = self.cobrado
        return "cobrado" if c >= self.monto else "parcial" if c > 0 else "pendiente"


class Cobro(models.Model):
    """Entrada de dinero que cancela (total o parcialmente) un ingreso."""

    ingreso = models.ForeignKey(Ingreso, on_delete=models.CASCADE, related_name="cobros")
    fecha = models.DateField(default=timezone.localdate, db_index=True)
    monto = models.DecimalField(max_digits=14, decimal_places=2)
    cuenta = models.ForeignKey(Cuenta, null=True, blank=True, on_delete=models.PROTECT, related_name="cobros")
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name_plural = "Cobros"

    def __str__(self):
        return f"{self.fecha} ${self.monto} ← {self.ingreso.concepto}"


class Presupuesto(models.Model):
    """Monto previsto por categoría y mes; se compara contra lo gastado (semáforo)."""

    categoria = models.ForeignKey(CategoriaEgreso, on_delete=models.CASCADE, related_name="presupuestos")
    mes = models.DateField(help_text="Primer día del mes.")
    monto = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["mes", "categoria__nombre"]
        unique_together = [("categoria", "mes")]

    def __str__(self):
        return f"{self.categoria} {self.mes:%m/%Y}: ${self.monto}"


class CostoFijo(models.Model):
    """Egreso recurrente mensual (sueldos, alquileres, seguros) para la proyección."""

    categoria = models.ForeignKey(CategoriaEgreso, on_delete=models.PROTECT)
    descripcion = models.CharField(max_length=150)
    monto_mensual = models.DecimalField(max_digits=14, decimal_places=2)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Costo fijo mensual"
        verbose_name_plural = "Costos fijos mensuales"

    def __str__(self):
        return f"{self.descripcion} (${self.monto_mensual}/mes)"


def registrar_egreso_automatico(origen: str, categoria_codigo: str, fecha, monto, descripcion):
    """Crea o actualiza el egreso asociado a un registro operativo."""
    monto = Decimal(monto or 0)
    if monto <= 0:
        Egreso.objects.filter(origen=origen).delete()
        return None
    nombres = {"sueldos": "Sueldos y cargas", "compras-stock": "Compras de stock", "gastos-de-campo": "Gastos de campo",
               "epp-herramientas": "EPP y herramientas"}
    cat, _ = CategoriaEgreso.objects.get_or_create(
        codigo=categoria_codigo, defaults={"nombre": nombres.get(categoria_codigo,
                                                                  categoria_codigo.replace("-", " ").capitalize())})
    obj, _ = Egreso.objects.update_or_create(
        origen=origen, defaults={"fecha": fecha, "categoria": cat, "monto": monto,
                                 "descripcion": descripcion[:200], "automatico": True})
    return obj


class Liquidacion(models.Model):
    """Pre-liquidación mensual de un empleado: arma las novedades (horas extra, presentismo, multas)
    y el costo para la empresa. La liquidación legal la hace el estudio contable."""

    class Estado(models.TextChoices):
        BORRADOR = "borrador", "Borrador"
        APROBADA = "aprobada", "Aprobada"
        PAGADA = "pagada", "Pagada"

    persona = models.ForeignKey("core.Persona", on_delete=models.PROTECT, related_name="liquidaciones")
    periodo = models.DateField(help_text="Primer día del mes liquidado.")
    basico = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    horas_extra_50 = models.DecimalField("HE al 50 % (h)", max_digits=6, decimal_places=2, default=Decimal("0"))
    horas_extra_100 = models.DecimalField("HE al 100 % (h)", max_digits=6, decimal_places=2, default=Decimal("0"))
    monto_horas_extra = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    presentismo = models.DecimalField("Adicional presentismo", max_digits=12, decimal_places=2, default=Decimal("0"))
    otros_adicionales = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    multas = models.DecimalField("Multas registradas (informativo, no se descuentan: art. 131 LCT)", max_digits=12,
                                 decimal_places=2, default=Decimal("0"))
    dias_descuento = models.DecimalField("Días no trabajados a descontar", max_digits=5, decimal_places=1,
                                         default=Decimal("0"), help_text="Faltas sin justificar + días de suspensión.")
    descuento_dias = models.DecimalField("Descuento por días no trabajados", max_digits=12, decimal_places=2,
                                         default=Decimal("0"))
    otros_descuentos = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    bruto = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    cargas_sociales = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    costo_total = models.DecimalField("Costo para la empresa", max_digits=12, decimal_places=2, default=Decimal("0"))
    dias_trabajados = models.PositiveSmallIntegerField(default=0)
    faltas_injustificadas = models.PositiveSmallIntegerField(default=0)
    tardanzas = models.PositiveSmallIntegerField(default=0)
    recibo = models.FileField("Recibo de sueldo firmado", upload_to="recibos/%Y/%m/", blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.BORRADOR)
    observaciones = models.CharField(max_length=200, blank=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-periodo", "persona__apellido"]
        unique_together = [("persona", "periodo")]
        verbose_name = "Liquidación (pre-liquidación de sueldo)"
        verbose_name_plural = "Liquidaciones (pre-liquidación de sueldos)"

    def __str__(self):
        return f"{self.persona} {self.periodo:%m/%Y}"
