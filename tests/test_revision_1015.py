"""Escenarios de la revisión del 15/10/2026 (H01–H11): U01–U15 deben dar el resultado esperado y los
controles K01–K02 deben seguir correctos. Cada test nombra su escenario."""
import json
import threading
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.http import HttpResponseRedirect, HttpResponseServerError
from django.test import RequestFactory, TestCase, TransactionTestCase

from .test_negocio import HOY, persona


def _material(codigo="MOD", nombre="Módem"):
    from inventario.models import Material
    return Material.objects.create(codigo=codigo, nombre=nombre, costo_unitario=Decimal("100"))


def _lote(material, cantidad):
    from inventario.models import LoteIngreso
    return LoteIngreso.objects.create(material=material, cantidad=cantidad, origen="apertura")


def _stock(material):
    from django.db.models import Sum

    from inventario.models import LoteIngreso
    return LoteIngreso.objects.filter(material=material).aggregate(t=Sum("cantidad_disponible"))["t"] or 0


class ReservasTests(TestCase):
    """H02 (U01–U03): la reserva gobierna entrega, entregas parciales y cierres sin consumo."""

    def setUp(self):
        from inventario.models import RecetaMaterial
        from operaciones.models import OrdenTrabajo, TipoTarea
        self.m = _material()
        self.tipo = TipoTarea.objects.create(codigo="INS", nombre="Instalación")
        RecetaMaterial.objects.create(tipo_tarea=self.tipo, material=self.m, cantidad=1)
        self.ta = persona("TA", usuario=User.objects.create_user("ta", password="x"))
        self.tb = persona("TB")
        self.a = OrdenTrabajo.objects.create(numero="A", tipo=self.tipo, tecnico=self.ta, estado="asignada",
                                             fecha_programada=HOY)
        self.b = OrdenTrabajo.objects.create(numero="B", tipo=self.tipo, tecnico=self.tb, estado="asignada",
                                             fecha_programada=HOY)

    def test_u01_lo_reservado_para_a_no_se_entrega_a_b(self):
        from inventario.reservas import ReservadoParaOtra, reasignar, reservar
        from inventario.services import prevision_materiales
        from inventario.stock_tecnico import entregar
        _lote(self.m, 1)
        r = reservar(self.a, self.m, 1)
        with self.assertRaises(ReservadoParaOtra):
            entregar(self.tb, self.m, 1, orden=self.b)
        with self.assertRaises(ReservadoParaOtra):
            entregar(self.tb, self.m, 1)  # tampoco una entrega suelta
        with self.assertRaises(ReservadoParaOtra):
            entregar(self.tb, self.m, 1, permitir_negativo=True)
        self.assertEqual(_stock(self.m), 1)
        f = prevision_materiales(HOY, HOY + timedelta(days=13))[0]
        self.assertEqual((f["necesario"], f["faltante"]), (1, 1))  # A cubierta por su reserva; B falta
        # sólo con una reasignación explícita
        reasignar(r, self.b, "A se reprogramó")
        entregar(self.tb, self.m, 1, orden=self.b)
        self.assertEqual(_stock(self.m), 0)

    def test_u02_entrega_parcial_deja_pendiente(self):
        from inventario.models import ReservaMaterial
        from inventario.reservas import reservar
        from inventario.stock_tecnico import entregar
        _lote(self.m, 2)
        reservar(self.a, self.m, 2)
        entregar(self.ta, self.m, 1, orden=self.a)
        r = ReservaMaterial.objects.get()
        self.assertEqual((r.estado, r.cantidad_entregada, r.pendiente), ("activa", 1, 1))
        with self.assertRaises(ValidationError):
            reservar(self.b, self.m, 1)  # la unidad restante sigue comprometida para A
        entregar(self.ta, self.m, 1, orden=self.a)
        r.refresh_from_db()
        self.assertEqual((r.estado, r.pendiente), ("consumida", 0))

    def test_u03_reprogramar_no_consume_la_reserva(self):
        from inventario.models import ReservaMaterial, Salida
        from inventario.reservas import reservar
        _lote(self.m, 1)
        reservar(self.a, self.m, 1)
        self.client.force_login(self.ta.usuario)
        self.client.post(f"/app/orden/{self.a.id}/cierre/", {"resultado": "reprogramada",
                                                              "motivo_no_resuelto": "cliente_ausente"})
        r = ReservaMaterial.objects.get()
        self.assertEqual((r.estado, r.cantidad_entregada), ("activa", 0))
        self.assertFalse(Salida.objects.filter(motivo="consumo").exists())
        self.assertEqual(_stock(self.m), 1)
        # completada (con material propio del técnico): lo no entregado se libera, sin consumo ficticio
        self.a.refresh_from_db()
        self.a.estado = "asignada"
        self.a.save()
        self.client.post(f"/app/orden/{self.a.id}/cierre/", {"resultado": "completada"})
        r.refresh_from_db()
        self.assertEqual(r.estado, "cancelada")
        self.assertFalse(Salida.objects.filter(motivo="consumo").exists())
        self.assertEqual(_stock(self.m), 1)


