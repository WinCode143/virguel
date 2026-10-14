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


class EvidenciaPorVisitaTests(TestCase):
    """B06/B07: consumos y evidencias pertenecen a la visita; revisión y aceptación son estados propios."""

    def setUp(self):
        from inventario.models import LoteIngreso, Material
        from inventario.stock_tecnico import entregar
        from operaciones.models import OrdenTrabajo, TarifaClaro, TipoTarea
        self.sup = persona("S1", rol="supervisor", usuario=User.objects.create_user("sup", password="x"))
        self.t = persona("T1", supervisor=self.sup, usuario=User.objects.create_user("tec", password="x"))
        self.tipo = TipoTarea.objects.create(codigo="I", nombre="Inst")
        TarifaClaro.objects.create(tipo_tarea=self.tipo, precio=Decimal("100"), vigente_desde=HOY - timedelta(days=99))
        self.m = Material.objects.create(codigo="C", nombre="Cable", costo_unitario=Decimal("2"))
        LoteIngreso.objects.create(material=self.m, cantidad=100, origen="apertura")
        entregar(self.t, self.m, 20)
        self.ot = OrdenTrabajo.objects.create(numero="1", tipo=self.tipo, tecnico=self.t, estado="asignada")

    def test_cierre_liga_consumo_y_evidencia_a_la_visita(self):
        from inventario.models import Salida
        self.client.force_login(self.t.usuario)
        self.client.post(f"/app/orden/{self.ot.id}/cierre/", {
            "resultado": "completada", "material_1": self.m.id, "cantidad_1": "3", "series_instaladas": "S123",
            "conforme_nombre": "Ana", "gasto_desc_1": "Tarugos", "gasto_monto_1": "500"})
        it = self.ot.intentos.get()
        self.assertEqual((it.series_instaladas, it.conforme.startswith("Ana")), ("S123", True))
        self.assertEqual(Salida.objects.get(motivo="consumo").intento_id, it.id)

    def test_revision_rechazada_no_se_estima_como_cobrable(self):
        from finanzas.liquidacion_claro import calcular
        from supervision.models import InformeControl
        self.ot.estado, self.ot.fecha_ejecucion = "completada", HOY
        self.ot.save()
        mes = HOY.replace(day=1)
        self.assertEqual(calcular(mes)["bruto"], Decimal("100"))
        InformeControl.objects.create(supervisor=self.sup, tecnico=self.t, orden=self.ot, puntaje=2,
                                      desvio_detectado=True, revision_visita="rechazada")
        it = self.ot.intentos.get()
        self.assertEqual((it.resultado, it.revision_tecnica), ("completada", "rechazada"))  # conserva ambas
        c = calcular(mes)
        self.assertEqual((c["bruto"], c["excluidas"]), (Decimal("0"), 1))


class CuadrillasTests(TestCase):
    """B03: dos personas en una visita → una resolución, dos participaciones; cambiar el equipo no
    reescribe la visita anterior."""

    def test_participaciones(self):
        from operaciones.models import Cuadrilla, MiembroCuadrilla, OrdenTrabajo, TipoTarea
        a, b, c = persona("TA"), persona("TB"), persona("TC")
        cu = Cuadrilla.objects.create(nombre="Norte 1")
        MiembroCuadrilla.objects.create(cuadrilla=cu, persona=a, desde=HOY - timedelta(days=30))
        mb = MiembroCuadrilla.objects.create(cuadrilla=cu, persona=b, funcion="ayudante", desde=HOY - timedelta(days=30))
        ot = OrdenTrabajo.objects.create(numero="1", tipo=TipoTarea.objects.create(codigo="I", nombre="I"),
                                         tecnico=a, estado="completada", fecha_ejecucion=HOY - timedelta(days=1))
        it = ot.intentos.get()
        self.assertEqual(OrdenTrabajo.objects.count(), 1)
        self.assertEqual(sorted(it.participantes.values_list("persona__legajo", "funcion")),
                         [("TA", "ejecutor"), ("TB", "ayudante")])
        # cambia el equipo: TB sale, entra TC; la visita anterior no cambia
        mb.hasta = HOY - timedelta(days=1)
        mb.save()
        MiembroCuadrilla.objects.create(cuadrilla=cu, persona=c, funcion="ayudante", desde=HOY)
        self.assertEqual(sorted(it.participantes.values_list("persona__legajo", flat=True)), ["TA", "TB"])


