"""App móvil (PWA) para técnicos y supervisores en calle."""
from datetime import date, timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from capacitacion.evaluacion import evaluar_tecnicos
from core.roles import SUPERVISOR, TECNICO, persona_de, requiere_rol, rol_de
from herramientas.models import Asignacion
from incidentes.models import Siniestro
from inventario.models import Salida
from inventario.services import StockInsuficiente, registrar_salida
from operaciones.models import Jornada, OrdenTrabajo
from supervision.evaluacion import evaluar_supervisores
from supervision.models import EncuestaSupervisor, InformeControl, TareaSupervisor

from .forms import (AccionForm, CerrarOrdenForm, EncuestaForm, FinJornadaForm, InformeForm, InicioJornadaForm,
                    NovedadForm, SiniestroMovilForm)

MOVIL = (TECNICO, SUPERVISOR)


def fecha_operacion(request):
    """Fecha en que el técnico cargó el dato en el celular (puede llegar más tarde
    si no tenía señal). Se acepta hasta 7 días hacia atrás; si no, se usa hoy."""
    hoy = timezone.localdate()
    try:
        f = date.fromisoformat(request.POST.get("_fecha_cliente", ""))
    except ValueError:
        return hoy
    return f if hoy - timedelta(days=7) <= f <= hoy else hoy


def _persona(request):
    p = persona_de(request.user)
    if p is None:
        raise Http404("El usuario no está vinculado a una persona del padrón.")
    return p


@requiere_rol(*MOVIL)
def inicio(request):
    p = _persona(request)
    if rol_de(request.user) == SUPERVISOR:
        return _inicio_supervisor(request, p)
    hoy = timezone.localdate()
    from personal.models import Asistencia
    jornada = Jornada.objects.filter(tecnico=p, fecha=hoy).first()
    asistencia = Asistencia.objects.filter(persona=p, fecha=hoy).first()
    ots = OrdenTrabajo.objects.filter(tecnico=p, fecha_programada__lte=hoy).filter(
        estado__in=["pendiente", "asignada"]).select_related("tipo", "cliente").order_by("fecha_programada")[:30]
    hechas = OrdenTrabajo.objects.filter(tecnico=p, fecha_ejecucion=hoy, estado="completada").count()
    encuesta = EncuestaSupervisor.objects.filter(tecnico=p, respondida__isnull=True,
                                                 fecha__gte=hoy - timedelta(days=1)).first()
    epp_vencido = Asignacion.objects.filter(persona=p, estado="en_uso", fecha_vencimiento__lt=hoy).count()
    epp_sin_firmar = Asignacion.objects.filter(persona=p, estado="en_uso", conformidad_firmada=False).count()
    return render(request, "movil/inicio_tecnico.html", {
        "p": p, "jornada": jornada, "asistencia": asistencia, "ots": ots, "hechas": hechas, "encuesta": encuesta,
        "epp_vencido": epp_vencido, "epp_sin_firmar": epp_sin_firmar, "tab": "inicio",
        "inicio_form": InicioJornadaForm(), "fin_form": FinJornadaForm()})


def _inicio_supervisor(request, p):
    from personal.indicadores import estado_del_dia
    from personal.models import Asistencia, Novedad
    hoy = timezone.localdate()
    equipo = p.a_cargo.filter(activo=True, rol="tecnico")
    estado_equipo = estado_del_dia(hoy, equipo)
    faltan = [e for e in estado_equipo if e.situacion[0] == "critico"]
    en_calle = Jornada.objects.filter(fecha=hoy, en_calle=True, tecnico__in=equipo).count()
    ots_hoy = OrdenTrabajo.objects.filter(tecnico__in=equipo, fecha_programada=hoy)
    resumen = {r["estado"]: r["n"] for r in ots_hoy.values("estado").annotate(n=Count("id"))}
    informes_hoy = InformeControl.objects.filter(supervisor=p, fecha=hoy).count()
    tareas = TareaSupervisor.objects.filter(supervisor=p, fecha=hoy)
    desvios_sin_accion = (InformeControl.objects.filter(supervisor=p, desvio_detectado=True,
                                                        fecha__gte=hoy - timedelta(days=14))
                          .annotate(n=Count("acciones")).filter(n=0).select_related("tecnico")[:10])
    return render(request, "movil/inicio_supervisor.html", {
        "p": p, "equipo": equipo.count(), "en_calle": en_calle, "resumen": resumen, "total_ots": ots_hoy.count(),
        "informes_hoy": informes_hoy, "tareas": tareas, "desvios_sin_accion": desvios_sin_accion, "tab": "inicio",
        "asistencia": Asistencia.objects.filter(persona=p, fecha=hoy).first(), "faltan": faltan,
        "tarde": [e for e in estado_equipo if e.situacion[0] == "aviso"],
        "novedades_pendientes": Novedad.objects.filter(persona__supervisor=p, estado="pendiente").count(),
        "inicio_form": InicioJornadaForm(), "fin_form": FinJornadaForm()})


