"""Sincronización de la app de campo sin señal (ver static/js/offline.js).

Los formularios con [data-offline] mandan `_id_operacion` (un UUID por envío):

* Si ese envío ya fue aceptado, no se vuelve a aplicar (evita fichadas, cierres o
  consumos duplicados cuando la respuesta se perdió y el celular reintenta).
* La operación y el registro de su aceptación se confirman en UNA transacción: si la vista falla
  o no acepta los datos, no queda ni el cambio ni la marca (no hay "guardado sin aceptación").
  Vale igual para el envío inicial (directo, sin cabecera) y para el reintento sincronizado.
* El mismo identificador con contenido distinto es un conflicto (409), no una repetición.
* Dos envíos concurrentes del mismo identificador tienen un único efecto (clave única).
* Cuando el envío viene de la sincronización automática (cabecera X-Virguel-Sync),
  la respuesta es JSON y explícita: `{"ok": true}` sólo si el servidor aceptó la
  operación; si el formulario tuvo errores, `{"ok": false, "mensaje": ..., "html": ...}`
  para que el técnico lo corrija. El celular borra el pendiente únicamente con ok=true.
"""
import hashlib
import uuid

from django.conf import settings
from django.contrib.messages import ERROR
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import resolve_url

from .models import OperacionOffline


def _id(request):
    try:
        return uuid.UUID(request.POST.get("_id_operacion", ""))
    except ValueError:
        return None


def _huella(request) -> str:
    """Contenido del envío (sin el token CSRF, que cambia entre sesiones), incluidos los BYTES de cada
    archivo: dos fotos distintas con igual nombre y tamaño no son la misma operación."""
    h = hashlib.sha256(request.path.encode())
    for k in sorted(request.POST):
        if k == "csrfmiddlewaretoken":
            continue
        for v in request.POST.getlist(k):
            h.update(f"{k}={v}\n".encode())
    for k in sorted(request.FILES):
        for f in request.FILES.getlist(k):
            h.update(f"{k}:{f.name}:{f.size}\n".encode())
            pos = f.tell()
            f.seek(0)
            for trozo in f.chunks():
                h.update(trozo)
            f.seek(pos)  # la vista lee el archivo desde donde estaba
    return h.hexdigest()


def _es_login(resp):
    destino = resp.get("Location", "")
    return destino.startswith(resolve_url(settings.LOGIN_URL))


def _errores_en_mensajes(request):
    """Mensajes de error que la vista dejó (p. ej. "no tenés stock") aunque haya redirigido."""
    almacen = getattr(request, "_messages", None)
    cola = getattr(almacen, "_queued_messages", []) if almacen is not None else []
    return [str(m) for m in cola if m.level >= ERROR]


class SincronizacionOfflineMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method != "POST" or not request.user.is_authenticated:
            return self.get_response(request)
        ident = _id(request)
        if ident is None:
            return self.get_response(request)
        es_sync = request.headers.get("X-Virguel-Sync") == "1"
        huella = _huella(request)
        with transaction.atomic():
            op, creada = OperacionOffline.objects.get_or_create(id_operacion=ident, defaults={
                "usuario": request.user, "ruta": request.path[:200], "huella": huella})
            if not creada:
                if op.usuario_id != request.user.pk:
                    return JsonResponse({"ok": False, "mensaje": "Envío de otro usuario."}, status=409)
                if op.huella and op.huella != huella:
                    return JsonResponse({"ok": False, "conflicto": True,
                                         "mensaje": "Ese envío ya se registró con otros datos: revisar antes de "
                                                    "volver a mandarlo."}, status=409)
                # Ya aplicado: no se repite.
                return JsonResponse({"ok": True, "repetido": True}) if es_sync else self._a_inicio()

            resp = self.get_response(request)

            aceptado = resp.status_code in (301, 302, 303) and not _es_login(resp)
            errores = _errores_en_mensajes(request) if aceptado else []
            if aceptado and not errores:
                return JsonResponse({"ok": True}) if es_sync else resp
            # No aceptado: ni la marca ni ningún cambio parcial, haya o no cabecera de sincronización.
            transaction.set_rollback(True)
        if errores and es_sync:
            return JsonResponse({"ok": False, "mensaje": " ".join(errores)})
        if es_sync and resp.status_code == 200 and "text/html" in resp.get("Content-Type", ""):
            # La vista volvió a mostrar el formulario: hubo errores de validación.
            return JsonResponse({"ok": False, "mensaje": "El servidor no aceptó los datos: revisar el formulario.",
                                 "html": resp.content.decode(resp.charset or "utf-8", errors="replace")})
        return resp  # login, 403, 4xx y 5xx: el celular decide (conservar / reintentar / marcar error)

    @staticmethod
    def _a_inicio():
        from django.shortcuts import redirect
        return redirect("movil:inicio")
