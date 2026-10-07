"""Notificaciones a las personas: campanita en la app + Web Push al celular (si autorizó).

Para Web Push hacen falta claves VAPID en .env (VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY,
VAPID_EMAIL); se generan con `manage.py generar_claves_push`. Sin claves, las
notificaciones igual quedan en la campanita de la app.
"""
import json
import logging
import os

from .models import Notificacion, SuscripcionPush

log = logging.getLogger(__name__)


def push_configurado() -> bool:
    return bool(os.environ.get("VAPID_PUBLIC_KEY") and os.environ.get("VAPID_PRIVATE_KEY"))


def notificar(persona, titulo: str, texto: str = "", url: str = "/app/") -> Notificacion | None:
    if persona is None:
        return None
    n = Notificacion.objects.create(persona=persona, titulo=titulo[:120], texto=texto[:300], url=url)
    if push_configurado():
        _push(persona, {"titulo": n.titulo, "texto": n.texto, "url": n.url})
    return n


def _push(persona, datos: dict):
    from pywebpush import WebPushException, webpush
    for s in SuscripcionPush.objects.filter(persona=persona):
        try:
            webpush(subscription_info={"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                    data=json.dumps(datos), vapid_private_key=os.environ["VAPID_PRIVATE_KEY"],
                    vapid_claims={"sub": f"mailto:{os.environ.get('VAPID_EMAIL', 'admin@virguel.local')}"}, ttl=86400)
        except WebPushException as e:
            if e.response is not None and e.response.status_code in (404, 410):
                s.delete()  # el celular revocó el permiso o desinstaló la app
            else:
                log.warning("Fallo de Web Push a %s: %s", persona, e)
        except Exception as e:  # noqa: BLE001 — una notificación nunca debe romper la operación
            log.warning("Fallo de Web Push a %s: %s", persona, e)
