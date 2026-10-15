from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from core.models import Persona


class Elemento(models.Model):
    """EPP, herramienta o material crítico que se asigna a una persona."""

    class Tipo(models.TextChoices):
        EPP = "epp", "Elemento de protección personal"
        HERRAMIENTA = "herramienta", "Herramienta"
        CRITICO = "critico", "Material crítico de seguridad"

    codigo = models.CharField(max_length=30, unique=True)
    nombre = models.CharField(max_length=120)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.EPP)
    vida_util_dias = models.PositiveIntegerField(
        null=True, blank=True, help_text="Días hasta reemplazo obligatorio (vacío = sin vencimiento).")
    obligatorio_tecnicos = models.BooleanField(
        default=False, help_text="Todo técnico en calle debe tenerlo asignado y vigente.")
    costo = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    stock = models.PositiveIntegerField(default=0, help_text="Unidades en pañol para entregar.")

    class Meta:
        ordering = ["tipo", "nombre"]
        verbose_name = "Herramienta / EPP"
        verbose_name_plural = "Herramientas / EPP"

    def __str__(self):
        return self.nombre


class CompraElemento(models.Model):
    """Compra de herramientas/EPP para el pañol: es el gasto (egreso). Asignarlas después a una
    persona es custodia y no vuelve a contar como gasto."""

    elemento = models.ForeignKey(Elemento, on_delete=models.PROTECT, related_name="compras")
    fecha = models.DateField(default=timezone.localdate)
    cantidad = models.PositiveIntegerField()
    costo_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    proveedor = models.CharField(max_length=120, blank=True)
    comprobante = models.CharField("N° de factura / remito", max_length=50, blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Compra de herramientas / EPP"
        verbose_name_plural = "Compras de herramientas / EPP"

    def __str__(self):
        return f"{self.cantidad} × {self.elemento} ({self.fecha:%d/%m/%Y})"

    def save(self, *args, **kwargs):
        nueva = self._state.adding
        with transaction.atomic():
            super().save(*args, **kwargs)
            if nueva:
                mover(self.elemento_id, MovimientoPanol.Tipo.COMPRA, self.cantidad, compra=self,
                      fecha=self.fecha, motivo=f"Compra {self.comprobante}".strip())


class MovimientoPanol(models.Model):
    """Libro del pañol: toda entrada y salida de herramientas/EPP. El stock es la suma de los movimientos;
    una diferencia física se registra como AJUSTE con responsable y motivo (nunca se trunca en cero)."""

    class Tipo(models.TextChoices):
        APERTURA = "apertura", "Saldo inicial"
        COMPRA = "compra", "Compra"
        ENTREGA = "entrega", "Entrega a una persona"
        DEVOLUCION = "devolucion", "Devolución al pañol"
        BAJA = "baja", "Baja (rotura / pérdida)"
        AJUSTE = "ajuste", "Ajuste por inventario físico"

    elemento = models.ForeignKey(Elemento, on_delete=models.CASCADE, related_name="movimientos")
    fecha = models.DateField(default=timezone.localdate)
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    cantidad = models.IntegerField(help_text="Positivo entra al pañol, negativo sale.")
    asignacion = models.ForeignKey("Asignacion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    compra = models.ForeignKey("CompraElemento", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    responsable = models.CharField(max_length=150, blank=True)
    motivo = models.CharField(max_length=200, blank=True)
    creado = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fecha", "-id"]
        verbose_name = "Movimiento del pañol"
        verbose_name_plural = "Movimientos del pañol"

    def __str__(self):
        return f"{self.get_tipo_display()} {self.cantidad:+d} {self.elemento}"

    def clean(self):
        if self.tipo == self.Tipo.AJUSTE and not (self.motivo or "").strip():
            raise ValidationError({"motivo": "Un ajuste necesita motivo (p. ej. 'conteo físico 14/10')."})
        if self.tipo in (self.Tipo.ENTREGA, self.Tipo.BAJA) and self.cantidad > 0:
            self.cantidad = -self.cantidad

    def save(self, *args, **kwargs):
        nuevo = self._state.adding
        with transaction.atomic():
            if nuevo and self.cantidad < 0 and self.tipo != self.Tipo.AJUSTE:
                el = Elemento.objects.select_for_update().get(pk=self.elemento_id)
                if el.stock + self.cantidad < 0:
                    raise ValidationError(f"Sin existencias de {el}: hay {el.stock} y se quieren sacar "
                                          f"{-self.cantidad}. Registrar la compra o un ajuste autorizado.")
            super().save(*args, **kwargs)
            if nuevo:
                Elemento.objects.filter(pk=self.elemento_id).update(stock=models.F("stock") + self.cantidad)


def mover(elemento_id, tipo, cantidad, **kw) -> MovimientoPanol:
    signo = -1 if tipo in (MovimientoPanol.Tipo.ENTREGA, MovimientoPanol.Tipo.BAJA) else 1
    return MovimientoPanol.objects.create(elemento_id=elemento_id, tipo=tipo, cantidad=signo * abs(int(cantidad)), **kw)


class Asignacion(models.Model):
    class Origen(models.TextChoices):
        PANOL = "panol", "Del pañol (ya comprado)"
        COMPRA = "compra", "Comprado para esta entrega"
        REASIGNACION = "reasignacion", "Reasignado (lo tenía otra persona)"

    class Estado(models.TextChoices):
        EN_USO = "en_uso", "En uso"
        DEVUELTO = "devuelto", "Devuelto"
        PERDIDO = "perdido", "Perdido"
        DANADO = "danado", "Dañado / reemplazado"

    persona = models.ForeignKey(Persona, on_delete=models.CASCADE, related_name="asignaciones")
    elemento = models.ForeignKey(Elemento, on_delete=models.PROTECT, related_name="asignaciones")
    fecha_entrega = models.DateField(default=timezone.localdate)
    cantidad = models.PositiveSmallIntegerField(default=1)
    origen = models.CharField(
        max_length=12, choices=Origen.choices, default=Origen.PANOL,
        help_text="Sólo 'Comprado para esta entrega' es un gasto nuevo; del pañol o reasignado es custodia.")
    fecha_vencimiento = models.DateField(null=True, blank=True, editable=False)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.EN_USO)
    conformidad_firmada = models.BooleanField(
        default=False, help_text="El técnico firmó/confirmó la recepción (en la app).")
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-fecha_entrega"]
        verbose_name = "Asignación de herramienta / EPP"
        verbose_name_plural = "Asignaciones de herramientas / EPP"

    def __str__(self):
        return f"{self.elemento} → {self.persona}"

    def save(self, *args, **kwargs):
        if self.elemento.vida_util_dias:
            self.fecha_vencimiento = self.fecha_entrega + timedelta(days=self.elemento.vida_util_dias)
        else:
            self.fecha_vencimiento = None
        nueva = self._state.adding
        antes = None if nueva else Asignacion.objects.filter(pk=self.pk).values(
            "estado", "cantidad", "persona_id", "elemento_id", "origen").first()
        if antes and (antes["persona_id"] != self.persona_id or antes["elemento_id"] != self.elemento_id
                      or antes["origen"] != self.origen):
            # una entrega confirmada no cambia de persona, elemento ni origen: se devuelve y se entrega de nuevo
            raise ValidationError("Una entrega registrada no cambia de persona, elemento ni origen: registrá la "
                                  "devolución y una entrega nueva.")
        with transaction.atomic():
            super().save(*args, **kwargs)
            # Custodia del pañol (libro de movimientos): cada cambio de lo que está en manos de la persona
            # genera su movimiento, así depósito + custodia + bajas siempre reconcilian.
            if self.origen != self.Origen.PANOL:
                return
            if nueva:
                mover(self.elemento_id, MovimientoPanol.Tipo.ENTREGA, self.cantidad, asignacion=self,
                      fecha=self.fecha_entrega, motivo=f"Entrega a {self.persona}")
                return
            # fuera del pañol = en uso, perdido o dañado (lo perdido no vuelve: no hay devolución)
            fuera = (self.Estado.EN_USO, self.Estado.PERDIDO, self.Estado.DANADO)
            delta = (self.cantidad if self.estado in fuera else 0) - (antes["cantidad"] if antes["estado"] in fuera else 0)
            if delta > 0:
                mover(self.elemento_id, MovimientoPanol.Tipo.ENTREGA, delta, asignacion=self,
                      motivo=f"Entrega (modificación) a {self.persona}")
            elif delta < 0:
                mover(self.elemento_id, MovimientoPanol.Tipo.DEVOLUCION, -delta, asignacion=self,
                      motivo=f"Devolución de {self.persona}")

    def clean(self):
        if self._state.adding and self.origen == self.Origen.PANOL and self.elemento_id:
            stock = Elemento.objects.filter(pk=self.elemento_id).values_list("stock", flat=True).first() or 0
            if stock < (self.cantidad or 0):
                raise ValidationError(f"Sin existencias en el pañol (hay {stock}). Registrar la compra, elegir "
                                      "'Comprado para esta entrega' o un ajuste autorizado.")

    @property
    def es_gasto(self) -> bool:
        return self.origen == self.Origen.COMPRA

    @property
    def vencida(self) -> bool:
        return bool(self.fecha_vencimiento and self.fecha_vencimiento < timezone.localdate())


class ReporteCondicion(models.Model):
    """Rotura, desgaste o pérdida reportada antes del vencimiento: el elemento deja de considerarse
    utilizable y se abre la reparación o reposición, con responsable y constancia del reemplazo."""

    class Tipo(models.TextChoices):
        ROTURA = "rotura", "Rotura"
        DESGASTE = "desgaste", "Desgaste / no protege"
        PERDIDA = "perdida", "Pérdida / robo"

    class Estado(models.TextChoices):
        ABIERTO = "abierto", "Abierto"
        RESUELTO = "resuelto", "Resuelto"

    class Resolucion(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        REPUESTO = "repuesto", "Repuesto (entregado otro)"
        REPARADO = "reparado", "Reparado y devuelto"
        SIN_ACCION = "sin_accion", "Sin acción (fundamentado)"

    asignacion = models.ForeignKey("Asignacion", on_delete=models.CASCADE, related_name="reportes")
    fecha = models.DateField(default=timezone.localdate)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.ROTURA)
    descripcion = models.CharField(max_length=300)
    foto = models.FileField(upload_to="informes/%Y/%m/", blank=True)
    reportado_por = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    responsable = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                    help_text="Quién gestiona la reposición o reparación.")
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ABIERTO)
    resolucion = models.CharField(max_length=12, choices=Resolucion.choices, default=Resolucion.PENDIENTE)
    reemplazo = models.ForeignKey("Asignacion", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                  help_text="Constancia de la entrega sustituta.")
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Reporte de rotura / condición"
        verbose_name_plural = "Reportes de rotura / condición"

    def __str__(self):
        return f"{self.get_tipo_display()} de {self.asignacion.elemento} ({self.fecha:%d/%m/%Y})"

    def save(self, *args, **kwargs):
        nuevo = self._state.adding
        super().save(*args, **kwargs)
        if nuevo:
            # retiro preventivo: deja de contar como EPP vigente / herramienta utilizable
            estado = Asignacion.Estado.PERDIDO if self.tipo == self.Tipo.PERDIDA else Asignacion.Estado.DANADO
            Asignacion.objects.filter(pk=self.asignacion_id).update(estado=estado)

    def reponer(self, responsable=None, origen="panol"):
        """Entrega el sustituto y deja la constancia vinculada."""
        a = self.asignacion
        nueva = Asignacion.objects.create(persona=a.persona, elemento=a.elemento, cantidad=a.cantidad, origen=origen,
                                          observaciones=f"Reposición por {self.get_tipo_display().lower()}")
        self.reemplazo, self.resolucion, self.estado = nueva, self.Resolucion.REPUESTO, self.Estado.RESUELTO
        self.responsable = self.responsable or responsable
        self.save()
        return nueva