class RelojesAntiguedadTests(TestCase):
    """B12: trasladar material de 59 días no lo vuelve nuevo; la pantalla dice qué reloj alerta."""

    def test_entrega_no_rejuvenece(self):
        from core.models import Parametros
        from inventario.models import LoteIngreso, Material
        from inventario.stock_tecnico import entregar, partes_paradas
        m = Material.objects.create(codigo="R", nombre="Roseta", costo_unitario=Decimal("1"))
        LoteIngreso.objects.create(material=m, cantidad=10, fecha=HOY - timedelta(days=59), origen="apertura")
        t = persona("T1")
        entregar(t, m, 5, fecha=HOY - timedelta(days=1))
        self.assertEqual(partes_paradas([t], hoy=HOY), [])            # 60 días todavía no
        f = partes_paradas([t], hoy=HOY + timedelta(days=1))[0]       # al día 60 por edad original
        self.assertEqual((f["dias_original"], f["dias_custodia"], f["reloj"]), (60, 2, "edad original"))
        p = Parametros.actual()
        p.reloj_antiguedad = "permanencia"
        p.save()
        self.assertEqual(partes_paradas([t], hoy=HOY + timedelta(days=1)), [])

    def test_devolucion_conserva_edad_y_registra_permanencia(self):
        from inventario.models import LoteIngreso, Material
        from inventario.services import lotes_envejecidos
        from inventario.stock_tecnico import devolver, entregar
        m = Material.objects.create(codigo="R", nombre="Roseta", costo_unitario=Decimal("1"))
        LoteIngreso.objects.create(material=m, cantidad=4, fecha=HOY - timedelta(days=70), origen="apertura")
        t = persona("T1")
        entregar(t, m, 4, fecha=HOY - timedelta(days=10))
        devolver(t, m, 4, fecha=HOY - timedelta(days=2))
        f = lotes_envejecidos(HOY)[0]
        self.assertEqual((f["dias_original"], f["dias_permanencia"], f["estado"]), (70, 2, "critico"))


class TransferenciasTests(TestCase):
    """B34: transferir entre cuentas propias no altera el total; simular cuotas no paga."""

    def test_transferencia(self):
        from finanzas.caja import saldo_cuentas
        from finanzas.models import Cuenta, TransferenciaCuenta
        a = Cuenta.objects.create(nombre="Banco", saldo_inicial=Decimal("1000"), fecha_saldo_inicial=HOY - timedelta(days=5))
        b = Cuenta.objects.create(nombre="Caja", saldo_inicial=Decimal("100"), fecha_saldo_inicial=HOY - timedelta(days=5))
        total = saldo_cuentas(HOY)
        TransferenciaCuenta.objects.create(origen=a, destino=b, monto=Decimal("300"), fecha=HOY)
        self.assertEqual((a.saldo(HOY), b.saldo(HOY), saldo_cuentas(HOY)), (Decimal("700"), Decimal("400"), total))

    def test_simular_no_paga(self):
        from finanzas.alternativas import comparar
        from finanzas.models import Pago
        comparar([{"nombre": "Cuotas", "cuotas": 6, "monto_cuota": Decimal("10")}], Decimal("3"))
        self.assertFalse(Pago.objects.exists())


class ImportacionTrazableTests(TestCase):
    """B01/B39/V11: reimportar la misma previsión no duplica; los cambios guardan su valor anterior."""

    def setUp(self):
        from operaciones.models import TipoTarea
        g = User.objects.create_user("g", password="x")
        g.groups.add(Group.objects.create(name="Gerencia"))
        self.client.force_login(g)
        TipoTarea.objects.create(codigo="I", nombre="I")

    def subir(self, tipo, contenido):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post("/tablero/importar/", {"tipo": tipo, "archivo": SimpleUploadedFile(
            "d.csv", contenido.encode(), content_type="text/csv")})

    def test_demanda_revisable(self):
        from inventario.models import DemandaComercial
        from tablero.models import Importacion
        f = (HOY + timedelta(days=3)).strftime("%d/%m/%Y")
        archivo = f"fecha;codigo_tipo_tarea;cantidad_clientes\n{f};I;40\n"
        self.subir("demanda", archivo)
        r = self.subir("demanda", archivo)
        self.assertEqual(DemandaComercial.objects.get().cantidad_clientes, 40)
        self.assertContains(self.client.get("/tablero/importar/"), "")  # pantalla ok
        self.assertEqual(Importacion.objects.filter(tipo="demanda").values("huella").distinct().count(), 1)
        self.subir("demanda", archivo.replace(";40", ";55"))
        self.assertEqual(DemandaComercial.objects.get().cantidad_clientes, 55)
        cambio = Importacion.objects.order_by("-id").first().resultado_filas[0]["cambios"][0]
        self.assertEqual((cambio["antes"], cambio["despues"]), ("40", "55"))
        del r


