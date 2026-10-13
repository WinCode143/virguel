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


class DevolucionesTests(TestCase):
    """H02: una devolución conserva antigüedad y costo de origen y no es una compra."""

    def setUp(self):
        from inventario.models import LoteIngreso, Material
        self.m = Material.objects.create(codigo="DECO", nombre="Deco", costo_unitario=Decimal("100"))
        self.t = persona("T1")
        self.hace90 = HOY - timedelta(days=90)
        self.lote = LoteIngreso.objects.create(material=self.m, fecha=self.hace90, cantidad=10,
                                               costo_unitario=Decimal("100"))

    def total_egresos(self):
        from django.db.models import Sum

        from finanzas.models import Egreso
        return Egreso.objects.aggregate(t=Sum("monto"))["t"]

    def test_escenario_de_la_revision(self):
        from inventario.models import LoteIngreso
        from inventario.stock_tecnico import devolver, entregar, saldo
        self.assertEqual(self.total_egresos(), Decimal("1000"))
        entregar(self.t, self.m, 4)
        self.m.costo_unitario = Decimal("130")  # el precio actual cambió: no debe usarse
        self.m.save()
        devolver(self.t, self.m, 2)
        self.assertEqual(self.total_egresos(), Decimal("1000"))  # antes: 1.200
        dev = LoteIngreso.objects.get(origen="devolucion")
        self.assertEqual((dev.fecha, dev.costo_unitario, dev.cantidad, dev.lote_origen), (
            self.hace90, Decimal("100"), Decimal("2"), self.lote))
        self.assertEqual(saldo(self.t, self.m), 2)
        self.assertEqual(self.m.stock_actual, 8)

    def test_antiguedad_se_mantiene_en_el_control_de_lotes(self):
        from inventario.services import lotes_envejecidos
        from inventario.stock_tecnico import devolver, entregar
        entregar(self.t, self.m, 10)
        devolver(self.t, self.m, 3)
        filas = lotes_envejecidos()
        self.assertEqual([(f["dias"], f["lote"].cantidad_disponible) for f in filas], [(90, 3)])

    def test_devuelve_lo_mas_viejo_y_respeta_lotes_mezclados(self):
        from inventario.models import LoteIngreso
        from inventario.stock_tecnico import consumir, devolver, entregar
        LoteIngreso.objects.create(material=self.m, fecha=HOY - timedelta(days=5), cantidad=10,
                                   costo_unitario=Decimal("120"))
        entregar(self.t, self.m, 14)       # 10 del lote viejo + 4 del nuevo
        consumir(self.t, None, self.m, 9)  # consume 9 del viejo (FIFO)
        devolver(self.t, self.m, 3)        # 1 del viejo + 2 del nuevo
        devs = list(LoteIngreso.objects.filter(origen="devolucion").order_by("fecha").values_list(
            "fecha", "cantidad", "costo_unitario"))
        self.assertEqual(devs, [(self.hace90, Decimal("1"), Decimal("100")),
                                (HOY - timedelta(days=5), Decimal("2"), Decimal("120"))])

    def test_comprar_si_genera_egreso_y_finanzas_no_cuenta_devoluciones(self):
        from finanzas.views import compras
        from inventario.stock_tecnico import devolver, entregar
        entregar(self.t, self.m, 4)
        devolver(self.t, self.m, 4)
        self.assertEqual([lote.pk for lote in compras(self.hace90, HOY)], [self.lote.pk])

    def test_comando_corrige_egresos_de_devoluciones_anteriores(self):
        from io import StringIO

        from django.core.management import call_command

        from finanzas.models import Egreso, registrar_egreso_automatico
        from inventario.models import LoteIngreso
        viejo = LoteIngreso.objects.create(material=self.m, cantidad=2, costo_unitario=Decimal("100"),
                                           origen="devolucion", proveedor="Devolución T1")
        registrar_egreso_automatico(f"lote:{viejo.pk}", "compras-stock", HOY, 200, "Compra 2 u Deco")  # como antes
        out = StringIO()
        call_command("recalcular_devoluciones", stdout=out)
        self.assertTrue(Egreso.objects.filter(origen=f"lote:{viejo.pk}").exists())  # sin --aplicar no cambia
        call_command("recalcular_devoluciones", "--aplicar", stdout=out)
        self.assertFalse(Egreso.objects.filter(origen=f"lote:{viejo.pk}").exists())
        self.assertEqual(self.total_egresos(), Decimal("1000"))