# ---------------------------------------------------------------- técnico
def momento_operacion(request):
    """Momento real de la fichada según el celular (llega más tarde si no había señal).
    Se acepta hasta 7 días hacia atrás y no en el futuro; si no, se usa ahora."""
    from datetime import datetime
    ahora = timezone.now()
    try:
        m = datetime.fromisoformat(request.POST.get("_momento_cliente", "").replace("Z", "+00:00"))
    except ValueError:
        return ahora
    if timezone.is_naive(m):
        return ahora
    return m if ahora - timedelta(days=7) <= m <= ahora + timedelta(minutes=5) else ahora


@requiere_rol(*MOVIL)
def jornada(request, accion):
    """Fichada de entrada/salida (todos) + jornada en calle con vehículo (técnicos)."""
    from personal.models import Asistencia
    p = _persona(request)
    if request.method != "POST":
        return redirect("movil:inicio")
    momento = momento_operacion(request)
    hoy = timezone.localtime(momento).date()
    es_tecnico = p.rol == "tecnico"
    if accion == "iniciar":
        f = InicioJornadaForm(request.POST)
        if f.is_valid():
            a, creada = Asistencia.objects.get_or_create(persona=p, fecha=hoy, defaults={
                "entrada": momento, "lat_entrada": f.cleaned_data["lat"], "lng_entrada": f.cleaned_data["lng"]})
            if es_tecnico:
                Jornada.objects.update_or_create(fecha=hoy, tecnico=p, defaults={
                    "en_calle": True, "zona": p.zona, "vehiculo": f.cleaned_data["vehiculo"],
                    "km_inicio": f.cleaned_data["km_inicio"]})
            if not creada:
                messages.info(request, f"Ya habías fichado la entrada a las {timezone.localtime(a.entrada):%H:%M}.")
            elif a.minutos_tarde:
                messages.warning(request, f"Entrada registrada a las {timezone.localtime(a.entrada):%H:%M} "
                                          f"({a.minutos_tarde} min tarde).")
            else:
                messages.success(request, f"Entrada registrada a las {timezone.localtime(a.entrada):%H:%M}. ¡Buen día!")
    elif accion == "finalizar":
        f = FinJornadaForm(request.POST)
        a = Asistencia.objects.filter(persona=p, fecha=hoy).first()
        if a and f.is_valid():
            a.salida, a.lat_salida, a.lng_salida = momento, f.cleaned_data["lat"], f.cleaned_data["lng"]
            a.save()
            j = Jornada.objects.filter(fecha=hoy, tecnico=p).first() if es_tecnico else None
            if j:
                j.km_fin = f.cleaned_data["km_fin"]
                if f.cleaned_data.get("hectareas_cubiertas") is not None:
                    j.hectareas_cubiertas = f.cleaned_data["hectareas_cubiertas"]
                j.horas_trabajadas = a.horas_trabajadas
                j.save()
                if j.vehiculo and j.km_fin and j.km_fin > j.vehiculo.km_actual:
                    j.vehiculo.km_actual = j.km_fin
                    j.vehiculo.save(update_fields=["km_actual"])
            messages.success(request, f"Salida registrada a las {timezone.localtime(momento):%H:%M} "
                                      f"({a.horas_trabajadas:g} h)." + (" No olvides la encuesta del día." if es_tecnico else ""))
            # La encuesta se genera al cerrar la jornada (además del proceso nocturno)
            if es_tecnico and p.supervisor_id:
                EncuestaSupervisor.objects.get_or_create(fecha=hoy, tecnico=p,
                                                         defaults={"supervisor_id": p.supervisor_id})
        elif not a:
            messages.error(request, "No hay fichada de entrada de hoy.")
    return redirect("movil:inicio")


@requiere_rol(*MOVIL)
def novedad(request):
    """Avisar una ausencia o pedir una licencia."""
    p = _persona(request)
    if request.method == "POST":
        f = NovedadForm(request.POST, request.FILES)
        if f.is_valid():
            n = f.save(commit=False)
            n.persona, n.cargada_por = p, p
            n.save()
            messages.success(request, "Aviso enviado. Tu supervisor lo va a revisar.")
            return redirect("movil:asistencia")
    else:
        f = NovedadForm()
    return render(request, "movil/form.html", {
        "form": f, "titulo": "Avisar ausencia / pedir licencia", "tab": "asistencia",
        "ayuda": "Avisá lo antes posible. Si tenés certificado, sacale una foto."})


