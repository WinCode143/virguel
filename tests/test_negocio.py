"""Tests de las reglas de negocio principales.

Ejecutar:  python manage.py test tests
"""
import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from capacitacion.evaluacion import Diagnostico, evaluar_tecnicos
from capacitacion.models import Capacitacion, Curso, Participacion
from core.models import Alerta, Parametros, Persona
from core.services import SincronizadorAlertas
from finanzas.models import Egreso
from flota.models import ServiceRealizado, TipoService, Vehiculo, proximos_services
from incidentes.models import Siniestro
from inventario.models import LoteIngreso, Material, Salida
from inventario.services import StockInsuficiente, lotes_envejecidos, registrar_salida, stock_diario
from operaciones.models import Jornada, OrdenTrabajo, TipoTarea
from supervision.evaluacion import evaluar_supervisores
from supervision.models import AccionCorrectiva, EncuestaSupervisor, InformeControl
from tablero.planificacion import capacidad, probabilidad_decodificador

HOY = timezone.localdate()


def persona(legajo, rol="tecnico", **kw):
    return Persona.objects.create(legajo=legajo, nombre=legajo, apellido=legajo, rol=rol,
                                  fecha_ingreso=kw.pop("fecha_ingreso", HOY - timedelta(days=400)), **kw)


class StockTests(TestCase):
    def setUp(self):
        self.m = Material.objects.create(codigo="X", nombre="Cable", costo_unitario=Decimal("10"))

    def test_salida_fifo_consume_primero_lo_mas_viejo(self):
        viejo = LoteIngreso.objects.create(material=self.m, fecha=HOY - timedelta(days=30), cantidad=10,
                                           costo_unitario=Decimal("5"))
        nuevo = LoteIngreso.objects.create(material=self.m, fecha=HOY, cantidad=10, costo_unitario=Decimal("8"))
        s = registrar_salida(Salida(material=self.m, cantidad=Decimal("14")))
        viejo.refresh_from_db(); nuevo.refresh_from_db()
        self.assertEqual(viejo.cantidad_disponible, 0)
        self.assertEqual(nuevo.cantidad_disponible, 6)
        self.assertEqual(s.costo_total, Decimal("10") * 5 + Decimal("4") * 8)

    def test_salida_sin_stock_falla_salvo_que_se_permita(self):
        LoteIngreso.objects.create(material=self.m, cantidad=2)
        with self.assertRaises(StockInsuficiente):
            registrar_salida(Salida(material=self.m, cantidad=5))
        s = registrar_salida(Salida(material=self.m, cantidad=5), permitir_negativo=True)
        self.assertEqual(s.costo_total, Decimal("50"))

    def test_antiguedad_marca_lotes_de_mas_de_60_dias(self):
        LoteIngreso.objects.create(material=self.m, fecha=HOY - timedelta(days=61), cantidad=3)
        LoteIngreso.objects.create(material=self.m, fecha=HOY - timedelta(days=50), cantidad=3)
        LoteIngreso.objects.create(material=self.m, fecha=HOY - timedelta(days=5), cantidad=3)
        estados = [f["estado"] for f in lotes_envejecidos(HOY)]
        self.assertEqual(estados, ["critico", "aviso", "ok"])

    def test_stock_diario_cruza_con_tecnicos_en_calle(self):
        LoteIngreso.objects.create(material=self.m, fecha=HOY - timedelta(days=40), cantidad=100)
        tecs = [persona(f"T{i}") for i in range(4)]
        for d in range(1, 11):
            for t in tecs:
                Jornada.objects.create(fecha=HOY - timedelta(days=d), tecnico=t)
            registrar_salida(Salida(material=self.m, cantidad=Decimal("4"), fecha=HOY - timedelta(days=d)))
        for t in tecs:
            Jornada.objects.create(fecha=HOY, tecnico=t)
        fila = stock_diario(HOY)["filas"][0]
        self.assertEqual(stock_diario(HOY)["tecnicos_en_calle"], 4)
        self.assertEqual(fila["consumo_tecnico_dia"], Decimal("1"))       # 40 unidades / 40 jornadas
        self.assertEqual(fila["stock"], Decimal("60"))
        self.assertAlmostEqual(float(fila["dias_cobertura"]), 15.0)    # 60 / (1 x 4 técnicos)


