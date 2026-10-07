"""Avisos automáticos al técnico cuando pasa algo que le concierne."""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from operaciones.models import OrdenTrabajo
from supervision.models import AccionCorrectiva, InformeControl

from .notificaciones import notificar


@receiver(pre_save, sender=OrdenTrabajo)
def _guardar_tecnico_anterior(sender, instance, **kwargs):
    instance._tecnico_anterior = (OrdenTrabajo.objects.filter(pk=instance.pk).values_list("tecnico_id", flat=True)
                                  .first() if instance.pk else None)


@receiver(post_save, sender=OrdenTrabajo)
def _orden_asignada(sender, instance, created, raw=False, **kwargs):
    if raw or getattr(instance, "_sin_notificar", False) or not instance.tecnico_id:
        return
    if instance.tecnico_id != getattr(instance, "_tecnico_anterior", None) and instance.estado in ("asignada", "pendiente") \
            and instance.fecha_programada >= timezone.localdate():
        notificar(instance.tecnico, f"Nueva orden {instance.numero}",
                  f"{instance.tipo} para el {instance.fecha_programada:%d/%m}", f"/app/orden/{instance.pk}/")


@receiver(post_save, sender=AccionCorrectiva)
def _accion_aplicada(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        notificar(instance.tecnico, f"Se registró: {instance.get_tipo_display()}",
                  instance.descripcion[:200], "/app/legajo/")


@receiver(post_save, sender=InformeControl)
def _control_recibido(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        notificar(instance.tecnico, f"Control de tu supervisor: {instance.puntaje}/5",
                  ("Detectó un desvío. " if instance.desvio_detectado else "") + instance.get_tipo_display(),
                  "/app/legajo/")


@receiver(pre_save, sender="core.Persona")
def _baja_de_acceso_al_egresar(sender, instance, raw=False, **kwargs):
    """Si la persona egresa o se desactiva, su acceso al sistema se da de baja automáticamente."""
    if raw or not instance.usuario_id:
        return
    if (not instance.activo or instance.fecha_egreso) and instance.usuario.is_active:
        instance.usuario.is_active = False
        instance.usuario.save(update_fields=["is_active"])
        from .models import RegistroAcceso
        RegistroAcceso.objects.create(usuario=instance.usuario, usuario_ingresado=instance.usuario.username,
                                      evento=RegistroAcceso.Evento.ADMIN, detalle="Baja automática por egreso")
