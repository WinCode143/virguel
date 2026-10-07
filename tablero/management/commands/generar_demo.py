"""Genera datos de demostración realistas para probar el sistema.

    python manage.py generar_demo --reset

Crea usuarios de prueba (contraseña común: virguel2026):
    admin      superusuario
    gerencia   gerencia (escritorio completo)
    s001..s005 supervisores (app móvil + tablero de su equipo)
    t001..t036 técnicos (app móvil)

Perfiles de técnicos simulados, para validar el diagnóstico:
    bueno, capacitar (rinde poco pero es prolijo), riesgo (rinde poco y además
    tiene siniestros/sanciones/retrabajos), nuevo (ingresó hace < 60 días),
    mejora (rendía poco, se capacitó en producción y mejoró).
"""
import math
import random
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from capacitacion.models import Capacitacion, Competencia, Curso, EvaluacionCompetencia, Participacion
from core.models import Alerta, Cliente, Parametros, Persona, Zona
from finanzas.models import CategoriaEgreso, CostoFijo, Egreso
from finanzas.signals import sincronizar
from flota.models import ServiceRealizado, TipoService, Vehiculo
from herramientas.models import Asignacion, Elemento
from incidentes.models import Siniestro
from inventario.models import DemandaComercial, LoteIngreso, Material, RecetaMaterial, Salida
from operaciones.models import Jornada, OrdenTrabajo, TipoTarea
from supervision.models import AccionCorrectiva, EncuestaSupervisor, InformeControl, TareaSupervisor

NOMBRES = ["Juan", "Carlos", "Diego", "Martín", "Lucas", "Matías", "Nicolás", "Facundo", "Gonzalo", "Pablo",
           "Sergio", "Hernán", "Ramiro", "Cristian", "Leandro", "Ezequiel", "Damián", "Federico", "Gustavo", "Walter",
           "Maximiliano", "Rodrigo", "Ariel", "Emiliano", "Brian", "Jonathan", "Franco", "Alejandro", "Marcelo",
           "Javier", "Agustín", "Tomás", "Iván", "Hugo", "Raúl", "Darío", "Lorena", "Silvia", "Andrea", "Paola"]
APELLIDOS = ["González", "Rodríguez", "Gómez", "Fernández", "López", "Díaz", "Martínez", "Pérez", "Romero",
             "Sosa", "Álvarez", "Torres", "Ruiz", "Ramírez", "Flores", "Benítez", "Acosta", "Medina", "Herrera",
             "Suárez", "Aguirre", "Giménez", "Gutiérrez", "Pereyra", "Rojas", "Molina", "Castro", "Ortiz", "Silva",
             "Núñez", "Luna", "Juárez", "Cabrera", "Ríos", "Ferreyra", "Godoy", "Morales", "Domínguez", "Moreno",
             "Peralta", "Vega", "Carrizo", "Quiroga", "Castillo", "Ledesma", "Muñoz", "Ojeda", "Ponce"]

# OT completadas por día esperadas y factores de riesgo por perfil
PERFILES = {
    "bueno":     {"ots": 5.6, "fallida": 0.04, "retrabajo": 0.03, "siniestro": 0.0015, "desvio": 0.08, "epp_ok": 0.985},
    "capacitar": {"ots": 3.4, "fallida": 0.05, "retrabajo": 0.03, "siniestro": 0.0015, "desvio": 0.10, "epp_ok": 0.985},
    "riesgo":    {"ots": 3.3, "fallida": 0.13, "retrabajo": 0.13, "siniestro": 0.030, "desvio": 0.55, "epp_ok": 0.40},
    "nuevo":     {"ots": 3.0, "fallida": 0.06, "retrabajo": 0.05, "siniestro": 0.002, "desvio": 0.15, "epp_ok": 1.00},
    "mejora":    {"ots": 3.4, "fallida": 0.05, "retrabajo": 0.04, "siniestro": 0.0015, "desvio": 0.12, "epp_ok": 0.985},
}
REPARTO = ["bueno"] * 25 + ["capacitar"] * 4 + ["riesgo"] * 3 + ["nuevo"] * 2 + ["mejora"] * 2

# Perfiles de supervisores: trato medio (1-5), informes/día, prob. de accionar ante desvío, cumplimiento
SUPERVISORES = [
    {"trato": 4.4, "informes": 4.5, "accion": 0.95, "cumple": 0.92, "doc": 0.9},
    {"trato": 4.1, "informes": 3.8, "accion": 0.85, "cumple": 0.85, "doc": 0.8},
    {"trato": 3.9, "informes": 4.0, "accion": 0.90, "cumple": 0.80, "doc": 0.7},
    {"trato": 2.4, "informes": 3.5, "accion": 0.80, "cumple": 0.75, "doc": 0.6},   # buen control, mal trato
    {"trato": 4.0, "informes": 0.9, "accion": 0.35, "cumple": 0.45, "doc": 0.3},   # poco presente
]


def poisson(r, lam):
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= r.random()
        if p <= l:
            return k
        k += 1