class OdometroTests(TestCase):
    """B30/V09: dos integrantes del mismo recorrido no duplican km; una lectura menor es anomalía."""

    def test_lecturas(self):
        from flota.models import LecturaOdometro, Vehiculo, km_por_dia, registrar_lectura
        v = Vehiculo.objects.create(patente="AA1", marca="X", modelo="Y", anio=2020, km_actual=1000)
        from django.utils import timezone
        ahora = timezone.now()
        registrar_lectura(v, 1000, momento=ahora - timedelta(days=10))
        registrar_lectura(v, 1500, "jornada", momento=ahora)
        self.assertIsNone(registrar_lectura(v, 1500, "jornada", momento=ahora))  # el compañero, mismo recorrido
        self.assertEqual(LecturaOdometro.objects.count(), 2)
        self.assertEqual(km_por_dia(v, timezone.localdate()), 50)
        mala = registrar_lectura(v, 900, momento=ahora + timedelta(hours=1))
        v.refresh_from_db()
        self.assertTrue(mala.anomalia)
        self.assertEqual(v.km_actual, 1500)


class RoturaYEppTests(TestCase):
    """B15/B16: la rotura retira el elemento y el recambio queda vinculado; falta de entrega = suministro."""

    def setUp(self):
        from herramientas.models import CompraElemento, Elemento
        self.casco = Elemento.objects.create(codigo="CAS", nombre="Casco", costo=Decimal("10"), vida_util_dias=365,
                                             obligatorio_tecnicos=True)
        CompraElemento.objects.create(elemento=self.casco, cantidad=5, costo_unitario=Decimal("10"))
        self.sup = persona("S1", rol="supervisor")
        self.t = persona("T1", supervisor=self.sup, usuario=User.objects.create_user("t", password="x"))

    def test_rotura_y_recambio(self):
        from herramientas.models import Asignacion, ReporteCondicion
        a = Asignacion.objects.create(persona=self.t, elemento=self.casco)
        self.client.force_login(self.t.usuario)
        self.client.post("/app/epp/", {"accion": "reportar", "asignacion": a.id, "tipo": "rotura",
                                       "descripcion": "Se partió la visera"})
        a.refresh_from_db()
        r = ReporteCondicion.objects.get()
        self.assertEqual((a.estado, r.responsable_id), ("danado", self.sup.id))
        nueva = r.reponer()
        r.refresh_from_db()
        self.assertEqual((r.estado, r.reemplazo_id, nueva.estado), ("resuelto", nueva.id, "en_uso"))

    def test_falta_de_epp_no_resta_seguridad_y_bloquea_por_suministro(self):
        from capacitacion.evaluacion import evaluar_tecnicos
        from core.models import Persona, Zona
        from herramientas.models import RequisitoEPP
        from operaciones.models import Jornada, OrdenTrabajo, TipoTarea
        from tablero.asignacion import proponer
        tipo = TipoTarea.objects.create(codigo="A", nombre="Altura", minutos_estandar=30)
        for d in range(1, 13):
            Jornada.objects.create(tecnico=self.t, fecha=HOY - timedelta(days=d))
            OrdenTrabajo.objects.create(numero=f"o{d}", tipo=tipo, tecnico=self.t, estado="completada",
                                        fecha_ejecucion=HOY - timedelta(days=d))
        e = evaluar_tecnicos(HOY, tecnicos=[self.t])[0]
        self.assertEqual((e.epp_faltantes, e.score_seguridad), (1, 100))
        RequisitoEPP.objects.create(tipo_tarea=tipo, elemento=self.casco)
        z = Zona.objects.create(nombre="Z")
        self.t.zona = z
        self.t.save()
        OrdenTrabajo.objects.create(numero="N1", tipo=tipo, zona=z, fecha_programada=HOY)
        p = proponer(HOY, Persona.objects.filter(rol="tecnico"))
        self.assertIn("suministro", p["sin_asignar"][0].causa)


