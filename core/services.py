"""Utilidades compartidas entre módulos."""
from datetime import date, timedelta

from .models import Alerta


class SincronizadorAlertas:
    """Abre/actualiza alertas de un módulo y cierra las que dejaron de aplicar.

    Uso:
        with SincronizadorAlertas("stock") as s:
            s.alerta("lote-12", "Lote parado 70 días", nivel="critica")
    Al salir, toda alerta abierta del módulo cuya clave no se reportó se
    marca como resuelta.
    """

    def __init__(self, modulo: str):
        self.modulo = modulo
        self.claves: set[str] = set()

    def alerta(self, clave, titulo, detalle="", nivel=Alerta.Nivel.AVISO, url=""):
        clave = f"{self.modulo}:{clave}"
        self.claves.add(clave)
        obj = Alerta.objects.filter(clave=clave, resuelta=False).first()
        if obj is None:
            Alerta.objects.create(modulo=self.modulo, clave=clave, titulo=titulo,
                                  detalle=detalle, nivel=nivel, url=url)
        else:
            obj.titulo, obj.detalle, obj.nivel, obj.url = titulo, detalle, nivel, url
            obj.save()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            (Alerta.objects.filter(modulo=self.modulo, resuelta=False)
             .exclude(clave__in=self.claves).update(resuelta=True))
        return False


def rango_fechas(desde: date, hasta: date):
    d = desde
    while d <= hasta:
        yield d
        d += timedelta(days=1)