class CustodiaHerramientasTests(TestCase):
    """Reasignar una herramienta es custodia: el gasto es la compra, una sola vez."""

    def test_reasignar_no_genera_gastos_repetidos(self):
        from finanzas.models import Egreso
        from herramientas.models import Asignacion, CompraElemento, Elemento
        taladro = Elemento.objects.create(codigo="TAL", nombre="Taladro", tipo="herramienta", costo=Decimal("500"))
        CompraElemento.objects.create(elemento=taladro, cantidad=1, costo_unitario=Decimal("500"))
        taladro.refresh_from_db()
        self.assertEqual(taladro.stock, 1)
        a = Asignacion.objects.create(persona=persona("T1"), elemento=taladro)
        taladro.refresh_from_db()
        self.assertEqual(taladro.stock, 0)
        a.estado = "devuelto"
        a.save()
        taladro.refresh_from_db()
        self.assertEqual(taladro.stock, 1)
        Asignacion.objects.create(persona=persona("T2"), elemento=taladro)
        Asignacion.objects.create(persona=persona("T3"), elemento=taladro, origen="reasignacion")
        self.assertEqual(Egreso.objects.count(), 1)
        self.assertEqual(Egreso.objects.get().monto, Decimal("500"))

    def test_compra_directa_para_una_persona_si_es_gasto(self):
        from finanzas.models import Egreso
        from herramientas.models import Asignacion, Elemento
        casco = Elemento.objects.create(codigo="CAS", nombre="Casco", costo=Decimal("80"))
        Asignacion.objects.create(persona=persona("T1"), elemento=casco, cantidad=2, origen="compra")
        self.assertEqual(Egreso.objects.get().monto, Decimal("160"))


class AtribucionNoResueltasTests(TestCase):
    """H03: una orden no resuelta por causa ajena (cliente ausente) no penaliza al técnico."""

    def setUp(self):
        from operaciones.models import Jornada, OrdenTrabajo, TipoTarea
        self.tipo = TipoTarea.objects.create(codigo="I", nombre="Inst", minutos_estandar=60)
        self.sup = persona("S1", rol="supervisor", usuario=User.objects.create_user("sup", password="x"))
        self.a = persona("TA", supervisor=self.sup)
        self.b = persona("TB", supervisor=self.sup)
        n = 0
        for t in (self.a, self.b):
            for d in range(12):
                f = HOY - timedelta(days=d + 1)
                Jornada.objects.create(tecnico=t, fecha=f, en_calle=True)
                n += 1
                OrdenTrabajo.objects.create(numero=f"OK{n}", tipo=self.tipo, tecnico=t, estado="completada",
                                            fecha_ejecucion=f, fecha_programada=f)
        for i in range(5):
            OrdenTrabajo.objects.create(numero=f"F{i}", tipo=self.tipo, tecnico=self.a, estado="fallida",
                                        motivo_no_resuelto="cliente_ausente", fecha_ejecucion=HOY - timedelta(days=1))

    def ev(self, t):
        from capacitacion.evaluacion import evaluar_tecnicos
        return {e.tecnico.legajo: e for e in evaluar_tecnicos(HOY, tecnicos=[self.a, self.b])}[t.legajo]

    def test_escenario_de_la_revision(self):
        # (la revisión usó 5 trabajos; acá 12 jornadas para superar el mínimo de evidencia)
        ea, eb = self.ev(self.a), self.ev(self.b)
        self.assertEqual(ea.score_calidad, eb.score_calidad)
        self.assertEqual(ea.score_calidad, 100)
        self.assertEqual((ea.fallidas, ea.no_resueltas_ajenas), (0, 5))
        self.assertEqual(ea.diagnostico, eb.diagnostico)

    def test_falta_material_queda_a_investigar_hasta_confirmar(self):
        from operaciones.models import OrdenTrabajo
        OrdenTrabajo.objects.filter(numero__startswith="F").update(motivo_no_resuelto="falta_material")
        ea = self.ev(self.a)
        self.assertEqual((ea.fallidas, ea.fallidas_a_investigar, ea.score_calidad), (0, 5, 100))
        # El supervisor confirma que dos fueron responsabilidad del técnico
        self.client.force_login(self.sup.usuario)
        for ot in OrdenTrabajo.objects.filter(numero__in=["F0", "F1"]):
            self.client.post("/app/no-resueltas/", {"orden": ot.id, "atribucion": "tecnico"})
        ea = self.ev(self.a)
        self.assertEqual((ea.fallidas, ea.fallidas_a_investigar), (2, 3))
        self.assertLess(ea.score_calidad, 100)

    def test_indicadores_usan_el_mismo_criterio(self):
        from operaciones.criterios import q_falla_tecnico
        from operaciones.models import OrdenTrabajo
        self.assertEqual(OrdenTrabajo.objects.filter(q_falla_tecnico()).count(), 0)
        OrdenTrabajo.objects.filter(numero="F0").update(atribucion_confirmada="tecnico")
        self.assertEqual(OrdenTrabajo.objects.filter(q_falla_tecnico()).count(), 1)

    def test_supervisor_no_confirma_ordenes_de_otro_equipo(self):
        from operaciones.models import OrdenTrabajo
        otro = persona("S2", rol="supervisor", usuario=User.objects.create_user("s2", password="x"))
        self.client.force_login(otro.usuario)
        ot = OrdenTrabajo.objects.get(numero="F0")
        r = self.client.post("/app/no-resueltas/", {"orden": ot.id, "atribucion": "tecnico"})
        self.assertEqual(r.status_code, 404)


