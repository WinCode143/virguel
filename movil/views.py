"""App móvil (PWA) para técnicos y supervisores en calle."""
import os
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
from core.models import Parametros
from core.roles import SUPERVISOR, TECNICO, persona_de, requiere_rol, rol_de
from herramientas.models import Asignacion
from incidentes.models import Siniestro
from operaciones.models import Jornada, OrdenTrabajo
from supervision.evaluacion import evaluar_supervisores
from supervision.models import EncuestaSupervisor, InformeControl, TareaSupervisor

from .forms import (AccionForm, CerrarOrdenForm, EncuestaForm, EncuestaSemanalForm, FinJornadaForm, InformeForm,
                    InicioJornadaForm, NovedadForm, PedidoForm, SiniestroMovilForm)

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
    if not Parametros.actual().encuesta_diaria:
        encuesta = None
    epp_sin_firmar = Asignacion.objects.filter(persona=p, estado="en_uso", conformidad_firmada=False).count()
    return render(request, "movil/inicio_tecnico.html", {
        "p": p, "jornada": jornada, "asistencia": asistencia, "ots": ots, "hechas": hechas, "encuesta": encuesta,
        "epp_vencido": epp_vencido, "epp_sin_firmar": epp_sin_firmar, "tab": "inicio",
        "inicio_form": InicioJornadaForm(), "fin_form": FinJornadaForm()})


