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