class EquiposYFechasTests(TestCase):
    """H03 (U04, U05) y H04 (U06)."""

    def setUp(self):
        from core.models import Cliente
        from inventario.models import RecetaMaterial
        from operaciones.models import OrdenTrabajo, TipoTarea
        self.m = _material()
        self.tipo = TipoTarea.objects.create(codigo="INS", nombre="Instalación")
        RecetaMaterial.objects.create(tipo_tarea=self.tipo, material=self.m, cantidad=1)
        self.t = persona("T1", usuario=User.objects.create_user("t", password="x"))
        self.ca = Cliente.objects.create(numero="CA", nombre="Cliente A")
        self.cb = Cliente.objects.create(numero="CB", nombre="Cliente B")
        self.OT = OrdenTrabajo

    def fila(self):
        from inventario.services import prevision_materiales
        return prevision_materiales(HOY, HOY + timedelta(days=13))[0]

    def test_u04_unidad_defectuosa_genera_faltante(self):
        from inventario.equipos import revisar
        from inventario.models import UnidadEquipo
        _lote(self.m, 1)
        u = UnidadEquipo.objects.create(material=self.m, numero_serie="SN1")  # la única unidad del lote
        self.OT.objects.create(numero="1", tipo=self.tipo, tecnico=self.t, estado="asignada", fecha_programada=HOY)
        self.assertEqual((self.fila()["deposito"], self.fila()["faltante"]), (1, 0))
        revisar(u, False)
        self.assertEqual((self.fila()["deposito"], self.fila()["faltante"]), (0, 1))
        # si vuelve a revisarse en condiciones, vuelve al suministro (una sola vez)
        revisar(UnidadEquipo.objects.get(), True)
        revisar(UnidadEquipo.objects.get(), True)
        self.assertEqual(self.fila()["faltante"], 0)
        self.assertEqual(_stock(self.m), 1)

    def test_u04_cambio_de_condicion_desde_el_administrador(self):
        from inventario.models import UnidadEquipo
        _lote(self.m, 1)
        u = UnidadEquipo.objects.create(material=self.m, numero_serie="SN1")
        u.condicion = "defectuoso"
        u.save()
        self.assertEqual(_stock(self.m), 0)

    def test_u05_serie_instalada_no_se_instala_en_otro_cliente(self):
        from inventario.equipos import mover
        from inventario.models import UnidadEquipo
        u = UnidadEquipo.objects.create(material=self.m, numero_serie="SN9", ubicacion="tecnico", custodio=self.t)
        mover(u, "cliente", cliente=self.ca, motivo="Instalada en A")
        ob = self.OT.objects.create(numero="B1", tipo=self.tipo, tecnico=self.t, cliente=self.cb, estado="asignada")
        self.client.force_login(self.t.usuario)
        r = self.client.post(f"/app/orden/{ob.id}/cierre/", {"resultado": "completada", "series_instaladas": "SN9"})
        self.assertContains(r, "figura instalada en el cliente")
        u.refresh_from_db()
        ob.refresh_from_db()
        self.assertEqual((u.cliente, ob.estado, ob.intentos.count()), (self.ca, "asignada", 0))
        # retirada en A (con su orden), recién entonces se puede instalar en B
        oa = self.OT.objects.create(numero="A1", tipo=self.tipo, tecnico=self.t, cliente=self.ca, estado="asignada")
        self.client.post(f"/app/orden/{oa.id}/cierre/", {"resultado": "completada", "series_retiradas": "SN9"})
        u.refresh_from_db()
        self.assertEqual(u.ubicacion, "tecnico")
        u.condicion = "usado_ok"
        u.save()
        self.client.post(f"/app/orden/{ob.id}/cierre/", {"resultado": "completada", "series_instaladas": "SN9"})
        u.refresh_from_db()
        self.assertEqual((u.ubicacion, u.cliente), ("cliente", self.cb))

    def test_u06_llegada_posterior_no_cubre_visita_anterior(self):
        from inventario.models import CompraEnCamino
        self.OT.objects.create(numero="1", tipo=self.tipo, tecnico=self.t, estado="asignada", fecha_programada=HOY)
        c = CompraEnCamino.objects.create(material=self.m, cantidad=1, fecha_esperada=HOY + timedelta(days=2))
        f = self.fila()
        self.assertEqual((f["faltante_inmediato"], f["llega_tarde"]), (1, 1))
        c.fecha_esperada = HOY
        c.save()
        self.assertEqual(self.fila()["faltante_inmediato"], 0)


