"""Preparación de visita: antecedentes y avisos para el técnico antes de salir (B40).

Es deliberadamente DETERMINÍSTICA: cada aviso sale de un dato registrado y dice de dónde sale. No
decide nada ni modifica datos; si en el futuro se agrega un asistente (dictado, consulta con IA),
debe producir borradores sobre esta misma estructura y pasar por las mismas reglas de cierre.
"""
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from .models import MOTIVOS_NO_RESUELTO, Intento, NotaOrden

NOMBRES_MOTIVO = dict(MOTIVOS_NO_RESUELTO)


def preparar_visita(ot, dias=180) -> dict:
    from incidentes.models import Siniestro
    from inventario.models import ReservaMaterial
    from inventario.services import necesidad_orden
    from inventario.stock_tecnico import saldos

    hoy = timezone.localdate()
    avisos = []  # (nivel, texto, fuente)
    visitas, notas, siniestros = [], [], []
    if ot.cliente_id:
        visitas = list(Intento.objects.filter(orden__cliente_id=ot.cliente_id, fecha__gte=hoy - timedelta(days=dias))
                       .exclude(orden=ot).select_related("orden__tipo", "tecnico").order_by("-fecha")[:6])
        notas = list(NotaOrden.objects.filter(orden__cliente_id=ot.cliente_id).exclude(orden=ot)
                     .select_related("orden", "autor").order_by("-creada")[:3])
        siniestros = list(Siniestro.objects.filter(cliente_id=ot.cliente_id).order_by("-fecha")[:3])
        fallidas = Counter(v.motivo_no_resuelto for v in visitas if v.resultado != "completada" and v.motivo_no_resuelto)
        for motivo, n in fallidas.most_common():
            texto = f"{n} visita{'s' if n > 1 else ''} no resuelta{'s' if n > 1 else ''} por «{NOMBRES_MOTIVO.get(motivo, motivo)}»"
            if motivo == "cliente_ausente":
                texto += ": llamá al cliente antes de ir"
            avisos.append(("aviso", texto, f"Visitas a este cliente en los últimos {dias} días"))
        if siniestros:
            avisos.append(("critico", f"Hubo {len(siniestros)} incidente(s) en este cliente: {siniestros[0].get_tipo_display().lower()} "
                                      f"({siniestros[0].fecha:%d/%m/%Y})", "Registro de incidentes"))
    if ot.es_retrabajo and ot.orden_original_id:
        o = ot.orden_original
        avisos.append(("aviso", f"Es un retrabajo de la orden {o.numero} ({o.fecha_ejecucion or o.fecha_programada:%d/%m}"
                                f"{', ' + o.tecnico.nombre_completo if o.tecnico_id else ''}): revisá qué falló",
                       "Orden original"))

    # Materiales: receta del tipo (con su condición), lo reservado y lo que el técnico tiene
    tengo = saldos(ot.tecnico) if ot.tecnico_id else {}
    reservado = {r.material_id: r.pendiente for r in ReservaMaterial.objects.filter(orden=ot, estado="activa")}
    materiales = []
    for n in necesidad_orden(ot):
        t = tengo.get(n["material"], Decimal("0"))
        materiales.append({"material": n["material"], "necesito": n["cantidad"], "estimado": n["estimado"],
                           "tengo": t, "reservado": reservado.get(n["material"].id),
                           "falta": max(Decimal("0"), n["cantidad"] - t)})
    faltan = [m for m in materiales if m["falta"] > 0]
    if faltan:
        avisos.append(("critico" if any(not m["estimado"] for m in faltan) else "aviso",
                       "Te falta: " + ", ".join(f"{m['material'].nombre} ({m['falta'].normalize():f})" for m in faltan[:4]),
                       "Receta del tipo de trabajo vs. tu stock"))
    if any(m["estimado"] for m in materiales):
        avisos.append(("info", "Parte de lo que lleva es estimado (no se sabe si hay recambio o cuántos equipos): "
                               "confirmalo con el cliente", "Condición de la receta"))
    return {"avisos": avisos, "visitas": visitas, "notas": notas, "materiales": materiales,
            "siniestros": siniestros, "sin_antecedentes": not (visitas or notas or siniestros)}