class AbastecimientoTests(TestCase):
    """B08–B11: series con una sola ubicación, reservas sin doble compromiso, recetas condicionadas y
    necesidad inmediata vs. backlog."""

    def setUp(self):
        from inventario.models import Material, RecetaMaterial
        from operaciones.models import TipoTarea
        self.modem = Material.objects.create(codigo="MOD", nombre="Módem", costo_unitario=Decimal("100"))
        self.rep = TipoTarea.objects.create(codigo="REP", nombre="Reparación")
        RecetaMaterial.objects.create(tipo_tarea=self.rep, material=self.modem, cantidad=1, condicion="si_recambio")
        self.t = persona("T1")

    def orden(self, n, **kw):
        from operaciones.models import OrdenTrabajo
        return OrdenTrabajo.objects.create(numero=n, tipo=self.rep, fecha_programada=HOY, **kw)

    def fila(self):
        from inventario.services import prevision_materiales
        return prevision_materiales(HOY, HOY + timedelta(days=13))[0]

    def test_receta_condicionada(self):
        self.orden("1", requiere_recambio=False, tecnico=self.t, estado="asignada")
        from inventario.services import prevision_materiales
        self.assertEqual(prevision_materiales(HOY, HOY + timedelta(days=13)), [])  # sin recambio: cero módems
        self.orden("2", requiere_recambio=True, tecnico=self.t, estado="asignada")
        f = self.fila()
        self.assertEqual((f["necesario"], f["estimado"]), (1, False))
        self.orden("3")  # desconocido: se estima con la probabilidad de recambio
        self.assertTrue(self.fila()["estimado"])

    def test_reserva_no_cubre_dos_ordenes_y_se_libera(self):
        from django.core.exceptions import ValidationError

        from inventario.models import LoteIngreso
        from inventario.services import reservar
        LoteIngreso.objects.create(material=self.modem, cantidad=1, origen="apertura")
        o1 = self.orden("1", requiere_recambio=True, tecnico=self.t, estado="asignada")
        o2 = self.orden("2", requiere_recambio=True, tecnico=self.t, estado="asignada")
        r = reservar(o1, self.modem, 1)
        with self.assertRaises(ValidationError):
            reservar(o2, self.modem, 1)
        f = self.fila()
        self.assertEqual((f["necesario"], f["deposito"], f["reservado"], f["faltante"]), (1, 0, 1, 1))  # o2 falta
        r.estado = "cancelada"
        r.save()
        self.assertEqual(self.fila()["faltante"], 1)  # 2 necesarios, 1 en depósito
        self.assertEqual(LoteIngreso.objects.count(), 1)  # cancelar no crea una entrada ficticia

    def test_entrega_posterior_no_destraba_lo_inmediato(self):
        from inventario.models import CompraEnCamino
        self.orden("1", requiere_recambio=True, tecnico=self.t, estado="asignada")
        CompraEnCamino.objects.create(material=self.modem, cantidad=5, fecha_esperada=HOY + timedelta(days=10))
        f = self.fila()
        self.assertEqual((f["inmediato"], f["faltante_inmediato"]), (1, 1))

    def test_serie_un_solo_lugar_y_defectuoso_fuera_de_suministro(self):
        from inventario.equipos import mover, recibir_en_deposito, revisar
        from inventario.models import UnidadEquipo
        u = UnidadEquipo.objects.create(material=self.modem, numero_serie="SN1")
        mover(u, "tecnico", custodio=self.t)
        mover(u, "cliente", motivo="Instalada")
        u.refresh_from_db()
        self.assertEqual((u.ubicacion, u.custodio, u.utilizable), ("cliente", None, False))
        u = recibir_en_deposito("SN1")
        self.assertEqual((u.ubicacion, u.condicion, u.utilizable), ("deposito", "a_revisar", False))
        u = revisar(u, False)
        self.assertFalse(u.utilizable)
        self.assertEqual(u.movimientos.count(), 4)


