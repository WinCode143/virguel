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
