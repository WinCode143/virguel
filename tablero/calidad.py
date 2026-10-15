"""Pantallas de calidad y supervisión que antes sólo existían en el administrador (contraste B20, B23, B28):
verificación de objetivos de supervisores, plantillas de control y expediente de incidentes."""
from collections import Counter
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import Persona
from core.roles import GERENCIA, SUPERVISOR, persona_de, requiere_rol, rol_de
from incidentes.models import ActuacionIncidente, Siniestro
from supervision.models import InformeControl, ItemPlantilla, PlantillaInspeccion, ResultadoItem, TareaSupervisor


# ---------------------------------------------------------------- objetivos de supervisores (B23)
class ObjetivoForm(forms.ModelForm):
    class Meta:
        model = TareaSupervisor
        fields = ["supervisor", "fecha", "descripcion", "meta", "criterio_aceptacion"]
        widgets = {"fecha": forms.DateInput(attrs={"type": "date"})}
        labels = {"meta": "Meta (cantidad, opcional)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supervisor"].queryset = Persona.objects.filter(rol="supervisor", activo=True)
        self.fields["criterio_aceptacion"].required = True


@requiere_rol(GERENCIA)
def objetivos(request):
    yo = persona_de(request.user)
    if request.method == "POST" and request.POST.get("accion") in ("verificado", "rechazado"):
        t = get_object_or_404(TareaSupervisor, pk=request.POST.get("tarea"))
        try:
            t.verificar(request.POST["accion"], request.user, yo, request.POST.get("nota", "").strip())
            messages.success(request, f"Objetivo {t.get_verificacion_display().lower()}.")
        except ValueError as e:
            messages.error(request, str(e))
        return redirect(request.get_full_path())
    form = ObjetivoForm(request.POST or None, initial={"fecha": timezone.localdate()})
    if request.method == "POST" and request.POST.get("accion") == "crear":
        if form.is_valid():
            form.save()
            messages.success(request, "Objetivo asignado.")
            return redirect("tablero:objetivos")
    estado = request.GET.get("estado", "reportado")
    qs = TareaSupervisor.objects.select_related("supervisor", "verificado_por").order_by("-fecha", "supervisor__apellido")
    if estado != "todos":
        qs = qs.filter(verificacion=estado)
    conteo = Counter(TareaSupervisor.objects.filter(fecha__gte=timezone.localdate() - timedelta(days=60))
                     .values_list("verificacion", flat=True))
    return render(request, "tablero/objetivos.html", {
        "tareas": qs[:150], "estado": estado, "form": form,
        "estados": [(k, n, conteo.get(k, 0) if k != "todos" else None) for k, n in [
            ("reportado", "A verificar"), ("verificado", "Verificados"), ("rechazado", "Rechazados"),
            ("sin_reporte", "Sin reporte"), ("todos", "Todos")]]})


# ---------------------------------------------------------------- plantillas de control (B20)
class ItemForm(forms.ModelForm):
    class Meta:
        model = ItemPlantilla
        fields = ["orden", "punto", "criterio", "defecto", "critico"]


@requiere_rol(GERENCIA, SUPERVISOR)
def plantillas(request):
    es_ger = rol_de(request.user) == GERENCIA
    if request.method == "POST" and es_ger and request.POST.get("accion") == "nueva":
        nombre = request.POST.get("nombre", "").strip()
        if nombre and not PlantillaInspeccion.objects.filter(nombre=nombre).exists():
            pl = PlantillaInspeccion.objects.create(nombre=nombre, tipo=request.POST.get("tipo") or "calidad")
            return redirect("tablero:plantilla", pk=pl.pk)
        messages.error(request, "Poné un nombre que no exista.")
    lista = PlantillaInspeccion.objects.order_by("nombre", "-version")
    desde = timezone.localdate() - timedelta(days=60)
    hallazgos = Counter()
    for defecto, critico in (ResultadoItem.objects.filter(resultado="no_cumple", informe__fecha__gte=desde)
                             .values_list("item__defecto", "item__critico")):
        hallazgos[(defecto, critico)] += 1
    usos = Counter(InformeControl.objects.filter(fecha__gte=desde, plantilla__isnull=False)
                   .values_list("plantilla_id", flat=True))
    return render(request, "tablero/plantillas.html", {
        "plantillas": [(p, usos.get(p.pk, 0)) for p in lista], "es_ger": es_ger,
        "hallazgos": [(d, c, n) for (d, c), n in hallazgos.most_common(15)],
        "controles": InformeControl.objects.filter(fecha__gte=desde).count(),
        "con_plantilla": sum(usos.values())})


@requiere_rol(GERENCIA, SUPERVISOR)
def plantilla(request, pk):
    pl = get_object_or_404(PlantillaInspeccion, pk=pk)
    es_ger = rol_de(request.user) == GERENCIA
    usada = pl.informes.exists()
    form = ItemForm(request.POST or None, initial={"orden": pl.items.count() + 1})
    if request.method == "POST" and es_ger:
        accion = request.POST.get("accion")
        if accion == "version":
            with transaction.atomic():
                ultima = PlantillaInspeccion.objects.filter(nombre=pl.nombre).order_by("-version").first()
                PlantillaInspeccion.objects.filter(nombre=pl.nombre).update(vigente=False)
                nueva = PlantillaInspeccion.objects.create(nombre=pl.nombre, tipo=pl.tipo, version=ultima.version + 1)
                for i in pl.items.all():
                    i.pk, i.plantilla = None, nueva
                    i.save()
            messages.success(request, f"Versión {nueva.version} creada: los controles anteriores conservan la suya.")
            return redirect("tablero:plantilla", pk=nueva.pk)
        if usada:
            messages.error(request, "Esta versión ya se usó en controles: creá una versión nueva para cambiarla.")
            return redirect("tablero:plantilla", pk=pl.pk)
        if accion == "agregar" and form.is_valid():
            item = form.save(commit=False)
            item.plantilla = pl
            item.save()
            return redirect("tablero:plantilla", pk=pl.pk)
        if accion == "quitar":
            pl.items.filter(pk=request.POST.get("item")).delete()
            return redirect("tablero:plantilla", pk=pl.pk)
    items = []
    for i in pl.items.all():
        rs = Counter(i.resultadoitem_set.values_list("resultado", flat=True))
        evaluados = rs["cumple"] + rs["no_cumple"]
        items.append((i, rs["no_cumple"], rs["no_cumple"] / evaluados if evaluados else None))
    return render(request, "tablero/plantilla.html", {
        "pl": pl, "items": items, "form": form, "es_ger": es_ger, "usada": usada,
        "versiones": PlantillaInspeccion.objects.filter(nombre=pl.nombre).order_by("-version")})


# ---------------------------------------------------------------- expediente de incidentes (B28)
class ActuacionForm(forms.ModelForm):
    class Meta:
        model = ActuacionIncidente
        fields = ["fecha", "tipo", "descripcion", "responsable", "referencia", "vence"]
        widgets = {"fecha": forms.DateInput(attrs={"type": "date"}), "vence": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsable"].queryset = Persona.objects.filter(activo=True).exclude(rol="tecnico")


@requiere_rol(GERENCIA, SUPERVISOR)
def incidente(request, pk):
    qs = Siniestro.objects.select_related("tecnico", "supervisor", "orden", "cliente", "responsable_gestion")
    if rol_de(request.user) == SUPERVISOR:
        qs = qs.filter(tecnico__supervisor=persona_de(request.user))
    sin = get_object_or_404(qs, pk=pk)
    form = ActuacionForm(request.POST or None, initial={"fecha": timezone.localdate(),
                                                        "responsable": persona_de(request.user)})
    if request.method == "POST":
        if request.POST.get("accion") == "cumplida":
            a = get_object_or_404(ActuacionIncidente, pk=request.POST.get("actuacion"), siniestro=sin)
            a.cumplida = True
            a.save(update_fields=["cumplida"])
            messages.success(request, "Plazo marcado como cumplido.")
            return redirect("tablero:incidente", pk=sin.pk)
        if form.is_valid():
            a = form.save(commit=False)
            a.siniestro = sin
            a.save()
            messages.success(request, "Actuación agregada al expediente.")
            return redirect("tablero:incidente", pk=sin.pk)
    return render(request, "tablero/incidente.html", {
        "s": sin, "actuaciones": sin.actuaciones.select_related("responsable"), "form": form,
        "hoy": timezone.localdate()})