class PlanificacionTests(TestCase):
    def test_capacidad_hectareas_y_clientes(self):
        Parametros.actual()  # 5-6 ha por cuadrilla, 2 técnicos por cuadrilla, 6 clientes/técnico
        cap = capacidad(10, densidad=1.0, prob_min=0.5, prob_max=0.6)
        self.assertEqual(cap.cuadrillas, 5)
        self.assertEqual((cap.ha_min, cap.ha_max), (25, 30))
        self.assertEqual((cap.clientes_min, cap.clientes_max), (25, 30))
        self.assertEqual((cap.deco_min, cap.deco_max), (12.5, 18))

    def test_capacidad_limitada_por_tope_de_visitas(self):
        cap = capacidad(10, densidad=5.0)
        self.assertEqual(cap.clientes_max, 60)  # 10 técnicos x 6 visitas

    def test_probabilidad_sin_datos_usa_supuesto(self):
        est = probabilidad_decodificador(HOY)
        self.assertAlmostEqual(est.media, 0.55)

    def test_probabilidad_se_corrige_con_datos_reales(self):
        tipo = TipoTarea.objects.create(codigo="I", nombre="Inst", puede_requerir_decodificador=True)
        for i in range(400):
            OrdenTrabajo.objects.create(numero=str(i), tipo=tipo, estado="completada", fecha_ejecucion=HOY,
                                        decodificador_solicitado=i < 300)  # 75% real
        est = probabilidad_decodificador(HOY)
        self.assertGreater(est.media, 0.72)
        self.assertLess(est.inf90, est.media)
        self.assertGreater(est.sup90, est.media)


class EvaluacionTecnicosTests(TestCase):
    """Escenario: 6 técnicos normales, uno lento pero prolijo y uno lento y problemático."""

    def setUp(self):
        self.tipo = TipoTarea.objects.create(codigo="R", nombre="Rep", minutos_estandar=60)
        self.sup = persona("S1", rol="supervisor")
        self.normales = [persona(f"N{i}", supervisor=self.sup) for i in range(6)]
        self.lento = persona("LENTO", supervisor=self.sup)
        self.malo = persona("MALO", supervisor=self.sup)
        n = 0
        for d in range(1, 41):
            f = HOY - timedelta(days=d)
            for t in self.normales + [self.lento, self.malo]:
                Jornada.objects.create(fecha=f, tecnico=t)
                cant = 3 if t in (self.lento, self.malo) else 5
                for k in range(cant):
                    n += 1
                    o = OrdenTrabajo.objects.create(numero=str(n), tipo=self.tipo, tecnico=t, estado="completada",
                                                    fecha_programada=f, fecha_ejecucion=f, minutos_reales=60)
                    if t is self.malo and k == 0:  # un retrabajo por día: 1 de cada 3 trabajos
                        n += 1
                        OrdenTrabajo.objects.create(numero=str(n), tipo=self.tipo, es_retrabajo=True,
                                                    orden_original=o, fecha_programada=f, estado="completada")
        for k in range(4):
            AccionCorrectiva.objects.create(tecnico=self.malo, tipo="apercibimiento", fecha=HOY - timedelta(days=k * 7))
        Siniestro.objects.create(numero="S1", tipo="cano_pinchado", gravedad="grave", tecnico=self.malo,
                                 descripcion="x", fecha=HOY - timedelta(days=10))

    def diag(self):
        return {e.tecnico.legajo: e for e in evaluar_tecnicos(HOY, dias=40)}

    def test_lento_pero_prolijo_necesita_capacitacion(self):
        self.assertEqual(self.diag()["LENTO"].diagnostico, Diagnostico.CAPACITACION)

    def test_lento_y_problematico_es_riesgo_alto(self):
        e = self.diag()["MALO"]
        self.assertEqual(e.diagnostico, Diagnostico.RIESGO)
        self.assertGreater(e.riesgo, self.diag()["LENTO"].riesgo)

    def test_normales_adecuados(self):
        d = self.diag()
        self.assertTrue(all(d[t.legajo].diagnostico == Diagnostico.ADECUADO for t in self.normales))

    def test_capacitado_y_mejorando(self):
        # el lento recibió capacitación en producción y en los últimos días rinde como el resto
        curso = Curso.objects.create(nombre="Acompañamiento")
        cap = Capacitacion.objects.create(curso=curso, fecha=HOY - timedelta(days=15), en_produccion=True)
        Participacion.objects.create(capacitacion=cap, persona=self.lento)
        for d in range(1, 14):
            f = HOY - timedelta(days=d)
            for i in range(2):
                OrdenTrabajo.objects.create(numero=f"X{d}-{i}", tipo=self.tipo, tecnico=self.lento,
                                            estado="completada", fecha_programada=f, fecha_ejecucion=f)
        e = self.diag()["LENTO"]
        self.assertGreater(e.tendencia, 10)
        self.assertIn(e.diagnostico, (Diagnostico.MEJORANDO, Diagnostico.ADECUADO))

    def test_ingresante_en_curva_de_aprendizaje(self):
        self.lento.fecha_ingreso = HOY - timedelta(days=30)
        self.lento.save()
        self.assertEqual(self.diag()["LENTO"].diagnostico, Diagnostico.APRENDIZAJE)


