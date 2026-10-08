"""Manejo de credenciales: accesos al sistema de cada persona (gerencia; supervisores sólo su equipo)."""
import secrets

from django.contrib import messages
from django.contrib.auth.models import Group, User
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.autenticacion import registrar
from core.models import CuentaUsuario, Persona, RegistroAcceso
from core.roles import GERENCIA, SUPERVISOR, persona_de, requiere_rol, rol_de

E = RegistroAcceso.Evento
GRUPO_POR_ROL = {"tecnico": "Técnicos", "supervisor": "Supervisores", "gerencia": "Gerencia",
                 "administrativo": "Administración"}
ROLES_SISTEMA = ["Gerencia", "Administración", "Contabilidad", "Depósito", "Supervisores", "Técnicos"]


def clave_temporal() -> str:
    """Clave fácil de dictar por teléfono: 3 bloques sin caracteres confusos (sin 0/O, 1/l)."""
    alfabeto = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3))


def personas_gestionables(request):
    qs = Persona.objects.select_related("usuario", "supervisor")
    if rol_de(request.user) == SUPERVISOR:
        qs = qs.filter(supervisor=persona_de(request.user))
    return qs


def link_whatsapp_clave(persona, usuario, clave, request):
    from tablero.views import link_whatsapp
    texto = (f"Hola {persona.nombre}, tu acceso a Virguel: {request.build_absolute_uri(reverse('login'))} "
             f"· usuario: {usuario} (o tu legajo) · clave temporal: {clave} . Al entrar vas a elegir una propia.")
    return link_whatsapp(persona.telefono, texto)


@requiere_rol(GERENCIA, SUPERVISOR)
def lista(request):
    q = request.GET.get("q", "").strip()
    filtro = request.GET.get("estado", "")
    personas = personas_gestionables(request).order_by("-activo", "rol", "apellido")
    if q:
        personas = personas.filter(Q(apellido__icontains=q) | Q(nombre__icontains=q) | Q(legajo__icontains=q)
                                   | Q(usuario__username__icontains=q))
    cuentas = {c.usuario_id: c for c in CuentaUsuario.objects.all()}
    filas = []
    for p in personas:
        u = p.usuario
        c = cuentas.get(u.id) if u else None
        if not u:
            estado = ("info", "Sin acceso")
        elif not u.is_active:
            estado = ("critico", "Dado de baja")
        elif c and c.bloqueada:
            estado = ("critico", "Bloqueado por intentos")
        elif c and c.debe_cambiar_clave:
            estado = ("aviso", "Clave temporal")
        else:
            estado = ("ok", "Activo")
        if filtro and estado[1] != filtro:
            continue
        filas.append({"p": p, "u": u, "c": c, "estado": estado,
                      "grupos": ", ".join(g.name for g in u.groups.all()) if u else ""})
    externos = []
    if rol_de(request.user) == GERENCIA:  # usuarios sin persona (p. ej. el administrador)
        externos = User.objects.filter(persona__isnull=True).order_by("username")
    estados = ["Activo", "Clave temporal", "Bloqueado por intentos", "Sin acceso", "Dado de baja"]
    return render(request, "personal/usuarios.html", {
        "filas": filas, "externos": externos, "q": q, "filtro": filtro, "estados": estados,
        "sin_acceso": sum(1 for f in filas if not f["u"] and f["p"].activo)})


