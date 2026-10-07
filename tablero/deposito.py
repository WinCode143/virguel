"""Depósito: pedidos de partes de los técnicos y stock en manos de cada técnico."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import Persona
from core.notificaciones import notificar
from core.roles import DEPOSITO, GERENCIA, SUPERVISOR, persona_de, requiere_rol, rol_de
from inventario.models import Material, MovimientoStockTecnico, PedidoMaterial
from inventario.services import StockInsuficiente
from inventario.stock_tecnico import devolver, entregar, partes_paradas


def _dec(v):
    try:
        return Decimal(str(v).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


@requiere_rol(GERENCIA, DEPOSITO)
def pedidos(request):
    if request.method == "POST":
        ped = get_object_or_404(PedidoMaterial.objects.prefetch_related("items__material"), pk=request.POST.get("pedido"))
        accion = request.POST.get("accion")
        if accion == "entregar" and ped.estado in ("aprobado", "pendiente"):
            faltantes = []
            with transaction.atomic():
                for it in ped.items.all():
                    cant = _dec(request.POST.get(f"cant_{it.id}", it.cantidad))
                    if cant is None or cant <= 0:
                        continue
                    try:
                        entregar(ped.tecnico, it.material, cant, pedido=ped)
                    except StockInsuficiente:
                        entregar(ped.tecnico, it.material, cant, pedido=ped, permitir_negativo=True)
                        faltantes.append(it.material.nombre)
                    it.cantidad_entregada = cant
                    it.save(update_fields=["cantidad_entregada"])
                ped.estado, ped.entregado = PedidoMaterial.Estado.ENTREGADO, timezone.now()
                if not ped.aprobado_por:
                    ped.aprobado_por = persona_de(request.user)
                ped.save()
            notificar(ped.tecnico, "Tu pedido de partes está listo", "Pasá a retirarlo por el depósito.", "/app/stock/")
            messages.success(request, f"Pedido {ped.id} entregado a {ped.tecnico.nombre_completo}.")
            if faltantes:
                messages.warning(request, "El depósito no tenía stock registrado suficiente de: " + ", ".join(faltantes)
                                 + ". Revisar ingresos.")
        elif accion == "rechazar" and ped.estado != "entregado":
            ped.estado, ped.respuesta = PedidoMaterial.Estado.RECHAZADO, request.POST.get("respuesta", "")[:200]
            ped.save()
            notificar(ped.tecnico, "Tu pedido de partes fue rechazado", ped.respuesta, "/app/stock/")
        return redirect("tablero:pedidos")
    abiertos = (PedidoMaterial.objects.exclude(estado__in=["entregado", "rechazado"])
                .select_related("tecnico", "tecnico__supervisor", "aprobado_por").prefetch_related("items__material")
                .order_by("estado", "creado"))
    stock_dep = {m.id: m.stock_actual for m in Material.objects.all()}
    return render(request, "tablero/pedidos.html", {
        "abiertos": abiertos, "stock_dep": stock_dep,
        "cerrados": PedidoMaterial.objects.filter(estado__in=["entregado", "rechazado"])
        .select_related("tecnico")[:30]})


@requiere_rol(GERENCIA, SUPERVISOR, DEPOSITO)
def stock_tecnicos(request):
    tecnicos = Persona.objects.filter(rol="tecnico", activo=True)
    if rol_de(request.user) == SUPERVISOR:
        tecnicos = tecnicos.filter(supervisor=persona_de(request.user))
    if request.method == "POST" and rol_de(request.user) in (GERENCIA, DEPOSITO):
        t = get_object_or_404(tecnicos, pk=request.POST.get("tecnico"))
        m = get_object_or_404(Material, pk=request.POST.get("material"))
        cant = _dec(request.POST.get("cantidad"))
        if cant and cant > 0:
            try:
                if request.POST.get("accion") == "devolver":
                    devolver(t, m, cant, observaciones=request.POST.get("observaciones", ""))
                    messages.success(request, f"{t.nombre_completo} devolvió {cant:g} {m.unidad} de {m.nombre}.")
                else:
                    entregar(t, m, cant)
                    notificar(t, "Recibiste partes del depósito", f"{cant:g} {m.unidad} de {m.nombre}", "/app/stock/")
                    messages.success(request, f"Entregado a {t.nombre_completo}: {cant:g} {m.unidad} de {m.nombre}.")
            except StockInsuficiente as e:
                messages.error(request, str(e))
        return redirect("tablero:stock_tecnicos")
    filas = (MovimientoStockTecnico.objects.filter(tecnico__in=tecnicos).values(
        "tecnico_id", "tecnico__apellido", "tecnico__nombre", "material__nombre", "material__unidad",
        "material__costo_unitario").annotate(saldo=Sum("cantidad")).order_by("tecnico__apellido", "material__nombre"))
    por_tecnico = {}
    for f in filas:
        if not f["saldo"]:
            continue
        d = por_tecnico.setdefault(f["tecnico_id"], {"nombre": f"{f['tecnico__apellido']}, {f['tecnico__nombre']}",
                                                     "items": [], "valor": Decimal("0"), "negativos": 0})
        d["items"].append(f)
        d["valor"] += f["saldo"] * f["material__costo_unitario"]
        d["negativos"] += f["saldo"] < 0
    paradas = partes_paradas(tecnicos)
    return render(request, "tablero/stock_tecnicos.html", {
        "por_tecnico": sorted(por_tecnico.items(), key=lambda kv: -kv[1]["valor"]), "paradas": paradas,
        "valor_total": sum(d["valor"] for d in por_tecnico.values()),
        "valor_parado": sum(f["valor"] for f in paradas),
        "tecnicos": tecnicos.order_by("apellido"), "materiales": Material.objects.filter(activo=True)})


@requiere_rol(GERENCIA, SUPERVISOR, DEPOSITO)
def deudas(request):
    """Partes adeudadas por los técnicos y su regularización (depósito / gerencia)."""
    from inventario.deudas import deudas as calcular, resumen_por_tecnico
    from inventario.models import EquipoRetirado
    tecnicos = Persona.objects.filter(rol="tecnico", activo=True)
    if rol_de(request.user) == SUPERVISOR:
        tecnicos = tecnicos.filter(supervisor=persona_de(request.user))
    puede = rol_de(request.user) in (GERENCIA, DEPOSITO)
    if request.method == "POST" and puede:
        accion = request.POST.get("accion")
        yo = persona_de(request.user)
        try:
            if accion in ("recibir", "extraviado"):
                e = get_object_or_404(EquipoRetirado, pk=request.POST.get("equipo"), estado="en_tecnico")
                e.estado = "devuelto" if accion == "recibir" else "extraviado"
                e.devuelto, e.recibido_por = timezone.now(), yo
                e.observaciones = request.POST.get("observaciones", "")[:200]
                e.save()
                if accion == "recibir":
                    notificar(e.tecnico, "Equipo recibido en el depósito", f"Serie {e.numero_serie}: regularizado.", "/app/stock/")
                messages.success(request, f"Equipo {e.numero_serie}: {e.get_estado_display().lower()}.")
            elif accion == "entrega_pendiente":
                t = get_object_or_404(tecnicos, pk=request.POST.get("tecnico"))
                m = get_object_or_404(Material, pk=request.POST.get("material"))
                cant = _dec(request.POST.get("cantidad"))
                entregar(t, m, cant, permitir_negativo=True)
                notificar(t, "Parte regularizada", f"Se registró la entrega de {cant:g} {m.unidad} de {m.nombre}.", "/app/stock/")
                messages.success(request, f"Registrada la entrega a {t.nombre_completo}.")
            elif accion == "devolucion":
                t = get_object_or_404(tecnicos, pk=request.POST.get("tecnico"))
                m = get_object_or_404(Material, pk=request.POST.get("material"))
                cant = _dec(request.POST.get("cantidad"))
                devolver(t, m, cant, observaciones="Devolución de partes paradas")
                notificar(t, "Devolución registrada", f"{cant:g} {m.unidad} de {m.nombre} volvieron al depósito.", "/app/stock/")
                messages.success(request, f"Devolución de {t.nombre_completo} registrada.")
        except StockInsuficiente as e:
            messages.error(request, str(e))
        return redirect("tablero:deudas")
    lista = calcular(tecnicos)
    por_tec = resumen_por_tecnico(lista)
    return render(request, "tablero/deudas.html", {
        "por_tec": sorted(por_tec.items(), key=lambda kv: (-kv[1]["rojas"], -kv[1]["mas_vieja"])),
        "total": len(lista), "rojas": sum(1 for d in lista if d.estado == "critico"),
        "amarillas": sum(1 for d in lista if d.estado == "aviso"), "puede": puede,
        "equipos": sum(1 for d in lista if d.tipo == "equipo_retirado")})
