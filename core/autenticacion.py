"""Ingreso al sistema: usuario/legajo/DNI, bloqueo por intentos, auditoría, cambio de clave obligatorio."""
from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models import Q
from django.dispatch import receiver
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from .models import CuentaUsuario, RegistroAcceso

MAX_INTENTOS = 5
MINUTOS_BLOQUEO = 15


def buscar_usuario(identificador: str):
    """Usuario por nombre de usuario, legajo o DNI (lo que la persona recuerde)."""
    User = get_user_model()
    ident = (identificador or "").strip()
    if not ident:
        return None
    return (User.objects.filter(Q(username__iexact=ident) | Q(persona__legajo__iexact=ident)
                                | Q(persona__dni=ident)).order_by("id").first())


class UsuarioLegajoDniBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        user = buscar_usuario(username)
        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        if user is None:
            get_user_model()().set_password(password)  # mismo tiempo de respuesta exista o no el usuario
        return None


def _ip(request):
    if request is None:
        return None
    reenviada = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (reenviada.split(",")[0].strip() or request.META.get("REMOTE_ADDR")) or None


def registrar(request, evento, usuario=None, ingresado="", detalle="", hecho_por=None):
    RegistroAcceso.objects.create(
        usuario=usuario, usuario_ingresado=ingresado[:150], evento=evento, ip=_ip(request), detalle=detalle[:200],
        dispositivo=(request.META.get("HTTP_USER_AGENT", "")[:200] if request else ""), hecho_por=hecho_por)


class FormularioIngreso(AuthenticationForm):
    username = forms.CharField(label="Usuario, legajo o DNI", max_length=150)
    error_messages = {
        "invalid_login": "Usuario o contraseña incorrectos.",
        "inactive": "Este acceso está dado de baja. Consultá con gerencia.",
    }

    def clean(self):
        usuario = buscar_usuario(self.cleaned_data.get("username"))
        if usuario:
            cuenta = CuentaUsuario.de(usuario)
            if cuenta.bloqueada:
                minutos = int((cuenta.bloqueado_hasta - timezone.now()).total_seconds() // 60) + 1
                raise forms.ValidationError(
                    f"Por seguridad el acceso está bloqueado {minutos} min por varios intentos fallidos. "
                    "Si no recordás la clave, pedí un blanqueo a tu supervisor o a gerencia.", code="bloqueado")
            if not usuario.is_active:
                raise forms.ValidationError(self.error_messages["inactive"], code="inactive")
        try:
            return super().clean()
        except forms.ValidationError:
            if usuario:
                cuenta.intentos_fallidos += 1
                if cuenta.intentos_fallidos >= MAX_INTENTOS:
                    cuenta.bloqueado_hasta = timezone.now() + timedelta(minutes=MINUTOS_BLOQUEO)
                    cuenta.intentos_fallidos = 0
                    registrar(self.request, RegistroAcceso.Evento.BLOQUEO, usuario,
                              self.cleaned_data.get("username", ""), f"{MAX_INTENTOS} intentos fallidos")
                cuenta.save()
            raise


@receiver(user_logged_in)
def _al_ingresar(sender, request, user, **kwargs):
    cuenta = CuentaUsuario.de(user)
    if cuenta.intentos_fallidos or cuenta.bloqueado_hasta:
        cuenta.intentos_fallidos, cuenta.bloqueado_hasta = 0, None
        cuenta.save(update_fields=["intentos_fallidos", "bloqueado_hasta"])
    registrar(request, RegistroAcceso.Evento.INGRESO, user, user.get_username())


@receiver(user_logged_out)
def _al_salir(sender, request, user, **kwargs):
    if user:
        registrar(request, RegistroAcceso.Evento.SALIDA, user, user.get_username())


@receiver(user_login_failed)
def _al_fallar(sender, credentials, request=None, **kwargs):
    ingresado = credentials.get("username", "")
    registrar(request, RegistroAcceso.Evento.FALLIDO, buscar_usuario(ingresado), ingresado)


class SeguridadCuentaMiddleware:
    """Si la cuenta debe cambiar la clave o aceptar el aviso de privacidad, se lo pide antes de seguir."""

    LIBRES = ("/static/", "/media/", "/logout/", "/cuenta/", "/encuesta/", "/app/sw.js", "/app/manifest")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and not request.path.startswith(self.LIBRES):
            cuenta = CuentaUsuario.objects.filter(usuario=user).only("debe_cambiar_clave", "acepto_privacidad").first()
            if cuenta and cuenta.debe_cambiar_clave:
                return redirect(f"{reverse('cambiar_clave')}?next={request.path}")
            persona = getattr(user, "persona", None)
            if persona and persona.rol in ("tecnico", "supervisor") and not (cuenta and cuenta.acepto_privacidad):
                return redirect(f"{reverse('privacidad')}?next={request.path}")
        return self.get_response(request)
