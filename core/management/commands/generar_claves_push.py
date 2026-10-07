"""Genera el par de claves VAPID para notificaciones push y las muestra para copiar al .env."""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Command(BaseCommand):
    help = "Genera claves VAPID (notificaciones push). Copiar las líneas al archivo .env."

    def handle(self, *args, **opts):
        clave = ec.generate_private_key(ec.SECP256R1())
        privada = b64(clave.private_numbers().private_value.to_bytes(32, "big"))
        publica = b64(clave.public_key().public_bytes(serialization.Encoding.X962,
                                                      serialization.PublicFormat.UncompressedPoint))
        self.stdout.write(f"VAPID_PUBLIC_KEY={publica}\nVAPID_PRIVATE_KEY={privada}\nVAPID_EMAIL=admin@empresa.com")