class LiquidacionCeroTests(TestCase):
    """H05 (U07) y control K01."""

    def setUp(self):
        from core.models import Parametros
        from operaciones.models import OrdenTrabajo, TarifaClaro, TipoTarea
        self.mes = HOY.replace(day=1)
        tipo = TipoTarea.objects.create(codigo="FO", nombre="Fibra")
        TarifaClaro.objects.create(tipo_tarea=tipo, precio=Decimal("100"), vigente_desde=HOY - timedelta(days=500))
        self.ot = OrdenTrabajo.objects.create(numero="1", tipo=tipo, tecnico=persona("T1"), estado="completada",
                                              fecha_ejecucion=self.mes)
        p = Parametros.actual()
        p.claro_retencion = 0
        p.save()

    def test_u07_estimacion_que_baja_a_cero(self):
        from finanzas.liquidacion_claro import registrar
        from finanzas.models import EstimacionLiquidacion
        i = registrar(self.mes)
        self.assertEqual(i.saldo, Decimal("100"))
        self.ot.intentos.update(revision_tecnica="rechazada")
        i2 = registrar(self.mes)
        self.assertEqual(i2.pk, i.pk)
        i.refresh_from_db()
        self.assertEqual((i.monto, i.saldo, i.confirmacion), (0, 0, "estimado"))
        self.assertEqual(list(EstimacionLiquidacion.objects.order_by("version").values_list("version", "neto")),
                         [(1, Decimal("100")), (2, Decimal("0"))])

    def test_k01_confirmado_y_cobrado_se_conserva(self):
        from finanzas.liquidacion_claro import confirmar, registrar
        from finanzas.models import Cobro
        i = registrar(self.mes)
        confirmar(i, Decimal("80"))
        Cobro.objects.create(ingreso=i, monto=Decimal("80"))
        self.ot.intentos.update(revision_tecnica="rechazada")
        registrar(self.mes)
        i.refresh_from_db()
        self.assertEqual((i.monto, i.saldo, i.confirmacion), (Decimal("80"), 0, "confirmado"))


class VisitasTests(TestCase):
    """H01 (U09) y H06 (U08)."""

    def setUp(self):
        from operaciones.models import OrdenTrabajo, TipoTarea
        self.sup = persona("S1", rol="supervisor")
        self.a, self.b = persona("TA", supervisor=self.sup), persona("TB", supervisor=self.sup)
        self.ot = OrdenTrabajo.objects.create(numero="1", tipo=TipoTarea.objects.create(codigo="R", nombre="R"),
                                              tecnico=self.a, estado="asignada")

    def cerrar(self, estado, fecha, tecnico):
        from operaciones.visitas import crear_visita
        self.ot.tecnico, self.ot.estado, self.ot.fecha_ejecucion = tecnico, estado, fecha
        self.ot._visita_explicita = True
        self.ot.save()
        return crear_visita(self.ot)

    def test_u08_rectificar_ejecutor_reconcilia_participaciones(self):
        from operaciones.models import ParticipacionVisita
        from operaciones.visitas import rectificar_visita
        v = self.cerrar("completada", HOY, self.a)
        rectificar_visita(v, {"tecnico": self.b}, "Lo hizo B", autor=self.sup)
        v.refresh_from_db()
        ejecutores = list(ParticipacionVisita.objects.filter(intento=v, funcion="ejecutor")
                          .values_list("persona__legajo", flat=True))
        self.assertEqual((v.tecnico, ejecutores), (self.b, ["TB"]))
        self.assertFalse(ParticipacionVisita.objects.filter(intento=v, persona=self.a).exists())
        self.assertEqual(v.rectificaciones.get().antes, "TA")  # la atribución anterior queda como historial

    def test_u09_informe_viejo_no_toca_la_visita_nueva(self):
        from operaciones.services import reabrir_orden
        from supervision.models import InformeControl
        v1 = self.cerrar("completada", HOY - timedelta(days=3), self.a)
        inf = InformeControl.objects.create(supervisor=self.sup, tecnico=self.a, orden=self.ot, puntaje=2,
                                            fecha=HOY - timedelta(days=2), revision_visita="rechazada")
        self.assertEqual(inf.visita, v1)
        reabrir_orden(self.ot, "rechazada por calidad")
        self.ot.refresh_from_db()
        v2 = self.cerrar("completada", HOY, self.b)
        inf.descripcion = "agrego detalle"
        inf.save()
        v1.refresh_from_db()
        v2.refresh_from_db()
        self.assertEqual((v1.revision_tecnica, v2.revision_tecnica), ("rechazada", "sin_revisar"))
        self.assertEqual(v2.tecnico, self.b)