class SupervisoresTests(TestCase):
    def test_encuesta_y_desvios_afectan_puntaje(self):
        bueno, malo = persona("S1", rol="supervisor"), persona("S2", rol="supervisor")
        tb, tm = persona("T1", supervisor=bueno), persona("T2", supervisor=malo)
        for d in range(1, 11):
            f = HOY - timedelta(days=d)
            for t, s, nota in ((tb, bueno, 5), (tm, malo, 2)):
                Jornada.objects.create(fecha=f, tecnico=t)
                EncuestaSupervisor.objects.create(fecha=f, tecnico=t, supervisor=s, respondida=timezone.now(),
                                                  trato=nota, claridad=nota, apoyo=nota, presencia=nota)
            inf = InformeControl.objects.create(supervisor=bueno, tecnico=tb, fecha=f, puntaje=2,
                                                desvio_detectado=True, descripcion="x" * 100)
            AccionCorrectiva.objects.create(informe=inf, tecnico=tb, tipo="recapacitacion", fecha=f + timedelta(days=1))
            InformeControl.objects.create(supervisor=malo, tecnico=tm, fecha=f, puntaje=2, desvio_detectado=True)
        evs = {e.supervisor.legajo: e for e in evaluar_supervisores(HOY, 30)}
        self.assertEqual(evs["S1"].nota_encuesta, 5)
        self.assertEqual(evs["S1"].desvios_con_accion, 10)
        self.assertEqual(evs["S2"].desvios_con_accion, 0)
        self.assertGreater(evs["S1"].score_total, evs["S2"].score_total + 30)


class AutomatismosTests(TestCase):
    def test_egresos_automaticos(self):
        m = Material.objects.create(codigo="X", nombre="Cable", costo_unitario=Decimal("10"))
        lote = LoteIngreso.objects.create(material=m, cantidad=5)
        self.assertEqual(Egreso.objects.get(origen=f"lote:{lote.id}").monto, Decimal("50"))
        s = Siniestro.objects.create(numero="S1", tipo="otro", descripcion="x")
        self.assertFalse(Egreso.objects.filter(origen=f"siniestro:{s.id}").exists())  # sin costo real aún
        s.costo_real = Decimal("1000"); s.save()
        self.assertEqual(Egreso.objects.get(origen=f"siniestro:{s.id}").monto, Decimal("1000"))
        lote.delete()
        self.assertFalse(Egreso.objects.filter(origen=f"lote:{lote.id}").exists())

    def test_alertas_se_abren_y_cierran_solas(self):
        with SincronizadorAlertas("stock") as s:
            s.alerta("a", "A"); s.alerta("b", "B")
        with SincronizadorAlertas("stock") as s:
            s.alerta("a", "A actualizada")
        abiertas = Alerta.objects.filter(resuelta=False)
        self.assertEqual([a.titulo for a in abiertas], ["A actualizada"])

    def test_service_vencido_por_km(self):
        v = Vehiculo.objects.create(patente="AA1", marca="X", modelo="Y", anio=2020, km_actual=21000)
        ts = TipoService.objects.create(nombre="Aceite", cada_km=10000, cada_dias=365)
        ServiceRealizado.objects.create(vehiculo=v, tipo=ts, fecha=HOY - timedelta(days=30), km=10000)
        p = proximos_services(v, HOY)[0]
        self.assertEqual(p["estado"], "critico")
        self.assertEqual(p["km_restantes"], -1000)


