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
from core.models import Alerta, Parametros, Persona, Zona
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
    def test_capacidad_sin_hectareas_es_tecnicos_por_clientes(self):
        cap = capacidad(10, prob_min=0.5, prob_max=0.6)
        self.assertEqual((cap.clientes_min, cap.clientes_max), (60, 60))
        self.assertEqual((cap.deco_min, cap.deco_max), (30, 36))

    def test_capacidad_hectareas_y_clientes(self):
        par = Parametros.actual()  # 5-6 ha por cuadrilla, 2 técnicos por cuadrilla, 6 clientes/técnico
        par.usar_hectareas = True
        par.save()
        cap = capacidad(10, densidad=1.0, prob_min=0.5, prob_max=0.6)
        self.assertEqual(cap.cuadrillas, 5)
        self.assertEqual((cap.ha_min, cap.ha_max), (25, 30))
        self.assertEqual((cap.clientes_min, cap.clientes_max), (25, 30))
        self.assertEqual((cap.deco_min, cap.deco_max), (12.5, 18))

    def test_capacidad_limitada_por_tope_de_visitas(self):
        par = Parametros.actual()
        par.usar_hectareas = True
        par.save()
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

    def test_evaluar_una_sola_persona_usa_mediana_de_todo_el_plantel(self):
        sola = evaluar_tecnicos(HOY, dias=40, tecnicos=[self.malo])[0]
        self.assertAlmostEqual(sola.indice_productividad, self.diag()["MALO"].indice_productividad)
        self.assertLess(sola.indice_productividad, 0.7)
        self.assertEqual(sola.diagnostico, Diagnostico.RIESGO)

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

    def test_tecnico_cierra_orden_y_descuenta_de_su_stock(self):
        from inventario.stock_tecnico import entregar, saldo
        tipo = TipoTarea.objects.create(codigo="I", nombre="Inst", puede_requerir_decodificador=True)
        m = Material.objects.create(codigo="C", nombre="Cable", costo_unitario=Decimal("2"))
        LoteIngreso.objects.create(material=m, cantidad=100)
        entregar(self.tec_p, m, 50)  # el depósito le entrega 50: salen del depósito
        self.assertEqual((m.stock_actual, saldo(self.tec_p, m)), (50, 50))
        ot = OrdenTrabajo.objects.create(numero="1", tipo=tipo, tecnico=self.tec_p, estado="asignada")
        self.client.login(username="tec", password="x")
        self.assertEqual(self.client.get(f"/app/orden/{ot.id}/").status_code, 200)
        r = self.client.post(f"/app/orden/{ot.id}/", {"resultado": "completada", "minutos_reales": 50,
                                                      "decodificador_solicitado": "on", "decodificadores_instalados": 1,
                                                      "material_1": m.id, "cantidad_1": "30",
                                                      "series_instaladas": "ABC123", "conforme_nombre": "Ana"})
        self.assertEqual(r.status_code, 302)
        ot.refresh_from_db()
        self.assertEqual((ot.estado, ot.series_instaladas, ot.conforme_nombre), ("completada", "ABC123", "Ana"))
        self.assertTrue(ot.decodificador_solicitado)
        self.assertEqual(saldo(self.tec_p, m), 20)      # se descontó de SU stock
        self.assertEqual(m.stock_actual, 50)            # el depósito no cambia al cerrar
        self.assertEqual(Salida.objects.get(orden=ot).costo_total, Decimal("60"))

    def test_orden_no_resuelta_exige_motivo(self):
        tipo = TipoTarea.objects.create(codigo="R", nombre="Rep")
        ot = OrdenTrabajo.objects.create(numero="2", tipo=tipo, tecnico=self.tec_p, estado="asignada")
        self.client.login(username="tec", password="x")
        r = self.client.post(f"/app/orden/{ot.id}/", {"resultado": "fallida"})
        self.assertEqual(r.status_code, 200)
        self.client.post(f"/app/orden/{ot.id}/", {"resultado": "fallida", "motivo_no_resuelto": "cliente_ausente"})
        ot.refresh_from_db()
        self.assertEqual((ot.estado, ot.motivo_no_resuelto), ("fallida", "cliente_ausente"))

    def test_empezar_trabajo_mide_el_tiempo(self):
        tipo = TipoTarea.objects.create(codigo="R", nombre="Rep")
        ot = OrdenTrabajo.objects.create(numero="3", tipo=tipo, tecnico=self.tec_p, estado="asignada")
        self.client.login(username="tec", password="x")
        hace = timezone.now() - timedelta(minutes=45)
        self.client.post(f"/app/orden/{ot.id}/", {"accion": "empezar", "_momento_cliente": hace.isoformat()})
        self.client.post(f"/app/orden/{ot.id}/", {"resultado": "completada"})
        ot.refresh_from_db()
        self.assertIn(ot.minutos_reales, (44, 45, 46))


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


