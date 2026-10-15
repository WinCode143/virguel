from datetime import timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.models import Persona


class Vehiculo(models.Model):
    class Estado(models.TextChoices):
        OPERATIVO = "operativo", "Operativo"
        TALLER = "taller", "En taller"
        FUERA = "fuera", "Fuera de servicio"

    patente = models.CharField(max_length=10, unique=True)
    marca = models.CharField(max_length=50)
    modelo = models.CharField(max_length=50)
    anio = models.PositiveSmallIntegerField("Año")
    km_actual = models.PositiveIntegerField(default=0)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.OPERATIVO)
    asignado_a = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="vehiculos")
    vencimiento_vtv = models.DateField("Vencimiento VTV", null=True, blank=True)
    vencimiento_seguro = models.DateField(null=True, blank=True)
    planes = models.ManyToManyField("TipoService", blank=True, related_name="vehiculos",
                                    verbose_name="Planes de mantenimiento aplicables")
    fecha_base_mantenimiento = models.DateField(
        "Fecha base del mantenimiento", null=True, blank=True,
        help_text="Incorporación o último service conocido antes del sistema. Sin base no se puede saber si está al día.")
    km_base_mantenimiento = models.PositiveIntegerField("Km base del mantenimiento", null=True, blank=True)

    class Meta:
        ordering = ["patente"]
        verbose_name = "Vehículo"

    def __str__(self):
        return f"{self.patente} {self.marca} {self.modelo}"


class LecturaOdometro(models.Model):
    """Lectura del cuentakilómetros: el contador pertenece al vehículo, no a cada técnico. Dos personas
    en el mismo recorrido producen una sola lectura; una lectura menor a la anterior es una anomalía."""

    class Fuente(models.TextChoices):
        JORNADA = "jornada", "Cierre de jornada"
        SERVICE = "service", "Service"
        MANUAL = "manual", "Carga manual"

    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name="lecturas")
    momento = models.DateTimeField(default=timezone.now)
    km = models.PositiveIntegerField()
    fuente = models.CharField(max_length=10, choices=Fuente.choices, default=Fuente.MANUAL)
    registrada_por = models.ForeignKey(Persona, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    anomalia = models.CharField(max_length=200, blank=True, help_text="Ej.: menor que la lectura anterior.")

    class Meta:
        ordering = ["-momento"]
        verbose_name = "Lectura de odómetro"
        verbose_name_plural = "Lecturas de odómetro"

    def __str__(self):
        return f"{self.vehiculo.patente} {self.km} km ({self.momento:%d/%m/%Y})"


def registrar_lectura(vehiculo, km: int, fuente="manual", persona=None, momento=None) -> LecturaOdometro | None:
    """Registra una lectura validando continuidad; si ya hay una igual ese día (otro integrante del mismo
    recorrido) no la duplica. Actualiza km_actual sólo hacia adelante."""
    momento = momento or timezone.now()
    dia = timezone.localtime(momento).date()
    if vehiculo.lecturas.filter(km=km, momento__date=dia).exists():
        return None
    anterior = vehiculo.lecturas.filter(momento__lte=momento).order_by("-momento").first()
    anomalia = ""
    if anterior and km < anterior.km:
        anomalia = f"Menor que la lectura anterior ({anterior.km} km del {timezone.localtime(anterior.momento):%d/%m})"
    lectura = LecturaOdometro.objects.create(vehiculo=vehiculo, km=km, fuente=fuente, registrada_por=persona,
                                             momento=momento, anomalia=anomalia)
    if not anomalia and km > vehiculo.km_actual:
        Vehiculo.objects.filter(pk=vehiculo.pk).update(km_actual=km)
        vehiculo.km_actual = km
    return lectura


def km_por_dia(vehiculo, hoy=None, dias=60) -> float:
    """Km recorridos por día según las lecturas del vehículo (no la suma de jornadas por técnico)."""
    hoy = hoy or timezone.localdate()
    lect = list(vehiculo.lecturas.filter(momento__date__gte=hoy - timedelta(days=dias), anomalia="")
                .order_by("momento").values_list("momento", "km"))
    if len(lect) < 2:
        return 0
    (t0, k0), (t1, k1) = lect[0], lect[-1]
    dias_reales = max(1, (t1 - t0).days)
    return max(0, k1 - k0) / dias_reales


class TipoService(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    cada_km = models.PositiveIntegerField(null=True, blank=True)
    cada_dias = models.PositiveIntegerField(null=True, blank=True)
    costo_estimado = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Tipo de service"
        verbose_name_plural = "Tipos de service"

    def __str__(self):
        return self.nombre


class ServiceRealizado(models.Model):
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name="services")
    tipo = models.ForeignKey(TipoService, on_delete=models.PROTECT)
    fecha = models.DateField(default=timezone.localdate)
    km = models.PositiveIntegerField()
    costo = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    taller = models.CharField(max_length=100, blank=True)
    observaciones = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Service realizado"
        verbose_name_plural = "Services realizados"

    def __str__(self):
        return f"{self.vehiculo.patente} {self.tipo} ({self.fecha})"


class ServiceProgramado(models.Model):
    """Turno de taller ya programado: el vehículo no está disponible esos días (la agenda lo bloquea)."""

    class Estado(models.TextChoices):
        PROGRAMADO = "programado", "Programado"
        REALIZADO = "realizado", "Realizado"
        CANCELADO = "cancelado", "Cancelado"

    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name="services_programados")
    tipo = models.ForeignKey(TipoService, null=True, blank=True, on_delete=models.SET_NULL)
    desde = models.DateField()
    hasta = models.DateField()
    taller = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PROGRAMADO)

    class Meta:
        ordering = ["desde"]
        verbose_name = "Service programado"
        verbose_name_plural = "Services programados"

    def __str__(self):
        return f"{self.vehiculo.patente} {self.desde:%d/%m}–{self.hasta:%d/%m}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.hasta and self.desde and self.hasta < self.desde:
            raise ValidationError("La fecha de fin no puede ser anterior al inicio.")


