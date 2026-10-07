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


class FinJornadaForm(forms.Form):
    km_fin = forms.IntegerField(required=False, min_value=0, label="Km al volver")
    hectareas_cubiertas = forms.DecimalField(min_value=0, max_digits=6, decimal_places=2,
                                             label="Hectáreas recorridas hoy (aprox.)")


class CerrarOrdenForm(forms.Form):
    resultado = forms.ChoiceField(choices=[("completada", "Completada"), ("fallida", "No se pudo resolver"),
                                           ("reprogramada", "Reprogramar")])
    minutos_reales = forms.IntegerField(min_value=1, max_value=1440, required=False, label="Minutos que llevó")
    decodificador_solicitado = forms.BooleanField(required=False, label="El cliente pidió decodificador para TV")
    decodificadores_instalados = forms.IntegerField(min_value=0, max_value=10, initial=0, required=False,
                                                    label="Decodificadores instalados")
    observaciones = forms.CharField(widget=forms.Textarea, required=False)

    def __init__(self, *args, orden=None, **kwargs):
        super().__init__(*args, **kwargs)
        materiales = Material.objects.filter(activo=True)
        for i in range(1, 4):
            self.fields[f"material_{i}"] = forms.ModelChoiceField(materiales, required=False,
                                                                  label=f"Material usado {i}")
            self.fields[f"cantidad_{i}"] = forms.DecimalField(min_value=0, required=False, label="Cantidad",
                                                              max_digits=10, decimal_places=2)
        if orden and not orden.tipo.puede_requerir_decodificador:
            del self.fields["decodificador_solicitado"]
            del self.fields["decodificadores_instalados"]

    def materiales(self):
        for i in range(1, 4):
            m, c = self.cleaned_data.get(f"material_{i}"), self.cleaned_data.get(f"cantidad_{i}")
            if m and c:
                yield m, c


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