class Command(BaseCommand):
    help = "Genera datos de demostración (usar --reset para borrar los datos operativos anteriores)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--dias", type=int, default=150)
        parser.add_argument("--semilla", type=int, default=42)

    def handle(self, *args, reset=False, dias=150, semilla=42, **opts):
        self.r = random.Random(semilla)
        self.hoy = timezone.localdate()
        self.inicio = self.hoy - timedelta(days=dias)
        with transaction.atomic():
            if reset:
                self.borrar()
            self.maestros()
            self.personas()
            self.flota()
            self.herramientas()
            self.capacitaciones()
            self.operacion()
            self.asistencia()
            self.cierres()
            self.supervision()
            self.siniestros()
            self.demanda()
            self.finanzas()
            self.equipos_retirados()
            self.tiempos_respuesta()
            self.historial()
        self.stdout.write(self.style.SUCCESS("Datos de demostración generados. Contraseña de todos: virguel2026"))

    # ------------------------------------------------------------------
    def borrar(self):
        from capacitacion.models import EvaluacionHistorica
        from personal.models import Asistencia, DocumentoPersonal, Feriado, Novedad, TipoDocumento
        EvaluacionHistorica.objects.all().delete()
        for m in (Asistencia, Novedad, DocumentoPersonal, TipoDocumento, Feriado):
            m.objects.all().delete()
        from core.models import Notificacion
        from inventario.models import MovimientoStockTecnico, PedidoMaterial
        from supervision.models import EncuestaSemanal
        from core.models import RegistroAcceso
        from inventario.models import EquipoRetirado
        for m in (EquipoRetirado, MovimientoStockTecnico, PedidoMaterial, EncuestaSemanal, Notificacion, RegistroAcceso):
            m.objects.all().delete()
        for m in (Egreso, CostoFijo, Alerta, AccionCorrectiva, InformeControl, EncuestaSupervisor, TareaSupervisor,
                  Siniestro, Salida, LoteIngreso, DemandaComercial, RecetaMaterial, Participacion, Capacitacion,
                  EvaluacionCompetencia, Curso, Competencia, Asignacion, Elemento, Jornada, OrdenTrabajo,
                  ServiceRealizado, TipoService, Vehiculo, Cliente, Material, TipoTarea):
            m.objects.all().delete()
        Persona.objects.all().delete()
        Zona.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()
        User.objects.filter(username="admin").delete()

    def maestros(self):
        par = Parametros.actual()
        par.destinatarios_parte = "gerencia@virguel.demo"
        par.save()
        from personal.models import Feriado
        feriados = [("01-01", "Año Nuevo"), ("03-24", "Día de la Memoria"), ("04-02", "Malvinas"),
                    ("05-01", "Día del Trabajador"), ("05-25", "Revolución de Mayo"), ("06-20", "Día de la Bandera"),
                    ("07-09", "Día de la Independencia"), ("08-17", "Paso a la Inmortalidad de San Martín"),
                    ("10-12", "Diversidad Cultural"), ("11-20", "Soberanía Nacional"), ("12-08", "Inmaculada Concepción"),
                    ("12-25", "Navidad")]
        self.feriados = set()
        for anio in {self.inicio.year, self.hoy.year}:
            for md, nombre in feriados:
                f = timezone.datetime.strptime(f"{anio}-{md}", "%Y-%m-%d").date()
                Feriado.objects.get_or_create(fecha=f, defaults={"nombre": nombre})
                self.feriados.add(f)
        self.zonas = [Zona.objects.create(nombre=n, densidad_clientes_ha=Decimal(d)) for n, d in
                      [("Norte", "1.6"), ("Sur", "1.2"), ("Centro", "2.4"), ("Oeste", "1.0")]]
        tipos = [("INST-FO", "Instalación fibra óptica", 75, True), ("INST-TV", "Instalación TV", 60, True),
                 ("REP", "Reparación", 50, False), ("MUD", "Mudanza de servicio", 80, True),
                 ("RET", "Retiro de equipos", 30, False), ("REL", "Relevamiento técnico", 25, False)]
        self.tipos = {c: TipoTarea.objects.create(codigo=c, nombre=n, minutos_estandar=m,
                                                  puede_requerir_decodificador=d) for c, n, m, d in tipos}
        self.peso_tipos = [("INST-FO", 35), ("INST-TV", 15), ("REP", 30), ("MUD", 8), ("RET", 7), ("REL", 5)]
        mats = [("FO-DROP", "Cable drop fibra", "material", "m", 650, 2000),
                ("FO-CON", "Conector mecánico SC/APC", "material", "u", 1800, 300),
                ("FO-ROS", "Roseta óptica", "material", "u", 3500, 100),
                ("ONT", "ONT / módem fibra", "equipo", "u", 48000, 40),
                ("DECO-HD", "Decodificador TV HD", "equipo", "u", 39000, 40),
                ("GRAMPA", "Grampa de sujeción", "material", "u", 120, 1500),
                ("COAX", "Cable coaxial RG6", "material", "m", 900, 300),
                ("PRECINTO", "Precinto plástico", "material", "u", 40, 2000),
                ("AMP", "Amplificador de señal", "equipo", "u", 52000, 3),
                ("DECO-SD", "Decodificador SD (modelo anterior)", "equipo", "u", 21000, 0)]
        self.mat = {c: Material.objects.create(codigo=c, nombre=n, categoria=cat, unidad=u,
                                               costo_unitario=Decimal(costo), stock_minimo=Decimal(minimo),
                                               es_decodificador=(c == "DECO-HD"))
                    for c, n, cat, u, costo, minimo in mats}
        recetas = {"INST-FO": [("FO-DROP", 60), ("FO-CON", 2), ("FO-ROS", 1), ("ONT", 1), ("GRAMPA", 25),
                               ("PRECINTO", 10)],
                   "INST-TV": [("COAX", 25), ("GRAMPA", 15), ("PRECINTO", 6)],
                   "REP": [("FO-CON", 1.2), ("FO-DROP", 12), ("GRAMPA", 5), ("PRECINTO", 4)],
                   "MUD": [("FO-DROP", 50), ("FO-CON", 2), ("FO-ROS", 1), ("GRAMPA", 20), ("PRECINTO", 8)],
                   "RET": [], "REL": []}
        self.recetas = recetas
        for t, items in recetas.items():
            for c, q in items:
                RecetaMaterial.objects.create(tipo_tarea=self.tipos[t], material=self.mat[c], cantidad=Decimal(str(q)))
        self.clientes = Cliente.objects.bulk_create([
            Cliente(numero=f"C{i:06d}", nombre=f"{self.r.choice(APELLIDOS)} {self.r.choice(NOMBRES)}",
                    direccion=f"Calle {self.r.randint(1, 180)} N° {self.r.randint(100, 4999)}",
                    zona=self.r.choice(self.zonas),
                    tipo=self.r.choices(["residencial", "moderno", "comercial"], [55, 35, 10])[0],
                    cantidad_televisores=self.r.choices([1, 2, 3], [50, 35, 15])[0],
                    telefono=f"11{self.r.randint(40000000, 69999999)}") for i in range(1, 2501)])

    def personas(self):
        r = self.r
        hash_ = make_password("virguel2026")
        from django.core.management import call_command
        call_command("configurar_grupos", stdout=self.stdout)
        User.objects.create(username="admin", password=hash_, is_superuser=True, is_staff=True,
                            first_name="Administrador")
        ger = User.objects.create(username="gerencia", password=hash_, is_staff=True, first_name="Gerencia")
        ger.groups.add(Group.objects.get(name="Gerencia"))
        ger.user_permissions.set([])
        usados = set()

        def nombre():
            while True:
                n, a = r.choice(NOMBRES), r.choice(APELLIDOS)
                if (n, a) not in usados:
                    usados.add((n, a))
                    return n, a

        self.sups = []
        for i, perfil in enumerate(SUPERVISORES, 1):
            n, a = nombre()
            u = User.objects.create(username=f"s{i:03d}", password=hash_, first_name=n, last_name=a)
            u.groups.add(Group.objects.get(name="Supervisores"))
            p = Persona.objects.create(legajo=f"S{i:03d}", nombre=n, apellido=a, rol="supervisor",
                                       email=f"supervisor{i}@virguel.demo",
                                       hora_entrada=timezone.datetime(2000, 1, 1, 7, 30).time(),
                                       hora_salida=timezone.datetime(2000, 1, 1, 16, 30).time(),
                                       zona=self.zonas[(i - 1) % len(self.zonas)], usuario=u,
                                       fecha_ingreso=self.hoy - timedelta(days=r.randint(700, 3000)))
            p.perfil = perfil
            self.sups.append(p)
        self.tecs = []
        perfiles = REPARTO[:]
        r.shuffle(perfiles)
        for i, perfil in enumerate(perfiles, 1):
            n, a = nombre()
            u = User.objects.create(username=f"t{i:03d}", password=hash_, first_name=n, last_name=a)
            u.groups.add(Group.objects.get(name="Técnicos"))
            sup = self.sups[(i - 1) % len(self.sups)]
            ingreso = (self.hoy - timedelta(days=r.randint(25, 50)) if perfil == "nuevo"
                       else self.hoy - timedelta(days=r.randint(200, 2500)))
            p = Persona.objects.create(legajo=f"T{i:03d}", nombre=n, apellido=a, rol="tecnico", supervisor=sup,
                                       zona=sup.zona, usuario=u, fecha_ingreso=ingreso,
                                       telefono=f"11{r.randint(40000000, 69999999)}")
            p.perfil = perfil
            p.prod_individual = r.uniform(0.9, 1.1)
            self.tecs.append(p)
        self.perfil_de = {t.id: t.perfil for t in self.tecs}
        # usuarios demo: aviso de privacidad ya aceptado (para poder recorrer la app directo)
        from core.models import CuentaUsuario
        CuentaUsuario.objects.bulk_create([CuentaUsuario(usuario=u, acepto_privacidad=timezone.now())
                                           for u in User.objects.all()], ignore_conflicts=True)
        # fecha de capacitación en producción para 'capacitar' (hace poco, aún sin efecto), 'mejora' y 'riesgo'
        self.fecha_cap = {}
        for t in self.tecs:
            if t.perfil == "mejora":
                self.fecha_cap[t.id] = self.hoy - timedelta(days=r.randint(45, 60))
            elif t.perfil == "riesgo":
                self.fecha_cap[t.id] = self.hoy - timedelta(days=r.randint(50, 70))

    def asistencia(self):
        """Fichadas y novedades derivadas de las jornadas simuladas + supervisores y administración."""
        from datetime import datetime, time as hora

        from personal.models import Asistencia, DocumentoPersonal, Novedad, TipoDocumento
        r = self.r
        tz = timezone.get_current_timezone()
        tarde_prob = {"bueno": .04, "capacitar": .06, "riesgo": .22, "nuevo": .08, "mejora": .05}
        injust_prob = {"bueno": .08, "capacitar": .1, "riesgo": .55, "nuevo": .15, "mejora": .1}

        def fichada(p, fecha, prob_tarde, salida=True):
            base = datetime.combine(fecha, p.hora_entrada, tz)
            if r.random() < prob_tarde:
                entrada = base + timedelta(minutes=r.randint(12, 70))
            else:
                entrada = base - timedelta(minutes=r.randint(0, 15)) + timedelta(minutes=r.choice([0, 0, 0, 5, 8]))
            fin = datetime.combine(fecha, p.hora_salida, tz)
            sal = fin + timedelta(minutes=r.randint(-10, 25)) + (timedelta(hours=r.randint(1, 3)) if r.random() < .12 else timedelta())
            lat, lng = Decimal(str(round(-34.6 + r.uniform(-.2, .2), 6))), Decimal(str(round(-58.4 + r.uniform(-.2, .2), 6)))
            a = Asistencia(persona=p, fecha=fecha, entrada=entrada, salida=sal if salida else None,
                           lat_entrada=lat, lng_entrada=lng, lat_salida=lat if salida else None,
                           lng_salida=lng if salida else None)
            a.calcular(self.param)
            return a

        self.param = Parametros.actual()
        tec = {t.id: t for t in self.tecs}
        # 2 técnicos que hoy no ficharon y no avisaron (para ver el control en vivo)
        hoy_jor = list(Jornada.objects.filter(fecha=self.hoy, en_calle=True).values_list("id", "tecnico_id"))
        faltan_hoy = {tid for _, tid in r.sample(hoy_jor, 2)} if len(hoy_jor) > 2 else set()
        Jornada.objects.filter(fecha=self.hoy, tecnico_id__in=faltan_hoy).delete()
        OrdenTrabajo.objects.filter(tecnico_id__in=faltan_hoy, fecha_programada=self.hoy,
                                    estado="completada").update(estado="asignada", fecha_ejecucion=None)
        asis, novs = [], []
        for j in Jornada.objects.all().only("tecnico_id", "fecha", "en_calle", "motivo_ausencia"):
            t = tec[j.tecnico_id]
            if j.en_calle:
                asis.append(fichada(t, j.fecha, tarde_prob[t.perfil], salida=j.fecha != self.hoy))
            else:
                if r.random() < injust_prob[t.perfil]:
                    tipo, estado = "injustificada", "aprobada"
                else:
                    tipo = {"Enfermedad": "enfermedad", "Licencia": "licencia", "Franco": "franco"}.get(j.motivo_ausencia, "licencia")
                    estado = "pendiente" if j.fecha >= self.hoy - timedelta(days=2) else "aprobada"
                novs.append(Novedad(persona=t, tipo=tipo, desde=j.fecha, hasta=j.fecha, estado=estado,
                                    certificado="certificados/demo.jpg" if tipo == "enfermedad" and r.random() < .7 else "",
                                    cargada_por=t, observaciones="" if tipo != "enfermedad" else "Reposo médico"))
        # vacaciones: un par de técnicos de vacaciones esta semana
        for t in r.sample(self.tecs, 2):
            novs.append(Novedad(persona=t, tipo="vacaciones", desde=self.hoy - timedelta(days=2),
                                hasta=self.hoy + timedelta(days=8), estado="aprobada", cargada_por=t))
            Jornada.objects.filter(tecnico=t, fecha__gte=self.hoy - timedelta(days=2)).delete()
            Asistencia.objects.filter(persona=t, fecha__gte=self.hoy - timedelta(days=2)).delete()
            asis = [a for a in asis if not (a.persona_id == t.id and a.fecha >= self.hoy - timedelta(days=2))]
        # supervisores y personal administrativo
        admins = []
        for i in range(1, 5):
            n, a = r.choice(NOMBRES), r.choice(APELLIDOS)
            admins.append(Persona.objects.create(
                legajo=f"A{i:03d}", nombre=n, apellido=a, rol="administrativo", trabaja_sabados=False,
                hora_entrada=hora(9, 0), hora_salida=hora(18, 0),
                fecha_ingreso=self.hoy - timedelta(days=r.randint(300, 3000))))
        for d in range((self.hoy - self.inicio).days + 1):
            f = self.inicio + timedelta(days=d)
            if f.weekday() == 6 or f in self.feriados:
                continue
            for p in self.sups + admins:
                if f.weekday() == 5 and not p.trabaja_sabados:
                    continue
                if r.random() < .04:
                    novs.append(Novedad(persona=p, tipo=r.choice(["enfermedad", "licencia", "franco"]), desde=f,
                                        hasta=f, estado="aprobada", cargada_por=p))
                    continue
                asis.append(fichada(p, f, .05 if p.rol == "administrativo" else .03, salida=f != self.hoy))
        Asistencia.objects.bulk_create(asis, batch_size=5000)
        Novedad.objects.bulk_create(novs, batch_size=2000)
        # egresos del último año (rotación)
        motivos = ["renuncia", "renuncia", "renuncia", "despido", "fin_contrato", "despido_causa"]
        for i, m in enumerate(motivos, 1):
            ingreso = self.hoy - timedelta(days=r.randint(200, 1200))
            Persona.objects.create(legajo=f"E{i:03d}", nombre=r.choice(NOMBRES), apellido=r.choice(APELLIDOS),
                                   rol="tecnico", activo=False, fecha_ingreso=ingreso, motivo_egreso=m,
                                   fecha_egreso=self.hoy - timedelta(days=r.randint(10, 350)))
        # documentación con vencimiento
        tipos = [TipoDocumento.objects.create(nombre="Registro de conducir", obligatorio_tecnicos=True,
                                              obligatorio_supervisores=True, dias_aviso=30),
                 TipoDocumento.objects.create(nombre="Apto médico anual", obligatorio_tecnicos=True,
                                              obligatorio_supervisores=True, dias_aviso=30),
                 TipoDocumento.objects.create(nombre="Certificado de trabajo en altura", obligatorio_tecnicos=True,
                                              dias_aviso=45),
                 TipoDocumento.objects.create(nombre="DNI", dias_aviso=0)]
        docs = []
        for p in self.tecs + self.sups:
            malo = getattr(p, "perfil", "bueno") == "riesgo"
            for t in tipos[:3]:
                if t.nombre.startswith("Certificado") and p.rol != "tecnico":
                    continue
                if r.random() < (.25 if malo else .03):
                    continue  # nunca lo presentó
                venc = self.hoy + timedelta(days=r.randint(-40, 20) if (malo or r.random() < .08) else r.randint(25, 700))
                docs.append(DocumentoPersonal(persona=p, tipo=t, numero=str(r.randint(10000000, 45000000)),
                                              vencimiento=venc, emision=venc - timedelta(days=365)))
            docs.append(DocumentoPersonal(persona=p, tipo=tipos[3], numero=str(r.randint(20000000, 45000000))))
        DocumentoPersonal.objects.bulk_create(docs)
        self.stdout.write(f"  {len(asis)} fichadas, {len(novs)} novedades, {len(docs)} documentos")

    def cierres(self):
        """Datos de cierre de los últimos 45 días (desde que se 'lanzó' el cierre completo en la app):
        hora de inicio de cada trabajo, foto, conformidad, firma y ubicación GPS."""
        from datetime import datetime

        from personal.models import Asistencia
        r = self.r
        tz = timezone.get_current_timezone()
        lanzamiento = self.hoy - timedelta(days=45)
        prob_doc = {"bueno": .92, "capacitar": .88, "riesgo": .45, "nuevo": .8, "mejora": .9}
        prob_sitio = {"bueno": .97, "capacitar": .95, "riesgo": .7, "nuevo": .95, "mejora": .96}
        arranque = {"bueno": (10, 35), "capacitar": (20, 50), "riesgo": (40, 95), "nuevo": (20, 50), "mejora": (15, 40)}
        # coordenadas de clientes alrededor del centro de su zona
        centros = {z.id: (-34.6 + r.uniform(-.15, .15), -58.45 + r.uniform(-.15, .15)) for z in self.zonas}
        clientes = list(Cliente.objects.all())
        for c in clientes:
            la, lo = centros.get(c.zona_id, (-34.6, -58.45))
            c.latitud = Decimal(str(round(la + r.uniform(-.03, .03), 6)))
            c.longitud = Decimal(str(round(lo + r.uniform(-.03, .03), 6)))
        Cliente.objects.bulk_update(clientes, ["latitud", "longitud"], batch_size=2000)
        coords = {c.id: (c.latitud, c.longitud) for c in clientes}
        entradas = {(a.persona_id, a.fecha): a.entrada for a in Asistencia.objects.filter(fecha__gte=lanzamiento)}
        perfil = {t.id: t.perfil for t in self.tecs}
        cambiadas = []
        ordenes = (OrdenTrabajo.objects.filter(fecha_ejecucion__gte=lanzamiento, estado="completada", es_retrabajo=False)
                   .order_by("tecnico_id", "fecha_ejecucion", "id"))
        cursor_key, cursor = None, None
        for o in ordenes:
            pf = perfil.get(o.tecnico_id, "bueno")
            clave = (o.tecnico_id, o.fecha_ejecucion)
            if clave != cursor_key:
                cursor_key = clave
                ent = entradas.get(clave) or datetime.combine(o.fecha_ejecucion, datetime.min.time(), tz) + timedelta(hours=8)
                cursor = ent + timedelta(minutes=r.randint(*arranque[pf]))
            o.inicio_trabajo = cursor
            o.fin_trabajo = cursor + timedelta(minutes=o.minutos_reales or 45)
            cursor = o.fin_trabajo + timedelta(minutes=r.randint(10, 30))
            if r.random() < prob_doc[pf]:
                o.foto_trabajo = "ordenes/demo.jpg"
                o.conforme_nombre = f"{r.choice(NOMBRES)} {r.choice(APELLIDOS)}"
                o.conforme_dni = str(r.randint(20000000, 45000000))
                if r.random() < .7:
                    o.firma = "firmas/demo.png"
            if o.cliente_id in coords and r.random() < .95:
                la, lo = coords[o.cliente_id]
                lejos = r.random() > prob_sitio[pf]
                d = .01 if lejos else .0008  # ~1 km vs ~90 m
                o.lat_cierre = la + Decimal(str(round(r.uniform(-d, d), 6)))
                o.lng_cierre = lo + Decimal(str(round(r.uniform(-d, d), 6)))
            cambiadas.append(o)
        OrdenTrabajo.objects.bulk_update(cambiadas, ["inicio_trabajo", "fin_trabajo", "foto_trabajo", "conforme_nombre",
                                                     "conforme_dni", "firma", "lat_cierre", "lng_cierre"], batch_size=2000)
        self.stdout.write(f"  {len(cambiadas)} cierres con datos completos (últimos 45 días)")

    def equipos_retirados(self):
        """Equipos retirados a clientes (órdenes de retiro de los últimos 30 días): la mayoría ya
        entregados al depósito; algunos pendientes, más en los técnicos de riesgo."""
        from datetime import datetime

        from inventario.models import EquipoRetirado
        from inventario.stock_tecnico import consumir
        r = self.r
        tz = timezone.get_current_timezone()
        pendiente = {"bueno": .04, "capacitar": .08, "riesgo": .6, "nuevo": .15, "mejora": .05}
        equipos = []
        for o in OrdenTrabajo.objects.filter(tipo__codigo="RET", estado="completada",
                                             fecha_ejecucion__gte=self.hoy - timedelta(days=30)).select_related("tecnico"):
            serie = f"{r.choice(['DCO', 'ONT', 'DCH'])}{r.randint(100000, 999999)}"
            o.series_retiradas = serie
            o.save(update_fields=["series_retiradas"])
            pf = getattr(o.tecnico, "perfil", None) or self.perfil_de.get(o.tecnico_id, "bueno")
            sigue = r.random() < pendiente.get(pf, .1) and o.fecha_ejecucion < self.hoy
            devuelto = None if sigue else datetime.combine(
                min(self.hoy, o.fecha_ejecucion + timedelta(days=r.choice([0, 1, 1, 2]))), datetime.min.time(), tz
            ) + timedelta(hours=17)
            equipos.append(EquipoRetirado(orden=o, tecnico=o.tecnico, numero_serie=serie, fecha_retiro=o.fecha_ejecucion,
                                          estado="en_tecnico" if sigue else "devuelto", devuelto=devuelto,
                                          material=self.mat["DECO-HD" if serie.startswith("D") else "ONT"]))
        EquipoRetirado.objects.bulk_create(equipos)
        # dos técnicos usaron partes que no figuraban a su cargo (falta registrar la entrega)
        for t in r.sample([t for t in self.tecs if t.perfil != "riesgo"], 2):
            consumir(t, None, self.mat["FO-ROS"], Decimal("40"), self.hoy - timedelta(days=r.randint(3, 9)))
        self.stdout.write(f"  {len(equipos)} equipos retirados ({sum(1 for e in equipos if e.estado == 'en_tecnico')} sin devolver)")

    def tiempos_respuesta(self):
        """Cuándo se cargó y cuándo resolvió el supervisor cada aviso y pedido."""
        from datetime import datetime

        from inventario.models import PedidoMaterial
        from personal.models import Novedad
        r = self.r
        tz = timezone.get_current_timezone()
        demora = {}  # supervisor -> (min, max) horas
        for s_ in self.sups:
            demora[s_.id] = (20, 70) if s_.perfil["informes"] < 2 else (1, 10)
        novs = list(Novedad.objects.select_related("persona"))
        for n in novs:
            n.creada = datetime.combine(n.desde, datetime.min.time(), tz) + timedelta(hours=r.randint(6, 9))
            if n.estado != "pendiente":
                lo, hi = demora.get(n.persona.supervisor_id, (2, 12))
                n.resuelta = n.creada + timedelta(hours=r.uniform(lo, hi))
        Novedad.objects.bulk_update(novs, ["creada", "resuelta"], batch_size=2000)
        peds = list(PedidoMaterial.objects.select_related("tecnico"))
        for p in peds:
            p.creado = timezone.now() - timedelta(hours=r.randint(2, 30))
            if p.estado != "pendiente":
                lo, hi = demora.get(p.tecnico.supervisor_id, (2, 12))
                p.resuelto = p.creado + timedelta(hours=r.uniform(lo, min(hi, 20)))
        PedidoMaterial.objects.bulk_update(peds, ["creado", "resuelto"])

    def flota(self):
        r = self.r
        marcas = [("Renault", "Kangoo"), ("Fiat", "Fiorino"), ("Peugeot", "Partner"), ("Toyota", "Hilux"),
                  ("Volkswagen", "Saveiro")]
        self.tipos_service = [
            TipoService.objects.create(nombre="Cambio de aceite y filtros", cada_km=10000, cada_dias=180,
                                       costo_estimado=Decimal("95000")),
            TipoService.objects.create(nombre="Service general", cada_km=30000, cada_dias=365,
                                       costo_estimado=Decimal("380000")),
            TipoService.objects.create(nombre="Neumáticos", cada_km=45000, costo_estimado=Decimal("620000")),
        ]
        self.vehiculos = []
        for i in range(18):
            m = r.choice(marcas)
            km = r.randint(30000, 160000)
            v = Vehiculo.objects.create(
                patente=f"A{chr(65 + i)}{r.randint(100, 999)}{chr(65 + r.randint(0, 25))}{chr(65 + r.randint(0, 25))}",
                marca=m[0], modelo=m[1], anio=r.randint(2015, 2024), km_actual=km,
                estado="taller" if i == 16 else "fuera" if i == 17 else "operativo",
                asignado_a=self.tecs[i * 2] if i < 16 else None,
                vencimiento_vtv=self.hoy + timedelta(days=r.randint(-5, 330)),
                vencimiento_seguro=self.hoy + timedelta(days=r.randint(5, 360)))
            v.km_dia = r.uniform(55, 95)
            self.vehiculos.append(v)
            # historial de services
            for ts in self.tipos_service:
                atraso = r.uniform(0.3, 1.08)  # algunos quedan vencidos
                km_serv = int(km - ts.cada_km * atraso)
                if km_serv <= 0:
                    continue
                dias = int(ts.cada_km * atraso / v.km_dia)
                fecha = self.hoy - timedelta(days=min(dias, (ts.cada_dias or 9999) - r.randint(-20, 60)))
                ServiceRealizado.objects.create(vehiculo=v, tipo=ts, fecha=fecha, km=km_serv,
                                                costo=ts.costo_estimado * Decimal(str(round(r.uniform(.85, 1.25), 2))),
                                                taller=r.choice(["Taller Ruta 8", "Lubricentro Sur", "Concesionario"]))

    def herramientas(self):
        r = self.r
        els = [("CASCO", "Casco con barbijo", "epp", 730, True, 18000), ("GUANTE", "Guantes dieléctricos", "epp", 180, True, 22000),
               ("ARNES", "Arnés de seguridad", "epp", 365, True, 95000), ("CALZ", "Calzado de seguridad", "epp", 365, True, 70000),
               ("ANTEOJO", "Anteojos de protección", "epp", 180, True, 9000), ("CHALECO", "Chaleco reflectivo", "epp", 365, True, 12000),
               ("ESCALERA", "Escalera telescópica", "herramienta", None, True, 260000),
               ("KIT", "Kit de herramientas", "herramienta", None, True, 140000),
               ("EMPALM", "Empalmadora de fibra", "critico", None, False, 2400000),
               ("POWER", "Medidor de potencia óptica", "critico", None, False, 380000)]
        self.elementos = [Elemento.objects.create(codigo=c, nombre=n, tipo=t, vida_util_dias=v, obligatorio_tecnicos=o,
                                                  costo=Decimal(costo), stock=r.randint(1, 15))
                          for c, n, t, v, o, costo in els]
        asigs = []
        for t in self.tecs:
            ok = PERFILES[t.perfil]["epp_ok"]
            for el in self.elementos:
                if not el.obligatorio_tecnicos:
                    continue
                base = max(t.fecha_ingreso, self.inicio - timedelta(days=200))
                if el.vida_util_dias:
                    # entrega reciente si 'cumple', vieja (vencida) si no
                    if r.random() < ok:
                        fecha = self.hoy - timedelta(days=r.randint(5, max(6, el.vida_util_dias - 12)))
                    else:
                        fecha = self.hoy - timedelta(days=el.vida_util_dias + r.randint(5, 90))
                else:
                    fecha = base + timedelta(days=r.randint(0, 30))
                fecha = max(fecha, t.fecha_ingreso)
                if r.random() > ok and el.tipo == "herramienta":
                    continue  # nunca se le entregó
                asigs.append(Asignacion(persona=t, elemento=el, fecha_entrega=fecha, conformidad_firmada=r.random() < .85,
                                        fecha_vencimiento=fecha + timedelta(days=el.vida_util_dias) if el.vida_util_dias else None))
            if t.perfil == "riesgo":
                asigs.append(Asignacion(persona=t, elemento=self.elementos[6], estado="perdido",
                                        fecha_entrega=self.hoy - timedelta(days=r.randint(30, 150))))
        Asignacion.objects.bulk_create(asigs)
        for el in self.elementos[:2]:
            el.stock = 2
            el.save()

    def capacitaciones(self):
        r = self.r
        comps = {n: Competencia.objects.create(nombre=n) for n in
                 ["Instalación FTTH", "Seguridad en altura", "Atención al cliente", "Diagnóstico de fallas"]}
        cursos = [Curso.objects.create(nombre="Instalación FTTH avanzada", competencia=comps["Instalación FTTH"], horas=8),
                  Curso.objects.create(nombre="Trabajo seguro en altura", competencia=comps["Seguridad en altura"],
                                       horas=4, obligatorio=True),
                  Curso.objects.create(nombre="Trato con el cliente", competencia=comps["Atención al cliente"], horas=3),
                  Curso.objects.create(nombre="Acompañamiento en producción", competencia=comps["Instalación FTTH"],
                                       horas=16)]
        for k in range(5):
            cap = Capacitacion.objects.create(curso=cursos[k % 3], fecha=self.inicio + timedelta(days=15 + k * 28),
                                              instructor="Instructor externo")
            for t in r.sample(self.tecs, 10):
                Participacion.objects.create(capacitacion=cap, persona=t, aprobado=r.random() < .9,
                                             nota=Decimal(str(round(r.uniform(5, 10), 1))))
        for tid, fecha in self.fecha_cap.items():
            cap = Capacitacion.objects.create(curso=cursos[3], fecha=fecha, en_produccion=True,
                                              instructor="Supervisor de calidad")
            Participacion.objects.create(capacitacion=cap, persona_id=tid)
        for t in self.tecs:
            for c in comps.values():
                base = {"bueno": 4, "capacitar": 2, "riesgo": 2, "nuevo": 2, "mejora": 3}[t.perfil]
                EvaluacionCompetencia.objects.create(persona=t, competencia=c, nivel=max(1, min(5, base + r.randint(-1, 1))),
                                                     fecha=self.hoy - timedelta(days=r.randint(10, 120)))

    # ------------------------------------------------------------------
    def operacion(self):
        """Jornadas, órdenes y consumo de materiales con lotes FIFO simulados en memoria."""
        r = self.r
        jornadas, ordenes = [], []
        meta_ordenes = []  # (orden, tecnico, fecha, tipo_codigo, deco)
        veh_de = {v.asignado_a_id: v for v in self.vehiculos if v.asignado_a_id}
        km_actual = {v.id: v.km_actual - int(v.km_dia * (self.hoy - self.inicio).days) for v in self.vehiculos}
        n_ot = 0
        tipos_cod = [c for c, _ in self.peso_tipos]
        pesos = [w for _, w in self.peso_tipos]
        dias = (self.hoy - self.inicio).days
        for d in range(dias + 1):
            fecha = self.inicio + timedelta(days=d)
            if fecha.weekday() == 6 or fecha in self.feriados:  # domingo o feriado
                continue
            es_hoy = fecha == self.hoy
            for t in self.tecs:
                if fecha < t.fecha_ingreso:
                    continue
                if r.random() < 0.07:
                    jornadas.append(Jornada(fecha=fecha, tecnico=t, en_calle=False, zona=t.zona,
                                            motivo_ausencia=r.choice(["Enfermedad", "Licencia", "Franco", "Trámite"])))
                    continue
                pf = PERFILES[t.perfil]
                lam = pf["ots"] * t.prod_individual * (0.85 if fecha.weekday() == 5 else 1.0)
                if t.perfil == "nuevo":
                    antig = (fecha - t.fecha_ingreso).days
                    lam = 2.4 + min(1.0, antig / 60) * 2.0
                if t.perfil == "mejora" and fecha >= self.fecha_cap[t.id]:
                    lam = 5.3 * t.prod_individual
                if t.perfil == "riesgo" and fecha >= self.fecha_cap.get(t.id, self.hoy):
                    lam *= 0.92  # capacitado y no mejora
                v = veh_de.get(t.id)
                km_ini = km_fin = None
                if v:
                    km_ini = km_actual[v.id]
                    km_actual[v.id] += int(r.uniform(.7, 1.3) * v.km_dia)
                    km_fin = km_actual[v.id]
                jornadas.append(Jornada(fecha=fecha, tecnico=t, en_calle=True, zona=t.zona, vehiculo=v,
                                        km_inicio=km_ini, km_fin=None if es_hoy else km_fin,
                                        hectareas_cubiertas=Decimal("0") if es_hoy else Decimal(str(round(r.uniform(2.3, 3.2), 2))),
                                        horas_trabajadas=Decimal("8")))
                cant = poisson(r, lam)
                if es_hoy:
                    cant_hechas = cant // 2
                for k in range(cant + (2 if es_hoy else 0)):
                    n_ot += 1
                    cod = r.choices(tipos_cod, pesos)[0]
                    tipo = self.tipos[cod]
                    estado = "completada"
                    x = r.random()
                    if es_hoy and k >= cant_hechas:
                        estado = "asignada"
                    elif x < pf["fallida"]:
                        estado = "fallida"
                    elif x < pf["fallida"] + 0.06:
                        estado = "reprogramada"
                    deco = estado == "completada" and tipo.puede_requerir_decodificador and r.random() < 0.57
                    cli = r.choice(self.clientes)
                    o = OrdenTrabajo(numero=f"OT{n_ot:07d}", tipo=tipo, cliente=cli, zona=t.zona, tecnico=t,
                                     fecha_programada=fecha,
                                     fecha_ejecucion=None if estado == "asignada" else fecha, estado=estado,
                                     minutos_reales=int(tipo.minutos_estandar * r.uniform(.8, 1.35)
                                                        * (1.25 if t.perfil in ("capacitar", "nuevo") else 1))
                                     if estado == "completada" else None,
                                     decodificador_solicitado=deco,
                                     motivo_no_resuelto=r.choices(
                                         ["cliente_ausente", "falta_material", "problema_red", "direccion", "clima", "rechazo"],
                                         [40, 15 if t.perfil != "riesgo" else 30, 20, 8, 10, 7])[0]
                                     if estado in ("fallida", "reprogramada") else "",
                                     decodificadores_instalados=(2 if r.random() < .22 else 1) if deco else 0)
                    ordenes.append(o)
                    meta_ordenes.append((o, t, fecha, cod))
        # algunas OT pendientes para los próximos días
        for t in self.tecs:
            for k in range(r.randint(1, 3)):
                n_ot += 1
                cod = r.choices(tipos_cod, pesos)[0]
                ordenes.append(OrdenTrabajo(numero=f"OT{n_ot:07d}", tipo=self.tipos[cod], cliente=r.choice(self.clientes),
                                            zona=t.zona, tecnico=t, fecha_programada=self.hoy + timedelta(days=r.randint(1, 3)),
                                            estado="asignada"))
        # órdenes que entraron sin técnico asignado, para mañana (las reparte la asignación automática)
        manana = self.hoy + timedelta(days=1 if self.hoy.weekday() != 5 else 2)
        for k in range(150):
            n_ot += 1
            cod = r.choices(tipos_cod, pesos)[0]
            cli = r.choice(self.clientes)
            ordenes.append(OrdenTrabajo(numero=f"OT{n_ot:07d}", tipo=self.tipos[cod], cliente=cli, zona=cli.zona,
                                        fecha_programada=manana - timedelta(days=r.choice([0, 0, 0, 1, 2])),
                                        estado="pendiente"))
        Jornada.objects.bulk_create(jornadas, batch_size=2000)
        OrdenTrabajo.objects.bulk_create(ordenes, batch_size=2000)
        for v in self.vehiculos:
            v.km_actual = km_actual[v.id]
            v.save(update_fields=["km_actual"])
        self.stdout.write(f"  {len(jornadas)} jornadas, {len(ordenes)} órdenes")

        # Retrabajos: visitas posteriores para corregir trabajos de un técnico
        retrabajos = []
        for o, t, fecha, cod in meta_ordenes:
            if o.estado == "completada" and r.random() < PERFILES[t.perfil]["retrabajo"] and fecha < self.hoy - timedelta(days=3):
                n_ot += 1
                otro = r.choice(self.tecs)
                f2 = fecha + timedelta(days=r.randint(1, 10))
                if f2 > self.hoy:
                    continue
                retrabajos.append(OrdenTrabajo(numero=f"OT{n_ot:07d}", tipo=self.tipos["REP"], cliente=o.cliente,
                                               zona=o.zona, tecnico=otro, fecha_programada=f2, fecha_ejecucion=f2,
                                               estado="completada", es_retrabajo=True, orden_original=o,
                                               minutos_reales=r.randint(30, 70)))
        OrdenTrabajo.objects.bulk_create(retrabajos, batch_size=2000)
        self.stdout.write(f"  {len(retrabajos)} retrabajos")
        self.ordenes_meta = meta_ordenes

        # ---- Stock: compras semanales + consumo FIFO
        consumo_dia = defaultdict(lambda: defaultdict(Decimal))  # fecha -> material -> cantidad
        salidas = []
        for o, t, fecha, cod in meta_ordenes:
            if o.estado != "completada":
                continue
            for mc, q in self.recetas[cod]:
                if self.mat[mc].unidad == "u":  # equipos y piezas: unidades enteras
                    cant = Decimal(max(1, round(q * r.uniform(.8, 1.2))))
                else:
                    cant = Decimal(str(round(q * r.uniform(.8, 1.2)))) or Decimal("1")
                salidas.append((fecha, self.mat[mc], cant, t, o))
            if o.decodificadores_instalados:
                salidas.append((fecha, self.mat["DECO-HD"], Decimal(o.decodificadores_instalados), t, o))
        salidas.sort(key=lambda x: x[0])
        for f, m, c, _, _ in salidas:
            consumo_dia[f][m.codigo] += c
        prom_diario = defaultdict(Decimal)
        total_dias = max(1, len(consumo_dia))
        for f, mats in consumo_dia.items():
            for c, q in mats.items():
                prom_diario[c] += q / total_dias

        lotes = defaultdict(list)  # material -> [LoteIngreso]
        todos_lotes = []

        def comprar(material, fecha, cantidad, proveedor="Proveedor mayorista"):
            l = LoteIngreso(material=material, fecha=fecha, cantidad=cantidad, cantidad_disponible=cantidad,
                            costo_unitario=material.costo_unitario * Decimal(str(round(r.uniform(.95, 1.05), 2))),
                            proveedor=proveedor, remito=f"R-{r.randint(10000, 99999)}")
            lotes[material.codigo].append(l)
            todos_lotes.append(l)

        # stock inicial
        for c, m in self.mat.items():
            if prom_diario[c]:
                comprar(m, self.inicio, (prom_diario[c] * 20).quantize(Decimal("1")))
        # lotes que quedan parados (para mostrar el control de antigüedad)
        comprar(self.mat["DECO-SD"], self.hoy - timedelta(days=118), Decimal("140"), "Importador")
        comprar(self.mat["COAX"], self.hoy - timedelta(days=84), Decimal("2500"))
        comprar(self.mat["AMP"], self.hoy - timedelta(days=52), Decimal("25"))
        comprar(self.mat["FO-ROS"], self.hoy - timedelta(days=67), Decimal("400"))

        # Flujo real de partes: el depósito entrega cada lunes a cada técnico lo que va a usar en la
        # semana (+15 %); al cerrar cada orden el consumo se descuenta del stock del técnico.
        from inventario.models import MovimientoStockTecnico
        necesidad = defaultdict(Decimal)  # (lunes, tecnico_id, codigo) -> cantidad
        for f, m, cant, t, o in salidas:
            necesidad[(f - timedelta(days=f.weekday()), t.id, m.codigo)] += cant
        tec_por_id = {t.id: t for t in self.tecs}
        saldo = defaultdict(Decimal)  # (tecnico_id, codigo) -> cantidad
        objetos_salida, movimientos = [], []

        def sacar_de_lotes(m, cant, fecha):
            restante, costo = cant, Decimal("0")
            for l in lotes[m.codigo]:
                if restante <= 0:
                    break
                if l.cantidad_disponible <= 0 or l.fecha > fecha:
                    continue
                # el lote parado de roseta/coaxial no se usa (quedó en otro depósito)
                if l.fecha in (self.hoy - timedelta(days=67), self.hoy - timedelta(days=84)):
                    continue
                tomado = min(l.cantidad_disponible, restante)
                l.cantidad_disponible -= tomado
                restante -= tomado
                costo += tomado * l.costo_unitario
            return costo + max(restante, Decimal("0")) * m.costo_unitario

        def entregar_sim(t, m, cant, fecha):
            objetos_salida.append(Salida(material=m, fecha=fecha, cantidad=cant, tecnico=t, motivo="entrega",
                                         costo_total=sacar_de_lotes(m, cant, fecha)))
            movimientos.append(MovimientoStockTecnico(tecnico=t, material=m, fecha=fecha, tipo="entrega", cantidad=cant))
            saldo[(t.id, m.codigo)] += cant

        idx = 0
        acopio = self.hoy - timedelta(days=80)
        for d in range((self.hoy - self.inicio).days + 1):
            fecha = self.inicio + timedelta(days=d)
            if fecha.weekday() == 0 and fecha > self.inicio:  # compra los lunes
                for c, m in self.mat.items():
                    if not prom_diario[c] or c in ("DECO-SD", "AMP"):
                        continue
                    stock = sum(l.cantidad_disponible for l in lotes[c])
                    objetivo = prom_diario[c] * (Decimal("8") if c == "DECO-HD" and fecha > self.hoy - timedelta(days=21)
                                                 else Decimal("16"))
                    if stock < objetivo:
                        comprar(m, fecha, (objetivo - stock + prom_diario[c] * 6).quantize(Decimal("1")))
            if fecha.weekday() == 0 or fecha == self.inicio:  # entrega semanal a técnicos
                lunes_ = fecha - timedelta(days=fecha.weekday())
                for (lu, tid, cod), q in necesidad.items():
                    if lu != lunes_:
                        continue
                    falta = (q * Decimal("1.15") - saldo[(tid, cod)]).to_integral_value(rounding="ROUND_CEILING")
                    if falta > 0:
                        entregar_sim(tec_por_id[tid], self.mat[cod], falta, fecha)
            if fecha == acopio:  # técnicos que acumulan partes que no usan (para el control de partes paradas)
                for t in [t for t in self.tecs if t.perfil == "riesgo"]:
                    entregar_sim(t, self.mat["AMP"], Decimal("2"), fecha)
                    entregar_sim(t, self.mat["DECO-SD"], Decimal("3"), fecha)
            while idx < len(salidas) and salidas[idx][0] == fecha:
                f, m, cant, t, o = salidas[idx]
                idx += 1
                objetos_salida.append(Salida(material=m, fecha=f, cantidad=cant, tecnico=t, orden=o,
                                             costo_total=cant * m.costo_unitario, motivo="consumo",
                                             observaciones="Del stock del técnico"))
                movimientos.append(MovimientoStockTecnico(tecnico=t, material=m, fecha=f, tipo="consumo",
                                                          cantidad=-cant, orden=o))
                saldo[(t.id, m.codigo)] -= cant
        LoteIngreso.objects.bulk_create(todos_lotes, batch_size=2000)
        Salida.objects.bulk_create(objetos_salida, batch_size=5000)
        MovimientoStockTecnico.objects.bulk_create(movimientos, batch_size=5000)
        self.stdout.write(f"  {len(todos_lotes)} lotes de stock, {len(objetos_salida)} salidas, "
                          f"{len(movimientos)} movimientos de stock de técnicos")

    def supervision(self):
        r = self.r
        tecs_de = defaultdict(list)
        for t in self.tecs:
            tecs_de[t.supervisor_id].append(t)
        jornadas = defaultdict(set)
        for tid, f in Jornada.objects.filter(en_calle=True).values_list("tecnico_id", "fecha"):
            jornadas[f].add(tid)
        ots_de = defaultdict(list)
        for o, t, f, _ in self.ordenes_meta:
            ots_de[(t.id, f)].append(o)
        informes, acciones_pend, encuestas, tareas = [], [], [], []
        corregido = {}  # técnico -> fecha de su última acción correctiva
        frases_ok = ["Instalación prolija, cableado bien sujeto y rotulado.", "Trabajo correcto, cliente conforme.",
                     "Uso correcto de EPP, escalera bien asegurada.", "Vehículo en orden, materiales completos."]
        frases_mal = ["Cableado sin grampas, riesgo de desprendimiento.", "No usaba arnés trabajando en altura.",
                      "Conector mal armado, potencia fuera de rango.", "Dejó restos de material en la vivienda.",
                      "Trato inadecuado con el cliente, hubo queja."]
        comentarios_mal = ["Nos grita delante de los clientes.", "No atiende el teléfono cuando lo necesitamos.",
                           "Reparte mal el trabajo, siempre los mismos a las zonas lejanas."]
        comentarios_bien = ["Siempre ayuda cuando hay un problema.", "Explica bien lo que hay que hacer.", ""]
        for d in range((self.hoy - self.inicio).days + 1):
            fecha = self.inicio + timedelta(days=d)
            if fecha.weekday() == 6:
                continue
            for s in self.sups:
                pf = s.perfil
                equipo = [t for t in tecs_de[s.id] if t.id in jornadas[fecha]]
                if not equipo:
                    continue
                if fecha.weekday() < 5:
                    for desc, meta in [("Controles de calidad en calle", 4), ("Revisar EPP del equipo", None)]:
                        estado = "pendiente" if fecha == self.hoy else (
                            "cumplida" if r.random() < pf["cumple"] else r.choice(["parcial", "no_cumplida"]))
                        res = None
                        if meta and fecha != self.hoy:
                            res = meta if estado == "cumplida" else (r.randint(1, meta - 1) if estado == "parcial" else 0)
                        tareas.append(TareaSupervisor(supervisor=s, fecha=fecha, descripcion=desc, meta=meta,
                                                      resultado=res, estado=estado))
                for _ in range(poisson(r, pf["informes"])):
                    t = r.choice(equipo)
                    prob = PERFILES[t.perfil]["desvio"]
                    # una corrección reciente reduce los desvíos (salvo en los técnicos de riesgo)
                    ult = corregido.get(t.id)
                    if ult and 0 < (fecha - ult).days <= 30 and t.perfil != "riesgo":
                        prob *= 0.3
                    desvio = r.random() < prob
                    puntaje = r.randint(1, 3) if desvio else r.randint(4, 5)
                    doc = r.random() < pf["doc"]
                    ots = ots_de.get((t.id, fecha))
                    inf = InformeControl(supervisor=s, tecnico=t, fecha=fecha, tipo=r.choice(InformeControl.Tipo.values),
                                         puntaje=puntaje, desvio_detectado=desvio,
                                         descripcion=(r.choice(frases_mal) if desvio else r.choice(frases_ok)) +
                                         (" Se conversó con el técnico en el lugar y se dejó registro fotográfico."
                                          if doc else ""),
                                         foto="informes/demo.jpg" if doc else "",
                                         latitud=Decimal(str(round(-34.6 + r.uniform(-.2, .2), 6))) if doc or r.random() < .5 else None,
                                         longitud=Decimal(str(round(-58.4 + r.uniform(-.2, .2), 6))) if doc or r.random() < .5 else None,
                                         orden=r.choice(ots) if ots and doc else None,
                                         creado=timezone.make_aware(timezone.datetime.combine(fecha, timezone.datetime.min.time()))
                                         + timedelta(hours=r.randint(9, 17)))
                    informes.append(inf)
                    if desvio and r.random() < pf["accion"] and fecha < self.hoy:
                        tipo = r.choices(["recapacitacion", "charla", "apercibimiento", "multa", "suspension"],
                                         [30, 30, 25, 12, 3] if t.perfil != "riesgo" else [15, 15, 40, 22, 8])[0]
                        f_acc = fecha + timedelta(days=r.choice([0, 1, 1, 1, 2, 3, 5]))
                        acciones_pend.append((inf, t, s, tipo, f_acc))
                        corregido[t.id] = f_acc
                for t in equipo:
                    if fecha == self.hoy:
                        continue
                    respondio = r.random() < 0.72
                    def nota(base):
                        return max(1, min(5, round(r.gauss(base, 0.7))))
                    malo = pf["trato"] < 3
                    encuestas.append(EncuestaSupervisor(
                        fecha=fecha, tecnico=t, supervisor=s,
                        respondida=timezone.make_aware(timezone.datetime.combine(fecha, timezone.datetime.min.time()))
                        + timedelta(hours=19) if respondio else None,
                        trato=nota(pf["trato"]) if respondio else None,
                        claridad=nota(pf["trato"] + (0.6 if malo else 0)) if respondio else None,
                        apoyo=nota(pf["trato"] - 0.1) if respondio else None,
                        presencia=nota(pf["trato"] if pf["informes"] > 2 else 2.6) if respondio else None,
                        comentario=(r.choice(comentarios_mal if malo else comentarios_bien)
                                    if respondio and r.random() < .08 else "")))
        InformeControl.objects.bulk_create(informes, batch_size=2000)
        AccionCorrectiva.objects.bulk_create([
            AccionCorrectiva(informe=inf, tecnico=t, aplicada_por=s, tipo=tipo, fecha=min(f, self.hoy),
                             monto=Decimal(r.choice([15000, 25000, 40000])) if tipo == "multa" else Decimal("0"),
                             descripcion="Acción por desvío detectado en control.", cumplida=True)
            for inf, t, s, tipo, f in acciones_pend], batch_size=2000)
        EncuestaSupervisor.objects.bulk_create(encuestas, batch_size=5000)
        TareaSupervisor.objects.bulk_create(tareas, batch_size=2000)
        # Evaluación semanal al supervisor (≈65 % de los técnicos la responde cada semana)
        from supervision.models import EncuestaSemanal
        semanales = []
        lunes_ = self.inicio + timedelta(days=(7 - self.inicio.weekday()) % 7)
        while lunes_ <= self.hoy:
            trabajaron = set()
            for k in range(6):
                trabajaron |= jornadas.get(lunes_ + timedelta(days=k), set())
            for s_ in self.sups:
                base = s_.perfil["trato"]
                for t in tecs_de[s_.id]:
                    if t.id not in trabajaron or r.random() > .65 or (lunes_ == self.hoy - timedelta(days=self.hoy.weekday()) and r.random() < .5):
                        continue
                    n = lambda ajuste=0: max(1, min(5, round(r.gauss(base + ajuste, .7))))
                    semanales.append(EncuestaSemanal(
                        semana=lunes_, tecnico=t, supervisor=s_, general=n(), trato=n(), organizacion=n(.2),
                        apoyo=n(), ensenanza=n(-.2 if s_.perfil["informes"] < 2 else .1), justicia=n(),
                        lo_mejor="" if r.random() < .8 else r.choice(["Nos ayudó con una instalación difícil.", "Buena organización de la semana."]),
                        a_mejorar="" if r.random() < .8 else r.choice(comentarios_mal if base < 3 else ["Más presencia en calle."])))
            lunes_ += timedelta(days=7)
        EncuestaSemanal.objects.bulk_create(semanales, batch_size=2000)
        # Pedidos de partes en curso
        from inventario.models import PedidoItem, PedidoMaterial
        for t in r.sample(self.tecs, 6):
            ped = PedidoMaterial.objects.create(tecnico=t, motivo="Para mis órdenes asignadas",
                                                estado=r.choice(["pendiente", "pendiente", "aprobado"]))
            if ped.estado == "aprobado":
                ped.aprobado_por = t.supervisor
                ped.save()
            for c in r.sample(["FO-CON", "FO-ROS", "ONT", "DECO-HD", "GRAMPA"], 2):
                PedidoItem.objects.create(pedido=ped, material=self.mat[c], cantidad=Decimal(r.choice([2, 5, 10, 20])))
        self.stdout.write(f"  {len(informes)} informes, {len(acciones_pend)} acciones, {len(encuestas)} encuestas")

    def siniestros(self):
        r = self.r
        jornadas = list(Jornada.objects.filter(en_calle=True).values_list("tecnico_id", "fecha"))
        tec = {t.id: t for t in self.tecs}
        n = 0
        for tid, fecha in jornadas:
            t = tec[tid]
            if r.random() >= PERFILES[t.perfil]["siniestro"]:
                continue
            n += 1
            tipo = r.choices(["rotura_vivienda", "cano_pinchado", "cableado", "vehiculo", "lesion", "otro"],
                             [35, 25, 15, 12, 5, 8])[0]
            grav = r.choices(["leve", "grave", "critica"], [45, 45, 10])[0]
            costo = {"leve": (20000, 90000), "grave": (90000, 600000), "critica": (500000, 3000000)}[grav]
            est = Decimal(r.randint(*costo))
            dias = (self.hoy - fecha).days
            cerrado = dias > 25 and r.random() < .85
            resol = r.choice(["reparacion", "acuerdo", "seguro"]) if cerrado else "pendiente"
            Siniestro.objects.create(
                numero=f"S-{fecha:%Y}-{n:05d}", fecha=fecha, tipo=tipo, gravedad=grav,
                responsabilidad_civil=r.random() < .85, tecnico=t, supervisor=t.supervisor, zona=t.zona,
                direccion=f"Calle {r.randint(1, 180)} N° {r.randint(100, 4999)}",
                descripcion={"rotura_vivienda": "Rotura de revestimiento al pasar cableado.",
                             "cano_pinchado": "Perforación de caño de agua al fijar soporte.",
                             "cableado": "Corte accidental de cableado de otra prestadora.",
                             "vehiculo": "Choque leve con vehículo de la empresa.",
                             "lesion": "Caída de escalera durante instalación.",
                             "otro": "Daño a mobiliario del cliente."}[tipo],
                causa_raiz=r.choice(["Apuro por cantidad de órdenes", "Falta de detector de cañerías",
                                     "No siguió el procedimiento", "Falta de capacitación"]),
                plan_accion="Recapacitación del técnico y revisión del procedimiento." if cerrado else "",
                costo_estimado=est, costo_real=(est * Decimal(str(round(r.uniform(.7, 1.3), 2)))) if cerrado else 0,
                monto_recuperado=(est * Decimal("0.6")) if resol == "seguro" else 0,
                estado="cerrado" if cerrado else r.choice(["abierto", "en_gestion", "legal"]),
                resolucion=resol, fecha_cierre=fecha + timedelta(days=r.randint(10, 25)) if cerrado else None,
                reportado_por=t)
        self.stdout.write(f"  {n} siniestros")

    def demanda(self):
        r = self.r
        tec_activos = len(self.tecs)
        dem = []
        for d in range(0, 30):
            f = self.hoy + timedelta(days=d)
            if f.weekday() == 6:
                continue
            # campaña comercial la semana 2: picos por encima de la capacidad
            factor = 1.3 if 7 <= d <= 12 else 0.78
            total = int(tec_activos * 0.93 * 5.0 * factor * r.uniform(.9, 1.1))
            for cod, w in self.peso_tipos:
                cant = round(total * w / 100)
                if cant:
                    dem.append(DemandaComercial(fecha=f, zona=r.choice(self.zonas), tipo_tarea=self.tipos[cod],
                                                cantidad_clientes=cant))
        DemandaComercial.objects.bulk_create(dem)

    def historial(self):
        """Fotos semanales de la evaluación (lunes) para ver la evolución a largo plazo."""
        from capacitacion.evaluacion import guardar_historial
        f = self.inicio + timedelta(days=60)
        f += timedelta(days=(7 - f.weekday()) % 7)
        n = 0
        while f <= self.hoy:
            guardar_historial(f)
            n += 1
            f += timedelta(days=7)
        self.stdout.write(f"  {n} semanas de historial de evaluación")

    def finanzas(self):
        cats = {c: CategoriaEgreso.objects.get_or_create(codigo=c, defaults={"nombre": n})[0] for c, n in
                [("compras-stock", "Compras de stock"), ("flota", "Flota"), ("epp-herramientas", "EPP y herramientas"),
                 ("siniestros", "Siniestros"), ("sueldos", "Sueldos y cargas"), ("combustible", "Combustible"),
                 ("estructura", "Estructura (alquiler, servicios)")]}
        CostoFijo.objects.create(categoria=cats["sueldos"], descripcion="Sueldos y cargas sociales",
                                 monto_mensual=Decimal("68000000"))
        CostoFijo.objects.create(categoria=cats["combustible"], descripcion="Combustible flota (promedio)",
                                 monto_mensual=Decimal("9500000"))
        CostoFijo.objects.create(categoria=cats["estructura"], descripcion="Alquiler depósito y oficinas",
                                 monto_mensual=Decimal("4200000"))
        # egresos automáticos de lo generado en bloque (bulk_create no dispara señales)
        for modelo in (LoteIngreso, ServiceRealizado, Asignacion, Siniestro):
            for obj in modelo.objects.all():
                sincronizar(obj)
        # egresos fijos reales de meses anteriores
        f = self.inicio.replace(day=1)
        while f <= self.hoy:
            for cf in CostoFijo.objects.all():
                Egreso.objects.create(fecha=f.replace(day=5), categoria=cf.categoria, descripcion=cf.descripcion,
                                      monto=cf.monto_mensual * Decimal(str(round(self.r.uniform(.96, 1.04), 3))))
            f = (f + timedelta(days=32)).replace(day=1)
