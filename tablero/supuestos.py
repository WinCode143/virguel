"""Supuestos del sistema: qué reglas y datos están definidos por la empresa y cuáles son INVENTADOS
(valores de prueba) y hay que confirmar. Se alimenta de Parámetros.provisorios y de los datos marcados."""
from django.shortcuts import render

from core.models import CambioParametro, Indicador, Parametros
from core.roles import GERENCIA, SUPERVISOR, requiere_rol

# Tema → (campos de Parámetros que lo componen, qué tiene que decidir o aportar la empresa)
TEMAS = [
    ("Pesos de los índices (IPT / IGS)", [], "Acordar los pesos con datos reales de varios meses (ver Calibrar pesos)."),
    ("Comparación entre técnicos", ["comparar_productividad_por", "evidencia_min_jornadas", "evidencia_min_ordenes",
                                    "evidencia_min_controles"],
     "Con qué grupo se compara a cada técnico y cuánta evidencia mínima hace falta."),
    ("Encuesta a técnicos", ["encuesta_min_respuestas", "encuesta_min_personas"],
     "Umbrales para mostrar resultados sin identificar a quién respondió, según el tamaño real de los equipos."),
    ("Liquidación de Claro y caja", ["claro_retencion", "claro_dias_cobro", "claro_paga_retrabajos",
                                     "tasa_descuento_mensual"],
     "Retenciones, plazos de cobro, si pagan retrabajos y tasa para comparar alternativas de pago."),
    ("Stock y antigüedad", ["reloj_antiguedad", "dias_max_stock", "dias_aviso_stock", "dias_necesidad_inmediata",
                            "prob_recambio", "prob_decodificador_min", "prob_decodificador_max"],
     "Qué fecha activa la alerta de 60 días y las probabilidades de recambio y decodificador."),
    ("Agenda", ["minutos_traslado_promedio", "clientes_por_tecnico_dia", "horas_jornada"],
     "Tiempos de traslado y capacidad por técnico."),
]


@requiere_rol(GERENCIA, SUPERVISOR)
def supuestos(request):
    p = Parametros.actual()
    prov = p.provisorios or {}
    temas = []
    for nombre, campos, decide in TEMAS:
        filas = []
        for c in campos:
            f = p._meta.get_field(c)
            valor = getattr(p, f"get_{c}_display")() if f.choices else getattr(p, c)
            filas.append({"campo": c, "nombre": f.verbose_name, "valor": valor, "inventado": c in prov,
                          "nota": prov.get(c, "")})
        temas.append({"nombre": nombre, "decide": decide, "filas": filas,
                      "inventado": nombre in prov or any(x["inventado"] for x in filas), "nota": prov.get(nombre, "")})
    from capacitacion.models import RequisitoCompetencia
    from herramientas.models import RequisitoEPP
    from inventario.models import RecetaMaterial
    from operaciones.models import TarifaClaro
    from supervision.models import PlantillaInspeccion
    datos = [
        ("Tarifas de Claro", TarifaClaro.objects.count(), TarifaClaro.objects.filter(provisoria=True).count()),
        ("Recetas de materiales", RecetaMaterial.objects.count(), None),
        ("Requisitos de competencias", RequisitoCompetencia.objects.count(), None),
        ("Requisitos de EPP", RequisitoEPP.objects.count(), None),
        ("Plantillas de control", PlantillaInspeccion.objects.count(), None),
    ]
    return render(request, "tablero/supuestos.html", {
        "temas": temas, "datos": datos, "demo": p.datos_demo,
        "pesos": Indicador.objects.filter(rol__in=("tecnico", "supervisor"), activo=True, tipo="calculado")
        .order_by("rol", "orden"),
        "cambios": CambioParametro.objects.all()[:15]})
