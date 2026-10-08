from decimal import Decimal

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


class Egreso(models.Model):
    """Gasto real. Los de compras de stock, services, EPP y siniestros se
    generan automáticamente; el resto se carga a mano."""

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