@requiere_rol(GERENCIA, SUPERVISOR)
def detalle(request, pk):
    p = get_object_or_404(personas_gestionables(request), pk=pk)
    es_gerencia = rol_de(request.user) == GERENCIA
    u = p.usuario
    if request.method == "POST":
        accion = request.POST.get("accion")
        permitido_sup = {"blanquear", "desbloquear"}
        if not es_gerencia and accion not in permitido_sup:
            messages.error(request, "Sólo gerencia puede hacer esa acción.")
            return redirect("personal:usuario", pk=p.pk)
        with transaction.atomic():
            if accion == "crear" and not u:
                if not p.activo:
                    messages.error(request, "La persona no está activa.")
                    return redirect("personal:usuario", pk=p.pk)
                nombre = (request.POST.get("usuario") or p.legajo).strip().lower()
                if User.objects.filter(username__iexact=nombre).exists():
                    messages.error(request, f"El usuario «{nombre}» ya existe; elegí otro.")
                    return redirect("personal:usuario", pk=p.pk)
                clave = clave_temporal()
                u = User.objects.create_user(nombre, email=p.email, password=clave, first_name=p.nombre,
                                             last_name=p.apellido)
                u.groups.add(Group.objects.get_or_create(name=GRUPO_POR_ROL.get(p.rol, "Técnicos"))[0])
                if p.rol in ("gerencia", "administrativo"):
                    u.is_staff = True
                    u.save(update_fields=["is_staff"])
                p.usuario = u
                p.save(update_fields=["usuario"])
                CuentaUsuario.objects.update_or_create(usuario=u, defaults={"debe_cambiar_clave": True})
                registrar(request, E.ADMIN, u, nombre, "Acceso creado", request.user)
                _mostrar_clave(request, p, u, clave)
            elif accion == "blanquear" and u:
                clave = clave_temporal()
                u.set_password(clave)  # invalida las sesiones abiertas en otros dispositivos
                u.save(update_fields=["password"])
                CuentaUsuario.objects.update_or_create(usuario=u, defaults={
                    "debe_cambiar_clave": True, "intentos_fallidos": 0, "bloqueado_hasta": None})
                registrar(request, E.BLANQUEO, u, u.username, "Clave blanqueada", request.user)
                _mostrar_clave(request, p, u, clave)
            elif accion == "desbloquear" and u:
                CuentaUsuario.objects.update_or_create(usuario=u, defaults={"intentos_fallidos": 0, "bloqueado_hasta": None})
                registrar(request, E.ADMIN, u, u.username, "Desbloqueado", request.user)
                messages.success(request, "Acceso desbloqueado.")
            elif accion in ("baja", "reactivar") and u:
                u.is_active = accion == "reactivar"
                u.save(update_fields=["is_active"])
                registrar(request, E.ADMIN, u, u.username, "Acceso reactivado" if u.is_active else "Acceso dado de baja",
                          request.user)
                messages.success(request, "Acceso " + ("reactivado." if u.is_active else "dado de baja: ya no puede ingresar."))
            elif accion == "rol" and u:
                nuevos = [g for g in request.POST.getlist("grupos") if g in ROLES_SISTEMA]
                u.groups.set(Group.objects.filter(name__in=nuevos))
                u.is_staff = any(g in ("Gerencia", "Administración", "Depósito", "Contabilidad") for g in nuevos)
                u.save(update_fields=["is_staff"])
                registrar(request, E.ADMIN, u, u.username, "Roles: " + (", ".join(nuevos) or "ninguno"), request.user)
                messages.success(request, "Roles actualizados.")
        return redirect("personal:usuario", pk=p.pk)
    cuenta = CuentaUsuario.de(u) if u else None
    return render(request, "personal/usuario.html", {
        "p": p, "u": u, "cuenta": cuenta, "roles": ROLES_SISTEMA, "es_gerencia_vista": es_gerencia,
        "grupos": [g.name for g in u.groups.all()] if u else [],
        "accesos": RegistroAcceso.objects.filter(Q(usuario=u) if u else Q(pk__in=[])).select_related("hecho_por")[:40],
        "clave": request.session.pop("clave_temporal", None)})


def _mostrar_clave(request, p, u, clave):
    """La clave temporal se muestra una sola vez (no se guarda en ningún lado)."""
    request.session["clave_temporal"] = {"clave": clave, "usuario": u.username,
                                         "wa": link_whatsapp_clave(p, u.username, clave, request)}


@requiere_rol(GERENCIA)
def accesos(request):
    """Auditoría de accesos de todo el sistema."""
    evento = request.GET.get("evento", "")
    qs = RegistroAcceso.objects.select_related("usuario", "hecho_por")
    if evento:
        qs = qs.filter(evento=evento)
    hoy = timezone.localdate()
    return render(request, "personal/accesos.html", {
        "registros": qs[:300], "evento": evento, "eventos": RegistroAcceso.Evento.choices,
        "fallidos_hoy": RegistroAcceso.objects.filter(evento=E.FALLIDO, fecha__date=hoy).count(),
        "bloqueos_hoy": RegistroAcceso.objects.filter(evento=E.BLOQUEO, fecha__date=hoy).count(),
        "ingresos_hoy": RegistroAcceso.objects.filter(evento=E.INGRESO, fecha__date=hoy).count()})
