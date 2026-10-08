from datetime import timedelta

from django import forms
from django.utils import timezone

from core.models import Persona
from flota.models import Vehiculo
from incidentes.models import Siniestro
from inventario.models import Material
from operaciones.models import OrdenTrabajo
from supervision.models import AccionCorrectiva, EncuestaSupervisor, InformeControl

ESTRELLAS = [(i, str(i)) for i in range(5, 0, -1)]


class InicioJornadaForm(forms.Form):
    vehiculo = forms.ModelChoiceField(Vehiculo.objects.filter(estado="operativo"), required=False,
                                      label="Vehículo (si usás uno)")
    km_inicio = forms.IntegerField(required=False, min_value=0, label="Km al salir")
    lat = forms.DecimalField(required=False, widget=forms.HiddenInput, max_digits=9, decimal_places=6)
    lng = forms.DecimalField(required=False, widget=forms.HiddenInput, max_digits=9, decimal_places=6)


class FinJornadaForm(forms.Form):
    km_fin = forms.IntegerField(required=False, min_value=0, label="Km al volver")
    hectareas_cubiertas = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2, required=False,
                                             label="Hectáreas recorridas hoy (aprox.)")
    lat = forms.DecimalField(required=False, widget=forms.HiddenInput, max_digits=9, decimal_places=6)
    lng = forms.DecimalField(required=False, widget=forms.HiddenInput, max_digits=9, decimal_places=6)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from core.models import Parametros
        if not Parametros.actual().usar_hectareas:
            del self.fields["hectareas_cubiertas"]