class ObjetivosVerificadosTests(TestCase):
    """B23: lo que el supervisor reporta no cuenta hasta que un tercero lo verifica; la meta se versiona."""

    def test_reportado_verificado_rechazado(self):
        from supervision.evaluacion import evaluar_supervisores
        from supervision.models import TareaSupervisor
        s = persona("S1", rol="supervisor", usuario=User.objects.create_user("s", password="x"))
        t = TareaSupervisor.objects.create(supervisor=s, fecha=HOY, descripcion="Controlar 3", meta=3,
                                           criterio_aceptacion="3 informes con foto")
        self.client.force_login(s.usuario)
        self.client.post(f"/app/tarea/{t.pk}/", {"resultado": 3, "evidencia": "informes 1, 2 y 3"})
        t.refresh_from_db()
        self.assertEqual((t.verificacion, t.estado, t.evidencia), ("reportado", "cumplida", "informes 1, 2 y 3"))
        self.assertIsNone(t.cumplimiento)
        self.assertIsNone(evaluar_supervisores(HOY, 30)[0].cumplimiento_tareas)
        t.verificacion = "verificado"
        t.save()
        self.assertEqual(evaluar_supervisores(HOY, 30)[0].cumplimiento_tareas, 1.0)
        t.verificacion = "rechazado"
        t.save()
        self.assertEqual(t.cumplimiento, 0.0)

    def test_vencido_sin_reporte_y_meta_versionada(self):
        from supervision.models import TareaSupervisor
        s = persona("S1", rol="supervisor")
        t = TareaSupervisor.objects.create(supervisor=s, fecha=HOY, descripcion="x", meta=3)
        self.assertIsNone(t.cumplimiento)  # todavía pendiente: sin dato
        t.meta = 5
        t.save()
        self.assertEqual([(h["antes"], h["despues"]) for h in t.historial_meta], [(3, 5)])
        t.estado = "no_cumplida"
        t.save()
        self.assertEqual(t.cumplimiento, 0.0)

    def test_nadie_verifica_lo_propio(self):
        from supervision.admin import TareaAdmin
        from supervision.models import TareaSupervisor
        from django.contrib.admin.sites import site
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        s = persona("S1", rol="supervisor", usuario=User.objects.create_user("s", password="x", is_staff=True))
        t = TareaSupervisor.objects.create(supervisor=s, fecha=HOY, descripcion="x", verificacion="reportado")
        req = RequestFactory().post("/")
        req.user, req.session = s.usuario, {}
        req._messages = FallbackStorage(req)
        TareaAdmin(TareaSupervisor, site).verificar(req, TareaSupervisor.objects.all())
        t.refresh_from_db()
        self.assertEqual(t.verificacion, "reportado")


class MotivoSeleccionTests(TestCase):
    """B21: un control por sospecha o reclamo no entra en la calidad general; se ve quién no tuvo control."""

    def test_sospecha_no_es_representativa(self):
        from capacitacion.evaluacion import evaluar_tecnicos
        from supervision.models import InformeControl
        s = persona("S1", rol="supervisor")
        t = persona("T1", supervisor=s)
        InformeControl.objects.create(supervisor=s, tecnico=t, fecha=HOY, puntaje=1, motivo_seleccion="sospecha")
        InformeControl.objects.create(supervisor=s, tecnico=t, fecha=HOY, puntaje=5, motivo_seleccion="aleatorio")
        self.assertEqual(InformeControl.objects.representativos().count(), 1)
        e = [x for x in evaluar_tecnicos(HOY, 30) if x.tecnico == t][0]
        self.assertEqual(e.puntaje_controles, 5.0)

    def test_equipo_sin_control(self):
        from operaciones.models import Jornada
        from supervision.models import InformeControl
        s = persona("S1", rol="supervisor", usuario=User.objects.create_user("s", password="x"))
        t1, t2 = persona("T1", supervisor=s), persona("T2", supervisor=s)
        for t in (t1, t2):
            Jornada.objects.create(tecnico=t, fecha=HOY, en_calle=True)
        InformeControl.objects.create(supervisor=s, tecnico=t1, fecha=HOY, puntaje=4)
        self.client.force_login(s.usuario)
        r = self.client.get("/app/")
        self.assertEqual(list(r.context["sin_control"]), [t2])