@requiere_rol(*MOVIL)
def mi_asistencia(request):
    from personal.indicadores import resumen
    from personal.models import Asistencia, Novedad
    p = _persona(request)
    hoy = timezone.localdate()
    desde = hoy.replace(day=1)
    r = resumen(desde, hoy, [p])[0]
    return render(request, "movil/asistencia.html", {
        "r": r, "desde": desde, "tab": "asistencia",
        "fichadas": Asistencia.objects.filter(persona=p, fecha__gte=hoy - timedelta(days=14)),
        "novedades": Novedad.objects.filter(persona=p).order_by("-desde")[:10]})


@requiere_rol(SUPERVISOR)
def novedades_equipo(request):
    """El supervisor aprueba o rechaza los avisos de su equipo."""
    from personal.models import Novedad
    p = _persona(request)
    if request.method == "POST":
        n = get_object_or_404(Novedad, pk=request.POST.get("novedad"), persona__supervisor=p)
        n.estado = Novedad.Estado.APROBADA if request.POST.get("accion") == "aprobar" else Novedad.Estado.RECHAZADA
        n.save(update_fields=["estado"])
        messages.success(request, f"Novedad {n.get_estado_display().lower()}.")
        return redirect("movil:novedades")
    return render(request, "movil/novedades.html", {
        "pendientes": Novedad.objects.filter(persona__supervisor=p, estado="pendiente").select_related("persona"),
        "recientes": Novedad.objects.filter(persona__supervisor=p).exclude(estado="pendiente")
        .select_related("persona")[:15], "tab": "asistencia"})


@requiere_rol(TECNICO)
def orden(request, pk):
    p = _persona(request)
    ot = get_object_or_404(OrdenTrabajo.objects.select_related("tipo", "cliente"), pk=pk, tecnico=p)
    if request.method == "POST":
        f = CerrarOrdenForm(request.POST, orden=ot)
        if f.is_valid():
            hoy = fecha_operacion(request)
            with transaction.atomic():
                ot.estado = f.cleaned_data["resultado"]
                ot.fecha_ejecucion = hoy
                ot.minutos_reales = f.cleaned_data.get("minutos_reales")
                ot.decodificador_solicitado = bool(f.cleaned_data.get("decodificador_solicitado"))
                ot.decodificadores_instalados = f.cleaned_data.get("decodificadores_instalados") or 0
                ot.observaciones = f.cleaned_data["observaciones"]
                if ot.estado == "reprogramada":
                    ot.fecha_programada = hoy + timedelta(days=1)
                ot.save()
                avisos = []
                for material, cantidad in f.materiales():
                    s = Salida(material=material, cantidad=cantidad, tecnico=p, orden=ot, fecha=hoy)
                    try:
                        registrar_salida(s)
                    except StockInsuficiente as e:
                        registrar_salida(s, permitir_negativo=True)
                        avisos.append(str(e))
            for a in avisos:
                messages.warning(request, a)
            messages.success(request, f"Orden {ot.numero} registrada.")
            return redirect("movil:inicio")
    else:
        f = CerrarOrdenForm(orden=ot)
    return render(request, "movil/orden.html", {"ot": ot, "form": f, "tab": "inicio"})


@requiere_rol(TECNICO)
def mi_epp(request):
    p = _persona(request)
    if request.method == "POST":
        Asignacion.objects.filter(persona=p, pk=request.POST.get("asignacion")).update(conformidad_firmada=True)
        messages.success(request, "Recepción confirmada.")
        return redirect("movil:epp")
    return render(request, "movil/epp.html", {
        "asignaciones": p.asignaciones.filter(estado="en_uso").select_related("elemento"),
        "hoy": timezone.localdate(), "tab": "epp"})


@requiere_rol(TECNICO)
def mi_desempeno(request):
    p = _persona(request)
    ev = evaluar_tecnicos(tecnicos=[p])[0]
    return render(request, "movil/desempeno.html", {"ev": ev, "tab": "yo"})