class AccesoTests(TestCase):
    def setUp(self):
        self.ger = User.objects.create_user("ger", password="x")
        self.ger.groups.add(Group.objects.create(name="Gerencia"))
        self.sup_p = persona("S1", rol="supervisor", usuario=User.objects.create_user("sup", password="x"))
        self.tec_p = persona("T1", supervisor=self.sup_p, usuario=User.objects.create_user("tec", password="x"))

    def test_cada_rol_llega_a_su_version(self):
        for user, destino in (("ger", "/tablero/"), ("sup", "/tablero/"), ("tec", "/app/")):
            self.client.login(username=user, password="x")
            self.assertRedirects(self.client.get("/"), destino, fetch_redirect_response=False)
        self.client.login(username="sup", password="x")
        r = self.client.get("/", HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 14) Mobile")
        self.assertRedirects(r, "/app/", fetch_redirect_response=False)

    def test_permisos(self):
        self.client.login(username="tec", password="x")
        self.assertEqual(self.client.get("/tablero/").status_code, 403)
        self.client.login(username="sup", password="x")
        self.assertEqual(self.client.get("/tablero/finanzas/").status_code, 403)
        self.assertEqual(self.client.get("/tablero/supervisores/").status_code, 403)
        self.assertEqual(self.client.get("/tablero/tecnicos/").status_code, 200)
        self.assertEqual(self.client.get("/api/powerbi/ordenes.csv").status_code, 403)

    def test_encuesta_por_link_sin_login(self):
        e = EncuestaSupervisor.objects.create(fecha=HOY, tecnico=self.tec_p, supervisor=self.sup_p)
        r = self.client.post(f"/encuesta/{e.token}/", {"trato": 4, "claridad": 5, "apoyo": 3, "presencia": 4})
        self.assertEqual(r.status_code, 200)
        e.refresh_from_db()
        self.assertIsNotNone(e.respondida)
        self.assertEqual(e.promedio, 4)

    def test_tecnico_cierra_orden_y_descuenta_material(self):
        tipo = TipoTarea.objects.create(codigo="I", nombre="Inst", puede_requerir_decodificador=True)
        m = Material.objects.create(codigo="C", nombre="Cable", costo_unitario=Decimal("2"))
        LoteIngreso.objects.create(material=m, cantidad=100)
        ot = OrdenTrabajo.objects.create(numero="1", tipo=tipo, tecnico=self.tec_p, estado="asignada")
        self.client.login(username="tec", password="x")
        r = self.client.post(f"/app/orden/{ot.id}/", {"resultado": "completada", "minutos_reales": 50,
                                                      "decodificador_solicitado": "on", "decodificadores_instalados": 1,
                                                      "material_1": m.id, "cantidad_1": "30"})
        self.assertEqual(r.status_code, 302)
        ot.refresh_from_db()
        self.assertEqual(ot.estado, "completada")
        self.assertTrue(ot.decodificador_solicitado)
        self.assertEqual(m.stock_actual, 70)
        self.assertEqual(Salida.objects.get(orden=ot).costo_total, Decimal("60"))


