"""Regresiones de la revisión funcional y técnica del 12/10/2026 (hallazgos H01–H10).

Cada test reproduce el escenario descripto en la revisión (ver docs/PLAN_CORRECCIONES.md).
"""
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from .test_negocio import HOY, persona

MEDIA_TMP = tempfile.mkdtemp(prefix="virguel-test-media-")


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class ArchivosPrivadosTests(TestCase):
    """H01: los archivos subidos sólo se entregan a quien puede ver el registro."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TMP, ignore_errors=True)

    def setUp(self):
        from finanzas.models import CategoriaEgreso, Egreso, Liquidacion
        from personal.models import DocumentoPersonal, Novedad, TipoDocumento
        self.ger = User.objects.create_user("ger", password="x")
        self.ger.groups.add(Group.objects.create(name="Gerencia"))
        self.cont = User.objects.create_user("cont", password="x")
        self.cont.groups.add(Group.objects.create(name="Contabilidad"))
        self.sup = persona("S1", rol="supervisor", usuario=User.objects.create_user("sup", password="x"))
        self.sup2 = persona("S2", rol="supervisor", usuario=User.objects.create_user("sup2", password="x"))
        self.t1 = persona("T1", supervisor=self.sup, usuario=User.objects.create_user("t1", password="x"))
        self.t2 = persona("T2", supervisor=self.sup2, usuario=User.objects.create_user("t2", password="x"))

        self.novedad = Novedad.objects.create(persona=self.t1, tipo="enfermedad")
        self.novedad.certificado.save("cert.pdf", ContentFile(b"%PDF certificado"))
        self.doc = DocumentoPersonal.objects.create(persona=self.t1, tipo=TipoDocumento.objects.create(nombre="Apto"))
        self.doc.archivo.save("apto.pdf", ContentFile(b"%PDF apto"))
        self.liq = Liquidacion.objects.create(persona=self.t1, periodo=HOY.replace(day=1))
        self.liq.recibo.save("recibo.pdf", ContentFile(b"%PDF recibo"))
        self.egreso = Egreso.objects.create(fecha=HOY, monto=Decimal("10"), descripcion="x",
                                            categoria=CategoriaEgreso.objects.get_or_create(
                                                codigo="otros", defaults={"nombre": "Otros"})[0])
        self.egreso.comprobante.save("factura.pdf", ContentFile(b"%PDF factura"))

    def url(self, campo):
        return "/" + "media/" + campo.name

    def estado(self, user, campo):
        self.client.logout()
        if user is not None:
            self.client.force_login(user)
        return self.client.get(self.url(campo)).status_code

    def test_sin_sesion_no_se_entrega_nada(self):
        for campo in (self.novedad.certificado, self.doc.archivo, self.liq.recibo, self.egreso.comprobante):
            r = self.client.get(self.url(campo))
            self.assertEqual(r.status_code, 302, campo.name)
            self.assertIn("/login/", r["Location"])

    def test_certificado_y_legajo_solo_propio_supervisor_y_gerencia(self):
        for campo in (self.novedad.certificado, self.doc.archivo):
            self.assertEqual(self.estado(self.t1.usuario, campo), 200)
            self.assertEqual(self.estado(self.sup.usuario, campo), 200)
            self.assertEqual(self.estado(self.ger, campo), 200)
            self.assertEqual(self.estado(self.t2.usuario, campo), 404)    # otro técnico
            self.assertEqual(self.estado(self.sup2.usuario, campo), 404)  # supervisor de otro equipo
            self.assertEqual(self.estado(self.cont, campo), 404)

    def test_recibo_no_lo_ve_el_supervisor(self):
        self.assertEqual(self.estado(self.t1.usuario, self.liq.recibo), 200)
        self.assertEqual(self.estado(self.cont, self.liq.recibo), 200)
        self.assertEqual(self.estado(self.sup.usuario, self.liq.recibo), 404)
        self.assertEqual(self.estado(self.t2.usuario, self.liq.recibo), 404)

    def test_comprobante_de_egreso_solo_finanzas(self):
        self.assertEqual(self.estado(self.cont, self.egreso.comprobante), 200)
        self.assertEqual(self.estado(self.ger, self.egreso.comprobante), 200)
        self.assertEqual(self.estado(self.t1.usuario, self.egreso.comprobante), 404)

    def test_respuesta_privada_y_sin_cache(self):
        self.client.force_login(self.t1.usuario)
        r = self.client.get(self.url(self.novedad.certificado))
        self.assertEqual(b"".join(r.streaming_content), b"%PDF certificado")
        self.assertIn("no-store", r["Cache-Control"])

    def test_archivo_html_se_descarga_no_se_muestra(self):
        self.novedad.certificado.save("pagina.html", ContentFile(b"<script>alert(1)</script>"))
        self.client.force_login(self.t1.usuario)
        r = self.client.get(self.url(self.novedad.certificado))
        self.assertTrue(r["Content-Disposition"].startswith("attachment"))

    def test_ruta_inexistente_o_fuera_de_carpetas_conocidas(self):
        self.client.force_login(self.ger)
        self.assertEqual(self.client.get("/media/legajos/no-existe.pdf").status_code, 404)
        self.assertEqual(self.client.get("/media/../config/settings.py").status_code, 404)
        self.assertEqual(self.client.get("/media/mails/parte.eml").status_code, 404)


class ImportacionOrdenesTests(TestCase):
    """H05: reimportar no reabre órdenes cerradas ni duplica stock; la reapertura es explícita."""

    def setUp(self):
        from operaciones.models import TipoTarea
        self.ger = User.objects.create_user("ger", password="x")
        self.ger.groups.add(Group.objects.create(name="Gerencia"))
        self.client.force_login(self.ger)
        self.tec = persona("T1")
        TipoTarea.objects.create(codigo="INST", nombre="Instalación")

    def subir(self, tipo, contenido):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post("/tablero/importar/", {"tipo": tipo, "archivo": SimpleUploadedFile(
            "datos.csv", contenido.encode("utf-8"), content_type="text/csv")})

    ORDEN = "numero;codigo_tipo_tarea;fecha_programada;legajo_tecnico\nOT1;INST;{f};T1\n"

    def test_reimportar_orden_completada_no_la_reabre(self):
        from operaciones.models import OrdenTrabajo
        from tablero.models import ConflictoImportacion, Importacion
        self.subir("ordenes", self.ORDEN.format(f=f"{HOY:%d/%m/%Y}"))
        OrdenTrabajo.objects.filter(numero="OT1").update(estado="completada", fecha_ejecucion=HOY)
        r = self.subir("ordenes", self.ORDEN.format(f=f"{HOY + timedelta(days=3):%d/%m/%Y}"))
        self.assertEqual(r.status_code, 200)  # se muestra el resultado con conflictos
        ot = OrdenTrabajo.objects.get(numero="OT1")
        self.assertEqual((ot.estado, ot.fecha_ejecucion, ot.fecha_programada), ("completada", HOY, HOY))
        c = ConflictoImportacion.objects.get()
        self.assertEqual((c.clave, c.campo), ("OT1", "fecha_programada"))
        self.assertEqual(Importacion.objects.count(), 2)
        self.assertEqual(Importacion.objects.first().omitidos, 1)

    def test_reimportar_orden_abierta_actualiza_planificacion(self):
        from operaciones.models import OrdenTrabajo
        self.subir("ordenes", self.ORDEN.format(f=f"{HOY:%d/%m/%Y}"))
        self.subir("ordenes", self.ORDEN.format(f=f"{HOY + timedelta(days=3):%d/%m/%Y}"))
        ot = OrdenTrabajo.objects.get(numero="OT1")
        self.assertEqual((ot.estado, ot.fecha_programada), ("asignada", HOY + timedelta(days=3)))

    def test_reimportar_el_mismo_stock_no_duplica_lotes_ni_egresos(self):
        from finanzas.models import Egreso
        from inventario.models import LoteIngreso, Material
        Material.objects.create(codigo="A", nombre="Cable", costo_unitario=Decimal("10"))
        archivo = "codigo_material;fecha_ingreso;cantidad;costo_unitario;remito\nA;01/08/2026;100;10;R-1\n"
        self.subir("stock", archivo)
        self.subir("stock", archivo)
        self.assertEqual(LoteIngreso.objects.count(), 1)
        self.assertEqual(Egreso.objects.count(), 1)

    def test_reabrir_es_explicito_y_queda_registrado(self):
        from operaciones.models import NotaOrden, OrdenTrabajo
        self.subir("ordenes", self.ORDEN.format(f=f"{HOY:%d/%m/%Y}"))
        OrdenTrabajo.objects.filter(numero="OT1").update(estado="completada", fecha_ejecucion=HOY)
        r = self.client.post("/tablero/ordenes/OT1/reabrir/", {"motivo": ""})
        self.assertEqual(OrdenTrabajo.objects.get(numero="OT1").estado, "completada")  # sin motivo, no
        r = self.client.post("/tablero/ordenes/OT1/reabrir/", {"motivo": "Claro la rechazó"})
        self.assertEqual(r.status_code, 302)
        ot = OrdenTrabajo.objects.get(numero="OT1")
        self.assertEqual((ot.estado, ot.fecha_ejecucion), ("asignada", None))
        nota = NotaOrden.objects.get(orden=ot, tipo="correccion")
        self.assertIn("Claro la rechazó", nota.texto)
        self.assertIn("Completada", nota.texto)

    def test_supervisor_no_puede_reabrir(self):
        from operaciones.models import OrdenTrabajo
        self.subir("ordenes", self.ORDEN.format(f=f"{HOY:%d/%m/%Y}"))
        OrdenTrabajo.objects.filter(numero="OT1").update(estado="completada")
        sup = persona("S1", rol="supervisor", usuario=User.objects.create_user("sup", password="x"))
        self.client.force_login(sup.usuario)
        self.client.post("/tablero/ordenes/OT1/reabrir/", {"motivo": "x"})
        self.assertEqual(OrdenTrabajo.objects.get(numero="OT1").estado, "completada")


class SincronizacionOfflineTests(TestCase):
    """H06: un envío sin señal sólo se da por aceptado con confirmación explícita, y no se duplica."""

    def setUp(self):
        import uuid

        from operaciones.models import OrdenTrabajo, TipoTarea
        self.uuid = uuid
        self.sup = persona("S1", rol="supervisor")
        self.tec = persona("T1", supervisor=self.sup, usuario=User.objects.create_user("tec", password="x"))
        tipo = TipoTarea.objects.create(codigo="R", nombre="Rep")
        self.ot = OrdenTrabajo.objects.create(numero="1", tipo=tipo, tecnico=self.tec, estado="asignada")
        self.client.force_login(self.tec.usuario)
        self.url = f"/app/orden/{self.ot.id}/notas/"

    def enviar(self, datos, sync=True):
        extra = {"HTTP_X_VIRGUEL_SYNC": "1"} if sync else {}
        return self.client.post(self.url, datos, **extra)

    def test_envio_aceptado_confirma_y_no_se_duplica(self):
        ident = str(self.uuid.uuid4())
        r = self.enviar({"texto": "Llegué", "_id_operacion": ident})
        self.assertEqual(r.json(), {"ok": True})
        r = self.enviar({"texto": "Llegué", "_id_operacion": ident})
        self.assertEqual(r.json()["ok"], True)
        self.assertEqual(self.ot.notas.count(), 1)

    def test_respuesta_perdida_y_reintento_no_duplica(self):
        ident = str(self.uuid.uuid4())
        self.enviar({"texto": "Nota", "_id_operacion": ident}, sync=False)  # online: el celular no vio la respuesta
        r = self.enviar({"texto": "Nota", "_id_operacion": ident})           # la sincronización lo reintenta
        self.assertTrue(r.json()["ok"])
        self.assertEqual(self.ot.notas.count(), 1)

    def test_formulario_con_errores_no_se_confirma(self):
        r = self.enviar({"texto": "", "_id_operacion": str(self.uuid.uuid4())})
        j = r.json()
        self.assertFalse(j["ok"])
        self.assertIn("<form", j["html"])
        self.assertEqual(self.ot.notas.count(), 0)

    def test_error_por_mensaje_y_redireccion_no_se_confirma(self):
        from core.models import OperacionOffline
        self.ot.estado = "completada"
        self.ot.save()
        # Cierre de una orden ya cerrada: la vista redirige con un aviso, no aplica nada.
        r = self.client.post(f"/app/orden/{self.ot.id}/cierre/", {"resultado": "completada",
                                                                  "_id_operacion": str(self.uuid.uuid4())},
                             HTTP_X_VIRGUEL_SYNC="1")
        self.assertEqual(r.json()["ok"], False)
        self.assertIn("ya estaba cerrada", r.json()["mensaje"])
        self.assertFalse(OperacionOffline.objects.exists())

    def test_envio_de_otro_usuario_se_rechaza(self):
        ident = str(self.uuid.uuid4())
        self.enviar({"texto": "Mía", "_id_operacion": ident})
        otro = persona("T2", supervisor=self.sup, usuario=User.objects.create_user("t2", password="x"))
        self.client.force_login(otro.usuario)
        r = self.enviar({"texto": "Mía", "_id_operacion": ident})
        self.assertEqual(r.status_code, 409)

    def test_sin_sesion_va_al_login_y_el_celular_lo_conserva(self):
        self.client.logout()
        r = self.enviar({"texto": "x", "_id_operacion": str(self.uuid.uuid4())})
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login/", r["Location"])

    def test_el_script_solo_borra_con_confirmacion(self):
        from pathlib import Path

        from django.conf import settings
        js = (Path(settings.BASE_DIR) / "static/js/offline.js").read_text()
        self.assertIn("j.ok === true", js)
        self.assertIn('"X-Virguel-Sync": "1"', js)