# ---------------------------------------------------------------- ambos
@requiere_rol(*MOVIL)
def reportar_incidente(request):
    p = _persona(request)
    if request.method == "POST":
        f = SiniestroMovilForm(request.POST)
        if f.is_valid():
            s = f.save(commit=False)
            ultimo = Siniestro.objects.aggregate(m=Max("id"))["m"] or 0
            s.numero = f"S-{timezone.localdate():%Y}-{ultimo + 1:05d}"
            s.reportado_por = p
            s.fecha = fecha_operacion(request)
            if p.rol == "tecnico":
                s.tecnico, s.supervisor = p, p.supervisor
            else:
                s.supervisor = p
            s.zona = p.zona
            s.save()
            messages.success(request, f"Incidente {s.numero} reportado. Gerencia fue notificada.")
            return redirect("movil:inicio")
    else:
        f = SiniestroMovilForm()
    return render(request, "movil/form.html", {"form": f, "titulo": "Reportar incidente / daño",
                                               "ayuda": "Roturas en casas, caños pinchados, daños a terceros, "
                                                        "accidentes. Reportalo aunque parezca menor.",
                                               "tab": "inicio"})


def encuesta(request, token):
    """Accesible con el link (sin login) para poder enviarse por WhatsApp/SMS."""
    e = get_object_or_404(EncuestaSupervisor.objects.select_related("supervisor", "tecnico"), token=token)
    if e.respondida:
        return render(request, "movil/mensaje.html", {"titulo": "¡Gracias!",
                                                      "texto": "Esta encuesta ya fue respondida."})
    if request.method == "POST":
        f = EncuestaForm(request.POST, instance=e)
        if f.is_valid():
            e = f.save(commit=False)
            e.respondida = timezone.now()
            e.save()
            return render(request, "movil/mensaje.html", {
                "titulo": "¡Gracias!", "texto": "Tu respuesta es confidencial: tu supervisor sólo ve promedios."})
    else:
        f = EncuestaForm(instance=e)
    return render(request, "movil/encuesta.html", {"e": e, "form": f})


# ---------------------------------------------------------------- supervisor
@requiere_rol(SUPERVISOR)
def nuevo_informe(request):
    p = _persona(request)
    if request.method == "POST":
        f = InformeForm(request.POST, request.FILES, supervisor=p)
        if f.is_valid():
            inf = f.save(commit=False)
            inf.supervisor = p
            inf.fecha = fecha_operacion(request)
            inf.save()
            messages.success(request, f"Informe guardado (calidad de documentación {inf.calidad_informe}/100).")
            if inf.desvio_detectado:
                return redirect(f"{reverse('movil:accion')}?informe={inf.pk}&tecnico={inf.tecnico_id}")
            return redirect("movil:inicio")
    else:
        f = InformeForm(supervisor=p, initial={"tecnico": request.GET.get("tecnico")})
    return render(request, "movil/informe.html", {"form": f, "tab": "control"})


@requiere_rol(SUPERVISOR)
def nueva_accion(request):
    p = _persona(request)
    informe = None
    if request.GET.get("informe") or request.POST.get("informe"):
        informe = InformeControl.objects.filter(
            pk=request.GET.get("informe") or request.POST.get("informe"), supervisor=p).first()
    if request.method == "POST":
        f = AccionForm(request.POST, supervisor=p)
        if f.is_valid():
            a = f.save(commit=False)
            a.aplicada_por, a.informe = p, informe
            a.fecha = fecha_operacion(request)
            a.save()
            messages.success(request, "Acción correctiva registrada.")
            return redirect("movil:inicio")
    else:
        f = AccionForm(supervisor=p, initial={"tecnico": request.GET.get("tecnico")})
    return render(request, "movil/form.html", {
        "form": f, "titulo": "Acción correctiva", "informe": informe, "tab": "control",
        "ayuda": "¿Qué hiciste con el desvío? Recapacitación al día siguiente, apercibimiento, multa…"})


@requiere_rol(SUPERVISOR)
def tarea(request, pk):
    p = _persona(request)
    t = get_object_or_404(TareaSupervisor, pk=pk, supervisor=p)
    if request.method == "POST":
        try:
            t.resultado = int(request.POST.get("resultado") or 0)
        except ValueError:
            t.resultado = 0
        t.comentario = request.POST.get("comentario", "")
        if t.meta:
            t.estado = "cumplida" if t.resultado >= t.meta else "parcial" if t.resultado else "no_cumplida"
        else:
            t.estado = request.POST.get("estado", t.estado)
        t.save()
        messages.success(request, "Objetivo actualizado.")
    return redirect("movil:inicio")


@requiere_rol(SUPERVISOR)
def mis_indicadores(request):
    p = _persona(request)
    ev = next((e for e in evaluar_supervisores() if e.supervisor.id == p.id), None)
    return render(request, "movil/indicadores_supervisor.html", {"ev": ev, "tab": "yo"})


# ---------------------------------------------------------------- PWA
def manifest(request):
    return HttpResponse(render_to_string("movil/manifest.webmanifest", request=request),
                        content_type="application/manifest+json")


def service_worker(request):
    resp = HttpResponse(render_to_string("movil/sw.js", request=request), content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/app/"
    return resp