class RequisitoEPP(models.Model):
    """EPP o herramienta que exige un tipo de tarea. La falta de entrega es un bloqueo de suministro
    (la empresa debe entregarlo), no una conducta del técnico."""

    tipo_tarea = models.ForeignKey("operaciones.TipoTarea", on_delete=models.CASCADE, related_name="requisitos_epp")
    elemento = models.ForeignKey(Elemento, on_delete=models.CASCADE)

    class Meta:
        unique_together = [("tipo_tarea", "elemento")]
        verbose_name = "EPP requerido por tarea"
        verbose_name_plural = "EPP requerido por tarea"

    def __str__(self):
        return f"{self.tipo_tarea}: {self.elemento}"


def epp_faltante(persona_id, tipo_tarea_id, fecha=None) -> list:
    """Elementos requeridos por la tarea que la persona no tiene entregados y vigentes."""
    from django.db.models import Q
    fecha = fecha or timezone.localdate()
    requeridos = set(RequisitoEPP.objects.filter(tipo_tarea_id=tipo_tarea_id).values_list("elemento_id", flat=True))
    if not requeridos:
        return []
    vigentes = set(Asignacion.objects.filter(persona_id=persona_id, estado=Asignacion.Estado.EN_USO,
                                             elemento_id__in=requeridos, fecha_entrega__lte=fecha)
                   .filter(Q(fecha_vencimiento__isnull=True) | Q(fecha_vencimiento__gte=fecha))
                   .values_list("elemento_id", flat=True))
    return list(Elemento.objects.filter(pk__in=requeridos - vigentes).values_list("nombre", flat=True))