def _inicio_supervisor(request, p):
    from inventario.models import PedidoMaterial
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
        "pedidos_pendientes": PedidoMaterial.objects.filter(tecnico__supervisor=p, estado="pendiente").count(),
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
        # sólo vino la fecha (versión anterior de la app): esa fecha con la hora actual
        f = fecha_operacion(request)
        if f != timezone.localdate():
            return timezone.make_aware(datetime.combine(f, timezone.localtime(ahora).time()))
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
    """Ficha completa de la orden + empezar trabajo + cierre con todos los datos de calle."""
    import base64

    from django.core.files.base import ContentFile

    from inventario.models import RecetaMaterial
    from inventario.stock_tecnico import consumir, saldos
    p = _persona(request)
    ot = get_object_or_404(OrdenTrabajo.objects.select_related("tipo", "cliente", "zona"), pk=pk, tecnico=p)
    abierta = ot.estado in ("pendiente", "asignada")
    stock = saldos(p)
    if request.method == "POST" and request.POST.get("accion") == "empezar" and abierta:
        if not ot.inicio_trabajo:
            ot.inicio_trabajo = momento_operacion(request)
            ot.save(update_fields=["inicio_trabajo"])
        return redirect("movil:orden", pk=ot.pk)
    if request.method == "POST" and abierta:
        f = CerrarOrdenForm(request.POST, request.FILES, orden=ot, stock=stock)
        if f.is_valid():
            d = f.cleaned_data
            fin = momento_operacion(request)
            hoy = timezone.localtime(fin).date()
            avisos = []
            with transaction.atomic():
                ot.estado = d["resultado"]
                ot.fecha_ejecucion = hoy
                ot.fin_trabajo = fin
                if ot.inicio_trabajo:
                    ot.minutos_reales = max(1, int((fin - ot.inicio_trabajo).total_seconds() // 60))
                else:
                    ot.minutos_reales = d.get("minutos_reales")
                ot.motivo_no_resuelto = "" if ot.estado == "completada" else (d.get("motivo_no_resuelto") or "")
                ot.decodificador_solicitado = bool(d.get("decodificador_solicitado"))
                ot.decodificadores_instalados = d.get("decodificadores_instalados") or 0
                ot.series_instaladas, ot.series_retiradas = d["series_instaladas"], d["series_retiradas"]
                ot.conforme_nombre, ot.conforme_dni = d["conforme_nombre"], d["conforme_dni"]
                ot.lat_cierre, ot.lng_cierre = d.get("lat"), d.get("lng")
                ot.observaciones = d["observaciones"] or ot.observaciones
                if d.get("foto_trabajo"):
                    ot.foto_trabajo = d["foto_trabajo"]
                if d.get("firma", "").startswith("data:image/png;base64,"):
                    ot.firma.save(f"firma_{ot.numero}.png",
                                  ContentFile(base64.b64decode(d["firma"].split(",", 1)[1])), save=False)
                if ot.estado == "reprogramada":
                    ot.fecha_programada = hoy + timedelta(days=1)
                    ot.inicio_trabajo = None
                ot._sin_notificar = True
                ot.save()
                for material, cantidad in f.materiales():
                    if not consumir(p, ot, material, cantidad, hoy):
                        avisos.append(f"{material.nombre}: usaste más de lo que figuraba a tu cargo. Avisale a tu supervisor.")
            for a in avisos:
                messages.warning(request, a)
            messages.success(request, f"Orden {ot.numero} registrada.")
            return redirect("movil:inicio")
    else:
        # materiales precargados con lo que normalmente lleva este tipo de trabajo
        inicial = {}
        for k, r in enumerate(RecetaMaterial.objects.filter(tipo_tarea=ot.tipo).select_related("material"), 1):
            if k > 6:
                break
            inicial[f"material_{k}"] = r.material_id
            inicial[f"cantidad_{k}"] = r.cantidad.normalize()
        f = CerrarOrdenForm(orden=ot, stock=stock, initial=inicial)
    previas = []
    if ot.cliente_id:
        previas = (OrdenTrabajo.objects.filter(cliente_id=ot.cliente_id).exclude(pk=ot.pk)
                   .exclude(fecha_ejecucion__isnull=True).select_related("tipo", "tecnico").order_by("-fecha_ejecucion")[:5])
    destino = ""
    if ot.cliente and ot.cliente.latitud:
        destino = f"{ot.cliente.latitud},{ot.cliente.longitud}"
    elif ot.cliente and ot.cliente.direccion:
        destino = f"{ot.cliente.direccion}, {ot.zona or ''}"
    from urllib.parse import quote
    return render(request, "movil/orden.html", {
        "ot": ot, "form": f, "abierta": abierta, "previas": previas, "tab": "inicio",
        "mapa": f"https://www.google.com/maps/dir/?api=1&destination={quote(destino)}" if destino else "",
        "consumos": ot.consumos.select_related("material") if not abierta else []})


@requiere_rol(TECNICO)
def historial(request):
    p = _persona(request)
    estado = request.GET.get("estado", "")
    qs = (OrdenTrabajo.objects.filter(tecnico=p, fecha_ejecucion__isnull=False)
          .select_related("tipo", "cliente").order_by("-fecha_ejecucion", "-id"))
    if estado:
        qs = qs.filter(estado=estado)
    return render(request, "movil/historial.html", {"ordenes": qs[:80], "estado": estado, "tab": "inicio"})


@requiere_rol(TECNICO)
def mi_stock(request):
    from inventario.models import PedidoMaterial
    from inventario.stock_tecnico import faltante_para_ordenes, partes_paradas, saldos
    p = _persona(request)
    faltante, n_ordenes = faltante_para_ordenes(p)
    return render(request, "movil/stock.html", {
        "saldos": sorted(saldos(p).items(), key=lambda kv: kv[0].nombre), "paradas": partes_paradas([p]),
        "faltante": faltante, "falta_algo": any(f["falta"] for f in faltante), "n_ordenes": n_ordenes,
        "pedidos": PedidoMaterial.objects.filter(tecnico=p).prefetch_related("items__material")[:10], "tab": "stock"})


@requiere_rol(TECNICO)
def pedir_partes(request):
    from core.notificaciones import notificar
    from inventario.models import PedidoItem, PedidoMaterial
    from inventario.stock_tecnico import faltante_para_ordenes
    p = _persona(request)
    if request.method == "POST":
        f = PedidoForm(request.POST)
        if f.is_valid():
            with transaction.atomic():
                ped = PedidoMaterial.objects.create(tecnico=p, motivo=f.cleaned_data["motivo"])
                for m, c in f.items():
                    PedidoItem.objects.create(pedido=ped, material_id=m, cantidad=c)
            notificar(p.supervisor, f"Pedido de partes de {p.nombre_completo}",
                      f"{len(f.items())} ítem(s) para aprobar", "/app/pedidos/")
            messages.success(request, "Pedido enviado. Te avisamos cuando lo aprueben.")
            return redirect("movil:stock")
    else:
        inicial = {}
        if request.GET.get("faltante"):
            faltante, _ = faltante_para_ordenes(p)
            for k, fila in enumerate([x for x in faltante if x["falta"]][:6], 1):
                inicial[f"material_{k}"] = fila["material"].id
                inicial[f"cantidad_{k}"] = fila["falta"].normalize()
            inicial["motivo"] = "Para mis órdenes asignadas"
        f = PedidoForm(initial=inicial)
    return render(request, "movil/pedido.html", {"form": f, "tab": "stock"})


@requiere_rol(SUPERVISOR)
def pedidos_equipo(request):
    from core.notificaciones import notificar
    from inventario.models import PedidoMaterial
    p = _persona(request)
    if request.method == "POST":
        ped = get_object_or_404(PedidoMaterial, pk=request.POST.get("pedido"), tecnico__supervisor=p, estado="pendiente")
        aprobar = request.POST.get("accion") == "aprobar"
        ped.estado = PedidoMaterial.Estado.APROBADO if aprobar else PedidoMaterial.Estado.RECHAZADO
        ped.aprobado_por, ped.respuesta = p, request.POST.get("respuesta", "")[:200]
        ped.save()
        notificar(ped.tecnico, f"Tu pedido de partes fue {'aprobado' if aprobar else 'rechazado'}",
                  ped.respuesta or ("El depósito lo prepara." if aprobar else ""), "/app/stock/")
        messages.success(request, "Pedido " + ("aprobado." if aprobar else "rechazado."))
        return redirect("movil:pedidos")
    return render(request, "movil/pedidos_equipo.html", {
        "pendientes": PedidoMaterial.objects.filter(tecnico__supervisor=p, estado="pendiente")
        .select_related("tecnico").prefetch_related("items__material"),
        "recientes": PedidoMaterial.objects.filter(tecnico__supervisor=p).exclude(estado="pendiente")
        .select_related("tecnico")[:10], "tab": "asistencia"})


@requiere_rol(TECNICO)
def yo(request):
    return render(request, "movil/yo.html", {"tab": "yo"})


@requiere_rol(TECNICO)
def mi_legajo(request):
    p = _persona(request)
    return render(request, "movil/legajo.html", {
        "acciones": p.acciones_correctivas.select_related("aplicada_por")[:30],
        "controles": p.informes_recibidos.select_related("supervisor")[:30],
        "siniestros": p.siniestros.all()[:10], "tab": "yo"})


def lunes(d):
    return d - timedelta(days=d.weekday())


@requiere_rol(TECNICO)
def mi_supervisor(request):
    """Evaluación semanal del supervisor (una por semana)."""
    from supervision.models import EncuestaSemanal
    p = _persona(request)
    semana = lunes(timezone.localdate())
    hecha = EncuestaSemanal.objects.filter(tecnico=p, semana=semana).first()
    if p.supervisor_id is None:
        return render(request, "movil/mensaje.html", {"titulo": "Sin supervisor", "texto": "No tenés supervisor asignado."})
    if request.method == "POST" and not hecha:
        f = EncuestaSemanalForm(request.POST)
        if f.is_valid():
            e = f.save(commit=False)
            e.tecnico, e.supervisor, e.semana = p, p.supervisor, semana
            e.save()
            messages.success(request, "¡Gracias! Tu evaluación es confidencial.")
            return redirect("movil:mi_supervisor")
    else:
        f = EncuestaSemanalForm()
    anteriores = EncuestaSemanal.objects.filter(tecnico=p).exclude(semana=semana)[:8]
    return render(request, "movil/mi_supervisor.html", {
        "form": f, "hecha": hecha, "semana": semana, "sup": p.supervisor, "anteriores": anteriores, "tab": "yo"})


@requiere_rol(*MOVIL)
def notificaciones(request):
    p = _persona(request)
    lista = list(p.notificaciones.all()[:50])
    p.notificaciones.filter(leida=False).update(leida=True)
    from core.notificaciones import push_configurado
    return render(request, "movil/notificaciones.html", {
        "lista": lista, "push": push_configurado(), "clave": os.environ.get("VAPID_PUBLIC_KEY", ""), "tab": ""})


@requiere_rol(*MOVIL)
def push_suscribir(request):
    """Guarda el permiso de notificaciones del navegador del celular."""
    import json

    from django.http import JsonResponse

    from core.models import SuscripcionPush
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    try:
        d = json.loads(request.body)
        SuscripcionPush.objects.update_or_create(endpoint=d["endpoint"], defaults={
            "persona": _persona(request), "p256dh": d["keys"]["p256dh"], "auth": d["keys"]["auth"]})
    except (KeyError, ValueError):
        return JsonResponse({"ok": False}, status=400)
    return JsonResponse({"ok": True})


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
    """Métricas propias del técnico: hoy, últimos 30 días vs. el equipo, y evolución semanal."""
    from collections import Counter

    from django.db.models import Avg, F

    from personal.indicadores import resumen
    from tablero.asignacion import capacidad_tecnicos
    p = _persona(request)
    hoy = timezone.localdate()
    desde = hoy - timedelta(days=29)
    ev = evaluar_tecnicos(tecnicos=[p])[0]
    meta = capacidad_tecnicos([p], hoy)[p.id]
    mias = OrdenTrabajo.objects.filter(tecnico=p, fecha_ejecucion__range=(desde, hoy))
    comp = mias.filter(estado="completada")
    ejecutadas = mias.count()
    dias = Jornada.objects.filter(tecnico=p, en_calle=True, fecha__range=(desde, hoy)).count()
    eq_dias = Jornada.objects.filter(en_calle=True, fecha__range=(desde, hoy)).count()
    eq_comp = OrdenTrabajo.objects.filter(estado="completada", fecha_ejecucion__range=(desde, hoy)).count()
    eq_ejec = OrdenTrabajo.objects.filter(fecha_ejecucion__range=(desde, hoy), tecnico__isnull=False).count()
    tiempo = comp.filter(minutos_reales__isnull=False).aggregate(
        real=Avg("minutos_reales"), est=Avg(F("tipo__minutos_estandar")))
    motivos = Counter(mias.exclude(motivo_no_resuelto="").values_list("motivo_no_resuelto", flat=True))
    nombres = dict(OrdenTrabajo._meta.get_field("motivo_no_resuelto").choices)
    asis = resumen(desde, hoy, [p])[0]
    # evolución semanal: OT por día en calle, propia y del equipo (8 semanas)
    semanas = []
    for n in range(7, -1, -1):
        ini = lunes(hoy) - timedelta(weeks=n)
        fin = ini + timedelta(days=6)
        d = Jornada.objects.filter(tecnico=p, en_calle=True, fecha__range=(ini, fin)).count()
        o = OrdenTrabajo.objects.filter(tecnico=p, estado="completada", fecha_ejecucion__range=(ini, fin)).count()
        ed = Jornada.objects.filter(en_calle=True, fecha__range=(ini, fin)).count()
        eo = OrdenTrabajo.objects.filter(estado="completada", fecha_ejecucion__range=(ini, fin)).count()
        semanas.append({"ini": ini, "yo": o / d if d else None, "equipo": eo / ed if ed else None})
    tope = max([x["yo"] or 0 for x in semanas] + [x["equipo"] or 0 for x in semanas] + [1])
    for x in semanas:
        x["ancho_yo"] = f"{(x['yo'] or 0) / tope * 100:.0f}"
        x["ancho_eq"] = f"{(x['equipo'] or 0) / tope * 100:.0f}"
    return render(request, "movil/desempeno.html", {
        "ev": ev, "tab": "yo", "meta": meta,
        "hoy_hechas": OrdenTrabajo.objects.filter(tecnico=p, estado="completada", fecha_ejecucion=hoy).count(),
        "completadas": comp.count(), "ejecutadas": ejecutadas, "dias": dias,
        "por_dia": comp.count() / dias if dias else None, "eq_por_dia": eq_comp / eq_dias if eq_dias else None,
        "efectividad": comp.count() / ejecutadas if ejecutadas else None,
        "eq_efectividad": eq_comp / eq_ejec if eq_ejec else None,
        "min_real": tiempo["real"], "min_est": tiempo["est"],
        "retrabajos": OrdenTrabajo.objects.filter(es_retrabajo=True, orden_original__tecnico=p,
                                                  fecha_programada__range=(desde, hoy)).count(),
        "controles": p.informes_recibidos.filter(fecha__range=(desde, hoy)).aggregate(n=Count("id"), prom=Avg("puntaje")),
        "motivos": [(nombres.get(k, k), n) for k, n in motivos.most_common()],
        "asis": asis, "semanas": semanas})


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
