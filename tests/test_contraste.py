"""Escenarios del "Modelo de referencia y contraste" (13/10/2026): C01–C09 y verificaciones V01–V12.

Cada test reproduce el escenario descripto en el documento y comprueba el comportamiento corregido.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase

from .test_negocio import HOY, persona


class PermisosTests(TestCase):
    """C09/B38: una cuenta staff sin rol empresarial no adquiere gerencia."""

    def test_staff_sin_rol_no_es_gerencia(self):
        from core.roles import rol_de
        u = User.objects.create_user("staff", password="x", is_staff=True)
        self.assertIsNone(rol_de(u))
        self.client.force_login(u)
        self.assertEqual(self.client.get("/tablero/").status_code, 403)
        self.assertEqual(self.client.get("/finanzas/").status_code, 403)

    def test_roles_explicitos(self):
        from core.roles import rol_de
        s = User.objects.create_user("su", password="x", is_superuser=True, is_staff=True)
        g = User.objects.create_user("g", password="x")
        g.groups.add(Group.objects.create(name="Gerencia"))
        self.assertEqual((rol_de(s), rol_de(g)), ("gerencia", "gerencia"))
        adm = persona("A1", rol="administrativo", usuario=User.objects.create_user("adm", password="x"))
        self.assertIsNone(rol_de(adm.usuario))  # su alcance se define con un grupo


class SupervisorSinEvidenciaTests(TestCase):
    """C01/B25: sin jornadas, informes, encuestas ni objetivos no hay 10/100 crítico."""

    def test_sin_evidencia(self):
        from supervision.evaluacion import evaluar_supervisores
        persona("S1", rol="supervisor")
        e = evaluar_supervisores(HOY, 30)[0]
        self.assertIsNone(e.score_total)
        self.assertEqual(e.color, "info")
        self.assertTrue(e.sin_evidencia)

    def test_pantallas(self):
        from tablero.metricas import tableros_supervisores
        s = persona("S1", rol="supervisor", usuario=User.objects.create_user("s", password="x"))
        g = User.objects.create_user("g", password="x")
        g.groups.add(Group.objects.create(name="Gerencia"))
        self.client.force_login(g)
        self.assertContains(self.client.get("/tablero/supervisores/"), "Sin evidencia suficiente")
        self.assertIsNone(tableros_supervisores(hasta=HOY, supervisores=[s])[0].indice)
        self.client.force_login(s.usuario)
        self.assertContains(self.client.get("/app/indicadores/"), "Sin evidencia suficiente")


class AccionPendienteTests(TestCase):
    """C07/B22: una acción indicada pero no cumplida no cuenta como desvío corregido."""

    def test_desvio_con_accion_pendiente(self):
        from operaciones.models import Jornada
        from supervision.evaluacion import evaluar_supervisores
        from supervision.models import AccionCorrectiva, InformeControl
        s = persona("S1", rol="supervisor")
        t = persona("T1", supervisor=s)
        Jornada.objects.create(tecnico=t, fecha=HOY - timedelta(days=2), en_calle=True)
        inf = InformeControl.objects.create(supervisor=s, tecnico=t, fecha=HOY - timedelta(days=2), puntaje=2,
                                            desvio_detectado=True)
        a = AccionCorrectiva.objects.create(informe=inf, tecnico=t, tipo="charla", fecha=HOY - timedelta(days=1))
        e = evaluar_supervisores(HOY, 30)[0]
        self.assertEqual((e.desvios_con_accion, e.desvios_corregidos), (1, 0))
        self.assertEqual(e.score_desvios, 0)
        a.cumplida = True
        a.save()
        self.assertEqual(evaluar_supervisores(HOY, 30)[0].desvios_corregidos, 1)


class EncuestaSuficienciaTests(TestCase):
    """B24: una respuesta aislada no genera una calificación de trato."""

    def test_respuesta_aislada(self):
        from supervision.evaluacion import evaluar_supervisores
        from supervision.models import EncuestaSupervisor
        from django.utils import timezone
        s = persona("S1", rol="supervisor")
        t = persona("T1", supervisor=s)
        EncuestaSupervisor.objects.create(fecha=HOY, tecnico=t, supervisor=s, respondida=timezone.now(),
                                          trato=1, claridad=1, apoyo=1, presencia=1)
        e = evaluar_supervisores(HOY, 30)[0]
        self.assertIsNone(e.nota_encuesta)
        self.assertFalse(e.encuesta_suficiente)


class IncidenteAtribucionTests(TestCase):
    """C02/B27: un incidente vinculado sin atribución confirmada no baja la seguridad del técnico."""

    def setUp(self):
        from operaciones.models import Jornada, OrdenTrabajo, TipoTarea
        self.t = persona("T1")
        tipo = TipoTarea.objects.create(codigo="I", nombre="I")
        for d in range(1, 15):
            f = HOY - timedelta(days=d)
            Jornada.objects.create(tecnico=self.t, fecha=f)
            OrdenTrabajo.objects.create(numero=f"o{d}", tipo=tipo, tecnico=self.t, estado="completada",
                                        fecha_ejecucion=f, fecha_programada=f)

    def test_vinculado_no_es_culpable(self):
        from capacitacion.evaluacion import evaluar_tecnicos
        from incidentes.models import Siniestro
        sin = Siniestro.objects.create(numero="S1", tipo="cano_pinchado", gravedad="grave", tecnico=self.t,
                                       descripcion="x", fecha=HOY - timedelta(days=3), responsabilidad_civil=False)
        self.assertEqual(evaluar_tecnicos(HOY, tecnicos=[self.t])[0].score_seguridad, 100)
        sin.atribucion = "confirmada"
        sin.atribucion_fundamento = "Fotos y testigos"
        sin.full_clean()
        sin.save()
        self.assertLess(evaluar_tecnicos(HOY, tecnicos=[self.t])[0].score_seguridad, 100)
        self.assertEqual(sin.atribucion_fecha, HOY)

    def test_confirmar_sin_fundamento_no_se_admite(self):
        from incidentes.models import Siniestro
        sin = Siniestro(numero="S2", tipo="otro", tecnico=self.t, descripcion="x", atribucion="confirmada")
        with self.assertRaises(ValidationError):
            sin.full_clean()

    def test_no_concluye_responsabilidad_por_casilla(self):
        from incidentes.models import Siniestro
        sin = Siniestro.objects.create(numero="S3", tipo="otro", tecnico=self.t, descripcion="x",
                                       responsabilidad_civil=False)
        self.assertNotIn("rechazar", sin.recomendacion_legal().lower())
        self.assertIn("investigación", sin.recomendacion_legal())


class PanolTests(TestCase):
    """C04/B14: el pañol no entrega lo que no tiene y el libro reconstruye el saldo."""

    def test_entrega_sin_existencias(self):
        from herramientas.models import Asignacion, Elemento
        el = Elemento.objects.create(codigo="CAS", nombre="Casco", costo=Decimal("10"))
        with self.assertRaises(ValidationError):
            Asignacion.objects.create(persona=persona("T1"), elemento=el, cantidad=2)
        self.assertEqual(Asignacion.objects.count(), 0)
        el.refresh_from_db()
        self.assertEqual(el.stock, 0)
        a = Asignacion(persona=persona("T2"), elemento=el, cantidad=2)
        with self.assertRaises(ValidationError):
            a.full_clean()

    def test_libro_reconstruye_el_saldo(self):
        from django.db.models import Sum

        from herramientas.models import Asignacion, CompraElemento, Elemento, MovimientoPanol
        el = Elemento.objects.create(codigo="TAL", nombre="Taladro", costo=Decimal("10"))
        CompraElemento.objects.create(elemento=el, cantidad=3, costo_unitario=Decimal("10"))
        a = Asignacion.objects.create(persona=persona("T1"), elemento=el, cantidad=2)
        a.estado = "devuelto"
        a.save()
        MovimientoPanol.objects.create(elemento=el, tipo="ajuste", cantidad=-1, motivo="Conteo físico", responsable="x")
        el.refresh_from_db()
        total = MovimientoPanol.objects.filter(elemento=el).aggregate(t=Sum("cantidad"))["t"]
        self.assertEqual((el.stock, total), (2, 2))
        self.assertEqual(list(MovimientoPanol.objects.filter(elemento=el).order_by("id").values_list("tipo", flat=True)),
                         ["compra", "entrega", "devolucion", "ajuste"])

    def test_ajuste_requiere_motivo(self):
        from herramientas.models import Elemento, MovimientoPanol
        el = Elemento.objects.create(codigo="X", nombre="X")
        with self.assertRaises(ValidationError):
            MovimientoPanol(elemento=el, tipo="ajuste", cantidad=1).full_clean()


class AperturaStockTests(TestCase):
    """B13: el saldo inicial y los equipos de Claro no generan compra ni deuda."""

    def test_origenes(self):
        from finanzas.models import Egreso
        from inventario.models import LoteIngreso, Material
        m = Material.objects.create(codigo="ONT", nombre="ONT", costo_unitario=Decimal("100"))
        for origen in ("apertura", "custodia"):
            LoteIngreso.objects.create(material=m, cantidad=10, origen=origen)
        self.assertEqual(Egreso.objects.count(), 0)
        LoteIngreso.objects.create(material=m, cantidad=10, origen="compra")
        self.assertEqual(Egreso.objects.get().saldo, Decimal("1000"))  # compra: obligación pendiente


class MantenimientoTests(TestCase):
    """C06/B29: sin base no hay "al día"; un plan no asignado no genera obligaciones."""

    def test_sin_base_y_plan_no_aplicable(self):
        from flota.models import TipoService, Vehiculo, proximos_services
        v = Vehiculo.objects.create(patente="AA1", marca="X", modelo="Y", anio=2020, km_actual=5000)
        anual = TipoService.objects.create(nombre="Anual", cada_dias=365)
        TipoService.objects.create(nombre="Neumáticos", cada_km=40000)  # no asignado a este vehículo
        v.planes.add(anual)
        p = proximos_services(v, HOY)
        self.assertEqual([(x["tipo"].nombre, x["estado"]) for x in p], [("Anual", "sin_base")])
        v.fecha_base_mantenimiento = HOY - timedelta(days=400)
        v.save()
        self.assertEqual(proximos_services(v, HOY)[0]["estado"], "critico")


class LiquidacionConfirmadaTests(TestCase):
    """N02/B31/V07: estimación 100, liquidación confirmada 80, cobro 80 → recalcular no reabre el saldo."""

    def setUp(self):
        from operaciones.models import OrdenTrabajo, TarifaClaro, TipoTarea
        self.mes = HOY.replace(day=1)
        tipo = TipoTarea.objects.create(codigo="FO", nombre="Fibra")
        TarifaClaro.objects.create(tipo_tarea=tipo, precio=Decimal("100"), vigente_desde=HOY - timedelta(days=500))
        OrdenTrabajo.objects.create(numero="1", tipo=tipo, tecnico=persona("T1"), estado="completada",
                                    fecha_ejecucion=self.mes)
        from core.models import Parametros
        p = Parametros.actual()
        p.claro_retencion = 0
        p.save()

    def test_v07(self):
        from finanzas.liquidacion_claro import confirmar, registrar
        from finanzas.models import Cobro, EstimacionLiquidacion
        i = registrar(self.mes)
        self.assertEqual((i.monto, i.confirmacion), (Decimal("100"), "estimado"))
        confirmar(i, Decimal("80"), nota="Débito por calidad")
        Cobro.objects.create(ingreso=i, monto=Decimal("80"))
        registrar(self.mes)
        i.refresh_from_db()
        self.assertEqual((i.monto, i.monto_estimado, i.saldo, i.confirmacion), (Decimal("80"), Decimal("100"), 0,
                                                                                  "confirmado"))
        versiones = list(EstimacionLiquidacion.objects.order_by("version").values_list("version", "aplicada"))
        self.assertEqual(versiones, [(1, True), (2, False)])

    def test_tarifa_nueva_no_revaloriza_trabajo_hecho(self):
        from finanzas.liquidacion_claro import calcular
        from operaciones.models import TarifaClaro, TipoTarea
        TarifaClaro.objects.create(tipo_tarea=TipoTarea.objects.get(), precio=Decimal("150"),
                                   vigente_desde=HOY + timedelta(days=1))
        self.assertEqual(calcular(self.mes)["bruto"], Decimal("100"))

    def test_cobro_parcial_de_estimado_congela_el_monto(self):
        from finanzas.liquidacion_claro import registrar
        from finanzas.models import Cobro
        i = registrar(self.mes)
        Cobro.objects.create(ingreso=i, monto=Decimal("50"))
        from operaciones.models import OrdenTrabajo, TipoTarea
        OrdenTrabajo.objects.create(numero="2", tipo=TipoTarea.objects.get(), estado="completada",
                                    fecha_ejecucion=self.mes)
        registrar(self.mes)
        i.refresh_from_db()
        self.assertEqual(i.monto, Decimal("100"))


class CajaVsCostoTests(TestCase):
    """C08/B33/V08: consumir stock ya pagado no agrega compras a la caja futura."""

    def test_v08(self):
        from finanzas.caja import proyeccion_caja
        from inventario.models import DemandaComercial, LoteIngreso, Material, RecetaMaterial
        from operaciones.models import TipoTarea
        from finanzas.models import Egreso
        m = Material.objects.create(codigo="M", nombre="Mat", costo_unitario=Decimal("100"))
        tipo = TipoTarea.objects.create(codigo="T", nombre="T")
        RecetaMaterial.objects.create(tipo_tarea=tipo, material=m, cantidad=1)
        LoteIngreso.objects.create(material=m, cantidad=10, origen="apertura")  # stock ya pagado
        DemandaComercial.objects.create(fecha=HOY + timedelta(days=3), tipo_tarea=tipo, cantidad_clientes=10)
        p = proyeccion_caja(4, HOY, estimados=True)
        self.assertEqual(sum(f["estimado"] for f in p["filas"]), 0)
        DemandaComercial.objects.create(fecha=HOY + timedelta(days=4), tipo_tarea=tipo, cantidad_clientes=5)
        p = proyeccion_caja(4, HOY, estimados=True)
        self.assertAlmostEqual(float(sum(f["estimado"] for f in p["filas"])), 500, delta=1)  # 5 a comprar
        self.assertEqual(Egreso.objects.count(), 0)


class OfflineAtomicoTests(TestCase):
    """N01/B36: misma operación → un solo efecto; mismo UUID con otro contenido → conflicto; falla → nada."""

    def setUp(self):
        from operaciones.models import OrdenTrabajo, TipoTarea
        self.tec = persona("T1", usuario=User.objects.create_user("tec", password="x"))
        self.ot = OrdenTrabajo.objects.create(numero="1", tipo=TipoTarea.objects.create(codigo="R", nombre="R"),
                                              tecnico=self.tec, estado="asignada")
        self.client.force_login(self.tec.usuario)
        self.url = f"/app/orden/{self.ot.id}/notas/"

    def test_mismo_id_otro_contenido_es_conflicto(self):
        ident = str(uuid.uuid4())
        self.client.post(self.url, {"texto": "A", "_id_operacion": ident}, HTTP_X_VIRGUEL_SYNC="1")
        r = self.client.post(self.url, {"texto": "B", "_id_operacion": ident}, HTTP_X_VIRGUEL_SYNC="1")
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()["conflicto"])
        self.assertEqual(self.ot.notas.count(), 1)

    def test_rechazo_no_deja_cambios_parciales(self):
        """Una vista que guarda algo y después falla: en la sincronización no queda ni el cambio ni la marca."""
        from django.http import HttpResponseServerError
        from django.test import RequestFactory

        from core.models import OperacionOffline
        from core.offline import SincronizacionOfflineMiddleware
        from operaciones.models import NotaOrden

        def vista_que_falla(request):
            NotaOrden.objects.create(orden=self.ot, texto="parcial")
            return HttpResponseServerError("falla")
        req = RequestFactory().post(self.url, {"texto": "x", "_id_operacion": str(uuid.uuid4())},
                                    HTTP_X_VIRGUEL_SYNC="1")
        req.user = self.tec.usuario
        resp = SincronizacionOfflineMiddleware(vista_que_falla)(req)
        self.assertEqual(resp.status_code, 500)
        self.assertFalse(NotaOrden.objects.filter(texto="parcial").exists())
        self.assertFalse(OperacionOffline.objects.exists())


class HistoriaRectificableTests(TestCase):
    """C03/B02/V01: varias visitas, reasignación y reapertura no destruyen autoría."""

    def test_v01(self):
        from operaciones.models import OrdenTrabajo, TipoTarea
        from operaciones.services import reabrir_orden
        a, b = persona("TA"), persona("TB")
        ot = OrdenTrabajo.objects.create(numero="1", tipo=TipoTarea.objects.create(codigo="R", nombre="R"),
                                         tecnico=a, estado="asignada")
        ot.estado, ot.fecha_ejecucion, ot.motivo_no_resuelto = "fallida", HOY - timedelta(days=2), "cliente_ausente"
        ot.save()
        ot.tecnico, ot.estado, ot.fecha_ejecucion = b, "asignada", None
        ot.save()
        ot.estado, ot.fecha_ejecucion = "completada", HOY - timedelta(days=1)
        ot.save()
        reabrir_orden(ot, "Claro la rechazó")
        ot.refresh_from_db()
        ot.tecnico = a
        ot.save()
        hist = list(ot.intentos.order_by("numero").values_list("tecnico__legajo", "resultado"))
        self.assertEqual(hist, [("TA", "fallida"), ("TB", "completada")])


class AgendaEjecutableTests(TestCase):
    """B04/B05/B17/V04: minutos de la jornada, disponibilidad unificada y competencias."""

    def setUp(self):
        from operaciones.models import OrdenTrabajo, TipoTarea
        from core.models import Zona
        self.z = Zona.objects.create(nombre="N")
        self.t = persona("T1", zona=self.z)
        self.larga = TipoTarea.objects.create(codigo="L", nombre="Larga", minutos_estandar=450)
        self.corta = TipoTarea.objects.create(codigo="C", nombre="Corta", minutos_estandar=30)
        self.OT = OrdenTrabajo

    def proponer(self):
        from core.models import Persona
        from tablero.asignacion import proponer
        return proponer(HOY, Persona.objects.filter(rol="tecnico"))

    def test_tarea_que_llena_la_jornada_no_admite_otra(self):
        self.OT.objects.create(numero="1", tipo=self.larga, zona=self.z, fecha_programada=HOY)
        self.OT.objects.create(numero="2", tipo=self.corta, zona=self.z, fecha_programada=HOY)
        p = self.proponer()
        self.assertEqual([o.numero for o in p["cupos"][0].nuevas], ["1"])
        self.assertEqual([(o.numero, "sin capacidad" in o.causa) for o in p["sin_asignar"]], [("2", True)])

    def test_licencia_aprobada_y_vehiculo_en_taller_bloquean(self):
        from flota.models import Vehiculo
        from personal.models import Novedad
        self.OT.objects.create(numero="1", tipo=self.corta, zona=self.z, fecha_programada=HOY)
        n = Novedad.objects.create(persona=self.t, tipo="enfermedad", desde=HOY, hasta=HOY)
        p = self.proponer()
        self.assertEqual(p["bloqueados"][0][1][0], "pendiente")  # pendiente de aprobar ≠ disponible
        n.estado = "aprobada"
        n.save()
        p = self.proponer()
        self.assertEqual((p["bloqueados"][0][1][0], p["cupos"]), ("no_disponible", []))
        n.delete()
        Vehiculo.objects.create(patente="AA1", marca="X", modelo="Y", anio=2020, asignado_a=self.t, estado="taller")
        p = self.proponer()
        self.assertIn("taller", p["bloqueados"][0][1][1])

    def test_competencia_faltante_bloquea_y_se_explica(self):
        from capacitacion.models import Competencia, EvaluacionCompetencia, RequisitoCompetencia
        fo = Competencia.objects.create(nombre="Fusión de fibra")
        RequisitoCompetencia.objects.create(tipo_tarea=self.corta, competencia=fo, nivel_minimo=3)
        self.OT.objects.create(numero="1", tipo=self.corta, zona=self.z, fecha_programada=HOY)
        p = self.proponer()
        self.assertIn("competencia", p["sin_asignar"][0].causa)
        EvaluacionCompetencia.objects.create(persona=self.t, competencia=fo, nivel=3)
        self.assertEqual(len(self.proponer()["cupos"][0].nuevas), 1)
        # una habilitación vencida no cuenta
        EvaluacionCompetencia.objects.update(vence=HOY - timedelta(days=1))
        self.assertEqual(self.proponer()["cupos"][0].nuevas, [])


class FormacionTests(TestCase):
    """B18/B19: asistir no aprueba; una decisión de plan requiere fundamento."""

    def test_participacion_pendiente(self):
        from capacitacion.models import Capacitacion, Curso, Participacion
        cap = Capacitacion.objects.create(curso=Curso.objects.create(nombre="EPP"))
        p = Participacion.objects.create(capacitacion=cap, persona=persona("T1"))
        self.assertEqual((p.aprobado, p.resultado), (None, "Pendiente de evaluación"))
        p.aprobado = True
        with self.assertRaises(ValidationError):
            p.full_clean()
        p.evaluador, p.evidencia = persona("S1", rol="supervisor"), "Práctica observada en obra"
        p.full_clean()

    def test_plan_requiere_fundamento(self):
        from capacitacion.models import PlanMejora
        pl = PlanMejora(persona=persona("T1"), revisar_el=HOY + timedelta(days=30), motivo="Baja producción",
                        decision="no_cumplido")
        with self.assertRaises(ValidationError):
            pl.full_clean()