def proximos_services(vehiculo: Vehiculo, hoy=None):
    """Para cada plan de mantenimiento APLICABLE al vehículo, cuándo toca el próximo (por km y/o fecha).

    La base es el último service de ese tipo o, si no hay, la fecha/km base del vehículo. Sin base el
    estado es "sin_base" (faltan antecedentes), nunca "ok"."""
    hoy = hoy or timezone.localdate()
    # km promedio por día según el odómetro del vehículo (si no hay lecturas, por jornadas sin duplicar
    # los recorridos compartidos: se toma el máximo km_fin y el mínimo km_inicio de cada día)
    km_dia = km_por_dia(vehiculo, hoy)
    if not km_dia:
        from django.db.models import Max, Min
        por_dia = (vehiculo.jornada_set.filter(fecha__gte=hoy - timedelta(days=60), km_fin__isnull=False,
                                              km_inicio__isnull=False)
                   .values("fecha").annotate(a=Min("km_inicio"), b=Max("km_fin")))
        total = sum(max(0, d["b"] - d["a"]) for d in por_dia)
        km_dia = total / 60 if total else 0
    res = []
    for tipo in vehiculo.planes.all():
        ultimo = vehiculo.services.filter(tipo=tipo).order_by("-fecha").first()
        if ultimo:
            base_fecha, base_km = ultimo.fecha, ultimo.km
        else:
            base_fecha, base_km = vehiculo.fecha_base_mantenimiento, vehiculo.km_base_mantenimiento
        # Sin base (ni service previo ni datos de incorporación) no se informa "al día": faltan antecedentes
        falta_base = (tipo.cada_dias and base_fecha is None) or (tipo.cada_km and base_km is None)
        prox_km = base_km + tipo.cada_km if (tipo.cada_km and base_km is not None) else None
        prox_fecha = base_fecha + timedelta(days=tipo.cada_dias) if (tipo.cada_dias and base_fecha) else None
        km_restantes = prox_km - vehiculo.km_actual if prox_km is not None else None
        fecha_por_km = (hoy + timedelta(days=int(km_restantes / km_dia))
                        if km_restantes is not None and km_dia > 0 and km_restantes > 0 else None)
        candidatas = [f for f in (prox_fecha, fecha_por_km) if f]
        if km_restantes is not None and km_restantes <= 0:
            candidatas.append(hoy)
        fecha_estimada = min(candidatas) if candidatas else None
        dias = (fecha_estimada - hoy).days if fecha_estimada else None
        if falta_base and fecha_estimada is None:
            estado = "sin_base"
        elif dias is None:
            estado = "ok"
        else:
            estado = "critico" if dias <= 0 else "aviso" if dias <= 15 else "ok"
        res.append({"tipo": tipo, "ultimo": ultimo, "prox_km": prox_km, "km_restantes": km_restantes,
                    "fecha_estimada": fecha_estimada, "dias": dias, "estado": estado, "falta_base": bool(falta_base)})
    return res