class ImportacionTests(TestCase):
    def setUp(self):
        u = User.objects.create_user("ger", password="x")
        u.groups.add(Group.objects.create(name="Gerencia"))
        self.client.login(username="ger", password="x")

    def subir(self, tipo, contenido, nombre="datos.csv"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post("/tablero/importar/", {"tipo": tipo, "archivo": SimpleUploadedFile(
            nombre, contenido.encode("utf-8"), content_type="text/csv")})

    def test_importa_personas_con_usuario_y_supervisor(self):
        r = self.subir("personas", "legajo;nombre;apellido;rol;legajo_supervisor;usuario;dni\n"
                                   "S9;Ana;Sup;supervisor;;asup;111\n"
                                   "T9;Beto;Tec;tecnico;S9;btec;222\n")
        self.assertEqual(r.status_code, 302)
        t = Persona.objects.get(legajo="T9")
        self.assertEqual(t.supervisor.legajo, "S9")
        self.assertTrue(t.usuario.check_password("222"))

    def test_error_en_una_fila_no_guarda_nada(self):
        r = self.subir("materiales", "codigo,nombre,costo_unitario\nA,Cable,10\nB,Conector,abc\n")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "no es un número")
        self.assertFalse(Material.objects.exists())

    def test_importa_stock_con_formato_argentino(self):
        Material.objects.create(codigo="A", nombre="Cable")
        self.subir("stock", "codigo_material;fecha_ingreso;cantidad;costo_unitario\nA;01/08/2026;1.500;12,50\n")
        lote = LoteIngreso.objects.get()
        self.assertEqual((lote.cantidad, lote.costo_unitario), (Decimal("1500"), Decimal("12.50")))

    def test_importa_excel(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from openpyxl import Workbook
        wb = Workbook()
        wb.active.append(["patente", "marca", "modelo", "anio", "km_actual", "vencimiento_vtv"])
        wb.active.append(["ab 123 cd", "Fiat", "Fiorino", 2022, 45000, timezone.datetime(2026, 12, 1)])
        buf = io.BytesIO()
        wb.save(buf)
        self.client.post("/tablero/importar/", {"tipo": "vehiculos", "archivo": SimpleUploadedFile("v.xlsx", buf.getvalue())})
        v = Vehiculo.objects.get(patente="AB123CD")
        self.assertEqual((v.km_actual, v.vencimiento_vtv.month), (45000, 12))


class SinSenalTests(TestCase):
    def test_orden_enviada_tarde_conserva_fecha_de_carga(self):
        sup = persona("S1", rol="supervisor")
        tec = persona("T1", supervisor=sup, usuario=User.objects.create_user("tec", password="x"))
        tipo = TipoTarea.objects.create(codigo="R", nombre="Rep")
        ot = OrdenTrabajo.objects.create(numero="1", tipo=tipo, tecnico=tec, estado="asignada")
        self.client.login(username="tec", password="x")
        ayer = HOY - timedelta(days=1)
        self.client.post(f"/app/orden/{ot.id}/", {"resultado": "completada", "_fecha_cliente": ayer.isoformat()})
        ot.refresh_from_db()
        self.assertEqual(ot.fecha_ejecucion, ayer)
        # una fecha demasiado vieja o futura se ignora
        ot2 = OrdenTrabajo.objects.create(numero="2", tipo=tipo, tecnico=tec, estado="asignada")
        self.client.post(f"/app/orden/{ot2.id}/", {"resultado": "completada", "_fecha_cliente": "2020-01-01"})
        ot2.refresh_from_db()
        self.assertEqual(ot2.fecha_ejecucion, HOY)


class SeguridadTests(TestCase):
    def test_resolver_alerta_no_redirige_a_sitios_externos(self):
        u = User.objects.create_user("ger", password="x")
        u.groups.add(Group.objects.create(name="Gerencia"))
        self.client.login(username="ger", password="x")
        a = Alerta.objects.create(modulo="stock", clave="x", titulo="X")
        r = self.client.post(f"/tablero/alertas/{a.id}/resolver/", {"next": "https://sitio-falso.com/"})
        self.assertEqual(r["Location"], "/tablero/alertas/")
        a2 = Alerta.objects.create(modulo="stock", clave="y", titulo="Y")
        r = self.client.post(f"/tablero/alertas/{a2.id}/resolver/", {"next": "/tablero/alertas/?modulo=stock"})
        self.assertEqual(r["Location"], "/tablero/alertas/?modulo=stock")

    def test_tecnico_no_puede_cerrar_orden_ajena(self):
        a = persona("T1", usuario=User.objects.create_user("a", password="x"))
        b = persona("T2")
        tipo = TipoTarea.objects.create(codigo="R", nombre="Rep")
        ot = OrdenTrabajo.objects.create(numero="1", tipo=tipo, tecnico=b, estado="asignada")
        self.client.login(username="a", password="x")
        self.assertEqual(self.client.post(f"/app/orden/{ot.id}/", {"resultado": "completada"}).status_code, 404)
        self.assertNotEqual(a.id, b.id)