class OfflineTests(TestCase):
    """H07 (U10, U11) y control K02."""

    def setUp(self):
        from operaciones.models import OrdenTrabajo, TipoTarea
        self.tec = persona("T1", usuario=User.objects.create_user("tec", password="x"))
        self.ot = OrdenTrabajo.objects.create(numero="1", tipo=TipoTarea.objects.create(codigo="R", nombre="R"),
                                              tecnico=self.tec, estado="asignada")
        self.url = f"/app/orden/{self.ot.id}/notas/"

    def correr(self, vista, datos, sync=False, archivos=None):
        from core.offline import SincronizacionOfflineMiddleware
        extra = {"HTTP_X_VIRGUEL_SYNC": "1"} if sync else {}
        req = RequestFactory().post(self.url, {**datos, **(archivos or {})}, **extra)
        req.user = self.tec.usuario
        return SincronizacionOfflineMiddleware(vista)(req)

    def vista_que_falla(self, request):
        from operaciones.models import NotaOrden
        NotaOrden.objects.create(orden=self.ot, texto="parcial")
        return HttpResponseServerError("falla")

    def test_u10_envio_directo_que_falla_no_deja_nada(self):
        from core.models import OperacionOffline
        from operaciones.models import NotaOrden
        ident = str(uuid.uuid4())
        for _ in range(2):
            self.assertEqual(self.correr(self.vista_que_falla, {"texto": "x", "_id_operacion": ident}).status_code, 500)
        self.assertEqual((NotaOrden.objects.count(), OperacionOffline.objects.count()), (0, 0))

    def test_k02_sincronizado_que_falla_no_deja_nada(self):
        from core.models import OperacionOffline
        from operaciones.models import NotaOrden
        self.correr(self.vista_que_falla, {"texto": "x", "_id_operacion": str(uuid.uuid4())}, sync=True)
        self.assertEqual((NotaOrden.objects.count(), OperacionOffline.objects.count()), (0, 0))

    def test_u11_mismo_uuid_otro_archivo_es_conflicto(self):
        ident = str(uuid.uuid4())
        ok = lambda request: HttpResponseRedirect("/app/")  # noqa: E731
        r1 = self.correr(ok, {"_id_operacion": ident}, sync=True,
                         archivos={"foto": SimpleUploadedFile("foto.jpg", b"AAAA", "image/jpeg")})
        r2 = self.correr(ok, {"_id_operacion": ident}, sync=True,
                         archivos={"foto": SimpleUploadedFile("foto.jpg", b"BBBB", "image/jpeg")})
        r3 = self.correr(ok, {"_id_operacion": ident}, sync=True,
                         archivos={"foto": SimpleUploadedFile("foto.jpg", b"AAAA", "image/jpeg")})
        self.assertEqual((r1.status_code, r2.status_code), (200, 409))
        self.assertTrue(json.loads(r3.content).get("repetido"))

    def test_huella_deja_el_archivo_legible(self):
        leido = {}

        def vista(request):
            leido["bytes"] = request.FILES["foto"].read()
            return HttpResponseRedirect("/app/")
        self.correr(vista, {"_id_operacion": str(uuid.uuid4())},
                    archivos={"foto": SimpleUploadedFile("f.jpg", b"CONTENIDO", "image/jpeg")})
        self.assertEqual(leido["bytes"], b"CONTENIDO")


