"""Pantallas de la cuenta propia: cambio de clave y aviso de privacidad."""
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .autenticacion import registrar
from .models import CuentaUsuario, RegistroAcceso


def _siguiente(request, defecto="raiz"):
    destino = request.POST.get("next") or request.GET.get("next") or ""
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return destino
    return defecto


@login_required
def cambiar_clave(request):
    cuenta = CuentaUsuario.de(request.user)
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, form.user)  # sigue conectado aquí; se cierran las otras sesiones
            cuenta.debe_cambiar_clave, cuenta.ultimo_cambio_clave = False, timezone.now()
            cuenta.save()
            registrar(request, RegistroAcceso.Evento.CAMBIO_CLAVE, request.user, request.user.get_username())
            messages.success(request, "Clave actualizada.")
            return redirect(_siguiente(request))
    else:
        form = PasswordChangeForm(request.user)
    for campo in form.fields.values():
        campo.widget.attrs["autocomplete"] = "new-password"
    form.fields["old_password"].label = "Clave actual (o la temporal que te dieron)"
    form.fields["new_password1"].label = "Clave nueva"
    form.fields["new_password2"].label = "Repetí la clave nueva"
    return render(request, "registration/cambiar_clave.html", {
        "form": form, "obligatorio": cuenta.debe_cambiar_clave, "next": request.GET.get("next", "")})


@login_required
def privacidad(request):
    cuenta = CuentaUsuario.de(request.user)
    if request.method == "POST" and request.POST.get("acepto"):
        cuenta.acepto_privacidad = timezone.now()
        cuenta.save(update_fields=["acepto_privacidad"])
        return redirect(_siguiente(request))
    return render(request, "registration/privacidad.html", {"cuenta": cuenta, "next": request.GET.get("next", "")})