class AsignacionTests(TestCase):
    def test_reparte_por_capacidad_real_y_zona(self):
        from tablero.asignacion import proponer
        norte, sur = Zona.objects.create(nombre="N"), Zona.objects.create(nombre="S")
        rapido = persona("R", zona=norte)
        lento = persona("L", zona=norte)
        otro = persona("O", zona=sur)
        tipo = TipoTarea.objects.create(codigo="I", nombre="Inst")
        n = 0
        for d in range(1, 11):
            f = HOY - timedelta(days=d)
            for t, cant in ((rapido, 6), (lento, 2), (otro, 4)):
                Jornada.objects.create(fecha=f, tecnico=t)
                for _ in range(cant):
                    n += 1
                    OrdenTrabajo.objects.create(numero=f"h{n}", tipo=tipo, tecnico=t, estado="completada",
                                                fecha_programada=f, fecha_ejecucion=f)
        for i in range(12):  # 12 pendientes en el norte: capacidad norte = 6 + 2 = 8
            OrdenTrabajo.objects.create(numero=f"p{i}", tipo=tipo, zona=norte, fecha_programada=HOY)
        prop = proponer(HOY, Persona.objects.filter(rol="tecnico"))
        nuevas = {c.tecnico.legajo: len(c.nuevas) for c in prop["cupos"]}
        self.assertEqual(nuevas, {"R": 6, "L": 2, "O": 4})  # los 4 que sobran van al sur
        self.assertEqual(len(prop["otra_zona"]), 4)
        self.assertEqual(prop["sin_asignar"], [])