class EnvioConcurrenteTests(TransactionTestCase):
    """H07: dos envíos simultáneos del mismo UUID confirman un único efecto (PostgreSQL)."""

    def test_mismo_uuid_en_paralelo(self):
        if connection.vendor != "postgresql":
            self.skipTest("requiere PostgreSQL")
        from operaciones.models import NotaOrden, OrdenTrabajo, TipoTarea
        tec = persona("T1", usuario=User.objects.create_user("tec", password="x"))
        ot = OrdenTrabajo.objects.create(numero="1", tipo=TipoTarea.objects.create(codigo="R", nombre="R"),
                                         tecnico=tec, estado="asignada")
        ident = str(uuid.uuid4())
        barrera = threading.Barrier(2)
        codigos = []

        def enviar():
            from django.db import connections
            from django.test import Client
            c = Client()
            c.force_login(tec.usuario)
            barrera.wait()
            r = c.post(f"/app/orden/{ot.id}/notas/", {"texto": "una sola", "_id_operacion": ident},
                       HTTP_X_VIRGUEL_SYNC="1")
            codigos.append(r.status_code)
            connections.close_all()
        hilos = [threading.Thread(target=enviar) for _ in range(2)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(NotaOrden.objects.filter(orden=ot, texto="una sola").count(), 1)
        self.assertEqual(sorted(codigos), [200, 200])


class AgendaMaterialTests(TestCase):
    """H09 (U12): la agenda consulta el material de la orden en la fecha."""

    def setUp(self):
        from core.models import Zona
        from inventario.models import RecetaMaterial
        from operaciones.models import OrdenTrabajo, TipoTarea
        self.z = Zona.objects.create(nombre="N")
        self.t = persona("T1", zona=self.z)
        self.m = _material()
        tipo = TipoTarea.objects.create(codigo="INS", nombre="Instalación", minutos_estandar=60)
        RecetaMaterial.objects.create(tipo_tarea=tipo, material=self.m, cantidad=1)
        self.ot = OrdenTrabajo.objects.create(numero="1", tipo=tipo, zona=self.z, fecha_programada=HOY)

    def proponer(self, excepciones=()):
        from core.models import Persona
        from tablero.asignacion import proponer
        return proponer(HOY, Persona.objects.filter(rol="tecnico"), excepciones)

    def test_u12_sin_material_no_se_asigna(self):
        p = self.proponer()
        self.assertEqual(p["cupos"][0].nuevas, [])
        self.assertIn("falta material", p["sin_asignar"][0].causa)
        _lote(self.m, 1)
        self.assertEqual([o.numero for o in self.proponer()["cupos"][0].nuevas], ["1"])

    def test_excepcion_con_motivo_queda_anotada(self):
        from operaciones.models import NotaOrden
        g = User.objects.create_user("g", password="x")
        g.groups.add(Group.objects.create(name="Gerencia"))
        self.client.force_login(g)
        self.assertEqual(self.proponer([self.ot.pk])["cupos"][0].nuevas[0].sin_material[0][1], 1)
        self.client.post("/tablero/asignacion/", {"fecha": HOY.isoformat(), "excepcion": [self.ot.pk]})
        self.ot.refresh_from_db()
        self.assertIsNone(self.ot.tecnico)  # sin motivo no hay excepción
        self.client.post("/tablero/asignacion/", {"fecha": HOY.isoformat(), "excepcion": [self.ot.pk],
                                               "motivo_excepcion": "El técnico pasa por el proveedor"})
        self.ot.refresh_from_db()
        self.assertEqual(self.ot.tecnico, self.t)
        self.assertIn("EXCEPCIÓN", NotaOrden.objects.get(orden=self.ot).texto)


class CierreRecetaTests(TestCase):
    """H08 (U13): el cierre propone lo que dice la receta con su condición."""

    def test_u13_sin_recambio_no_precarga_modem(self):
        from inventario.models import RecetaMaterial
        from inventario.stock_tecnico import entregar
        from operaciones.models import OrdenTrabajo, TipoTarea
        m = _material()
        tipo = TipoTarea.objects.create(codigo="REP", nombre="Reparación")
        RecetaMaterial.objects.create(tipo_tarea=tipo, material=m, cantidad=1, condicion="si_recambio")
        t = persona("T1", usuario=User.objects.create_user("t", password="x"))
        _lote(m, 1)
        entregar(t, m, 1)
        ot = OrdenTrabajo.objects.create(numero="1", tipo=tipo, tecnico=t, estado="asignada", requiere_recambio=False)
        self.client.force_login(t.usuario)
        inicial = self.client.get(f"/app/orden/{ot.id}/cierre/").context["form"].initial
        self.assertNotIn("material_1", inicial)
        ot.requiere_recambio = True
        ot.save()
        inicial = self.client.get(f"/app/orden/{ot.id}/cierre/").context["form"].initial
        self.assertEqual((inicial["material_1"], inicial["cantidad_1"]), (m.id, 1))


class PanolTests(TestCase):
    """H10 (U14): modificar una entrega mueve el libro o se rechaza."""

    def setUp(self):
        from herramientas.models import Elemento, MovimientoPanol
        self.el = Elemento.objects.create(codigo="ESC", nombre="Escalera", tipo="herramienta", costo=100)
        MovimientoPanol.objects.create(elemento=self.el, tipo="ajuste", cantidad=2, motivo="conteo inicial")
        self.t = persona("T1")

    def stock(self):
        self.el.refresh_from_db()
        return self.el.stock

    def test_u14_modificar_cantidad_reconcilia(self):
        from django.db.models import Sum

        from herramientas.models import Asignacion, MovimientoPanol
        a = Asignacion.objects.create(persona=self.t, elemento=self.el, cantidad=1)
        self.assertEqual(self.stock(), 1)
        a.cantidad = 2
        a.save()
        self.assertEqual(self.stock(), 0)
        self.assertEqual(MovimientoPanol.objects.filter(asignacion=a).aggregate(t=Sum("cantidad"))["t"], -2)
        a.cantidad = 3
        with self.assertRaises(ValidationError):
            a.save()  # no hay una tercera unidad
        a.refresh_from_db()
        a.cantidad = 1
        a.save()
        self.assertEqual(self.stock(), 1)
        a.estado = "devuelto"
        a.save()
        self.assertEqual(self.stock(), 2)  # depósito + custodia = 2 entradas, siempre

    def test_no_cambia_de_persona(self):
        from herramientas.models import Asignacion
        a = Asignacion.objects.create(persona=self.t, elemento=self.el, cantidad=1)
        a.persona = persona("T2")
        with self.assertRaises(ValidationError):
            a.save()

    def test_perdido_no_vuelve_al_panol(self):
        from herramientas.models import Asignacion
        a = Asignacion.objects.create(persona=self.t, elemento=self.el, cantidad=1)
        a.estado = "perdido"
        a.save()
        self.assertEqual(self.stock(), 1)


class HabilitacionPorFechaTests(TestCase):
    """H11 (U15): una evaluación futura no habilita antes de su fecha."""

    def test_u15(self):
        from capacitacion.models import Competencia, EvaluacionCompetencia, RequisitoCompetencia, habilitacion
        from operaciones.models import TipoTarea
        t = persona("T1")
        tipo = TipoTarea.objects.create(codigo="INS", nombre="Instalación")
        c = Competencia.objects.create(nombre="FTTH")
        RequisitoCompetencia.objects.create(tipo_tarea=tipo, competencia=c, nivel_minimo=3)
        EvaluacionCompetencia.objects.create(persona=t, competencia=c, nivel=3, fecha=HOY + timedelta(days=7))
        self.assertEqual(habilitacion(t.id, tipo.id, HOY)["estado"], "bloqueado")
        self.assertEqual(habilitacion(t.id, tipo.id, HOY + timedelta(days=7))["estado"], "habilitado")


class DesviosYObjetivosTests(TestCase):
    """B22: indicada ≠ ejecutada ≠ eficaz. B23: quién verificó (aun sin ficha) y sobre qué."""

    def test_b22_ejecutada_no_es_eficaz(self):
        from operaciones.models import Jornada
        from supervision.evaluacion import evaluar_supervisores
        from supervision.models import AccionCorrectiva, InformeControl
        s = persona("S1", rol="supervisor")
        t = persona("T1", supervisor=s)
        Jornada.objects.create(tecnico=t, fecha=HOY - timedelta(days=2), en_calle=True)
        inf = InformeControl.objects.create(supervisor=s, tecnico=t, fecha=HOY - timedelta(days=2), puntaje=2,
                                            desvio_detectado=True)
        AccionCorrectiva.objects.create(informe=inf, tecnico=t, tipo="charla", fecha=HOY - timedelta(days=1),
                                        cumplida=True, fecha_cumplida=HOY - timedelta(days=1))
        e = evaluar_supervisores(HOY, 30)[0]
        self.assertEqual((e.desvios_con_accion, e.desvios_accion_ejecutada, e.desvios_accion_eficaz), (1, 1, 0))

    def test_b23_verificador_sin_ficha_y_cambio_posterior(self):
        from supervision.models import TareaSupervisor
        s = persona("S1", rol="supervisor", usuario=User.objects.create_user("s", password="x"))
        g = User.objects.create_user("g", password="x")  # gerencia sin ficha de persona
        g.groups.add(Group.objects.create(name="Gerencia"))
        t = TareaSupervisor.objects.create(supervisor=s, fecha=HOY, descripcion="Corregir 3 desvíos", meta=3,
                                           resultado=3, estado="cumplida", verificacion="reportado",
                                           evidencia="informes 1-3")
        self.client.force_login(g)
        self.client.post("/tablero/objetivos/", {"tarea": t.pk, "accion": "verificado"})
        t.refresh_from_db()
        self.assertEqual((t.verificacion, t.verificado_por_usuario, t.verificado_sobre["resultado"]),
                         ("verificado", "g", 3))
        # el supervisor no puede reescribir lo verificado desde la app
        self.client.force_login(s.usuario)
        self.client.post(f"/app/tarea/{t.pk}/", {"resultado": 8, "evidencia": "otra cosa"})
        t.refresh_from_db()
        self.assertEqual((t.verificacion, t.resultado), ("verificado", 3))
        # si gerencia cambia la meta después, la verificación deja de valer (queda en el historial)
        t.meta = 5
        t.save()
        t.refresh_from_db()
        self.assertEqual((t.verificacion, t.cumplimiento), ("reportado", None))
        self.assertTrue(any("verificacion_anterior" in h for h in t.historial_meta))


class AgendaCompletaTests(TestCase):
    """B04/B05/B17/B30: ventanas horarias, cuadrillas, tutor real y service programado."""

    def setUp(self):
        from core.models import Zona
        from operaciones.models import OrdenTrabajo, TipoTarea
        self.z = Zona.objects.create(nombre="N")
        self.t = persona("T1", zona=self.z)  # entra 8:00 (por defecto)
        self.tipo = TipoTarea.objects.create(codigo="C", nombre="Corta", minutos_estandar=60)
        self.OT = OrdenTrabajo

    def proponer(self):
        from core.models import Persona
        from tablero.asignacion import proponer
        return proponer(HOY, Persona.objects.filter(rol="tecnico"))

    def test_ventana_horaria(self):
        from datetime import time
        from core.models import Parametros
        p = Parametros.actual()
        p.minutos_traslado_promedio = 0
        p.save()
        # ventana de la mañana que no se alcanza si la agenda ya está llena
        self.OT.objects.create(numero="tarde", tipo=self.tipo, zona=self.z, fecha_programada=HOY,
                               ventana_desde=time(14, 0), ventana_hasta=time(16, 0))
        self.OT.objects.create(numero="temprano", tipo=self.tipo, zona=self.z, fecha_programada=HOY,
                               ventana_desde=time(8, 0), ventana_hasta=time(9, 0))
        r = self.proponer()
        horas = {o.numero: o.hora_propuesta for o in r["cupos"][0].nuevas}
        self.assertEqual(horas, {"temprano": 8 * 60, "tarde": 14 * 60})  # la de las 14 espera su ventana
        imposible = self.OT.objects.create(numero="x", tipo=self.tipo, zona=self.z, fecha_programada=HOY,
                                           ventana_desde=time(6, 0), ventana_hasta=time(7, 0))
        r = self.proponer()
        self.assertIn("ventana", next(o.causa for o in r["sin_asignar"] if o.pk == imposible.pk))

    def test_service_programado_bloquea(self):
        from flota.models import ServiceProgramado, Vehiculo
        v = Vehiculo.objects.create(patente="AA1", marca="X", modelo="Y", anio=2020, asignado_a=self.t)
        ServiceProgramado.objects.create(vehiculo=v, desde=HOY, hasta=HOY + timedelta(days=1))
        r = self.proponer()
        self.assertIn("service programado", r["bloqueados"][0][1][1])

    def test_cuadrilla_y_tutor(self):
        from capacitacion.models import Competencia, EvaluacionCompetencia, RequisitoCompetencia
        from operaciones.models import Cuadrilla, MiembroCuadrilla
        ayud = persona("T2", zona=self.z)
        cu = Cuadrilla.objects.create(nombre="C1")
        MiembroCuadrilla.objects.create(cuadrilla=cu, persona=self.t, funcion="responsable", desde=HOY - timedelta(days=9))
        MiembroCuadrilla.objects.create(cuadrilla=cu, persona=ayud, funcion="ayudante", desde=HOY - timedelta(days=9))
        self.OT.objects.create(numero="1", tipo=self.tipo, zona=self.z, fecha_programada=HOY)
        r = self.proponer()
        self.assertEqual([c.tecnico for c in r["cupos"]], [self.t])  # el ayudante no recibe órdenes propias
        # tutelada: el responsable necesita tutor; su compañero lo es sólo si está habilitado
        comp = Competencia.objects.create(nombre="FTTH")
        RequisitoCompetencia.objects.create(tipo_tarea=self.tipo, competencia=comp, nivel_minimo=3,
                                            permite_tutelada=True)
        EvaluacionCompetencia.objects.create(persona=self.t, competencia=comp, nivel=1, fecha=HOY - timedelta(days=5))
        self.assertEqual(self.proponer()["cupos"][0].nuevas, [])  # sin tutor real
        EvaluacionCompetencia.objects.create(persona=ayud, competencia=comp, nivel=4, fecha=HOY - timedelta(days=5))
        self.assertEqual([o.numero for o in self.proponer()["cupos"][0].nuevas], ["1"])


class AccesoPorObjetoTests(TestCase):
    """B38: cada rol accede sólo a las acciones y objetos que le corresponden en los flujos nuevos."""

    def setUp(self):
        from incidentes.models import Siniestro
        from supervision.models import PlantillaInspeccion, TareaSupervisor
        self.s1 = persona("S1", rol="supervisor", usuario=User.objects.create_user("s1", password="x"))
        self.s2 = persona("S2", rol="supervisor", usuario=User.objects.create_user("s2", password="x"))
        self.t1 = persona("T1", supervisor=self.s1, usuario=User.objects.create_user("t1", password="x"))
        self.t2 = persona("T2", supervisor=self.s2)
        self.sin2 = Siniestro.objects.create(numero="S-2", tipo="otro", descripcion="x", tecnico=self.t2)
        self.pl = PlantillaInspeccion.objects.create(nombre="P")
        self.tarea2 = TareaSupervisor.objects.create(supervisor=self.s2, fecha=HOY, descripcion="x")

    def test_supervisor(self):
        c = self.client
        c.force_login(self.s1.usuario)
        self.assertEqual(c.get(f"/tablero/incidentes/{self.sin2.pk}/").status_code, 404)  # incidente de otro equipo
        self.assertEqual(c.get("/tablero/objetivos/").status_code, 403)                  # verifica gerencia
        self.assertEqual(c.get("/tablero/productividad/calibrar/").status_code, 403)
        self.assertEqual(c.get("/app/tarea/%d/" % self.tarea2.pk).status_code in (404, 405), True)
        c.post(f"/tablero/plantillas/{self.pl.pk}/", {"accion": "agregar", "orden": 1, "punto": "p",
                                                     "criterio": "c", "defecto": "d"})
        self.assertEqual(self.pl.items.count(), 0)                                       # no edita plantillas
        self.assertEqual(c.get("/tablero/visitas/1/rectificar/").status_code, 403)

    def test_tecnico(self):
        self.client.force_login(self.t1.usuario)
        for url in ("/tablero/objetivos/", "/tablero/plantillas/", f"/tablero/incidentes/{self.sin2.pk}/",
                    "/tablero/indicadores/", "/tablero/asignacion/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)


class ConfidencialidadEncuestaTests(TestCase):
    """B24: el supervisor evaluado no ve quién respondió."""

    def test_supervisor_no_ve_quien_respondio(self):
        from supervision.models import EncuestaSupervisor
        s = persona("S1", rol="supervisor", usuario=User.objects.create_user("s", password="x"))
        t = persona("T1", supervisor=s)
        from django.utils import timezone
        EncuestaSupervisor.objects.create(supervisor=s, tecnico=t, fecha=HOY, respondida=timezone.now(), trato=2)
        self.client.force_login(s.usuario)
        r = self.client.get(f"/tablero/encuestas/?fecha={HOY.isoformat()}")
        self.assertNotContains(r, "Respondida")
        g = User.objects.create_user("g", password="x")
        g.groups.add(Group.objects.create(name="Gerencia"))
        self.client.force_login(g)
        self.assertContains(self.client.get(f"/tablero/encuestas/?fecha={HOY.isoformat()}"), "Respondida")


class ReproducibilidadTests(TestCase):
    """B35/B39: un cambio de meta no reescribe el pasado; los parámetros tienen historial."""

    def test_indicador_en_fecha(self):
        from core.metas import indicadores_efectivos
        from core.models import Indicador
        i = Indicador.objects.get(codigo="eficiencia_jornada")
        meta_vieja = i.meta
        i.historial = [{"version": 2, "fecha": HOY.isoformat(), "cambios": {"meta": [str(meta_vieja), "90"]}}]
        i.meta, i.version = 90, 2
        Indicador.objects.filter(pk=i.pk).update(meta=90, version=2, historial=i.historial)
        ayer = HOY - timedelta(days=1)
        en_ayer = {x.codigo: x for x in indicadores_efectivos("tecnico", al=ayer)}["eficiencia_jornada"]
        hoy = {x.codigo: x for x in indicadores_efectivos("tecnico", al=HOY)}["eficiencia_jornada"]
        self.assertEqual((en_ayer.meta, en_ayer.version, hoy.meta), (meta_vieja, 1, 90))

    def test_historial_de_parametros(self):
        from core.models import CambioParametro, Parametros
        Parametros.actual()
        p = Parametros.objects.get()
        antes = p.claro_retencion
        p.claro_retencion = 7
        p._usuario = "gerencia"
        p.save()
        c = CambioParametro.objects.get(campo="claro_retencion")
        self.assertEqual((c.antes, c.despues, c.usuario), (str(antes), "7.00", "gerencia"))
        self.assertEqual(p.valor_en("claro_retencion", HOY - timedelta(days=1)), str(antes))


class VerificarConsistenciaTests(TestCase):
    """Después de migrar o restaurar: el comando detecta contradicciones entre registros."""

    def test_detecta_panol_desbalanceado(self):
        from io import StringIO

        from django.core.management import call_command

        from herramientas.models import Elemento, MovimientoPanol
        el = Elemento.objects.create(codigo="E", nombre="E", tipo="herramienta", costo=1)
        MovimientoPanol.objects.create(elemento=el, tipo="ajuste", cantidad=3, motivo="inicial")
        call_command("verificar_consistencia", stdout=StringIO())  # consistente: no sale con error
        Elemento.objects.filter(pk=el.pk).update(stock=5)          # alguien tocó el campo a mano
        with self.assertRaises(SystemExit):
            call_command("verificar_consistencia", stdout=StringIO())