class EfectividadAccionesTests(TestCase):
    """H04: una acción sólo es efectiva si se cumplió y los controles posteriores lo verifican."""

    def setUp(self):
        self.sup = persona("S1", rol="supervisor", usuario=User.objects.create_user("sup", password="x"))
        self.tecs = [persona(f"T{i}", supervisor=self.sup) for i in range(3)]

    def accion(self, t, dias, **kw):
        from supervision.models import AccionCorrectiva
        return AccionCorrectiva.objects.create(tecnico=t, tipo="apercibimiento", fecha=HOY - timedelta(days=dias),
                                               aplicada_por=self.sup, **kw)

    def control(self, t, dias, desvio=False, tipo="calidad"):
        from supervision.models import InformeControl
        return InformeControl.objects.create(supervisor=self.sup, tecnico=t, fecha=HOY - timedelta(days=dias),
                                             puntaje=2 if desvio else 5, desvio_detectado=desvio, tipo=tipo)

    def efectividad(self):
        from tablero.metricas import tableros_supervisores
        return tableros_supervisores(hasta=HOY, supervisores=[self.sup])[0].get("efectividad_correccion").valor

    def test_escenario_de_la_revision_sin_cumplir_ni_controlar_no_es_100(self):
        for t in self.tecs:
            self.accion(t, 40)
        self.assertIsNone(self.efectividad())

    def test_cumplidas_sin_controles_quedan_no_verificadas(self):
        from supervision.efectividad import NO_VERIFICADA, clasificar
        a = [self.accion(t, 40, cumplida=True) for t in self.tecs]
        self.assertEqual({clasificar(x, HOY) for x in a}, {NO_VERIFICADA})
        self.assertIsNone(self.efectividad())

    def test_cumplidas_y_verificadas(self):
        from supervision.efectividad import EFECTIVA, NO_EFECTIVA, clasificar
        acciones = []
        for i, t in enumerate(self.tecs):
            acciones.append(self.accion(t, 45, cumplida=True))
            self.control(t, 40)
            self.control(t, 35, desvio=(i == 0))  # el primero repite el desvío
        self.assertEqual([clasificar(a, HOY) for a in acciones], [NO_EFECTIVA, EFECTIVA, EFECTIVA])
        self.assertAlmostEqual(self.efectividad(), 200 / 3)

    def test_recurrencia_se_mide_sobre_el_mismo_problema(self):
        from supervision.efectividad import EFECTIVA, clasificar
        t = self.tecs[0]
        origen = self.control(t, 50, desvio=True, tipo="seguridad")
        a = self.accion(t, 45, cumplida=True, informe=origen)
        self.control(t, 40, tipo="seguridad")
        self.control(t, 38, tipo="seguridad")
        self.control(t, 36, desvio=True, tipo="vehiculo")  # otro problema
        self.assertEqual(clasificar(a, HOY), EFECTIVA)

    def test_supervisor_marca_cumplida_desde_la_app(self):
        a = self.accion(self.tecs[0], 3)
        self.client.force_login(self.sup.usuario)
        self.client.post(f"/app/accion/{a.id}/cumplida/")
        a.refresh_from_db()
        self.assertTrue(a.cumplida)
        self.assertEqual(a.fecha_cumplida, HOY)