class ControlPersonalTests(TestCase):
    def setUp(self):
        from datetime import time
        Parametros.actual()
        self.sup = persona("S1", rol="supervisor", usuario=User.objects.create_user("sup", password="x"))
        self.t = persona("T1", supervisor=self.sup, usuario=User.objects.create_user("tec", password="x"),
                         fecha_ingreso=HOY - timedelta(days=400))
        self.t.hora_entrada, self.t.hora_salida, self.t.trabaja_sabados = time(8, 0), time(17, 0), False
        self.t.save()

    def momento(self, d, h, m=0):
        from datetime import datetime
        return timezone.make_aware(datetime(d.year, d.month, d.day, h, m))

    def lunes_pasado(self):
        return HOY - timedelta(days=HOY.weekday() + 7)

    def test_llegada_tarde_y_horas_extra(self):
        from personal.models import Asistencia
        d = self.lunes_pasado()
        a = Asistencia.objects.create(persona=self.t, fecha=d, entrada=self.momento(d, 8, 25), salida=self.momento(d, 19, 25))
        self.assertEqual(a.minutos_tarde, 25)
        self.assertEqual(a.horas_trabajadas, Decimal("11.00"))
        self.assertEqual(a.horas_extra, Decimal("2.00"))  # jornada normal de 9 h
        b = Asistencia.objects.create(persona=self.t, fecha=d + timedelta(days=1), entrada=self.momento(d, 8, 9))
        self.assertEqual(b.minutos_tarde, 0)  # dentro de la tolerancia de 10 min

    def test_resumen_distingue_justificadas_injustificadas_y_vacaciones(self):
        from personal.indicadores import resumen
        from personal.models import Asistencia, Feriado, Novedad
        lunes = self.lunes_pasado()
        # semana lun–vie: lunes trabajó, martes enfermo, miércoles feriado, jueves vacaciones, viernes falta sin aviso
        Asistencia.objects.create(persona=self.t, fecha=lunes, entrada=self.momento(lunes, 8))
        Novedad.objects.create(persona=self.t, tipo="enfermedad", desde=lunes + timedelta(days=1),
                               hasta=lunes + timedelta(days=1), estado="aprobada")
        Feriado.objects.create(fecha=lunes + timedelta(days=2), nombre="Feriado")
        Novedad.objects.create(persona=self.t, tipo="vacaciones", desde=lunes + timedelta(days=3),
                               hasta=lunes + timedelta(days=3), estado="aprobada")
        r = resumen(lunes, lunes + timedelta(days=4), [self.t])[0]
        self.assertEqual((r.esperados, r.presentes, r.justificadas, r.injustificadas, r.no_computables),
                         (4, 1, 2, 1, 1))
        self.assertAlmostEqual(r.presentismo, 1 / 3)  # 1 presente de 3 días computables

    def test_sin_control_de_asistencia_no_hay_faltas(self):
        from personal.indicadores import resumen
        r = resumen(HOY - timedelta(days=30), HOY, [self.t])[0]
        self.assertEqual((r.esperados, r.injustificadas), (0, 0))

    def test_fichar_desde_el_celular_con_hora_del_celular(self):
        from personal.models import Asistencia
        self.client.login(username="tec", password="x")
        hace_un_rato = timezone.now() - timedelta(hours=2)
        self.client.post("/app/jornada/iniciar/", {"lat": "-34.6", "lng": "-58.4",
                                                   "_momento_cliente": hace_un_rato.isoformat()})
        a = Asistencia.objects.get(persona=self.t)
        self.assertEqual(a.entrada, hace_un_rato)
        self.assertTrue(Jornada.objects.filter(tecnico=self.t, en_calle=True).exists())
        self.client.post("/app/jornada/finalizar/", {})
        a.refresh_from_db()
        self.assertIsNotNone(a.salida)

    def test_supervisor_aprueba_solo_avisos_de_su_equipo(self):
        from personal.models import Novedad
        ajeno = persona("T2")
        n1 = Novedad.objects.create(persona=self.t, tipo="enfermedad")
        n2 = Novedad.objects.create(persona=ajeno, tipo="enfermedad")
        self.client.login(username="sup", password="x")
        self.client.post("/app/novedades/", {"novedad": n1.id, "accion": "aprobar"})
        self.assertEqual(self.client.post("/app/novedades/", {"novedad": n2.id, "accion": "aprobar"}).status_code, 404)
        n1.refresh_from_db(); n2.refresh_from_db()
        self.assertEqual((n1.estado, n2.estado), ("aprobada", "pendiente"))
        self.assertEqual(self.client.get(f"/personal/legajos/{ajeno.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/personal/legajos/{self.t.id}/").status_code, 200)

    def test_tecnico_avisa_ausencia_con_certificado(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from personal.models import Novedad
        self.client.login(username="tec", password="x")
        r = self.client.post("/app/ausencia/", {"tipo": "enfermedad", "desde": HOY.isoformat(), "hasta": HOY.isoformat(),
                                                "certificado": SimpleUploadedFile("c.jpg", b"img", content_type="image/jpeg")})
        self.assertEqual(r.status_code, 302)
        n = Novedad.objects.get(persona=self.t)
        self.assertEqual(n.estado, "pendiente")
        self.assertTrue(n.certificado.name.endswith(".jpg"))
        n.certificado.delete()
        # no puede autoasignarse una "suspensión" o "injustificada"
        r = self.client.post("/app/ausencia/", {"tipo": "injustificada", "desde": HOY.isoformat(), "hasta": HOY.isoformat()})
        self.assertEqual(r.status_code, 200)



class PartesTecnicoTests(TestCase):
    def setUp(self):
        self.sup = persona("S1", rol="supervisor", usuario=User.objects.create_user("sup", password="x"))
        self.t = persona("T1", supervisor=self.sup, usuario=User.objects.create_user("tec", password="x"))
        self.ger = User.objects.create_user("ger", password="x")
        self.ger.groups.add(Group.objects.create(name="Gerencia"))
        self.m = Material.objects.create(codigo="ONT", nombre="Módem", costo_unitario=Decimal("100"))
        LoteIngreso.objects.create(material=self.m, cantidad=20)

    def test_pedido_aprobado_y_entregado_pasa_al_stock_del_tecnico(self):
        from core.models import Notificacion
        from inventario.models import PedidoMaterial
        from inventario.stock_tecnico import saldo
        self.client.login(username="tec", password="x")
        self.client.post("/app/stock/pedir/", {"material_1": self.m.id, "cantidad_1": "5", "motivo": "x"})
        ped = PedidoMaterial.objects.get()
        self.assertTrue(Notificacion.objects.filter(persona=self.sup).exists())  # se avisó al supervisor
        self.client.login(username="sup", password="x")
        self.client.post("/app/pedidos/", {"pedido": ped.id, "accion": "aprobar"})
        ped.refresh_from_db()
        self.assertEqual(ped.estado, "aprobado")
        self.client.login(username="ger", password="x")
        item = ped.items.get()
        self.client.post("/tablero/pedidos/", {"pedido": ped.id, "accion": "entregar", f"cant_{item.id}": "4"})
        ped.refresh_from_db()
        self.assertEqual(ped.estado, "entregado")
        self.assertEqual((saldo(self.t, self.m), self.m.stock_actual), (4, 16))
        self.assertTrue(Notificacion.objects.filter(persona=self.t, titulo__icontains="listo").exists())

    def test_supervisor_no_aprueba_pedidos_de_otro_equipo(self):
        from inventario.models import PedidoMaterial
        otro = persona("T2")
        ped = PedidoMaterial.objects.create(tecnico=otro)
        self.client.login(username="sup", password="x")
        self.assertEqual(self.client.post("/app/pedidos/", {"pedido": ped.id, "accion": "aprobar"}).status_code, 404)

    def test_partes_paradas_fifo(self):
        from inventario.stock_tecnico import consumir, entregar, partes_paradas
        entregar(self.t, self.m, 5, fecha=HOY - timedelta(days=90))
        entregar(self.t, self.m, 5, fecha=HOY - timedelta(days=5))
        consumir(self.t, None, self.m, 3, fecha=HOY - timedelta(days=2))  # consume primero lo más viejo
        f = partes_paradas([self.t], HOY)[0]
        self.assertEqual((f["cantidad"], f["dias"]), (2, 90))

    def test_faltante_para_ordenes(self):
        from inventario.models import RecetaMaterial
        from inventario.stock_tecnico import entregar, faltante_para_ordenes
        tipo = TipoTarea.objects.create(codigo="I", nombre="Inst")
        RecetaMaterial.objects.create(tipo_tarea=tipo, material=self.m, cantidad=1)
        for i in range(3):
            OrdenTrabajo.objects.create(numero=f"o{i}", tipo=tipo, tecnico=self.t, estado="asignada")
        entregar(self.t, self.m, 1)
        filas, n = faltante_para_ordenes(self.t)
        self.assertEqual((n, filas[0]["necesito"], filas[0]["falta"]), (3, 3, 2))

    def test_devolucion_vuelve_al_deposito(self):
        from inventario.stock_tecnico import devolver, entregar, saldo
        entregar(self.t, self.m, 5)
        devolver(self.t, self.m, 2)
        self.assertEqual((saldo(self.t, self.m), self.m.stock_actual), (3, 17))


class EncuestaSemanalTests(TestCase):
    def test_una_evaluacion_por_semana_y_cuenta_para_el_supervisor(self):
        from supervision.evaluacion import evaluar_supervisores
        from supervision.models import EncuestaSemanal
        sup = persona("S1", rol="supervisor")
        t = persona("T1", supervisor=sup, usuario=User.objects.create_user("tec", password="x"))
        self.client.login(username="tec", password="x")
        datos = {k: 4 for k in ("general", "trato", "organizacion", "apoyo", "ensenanza", "justicia")}
        self.client.post("/app/mi-supervisor/", datos)
        self.client.post("/app/mi-supervisor/", {**datos, "general": 1})  # segunda vez la misma semana: se ignora
        self.assertEqual(EncuestaSemanal.objects.filter(tecnico=t).count(), 1)
        ev = [e for e in evaluar_supervisores(HOY, 30) if e.supervisor == sup][0]
        self.assertEqual(ev.nota_semanal, 4)
        self.assertEqual(ev.score_imagen, 75)


class NotificacionesTests(TestCase):
    def test_orden_asignada_y_control_notifican_al_tecnico(self):
        from core.models import Notificacion
        sup = persona("S1", rol="supervisor")
        t = persona("T1", supervisor=sup, usuario=User.objects.create_user("tec", password="x"))
        tipo = TipoTarea.objects.create(codigo="R", nombre="Rep")
        OrdenTrabajo.objects.create(numero="1", tipo=tipo, tecnico=t, estado="asignada")
        InformeControl.objects.create(supervisor=sup, tecnico=t, puntaje=2, desvio_detectado=True)
        titulos = list(Notificacion.objects.filter(persona=t).values_list("titulo", flat=True))
        self.assertEqual(len(titulos), 2)
        self.client.login(username="tec", password="x")
        self.assertContains(self.client.get("/app/"), 'class="badge"')
        self.client.get("/app/notificaciones/")
        self.assertFalse(Notificacion.objects.filter(persona=t, leida=False).exists())
