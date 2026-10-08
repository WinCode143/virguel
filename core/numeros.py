"""Números como se escriben acá y campos de formulario para montos y cantidades.

Montos: aceptan 125.000,50 · 125000,5 · 125000.50 · $ 10.000 (el navegador además muestra el "$"
y no deja escribir letras: static/js/ui.js). Cantidades de partes: sólo enteros.
"""
import math
import re
from decimal import Decimal, InvalidOperation

from django import forms

MILES = re.compile(r"-?\d{1,3}(\.\d{3})+")


def a_decimal(v):
    """Texto → Decimal. None si está vacío, False si no es un número."""
    v = str(v if v is not None else "").strip().replace("$", "").replace(" ", "").replace("\xa0", "")
    if not v:
        return None
    if "," in v or MILES.fullmatch(v):
        v = v.replace(".", "").replace(",", ".")
    try:
        d = Decimal(v)
    except InvalidOperation:
        return False
    return d if d.is_finite() else False


def a_entero(v):
    """Texto → int (cantidad de partes). None si está vacío, False si no es un entero ≥ 0."""
    d = a_decimal(v)
    if d is None or d is False:
        return d
    return int(d) if d == int(d) and d >= 0 else False


def entero_arriba(v) -> int:
    """Para proponer cantidades: 15,5 m → 16."""
    return int(math.ceil(v or 0))


def attrs_pesos(**extra):
    return {"data-moneda": "", "inputmode": "decimal", "autocomplete": "off", **extra}


def attrs_cantidad(**extra):
    return {"data-entero": "", "inputmode": "numeric", "min": "0", "step": "1", **extra}


class CampoPesos(forms.DecimalField):
    """Monto en pesos: se muestra con "$" y separador de miles; acepta formato argentino."""

    widget = forms.TextInput

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", 2)
        super().__init__(*args, **kwargs)
        self.widget.attrs.update(attrs_pesos())
        self.widget.attrs.pop("step", None)

    def to_python(self, value):
        d = a_decimal(value)
        if d is False:
            raise forms.ValidationError("Escribí sólo el número (ej. 125.000,50).", code="invalid")
        return d

    def widget_attrs(self, widget):
        return {}


class CampoCantidad(forms.IntegerField):
    """Cantidad de partes: sólo números enteros (negativos sólo si se pide, p. ej. ajustes)."""

    def __init__(self, *args, negativos=False, **kwargs):
        self.negativos = negativos
        if not negativos:
            kwargs.setdefault("min_value", 0)
        super().__init__(*args, **kwargs)
        self.widget.attrs.update(attrs_cantidad())
        if negativos:
            self.widget.attrs.pop("min", None)

    def to_python(self, value):
        if value in self.empty_values:
            return None
        d = a_decimal(value)
        n = int(d) if d not in (None, False) and d == int(d) and (self.negativos or d >= 0) else False
        if n is False:
            raise forms.ValidationError("Las partes se cuentan en números enteros (sin decimales).", code="invalid")
        return n


PESOS = ("costo", "monto", "precio", "basico", "sueldo", "importe", "presupuesto", "multa")


def campo_para(db_field):
    """Campo de formulario para un DecimalField de un modelo según su nombre: cantidades → enteros,
    importes → pesos. None si no corresponde."""
    from django.db import models
    if not isinstance(db_field, models.DecimalField) or not db_field.editable:
        return None
    comunes = {"required": not db_field.blank, "label": db_field.verbose_name[:1].upper() + db_field.verbose_name[1:],
               "help_text": db_field.help_text}
    if db_field.name.startswith("cantidad") or db_field.name == "stock_minimo":
        return CampoCantidad(negativos="negativo" in str(db_field.help_text), **comunes)
    if any(k in db_field.name for k in PESOS):
        return CampoPesos(max_digits=db_field.max_digits, decimal_places=db_field.decimal_places, **comunes)
    return None


def instalar_en_admin():
    """Aplica la regla en toda la carga de datos (admin)."""
    from django.contrib.admin.options import BaseModelAdmin
    original = BaseModelAdmin.formfield_for_dbfield
    if getattr(original, "_numeros", False):
        return

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        campo = campo_para(db_field)
        if campo is not None:
            if db_field.has_default() and not callable(db_field.default):
                campo.initial = db_field.default
            return campo
        return original(self, db_field, request, **kwargs)

    formfield_for_dbfield._numeros = True
    BaseModelAdmin.formfield_for_dbfield = formfield_for_dbfield