class EvidenciaSuficienteTests(TestCase):
    """H09: sin datos suficientes no hay diagnóstico ni puntajes inventados."""

    def test_sin_jornadas_ni_ordenes_es_sin_evidencia(self):
        from capacitacion.evaluacion import Diagnostico, evaluar_tecnicos
        e = evaluar_tecnicos(HOY, tecnicos=[persona("T1")])[0]
        self.assertEqual(e.diagnostico, Diagnostico.SIN_EVIDENCIA)
        self.assertIsNone(e.riesgo)
        self.assertIsNone(e.score_productividad)

    def test_pantallas_y_exportacion_toleran_sin_evidencia(self):
        g = User.objects.create_user("ger", password="x")
        g.groups.add(Group.objects.create(name="Gerencia"))
        t = persona("T1")
        self.client.force_login(g)
        self.assertContains(self.client.get("/tablero/tecnicos/"), "Sin evidencia suficiente")
        self.assertEqual(self.client.get(f"/tablero/tecnicos/{t.id}/").status_code, 200)
        self.assertEqual(self.client.get("/api/powerbi/evaluacion_tecnicos.csv").status_code, 200)

    def test_recapacitacion_no_resta_y_se_guarda_la_version(self):
        from capacitacion.evaluacion import evaluar_tecnicos, guardar_historial
        from capacitacion.models import EvaluacionHistorica
        from operaciones.models import Jornada, OrdenTrabajo, TipoTarea
        from supervision.models import AccionCorrectiva
        tipo = TipoTarea.objects.create(codigo="I", nombre="I")
        t = persona("T1")
        for d in range(1, 21):
            f = HOY - timedelta(days=d)
            Jornada.objects.create(tecnico=t, fecha=f)
            OrdenTrabajo.objects.create(numero=f"o{d}", tipo=tipo, tecnico=t, estado="completada",
                                        fecha_ejecucion=f, fecha_programada=f)
        antes = evaluar_tecnicos(HOY, tecnicos=[t])[0].score_disciplina
        AccionCorrectiva.objects.create(tecnico=t, tipo="recapacitacion", fecha=HOY - timedelta(days=3))
        self.assertEqual(evaluar_tecnicos(HOY, tecnicos=[t])[0].score_disciplina, antes)
        guardar_historial(HOY)
        self.assertEqual(EvaluacionHistorica.objects.get(persona=t).criterio_version, 2)


class RetrospectivaTests(TestCase):
    def test_informa_por_diagnostico(self):
        from io import StringIO

        from django.core.management import call_command

        from capacitacion.models import EvaluacionHistorica
        t = persona("T1")
        t.fecha_egreso = HOY - timedelta(days=20)
        t.save()
        EvaluacionHistorica.objects.create(fecha=HOY - timedelta(days=100), persona=t, productividad=1,
                                           indice_productividad=1, score_productividad=50, score_calidad=50,
                                           score_disciplina=50, score_seguridad=50, riesgo=60,
                                           diagnostico="Requiere revisión del supervisor (riesgo alto)",
                                           criterio_version=2)
        out = StringIO()
        call_command("evaluacion_retrospectiva", "--horizonte", "90", stdout=out)
        self.assertIn("100%", out.getvalue())