class PlantillaInspeccionTests(TestCase):
    """B20: plantilla versionada con puntos y criterio; un punto crítico que no cumple es desvío."""

    def test_control_con_plantilla(self):
        from supervision.models import InformeControl, ItemPlantilla, PlantillaInspeccion
        s = persona("S1", rol="supervisor", usuario=User.objects.create_user("s", password="x"))
        t = persona("T1", supervisor=s)
        pl = PlantillaInspeccion.objects.create(nombre="Instalación FTTH")
        i1 = ItemPlantilla.objects.create(plantilla=pl, orden=1, punto="Potencia óptica", criterio="≥ -25 dBm",
                                          defecto="Potencia baja", critico=True)
        i2 = ItemPlantilla.objects.create(plantilla=pl, orden=2, punto="Orden del cableado", criterio="Grampeado",
                                          defecto="Cableado suelto")
        self.client.force_login(s.usuario)
        r = self.client.get(f"/app/informe/?plantilla={pl.pk}")
        self.assertContains(r, "Potencia óptica")
        r = self.client.post("/app/informe/", {
            "plantilla": pl.pk, "tecnico": t.pk, "motivo_seleccion": "aleatorio", "tipo": "calidad", "puntaje": 3,
            "descripcion": "control", f"item_{i1.pk}": "no_cumple", f"medida_{i1.pk}": "-28 dBm",
            f"item_{i2.pk}": "cumple"})
        self.assertEqual(r.status_code, 302)
        inf = InformeControl.objects.get()
        self.assertTrue(inf.desvio_detectado)
        self.assertEqual([h.item.defecto for h in inf.hallazgos], ["Potencia baja"])
        self.assertEqual(inf.plantilla, pl)

    def test_completitud_cae_si_faltan_puntos(self):
        from supervision.models import InformeControl, ItemPlantilla, PlantillaInspeccion, ResultadoItem
        s, t = persona("S1", rol="supervisor"), persona("T1")
        pl = PlantillaInspeccion.objects.create(nombre="P")
        items = [ItemPlantilla.objects.create(plantilla=pl, punto=f"p{i}", criterio="c", defecto="d") for i in range(2)]
        inf = InformeControl.objects.create(supervisor=s, tecnico=t, fecha=HOY, puntaje=4, descripcion="x" * 80)
        base = inf.calidad_informe
        inf.plantilla = pl
        inf.save()
        ResultadoItem.objects.create(informe=inf, item=items[0], resultado="cumple")
        self.assertEqual(inf.calidad_informe, base // 2)


class ActuacionesIncidenteTests(TestCase):
    """B28: cronología del expediente con plazos y alerta cuando vencen."""

    def test_plazo_vencido_alerta(self):
        from core.models import Alerta
        from incidentes.models import ActuacionIncidente, Siniestro, proximo_plazo
        from tablero.automatizacion import alertas_incidentes
        sin = Siniestro.objects.create(numero="S-1", tipo="vehiculo", gravedad="leve", descripcion="x")
        ActuacionIncidente.objects.create(siniestro=sin, tipo="aseguradora", descripcion="Presentar denuncia",
                                          vence=HOY + timedelta(days=10))
        a = ActuacionIncidente.objects.create(siniestro=sin, tipo="descargo", descripcion="Descargo del técnico",
                                              vence=HOY - timedelta(days=1))
        self.assertEqual(proximo_plazo(sin), a)
        self.assertTrue(a.vencida)
        alertas_incidentes(HOY)
        self.assertTrue(Alerta.objects.filter(clave=f"incidentes:plazo-{a.id}", nivel="critica").exists())
        a.cumplida = True
        a.save()
        alertas_incidentes(HOY)
        self.assertFalse(Alerta.objects.filter(clave=f"incidentes:plazo-{a.id}", resuelta=False).exists())


class DiccionarioIndicadoresTests(TestCase):
    """B35: cada indicador publica su contrato; los cambios de criterio se versionan; un único cálculo."""

    def test_contrato_y_version(self):
        from core.models import Indicador
        i = Indicador.objects.get(codigo="eficiencia_jornada")
        self.assertTrue(i.poblacion and i.ventana and i.fuente and i.sin_dato)
        self.assertIn("Horas estándar", i.numerador)
        self.assertTrue(i.denominador)
        v = i.version
        i.nombre = "Eficiencia"  # no es criterio: no cambia la versión
        i.save()
        self.assertEqual(i.version, v)
        i.meta = 75
        i.save()
        self.assertEqual(i.version, v + 1)
        self.assertEqual(i.historial[-1]["cambios"]["meta"][1], "75")
        g = User.objects.create_user("g", password="x")
        g.groups.add(Group.objects.create(name="Gerencia"))
        self.client.force_login(g)
        r = self.client.get("/tablero/indicadores/")
        self.assertContains(r, "Eficiencia")
        self.assertContains(r, f"v{v + 1}")

    def test_mismo_valor_en_app_y_escritorio(self):
        from operaciones.models import Jornada, OrdenTrabajo, TipoTarea
        s = persona("S1", rol="supervisor")
        t = persona("T1", supervisor=s, usuario=User.objects.create_user("t", password="x"))
        tipo = TipoTarea.objects.create(codigo="INS", nombre="Instalación", minutos_estandar=60)
        for d in range(1, 4):
            f = HOY - timedelta(days=d)
            Jornada.objects.create(tecnico=t, fecha=f, en_calle=True)
            OrdenTrabajo.objects.create(numero=f"O{d}", tipo=tipo, tecnico=t, estado="completada",
                                        fecha_programada=f, fecha_ejecucion=f)
        g = User.objects.create_user("g", password="x")
        g.groups.add(Group.objects.create(name="Gerencia"))
        self.client.force_login(t.usuario)
        app = self.client.get("/app/desempeno/").context["tb"]
        self.client.force_login(g)
        esc = self.client.get(f"/tablero/productividad/{t.pk}/").context["tb"]
        self.assertEqual([(m.indicador.codigo, m.valor) for m in app.mediciones],
                         [(m.indicador.codigo, m.valor) for m in esc.mediciones])


class PreparacionVisitaTests(TestCase):
    """B40 (primer paso, sin IA): antecedentes y avisos con fuente, sin modificar nada."""

    def test_avisos_con_fuente(self):
        from core.models import Cliente
        from incidentes.models import Siniestro
        from inventario.models import Material, RecetaMaterial
        from operaciones.models import Intento, OrdenTrabajo, TipoTarea
        from operaciones.preparacion import preparar_visita
        t = persona("T1", usuario=User.objects.create_user("t", password="x"))
        tipo = TipoTarea.objects.create(codigo="INS", nombre="Instalación", minutos_estandar=60)
        mat = Material.objects.create(codigo="M1", nombre="Conector", unidad="u", costo_unitario=10)
        RecetaMaterial.objects.create(tipo_tarea=tipo, material=mat, cantidad=2)
        cli = Cliente.objects.create(numero="C1", nombre="Cliente")
        vieja = OrdenTrabajo.objects.create(numero="O0", tipo=tipo, cliente=cli, tecnico=t, estado="fallida",
                                            fecha_programada=HOY - timedelta(days=5))
        Intento.objects.create(orden=vieja, fecha=HOY - timedelta(days=5), resultado="fallida",
                               motivo_no_resuelto="cliente_ausente", tecnico=t)
        Siniestro.objects.create(numero="S1", tipo="otro", cliente=cli, descripcion="x")
        ot = OrdenTrabajo.objects.create(numero="O1", tipo=tipo, cliente=cli, tecnico=t, estado="asignada",
                                         fecha_programada=HOY)
        n_intentos = Intento.objects.count()
        prep = preparar_visita(ot)
        textos = " | ".join(a[1] for a in prep["avisos"])
        self.assertIn("llamá al cliente", textos)
        self.assertIn("incidente", textos)
        self.assertIn("Te falta: Conector (2)", textos)
        self.assertTrue(all(a[2] for a in prep["avisos"]))  # todo aviso dice de dónde sale
        self.assertEqual(Intento.objects.count(), n_intentos)
        self.client.force_login(t.usuario)
        self.assertContains(self.client.get(f"/app/orden/{ot.pk}/"), "Preparar la visita")


class PantallasCalidadTests(TestCase):
    """Objetivos, plantillas e incidentes se gestionan desde pantallas propias, no sólo desde el administrador."""

    def setUp(self):
        self.g = User.objects.create_user("g", password="x")
        self.g.groups.add(Group.objects.create(name="Gerencia"))
        self.client.force_login(self.g)

    def test_verificar_objetivo(self):
        from supervision.models import TareaSupervisor
        s = persona("S1", rol="supervisor")
        t = TareaSupervisor.objects.create(supervisor=s, fecha=HOY, descripcion="Controlar 3", meta=3, resultado=3,
                                           estado="cumplida", verificacion="reportado", evidencia="informes 1-3")
        r = self.client.get("/tablero/objetivos/")
        self.assertContains(r, "informes 1-3")
        self.client.post("/tablero/objetivos/", {"tarea": t.pk, "accion": "verificado", "nota": "ok"})
        t.refresh_from_db()
        self.assertEqual(t.verificacion, "verificado")
        self.client.post("/tablero/objetivos/", {"accion": "crear", "supervisor": s.pk, "fecha": HOY.isoformat(),
                                                 "descripcion": "Revisar EPP", "criterio_aceptacion": "Planilla firmada"})
        self.assertTrue(TareaSupervisor.objects.filter(descripcion="Revisar EPP").exists())

    def test_plantilla_versionada(self):
        from supervision.models import InformeControl, PlantillaInspeccion
        self.client.post("/tablero/plantillas/", {"accion": "nueva", "nombre": "FTTH", "tipo": "calidad"})
        pl = PlantillaInspeccion.objects.get(nombre="FTTH")
        self.client.post(f"/tablero/plantillas/{pl.pk}/", {"accion": "agregar", "orden": 1, "punto": "Potencia",
                                                          "criterio": "≥ -25 dBm", "defecto": "Potencia baja",
                                                          "critico": "on"})
        self.assertEqual(pl.items.count(), 1)
        s, t = persona("S1", rol="supervisor"), persona("T1")
        InformeControl.objects.create(supervisor=s, tecnico=t, fecha=HOY, puntaje=4, plantilla=pl)
        # usada: no se edita, se versiona
        self.client.post(f"/tablero/plantillas/{pl.pk}/", {"accion": "quitar", "item": pl.items.get().pk})
        self.assertEqual(pl.items.count(), 1)
        self.client.post(f"/tablero/plantillas/{pl.pk}/", {"accion": "version"})
        nueva = PlantillaInspeccion.objects.get(nombre="FTTH", version=2)
        self.assertTrue(nueva.vigente)
        self.assertEqual(nueva.items.count(), 1)
        pl.refresh_from_db()
        self.assertFalse(pl.vigente)
        self.assertContains(self.client.get("/tablero/plantillas/"), "FTTH")

    def test_expediente_incidente(self):
        from incidentes.models import Siniestro
        sin = Siniestro.objects.create(numero="S-9", tipo="otro", descripcion="x")
        self.client.post(f"/tablero/incidentes/{sin.pk}/", {
            "fecha": HOY.isoformat(), "tipo": "aseguradora", "descripcion": "Presentar a la aseguradora",
            "vence": (HOY - timedelta(days=1)).isoformat()})
        a = sin.actuaciones.get()
        r = self.client.get(f"/tablero/incidentes/{sin.pk}/")
        self.assertContains(r, "vencido")
        self.assertContains(self.client.get("/tablero/incidentes/"), "vencido")
        self.client.post(f"/tablero/incidentes/{sin.pk}/", {"accion": "cumplida", "actuacion": a.pk})
        a.refresh_from_db()
        self.assertTrue(a.cumplida)

    def test_aviso_demo(self):
        from core.models import Parametros
        self.assertNotContains(self.client.get("/tablero/plantillas/"), "Datos de demostración")
        p = Parametros.actual()
        p.datos_demo = True
        p.save()
        self.assertContains(self.client.get("/tablero/plantillas/"), "Datos de demostración")


class CalibracionPesosTests(TestCase):
    """B26: simular pesos no guarda nada y muestra cómo cambia el orden."""

    def test_simular(self):
        from core.models import Indicador
        g = User.objects.create_user("g", password="x")
        g.groups.add(Group.objects.create(name="Gerencia"))
        self.client.force_login(g)
        antes = dict(Indicador.objects.values_list("codigo", "peso"))
        r = self.client.get("/tablero/productividad/calibrar/")
        self.assertContains(r, "Eficiencia de la jornada")
        r = self.client.get("/tablero/productividad/calibrar/?rol=tecnico&peso_eficiencia_jornada=0")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["cambio"])
        self.assertEqual(dict(Indicador.objects.values_list("codigo", "peso")), antes)

    def test_spearman(self):
        from tablero.productividad import _spearman
        self.assertEqual(_spearman([3, 2, 1], [3, 2, 1]), 1)
        self.assertEqual(_spearman([3, 2, 1], [1, 2, 3]), -1)
