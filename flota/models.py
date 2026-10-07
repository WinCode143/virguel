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

    class Meta:
        ordering = ["patente"]
        verbose_name = "Vehículo"

    def __str__(self):
        return f"{self.patente} {self.marca} {self.modelo}"


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


def proximos_services(vehiculo: Vehiculo, hoy=None):
    """Para cada tipo de service, cuándo toca el próximo (por km y/o fecha)."""
    hoy = hoy or timezone.localdate()
    # km promedio por día de los últimos 60 días (para estimar fecha por km)
    jornadas = vehiculo.jornada_set.filter(
        fecha__gte=hoy - timedelta(days=60), km_fin__isnull=False, km_inicio__isnull=False)
    km_dia = 0
    if jornadas.exists():
        total = sum(j.km_fin - j.km_inicio for j in jornadas)
        km_dia = total / 60
    res = []
    for tipo in TipoService.objects.all():
        ultimo = vehiculo.services.filter(tipo=tipo).order_by("-fecha").first()
        base_fecha = ultimo.fecha if ultimo else None
        base_km = ultimo.km if ultimo else 0
        prox_km = base_km + tipo.cada_km if tipo.cada_km else None
        prox_fecha = base_fecha + timedelta(days=tipo.cada_dias) if (tipo.cada_dias and base_fecha) else None
        km_restantes = prox_km - vehiculo.km_actual if prox_km is not None else None
        fecha_por_km = (hoy + timedelta(days=int(km_restantes / km_dia))
                        if km_restantes is not None and km_dia > 0 and km_restantes > 0 else None)
        candidatas = [f for f in (prox_fecha, fecha_por_km) if f]
        if km_restantes is not None and km_restantes <= 0:
            candidatas.append(hoy)
        fecha_estimada = min(candidatas) if candidatas else None
        dias = (fecha_estimada - hoy).days if fecha_estimada else None
        estado = "ok"
        if dias is not None:
            estado = "critico" if dias <= 0 else "aviso" if dias <= 15 else "ok"
        res.append({"tipo": tipo, "ultimo": ultimo, "prox_km": prox_km, "km_restantes": km_restantes,
                    "fecha_estimada": fecha_estimada, "dias": dias, "estado": estado})
    return res