class NovedadForm(forms.ModelForm):
    """Aviso de ausencia o pedido de licencia desde el celular."""

    class Meta:
        from personal.models import Novedad
        model = Novedad
        fields = ["tipo", "desde", "hasta", "certificado", "observaciones"]
        labels = {"certificado": "Foto del certificado (si tenés)", "observaciones": "Detalle"}
        widgets = {"desde": forms.DateInput(attrs={"type": "date"}), "hasta": forms.DateInput(attrs={"type": "date"}),
                   "certificado": forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf"}),
                   "observaciones": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from personal.models import Novedad
        # el empleado sólo puede avisar estos tipos; injustificada/suspensión las carga la empresa
        self.fields["tipo"].choices = [c for c in Novedad.Tipo.choices
                                       if c[0] in ("enfermedad", "accidente", "licencia", "vacaciones", "franco")]

    def clean(self):
        d = super().clean()
        if d.get("desde") and d.get("hasta") and d["hasta"] < d["desde"]:
            self.add_error("hasta", "La fecha final no puede ser anterior a la inicial.")
        return d


FILAS_MATERIAL = 6
FILAS_GASTO = 3


class CerrarOrdenForm(forms.Form):
    resultado = forms.ChoiceField(choices=[("completada", "Completada"), ("fallida", "No se pudo resolver"),
                                           ("reprogramada", "Reprogramar")])
    motivo_no_resuelto = forms.ChoiceField(required=False, label="¿Por qué no se pudo?",
                                           choices=[("", "—")] + OrdenTrabajo._meta.get_field("motivo_no_resuelto").choices)
    # Viaje y trabajo (minutos)
    minutos_viaje = forms.IntegerField(min_value=0, max_value=1440, required=False, label="Tiempo de viaje (min)")
    minutos_reales = forms.IntegerField(min_value=1, max_value=1440, required=False, label="Tiempo de trabajo (min)")
    minutos_retorno = forms.IntegerField(min_value=0, max_value=1440, required=False, label="Tiempo de retorno (min)")
    # Nota de cierre
    nota = forms.CharField(required=False, label="Qué se hizo",
                           widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Trabajo realizado, pruebas, pendientes…"}))
    decodificador_solicitado = forms.BooleanField(required=False, label="El cliente pidió decodificador para TV")
    decodificadores_instalados = forms.IntegerField(min_value=0, max_value=10, initial=0, required=False,
                                                    label="Decodificadores instalados")
    series_instaladas = forms.CharField(required=False, max_length=300, label="N° de serie de equipos instalados",
                                        widget=forms.TextInput(attrs={"placeholder": "Separados por coma"}))
    series_retiradas = forms.CharField(required=False, max_length=300, label="N° de serie de equipos retirados",
                                       widget=forms.TextInput(attrs={"placeholder": "Separados por coma"}))
    foto_trabajo = forms.FileField(required=False, label="Foto del trabajo terminado",
                                   widget=forms.ClearableFileInput(attrs={"accept": "image/*", "capture": "environment"}))
    conforme_nombre = forms.CharField(required=False, max_length=120, label="Nombre")
    conforme_apellido = forms.CharField(required=False, max_length=120, label="Apellido")
    conforme_dni = forms.CharField(required=False, max_length=15, label="DNI (si lo da)")
    firma = forms.CharField(required=False, widget=forms.HiddenInput)
    lat = forms.DecimalField(required=False, widget=forms.HiddenInput, max_digits=9, decimal_places=6)
    lng = forms.DecimalField(required=False, widget=forms.HiddenInput, max_digits=9, decimal_places=6)
    observaciones = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def __init__(self, *args, orden=None, stock=None, **kwargs):
        super().__init__(*args, **kwargs)
        stock = stock or {}
        materiales = Material.objects.filter(activo=True)
        # primero lo que el técnico tiene, con su saldo a la vista
        opciones = [("", "—")] + [(m.id, f"{m.nombre} · tenés {stock[m].normalize():f}")
                                  for m in sorted(stock, key=lambda m: m.nombre) if stock[m] > 0]
        otros = [(m.id, f"{m.nombre} · no lo tenés") for m in materiales if stock.get(m, 0) <= 0]
        if otros:
            opciones.append(("Otros", otros))
        for i in range(1, FILAS_MATERIAL + 1):
            self.fields[f"material_{i}"] = forms.TypedChoiceField(choices=opciones, required=False, coerce=int,
                                                                  empty_value=None, label=f"Material {i}")
            self.fields[f"cantidad_{i}"] = forms.DecimalField(min_value=0, required=False, label="Cantidad",
                                                              max_digits=10, decimal_places=2)
        # Gastos extra (expensas): qué, cuánto y comprobante
        for i in range(1, FILAS_GASTO + 1):
            self.fields[f"gasto_desc_{i}"] = forms.CharField(required=False, max_length=200, label="Qué compraste")
            self.fields[f"gasto_monto_{i}"] = forms.DecimalField(required=False, min_value=0, max_digits=12,
                                                                 decimal_places=2, label="Monto ($)")
            self.fields[f"gasto_comp_{i}"] = forms.FileField(
                required=False, label="Foto de la factura / ticket",
                widget=forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf"}))
        if orden and not orden.tipo.puede_requerir_decodificador:
            del self.fields["decodificador_solicitado"]
            del self.fields["decodificadores_instalados"]

    def clean(self):
        d = super().clean()
        if d.get("resultado") in ("fallida", "reprogramada") and not d.get("motivo_no_resuelto"):
            self.add_error("motivo_no_resuelto", "Indicá el motivo.")
        for i in range(1, FILAS_GASTO + 1):
            desc, monto = d.get(f"gasto_desc_{i}"), d.get(f"gasto_monto_{i}")
            if bool(desc) != bool(monto):
                self.add_error(f"gasto_monto_{i}" if desc else f"gasto_desc_{i}", "Completá qué compraste y el monto.")
        return d

    def gastos(self):
        return [(self.cleaned_data[f"gasto_desc_{i}"], self.cleaned_data[f"gasto_monto_{i}"],
                 self.cleaned_data.get(f"gasto_comp_{i}")) for i in range(1, FILAS_GASTO + 1)
                if self.cleaned_data.get(f"gasto_desc_{i}") and self.cleaned_data.get(f"gasto_monto_{i}")]

    def materiales(self):
        ids = {}
        for i in range(1, FILAS_MATERIAL + 1):
            m, c = self.cleaned_data.get(f"material_{i}"), self.cleaned_data.get(f"cantidad_{i}")
            if m and c:
                ids[m] = ids.get(m, 0) + c
        mats = Material.objects.in_bulk(list(ids))
        return [(mats[k], v) for k, v in ids.items()]


class NotaForm(forms.Form):
    texto = forms.CharField(label="Nueva nota", widget=forms.Textarea(attrs={"rows": 3}), max_length=2000)


class PedidoForm(forms.Form):
    motivo = forms.CharField(required=False, max_length=200, label="Para qué / comentario")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        opciones = [("", "—")] + [(m.id, f"{m.nombre} ({m.unidad})") for m in Material.objects.filter(activo=True)]
        for i in range(1, FILAS_MATERIAL + 1):
            self.fields[f"material_{i}"] = forms.TypedChoiceField(choices=opciones, required=False, coerce=int,
                                                                  empty_value=None, label=f"Parte {i}")
            self.fields[f"cantidad_{i}"] = forms.DecimalField(min_value=0, required=False, label="Cantidad",
                                                              max_digits=10, decimal_places=2)

    def items(self):
        filas = []
        for i in range(1, FILAS_MATERIAL + 1):
            m, c = self.cleaned_data.get(f"material_{i}"), self.cleaned_data.get(f"cantidad_{i}")
            if m and c:
                filas.append((m, c))
        return filas

    def clean(self):
        d = super().clean()
        if not self.items():
            raise forms.ValidationError("Cargá al menos una parte con su cantidad.")
        return d


class SiniestroMovilForm(forms.ModelForm):
    class Meta:
        model = Siniestro
        fields = ["tipo", "gravedad", "direccion", "descripcion", "costo_estimado"]
        labels = {"costo_estimado": "Costo estimado del daño ($, si lo sabés)"}
        widgets = {"descripcion": forms.Textarea(attrs={"placeholder": "Qué pasó, dónde y cómo."})}


class EncuestaForm(forms.ModelForm):
    trato = forms.TypedChoiceField(choices=ESTRELLAS, coerce=int, widget=forms.RadioSelect,
                                   label="¿Cómo te trató tu supervisor hoy?")
    claridad = forms.TypedChoiceField(choices=ESTRELLAS, coerce=int, widget=forms.RadioSelect,
                                      label="¿Fueron claras sus indicaciones?")
    apoyo = forms.TypedChoiceField(choices=ESTRELLAS, coerce=int, widget=forms.RadioSelect,
                                   label="¿Te ayudó cuando tuviste un problema?")
    presencia = forms.TypedChoiceField(choices=ESTRELLAS, coerce=int, widget=forms.RadioSelect,
                                       label="¿Estuvo disponible cuando lo necesitaste?")

    class Meta:
        model = EncuestaSupervisor
        fields = ["trato", "claridad", "apoyo", "presencia", "comentario"]
        labels = {"comentario": "Comentario (opcional)"}


class EncuestaSemanalForm(forms.ModelForm):
    class Meta:
        from supervision.models import EncuestaSemanal
        model = EncuestaSemanal
        fields = ["general", "trato", "organizacion", "apoyo", "ensenanza", "justicia", "lo_mejor", "a_mejorar"]
        widgets = {"lo_mejor": forms.Textarea(attrs={"rows": 2}), "a_mejorar": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre in ("general", "trato", "organizacion", "apoyo", "ensenanza", "justicia"):
            campo = self.fields[nombre]
            self.fields[nombre] = forms.TypedChoiceField(choices=ESTRELLAS, coerce=int, widget=forms.RadioSelect,
                                                         label=campo.label)


class InformeForm(forms.ModelForm):
    class Meta:
        model = InformeControl
        fields = ["tecnico", "orden", "tipo", "puntaje", "desvio_detectado", "descripcion", "foto",
                  "latitud", "longitud"]
        labels = {"puntaje": "Puntaje del trabajo (1 = muy mal, 5 = excelente)",
                  "desvio_detectado": "Detecté un desvío / problema",
                  "descripcion": "Qué controlaste y qué encontraste"}
        widgets = {"latitud": forms.HiddenInput, "longitud": forms.HiddenInput,
                   "puntaje": forms.NumberInput(attrs={"min": 1, "max": 5}),
                   "foto": forms.ClearableFileInput(attrs={"accept": "image/*", "capture": "environment"})}

    def __init__(self, *args, supervisor=None, **kwargs):
        super().__init__(*args, **kwargs)
        equipo = Persona.objects.filter(rol="tecnico", activo=True)
        if supervisor:
            equipo = equipo.filter(supervisor=supervisor)
        self.fields["tecnico"].queryset = equipo
        hoy = timezone.localdate()
        self.fields["orden"].queryset = OrdenTrabajo.objects.filter(
            tecnico__in=equipo, fecha_programada__gte=hoy - timedelta(days=3))
        self.fields["orden"].required = False


class AccionForm(forms.ModelForm):
    class Meta:
        model = AccionCorrectiva
        fields = ["tecnico", "tipo", "monto", "descripcion"]
        labels = {"monto": "Monto (sólo si es multa)", "descripcion": "Detalle"}

    def __init__(self, *args, supervisor=None, **kwargs):
        super().__init__(*args, **kwargs)
        equipo = Persona.objects.filter(rol="tecnico", activo=True)
        if supervisor:
            equipo = equipo.filter(supervisor=supervisor)
        self.fields["tecnico"].queryset = equipo
