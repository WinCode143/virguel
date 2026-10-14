"""Entrega de archivos subidos (certificados, legajos, recibos, firmas, fotos, comprobantes).

Ningún archivo de `media/` se sirve directamente: cada pedido pasa por Django, que
busca a qué registro pertenece el archivo y aplica las mismas reglas de rol que las
pantallas. Un nombre difícil de adivinar no sustituye la autorización.

* gerencia ve todo;
* contabilidad, lo de finanzas (comprobantes, recibos, gastos de campo);
* el supervisor, lo de su equipo y lo propio;
* el técnico (o cualquier empleado), sólo lo propio.
"""
import mimetypes

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.views.decorators.http import require_GET

from .roles import CONTABILIDAD, GERENCIA, SUPERVISOR, persona_de, rol_de


def _de_su_equipo(yo, persona_id) -> bool:
    """La persona es `yo` o alguien a cargo de `yo` (supervisor)."""
    if yo is None or persona_id is None:
        return False
    if persona_id == yo.pk:
        return True
    return yo.rol == "supervisor" and yo.a_cargo.filter(pk=persona_id).exists()


def _personal(rol, yo, persona_id):
    return rol == GERENCIA or _de_su_equipo(yo, persona_id)


def _novedad(rol, yo, obj):
    return _personal(rol, yo, obj.persona_id)


def _documento(rol, yo, obj):
    return _personal(rol, yo, obj.persona_id)


def _recibo(rol, yo, obj):
    # El sueldo no lo ve el supervisor: sólo gerencia, contabilidad y el propio empleado.
    return rol in (GERENCIA, CONTABILIDAD) or (yo is not None and obj.persona_id == yo.pk)


def _egreso(rol, yo, obj):
    return rol in (GERENCIA, CONTABILIDAD)


def _gasto(rol, yo, obj):
    return rol in (GERENCIA, CONTABILIDAD) or _de_su_equipo(yo, obj.tecnico_id)


def _orden(rol, yo, obj):
    return _personal(rol, yo, obj.tecnico_id)


def _visita(rol, yo, obj):
    return _personal(rol, yo, obj.tecnico_id)


def _reporte(rol, yo, obj):
    return _personal(rol, yo, obj.asignacion.persona_id)


def _informe(rol, yo, obj):
    if rol == GERENCIA:
        return True
    return rol == SUPERVISOR and yo is not None and (obj.supervisor_id == yo.pk or _de_su_equipo(yo, obj.tecnico_id))


def _reglas():
    from finanzas.models import Egreso, Liquidacion
    from operaciones.models import GastoOrden, Intento, OrdenTrabajo
    from personal.models import DocumentoPersonal, Novedad
    from herramientas.models import ReporteCondicion
    from supervision.models import InformeControl
    # carpeta (upload_to) -> [(modelo, campo, permiso)]
    return {
        "certificados": [(Novedad, "certificado", _novedad)],
        "legajos": [(DocumentoPersonal, "archivo", _documento)],
        "recibos": [(Liquidacion, "recibo", _recibo)],
        "egresos": [(Egreso, "comprobante", _egreso)],
        "gastos": [(GastoOrden, "comprobante", _gasto)],
        "ordenes": [(OrdenTrabajo, "foto_trabajo", _orden), (Intento, "foto", _visita)],
        "firmas": [(OrdenTrabajo, "firma", _orden), (Intento, "firma", _visita)],
        "informes": [(InformeControl, "foto", _informe), (ReporteCondicion, "foto", _reporte)],
    }


def puede_ver(user, ruta: str):
    """Devuelve el FieldFile si `user` puede ver el archivo `ruta`; si no, None."""
    rol = rol_de(user)
    if rol is None:
        return None
    carpeta = ruta.split("/", 1)[0]
    if carpeta == "mails":  # copias de los mails del parte diario (sólo sin servidor de correo)
        return None
    yo = persona_de(user)
    for modelo, campo, permiso in _reglas().get(carpeta, []):
        # Puede verlo si puede ver alguno de los registros que usan ese archivo
        for obj in modelo.objects.filter(**{campo: ruta})[:50]:
            if permiso(rol, yo, obj):
                archivo = getattr(obj, campo)
                if isinstance(archivo, str):  # referencia guardada como texto (instantánea de una visita)
                    from django.db.models.fields.files import FieldFile

                    from operaciones.models import OrdenTrabajo
                    return FieldFile(None, OrdenTrabajo._meta.get_field("foto_trabajo"), archivo) if archivo else None
                return archivo
    return None


@require_GET
@login_required
def servir(request, ruta):
    archivo = puede_ver(request.user, ruta)
    if archivo is None:
        # 404 tanto si no existe como si no tiene permiso: no se revela qué archivos hay.
        raise Http404
    try:
        fh = archivo.open("rb")
    except FileNotFoundError:
        raise Http404
    tipo = mimetypes.guess_type(ruta)[0] or "application/octet-stream"
    # Imágenes y PDF se ven en el navegador; cualquier otra cosa (HTML, SVG...) se descarga,
    # para que un archivo subido no pueda ejecutar código dentro del sitio.
    en_linea = tipo == "application/pdf" or (tipo.startswith("image/") and tipo != "image/svg+xml")
    resp = FileResponse(fh, content_type=tipo, as_attachment=not en_linea,
                        filename=ruta.rsplit("/", 1)[-1])
    resp["Cache-Control"] = "private, no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp
