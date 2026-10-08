"""Área de Contabilidad (gerencia y rol Contabilidad).

Resumen en 4 bloques (sueldos, horas extra, materiales, otros gastos) · comprobantes (facturas,
tickets, recibos) y cuentas a pagar · sueldos por empleado · materiales · reintegros · presupuesto.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO

from django import forms
from django.contrib import messages
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from core.models import Parametros, Persona
from core.numeros import CampoPesos, a_decimal
from core.templatetags.formato import pesos
from core.notificaciones import notificar
from core.roles import CONTABILIDAD, GERENCIA, requiere_rol
from operaciones.models import GastoOrden

from .models import CategoriaEgreso, CostoFijo, Egreso, Liquidacion, Presupuesto, Proveedor
from .proyeccion import inicio_mes, proyectar, sumar_meses
from .sueldos import fin_de_mes, generar

ROLES = (GERENCIA, CONTABILIDAD)


def _mes(request):
    try:
        return inicio_mes(date.fromisoformat((request.GET.get("mes") or request.POST.get("mes") or "") + "-01"))
    except ValueError:
        return inicio_mes(timezone.localdate())


def _nav_mes(mes):
    return {"mes": mes, "anterior": sumar_meses(mes, -1), "siguiente": sumar_meses(mes, 1)}


_dec = a_decimal


# ------------------------------------------------------------------ resumen
def consumos(desde, hasta):
    """Materiales usados en órdenes, valorizados a costo (los del stock del técnico también quedan
    registrados como salida de consumo). Una fila por salida."""
    from inventario.models import Salida
    return [{"tecnico": s.tecnico, "material": s.material, "orden": s.orden, "cantidad": s.cantidad, "valor": s.costo_total}
            for s in Salida.objects.filter(fecha__range=(desde, hasta), motivo="consumo")
            .select_related("tecnico", "material", "orden__tipo")]


def compras(desde, hasta):
    from inventario.models import LoteIngreso
    return (LoteIngreso.objects.filter(fecha__range=(desde, hasta)).exclude(proveedor__startswith="Devolución")
            .select_related("material"))


def _valor_compras(qs):
    return sum((lote.cantidad * lote.costo_unitario for lote in qs), Decimal("0"))


def bloques_del_mes(mes):
    """Gasto del mes en 4 bloques: sueldos, horas extra, materiales, otros."""
    fin = fin_de_mes(mes)
    par = Parametros.actual()
    liq = Liquidacion.objects.filter(periodo=mes)
    he = (liq.aggregate(t=Sum("monto_horas_extra"))["t"] or Decimal("0")) * (1 + par.cargas_sociales / 100)
    sueldos = (liq.aggregate(t=Sum("costo_total"))["t"] or Decimal("0")) - he
    estimado = liq.filter(estado="borrador").exists()
    consumo = sum((f["valor"] for f in consumos(mes, fin)), Decimal("0"))
    egresos = Egreso.objects.filter(fecha__range=(mes, fin))
    compras = egresos.filter(categoria__codigo="compras-stock").aggregate(t=Sum("monto"))["t"] or Decimal("0")
    otros = egresos.exclude(categoria__codigo__in=["sueldos", "compras-stock"]).aggregate(t=Sum("monto"))["t"] or Decimal("0")
    return {"sueldos": sueldos, "horas_extra": he, "materiales": compras, "consumo": consumo, "otros": otros,
            "total": sueldos + he + compras + otros, "estimado": estimado}


def presupuesto_vs_real(mes):
    """Por categoría: presupuesto, gastado y semáforo (verde ≤ presupuesto; amarillo ≤ +tolerancia; rojo >)."""
    fin = fin_de_mes(mes)
    real = dict(Egreso.objects.filter(fecha__range=(mes, fin)).values_list("categoria").annotate(t=Sum("monto")))
    pres = {p.categoria_id: p.monto for p in Presupuesto.objects.filter(mes=mes)}
    filas = []
    for c in CategoriaEgreso.objects.all():
        r, p = real.get(c.id, Decimal("0")), pres.get(c.id)
        if p is None and not r:
            continue
        if p is None:
            estado, uso = "info", None
        else:
            uso = float(r / p * 100) if p else None
            estado = "ok" if r <= p else "aviso" if r <= p * (1 + Decimal(c.tolerancia_presupuesto) / 100) else "critico"
        filas.append({"c": c, "presupuesto": p, "real": r, "uso": uso, "estado": estado,
                      "diferencia": (p - r) if p is not None else None})
    return filas


def cuentas_a_pagar():
    hoy = timezone.localdate()
    pend = Egreso.objects.filter(pagado=False)
    return {"vencidas": pend.filter(vencimiento__lt=hoy), "semana": pend.filter(vencimiento__range=(hoy, hoy + timedelta(days=7))),
            "total": pend.aggregate(t=Sum("monto"))["t"] or Decimal("0"), "n": pend.count(),
            "monto_vencido": pend.filter(vencimiento__lt=hoy).aggregate(t=Sum("monto"))["t"] or Decimal("0")}


@requiere_rol(*ROLES)
def panel(request):
    from tablero.views import grafico
    mes = _mes(request)
    b = bloques_del_mes(mes)
    filas = presupuesto_vs_real(mes)
    meses = [sumar_meses(mes, -i) for i in range(5, -1, -1)]
    serie = [bloques_del_mes(m) for m in meses]
    g = grafico("bar", [m.strftime("%m/%Y") for m in meses], [
        {"nombre": "Sueldos y cargas", "datos": [x["sueldos"] for x in serie], "serie": 1},
        {"nombre": "Horas extra", "datos": [x["horas_extra"] for x in serie], "serie": 2},
        {"nombre": "Compras de materiales", "datos": [x["materiales"] for x in serie], "serie": 3},
        {"nombre": "Otros gastos", "datos": [x["otros"] for x in serie], "serie": 4},
    ], apilado=True, formato="pesos")
    total_pres = sum((f["presupuesto"] or 0) for f in filas)
    return render(request, "finanzas/panel.html", {
        **_nav_mes(mes), "b": b, "filas": filas, "g": g, "total_pres": total_pres,
        "cap": cuentas_a_pagar(), "proy": proyectar(3),
        "pendientes": {
            "reintegros": GastoOrden.objects.filter(estado="pendiente").count(),
            "sin_archivo": Egreso.objects.filter(fecha__range=(mes, fin_de_mes(mes)), automatico=False, comprobante="").count(),
            "borradores": Liquidacion.objects.filter(periodo=mes, estado="borrador").count(),
            "sin_sueldo": Persona.objects.filter(activo=True, sueldo_basico__isnull=True).exclude(rol="gerencia").count()}})


# ------------------------------------------------------------------ comprobantes
class ComprobanteForm(forms.ModelForm):
    proveedor_nombre = forms.CharField(label="Proveedor", max_length=120, required=False,
                                       widget=forms.TextInput(attrs={"list": "proveedores", "autocomplete": "off"}))
    cuit = forms.CharField(label="CUIT (si es nuevo)", max_length=13, required=False)

    class Meta:
        model = Egreso
        fields = ["comprobante", "tipo_comprobante", "numero_comprobante", "fecha", "vencimiento", "categoria",
                  "monto", "descripcion", "pagado", "fecha_pago", "medio_pago"]
        labels = {"comprobante": "Archivo (foto o PDF)", "descripcion": "Concepto", "categoria": "Categoría",
                  "fecha_pago": "Fecha de pago", "medio_pago": "Medio de pago",
                  "pagado": "Ya está pagado"}
        widgets = {"fecha": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "vencimiento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "fecha_pago": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "comprobante": forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].required = False
        self.fields["categoria"].empty_label = "— la habitual del proveedor —"
        self.fields["descripcion"].required = False
        self.fields["monto"] = CampoPesos(label="Total")
        if self.instance.pk and self.instance.proveedor_ref:
            self.fields["proveedor_nombre"].initial = self.instance.proveedor_ref.nombre

    def clean_monto(self):
        v = self.cleaned_data["monto"]
        if not v:
            raise forms.ValidationError("Poné el total del comprobante (ej. 125.000,50).")
        return v

    def clean(self):
        d = super().clean()
        if d.get("tipo_comprobante") == "nota_credito" and d.get("monto") and d["monto"] > 0:
            d["monto"] = -d["monto"]  # la nota de crédito resta
        return d

    def save(self, commit=True, usuario=None):
        e = super().save(commit=False)
        nombre = self.cleaned_data.get("proveedor_nombre", "").strip()
        if nombre:
            prov, creado = Proveedor.objects.get_or_create(nombre=nombre, defaults={"cuit": self.cleaned_data.get("cuit", "")})
            e.proveedor_ref, e.proveedor = prov, prov.nombre
        if not e.categoria_id:
            e.categoria = (e.proveedor_ref.categoria if e.proveedor_ref and e.proveedor_ref.categoria
                           else CategoriaEgreso.objects.get_or_create(codigo="otros", defaults={"nombre": "Otros gastos"})[0])
        if e.proveedor_ref and not e.proveedor_ref.categoria:
            e.proveedor_ref.categoria = e.categoria
            e.proveedor_ref.save(update_fields=["categoria"])
        if e.pagado and not e.fecha_pago:
            e.fecha_pago = e.fecha
        if not e.descripcion:
            e.descripcion = f"{e.get_tipo_comprobante_display()} {e.numero_comprobante}".strip()
        if usuario and not e.cargado_por_id:
            e.cargado_por = usuario
        if commit:
            e.save()
        return e


@requiere_rol(*ROLES)
def comprobantes(request):
    mes = _mes(request)
    ver = request.GET.get("ver", "mes")  # mes | a_pagar
    if request.method == "POST" and request.POST.get("accion") == "pagar":
        e = get_object_or_404(Egreso, pk=request.POST.get("egreso"))
        e.pagado, e.fecha_pago = True, timezone.localdate()
        e.medio_pago = request.POST.get("medio_pago") or e.medio_pago
        e.save(update_fields=["pagado", "fecha_pago", "medio_pago"])
        messages.success(request, f"Marcado como pagado: {e.proveedor or e.descripcion}.")
        return redirect(request.get_full_path())
    if ver == "a_pagar":
        qs = Egreso.objects.filter(pagado=False).order_by(F("vencimiento").asc(nulls_last=True))
    else:
        qs = Egreso.objects.filter(fecha__range=(mes, fin_de_mes(mes))).order_by("-fecha", "-id")
    tipo, prov, origen, q = (request.GET.get(k, "") for k in ("tipo", "proveedor", "origen", "q"))
    if tipo:
        qs = qs.filter(tipo_comprobante=tipo)
    if prov:
        qs = qs.filter(proveedor_ref_id=prov)
    if origen in ("manual", "automatico"):
        qs = qs.filter(automatico=origen == "automatico")
    if q:
        qs = qs.filter(Q(descripcion__icontains=q) | Q(proveedor__icontains=q) | Q(numero_comprobante__icontains=q))
    if request.GET.get("formato") == "excel":
        return _excel_comprobantes(qs, mes)
    return render(request, "finanzas/comprobantes.html", {
        **_nav_mes(mes), "ver": ver, "comprobantes": qs.select_related("categoria", "proveedor_ref", "cargado_por")[:500],
        "total": qs.aggregate(t=Sum("monto"))["t"] or 0, "tipos": Egreso.TipoComprobante.choices,
        "medios": Egreso.Medio.choices, "proveedores": Proveedor.objects.all(), "f": request.GET, "hoy": timezone.localdate(),
        "cap": cuentas_a_pagar()})


@requiere_rol(*ROLES)
def comprobante_form(request, pk=None):
    e = get_object_or_404(Egreso, pk=pk, automatico=False) if pk else None
    if request.method == "POST":
        if e and request.POST.get("accion") == "eliminar":
            e.delete()
            messages.success(request, "Comprobante eliminado.")
            return redirect("finanzas:comprobantes")
        f = ComprobanteForm(request.POST, request.FILES, instance=e)
        if f.is_valid():
            guardado = f.save(usuario=request.user)
            messages.success(request, f"Comprobante guardado: {guardado.proveedor or guardado.descripcion} {pesos(guardado.monto)}")
            return redirect("finanzas:comprobante_nuevo" if "otro" in request.POST else "finanzas:comprobantes")
    else:
        f = ComprobanteForm(instance=e, initial={} if e else {"fecha": timezone.localdate(), "pagado": False})
    return render(request, "finanzas/comprobante_form.html", {"form": f, "e": e, "proveedores": Proveedor.objects.all()})


# ------------------------------------------------------------------ sueldos
@requiere_rol(*ROLES)
def sueldos(request):
    mes = _mes(request)
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "generar":
            n, r = generar(mes)
            messages.success(request, f"Liquidaciones de {mes:%m/%Y}: {n} nuevas, {r} recalculadas (las aprobadas no se tocan).")
        elif accion in ("aprobar_todas", "pagar_todas"):
            estado = "aprobada" if accion == "aprobar_todas" else "pagada"
            desde = ["borrador"] if estado == "aprobada" else ["borrador", "aprobada"]
            n = 0
            for liq in Liquidacion.objects.filter(periodo=mes, estado__in=desde):
                liq.estado = estado
                liq.save()  # dispara el egreso de sueldos
                n += 1
            messages.success(request, f"{n} liquidación(es) {estado}(s).")
        elif accion == "fila":
            liq = get_object_or_404(Liquidacion, pk=request.POST.get("liq"))
            if liq.estado == "borrador":
                for campo in ("otros_adicionales", "otros_descuentos"):
                    v = _dec(request.POST.get(campo))
                    if v is not False:
                        setattr(liq, campo, v or Decimal("0"))
                liq.observaciones = request.POST.get("observaciones", "")[:200]
                from .sueldos import calcular
                calcular(liq.persona, liq.periodo, liq).save()
            if request.FILES.get("recibo"):
                liq.recibo = request.FILES["recibo"]
                liq.save(update_fields=["recibo"])
            nuevo = request.POST.get("estado")
            if nuevo in ("borrador", "aprobada", "pagada") and nuevo != liq.estado:
                liq.estado = nuevo
                liq.save()
            messages.success(request, f"Liquidación de {liq.persona.nombre_completo} actualizada.")
        elif accion == "basicos":
            n = 0
            for p in Persona.objects.filter(activo=True).exclude(rol="gerencia"):
                v = _dec(request.POST.get(f"b_{p.id}"))
                if v not in (None, False) and v != p.sueldo_basico:
                    p.sueldo_basico = v
                    p.save(update_fields=["sueldo_basico"])
                    n += 1
            messages.success(request, f"{n} sueldo(s) básico(s) actualizado(s). Recalculá las liquidaciones en borrador.")
        return redirect(f"{request.path}?mes={mes:%Y-%m}")
    liqs = list(Liquidacion.objects.filter(periodo=mes).select_related("persona", "persona__supervisor")
                .order_by("persona__rol", "persona__apellido"))
    if request.GET.get("formato") == "excel":
        return _excel_novedades(liqs, mes)
    tot = defaultdict(Decimal)
    for liq in liqs:
        for k in ("basico", "monto_horas_extra", "horas_extra_50", "horas_extra_100", "presentismo", "descuento_dias",
                  "bruto", "cargas_sociales", "costo_total", "multas"):
            tot[k] += getattr(liq, k)
    he_ranking = sorted([liq for liq in liqs if liq.monto_horas_extra], key=lambda x: -x.monto_horas_extra)[:8]
    return render(request, "finanzas/sueldos.html", {
        **_nav_mes(mes), "liqs": liqs, "tot": tot, "he_ranking": he_ranking, "par": Parametros.actual(),
        "borradores": sum(1 for x in liqs if x.estado == "borrador"),
        "sin_recibo": sum(1 for x in liqs if x.estado == "pagada" and not x.recibo),
        "personas": Persona.objects.filter(activo=True).exclude(rol="gerencia").order_by("rol", "apellido")
        if request.GET.get("basicos") else None})


# ------------------------------------------------------------------ materiales
@requiere_rol(*ROLES)
def materiales(request):
    from inventario.models import LoteIngreso, Material
    from inventario.stock_tecnico import partes_paradas, total_en_tecnicos
    from tablero.views import grafico
    mes = _mes(request)
    fin = fin_de_mes(mes)
    usados = consumos(mes, fin)
    comprado = compras(mes, fin)
    por_material, por_tecnico, por_tipo = defaultdict(lambda: [Decimal("0"), Decimal("0")]), {}, {}
    for f in usados:
        pm = por_material[f["material"].nombre]
        pm[0] += f["cantidad"]
        pm[1] += f["valor"]
        if f["tecnico"]:
            t = por_tecnico.setdefault(f["tecnico"].id, {"tecnico": f["tecnico"], "valor": Decimal("0"), "ordenes": set()})
            t["valor"] += f["valor"]
            if f["orden"]:
                t["ordenes"].add(f["orden"].id)
        if f["orden"]:
            t = por_tipo.setdefault(f["orden"].tipo.nombre, {"tipo": f["orden"].tipo.nombre, "valor": Decimal("0"), "ordenes": set()})
            t["valor"] += f["valor"]
            t["ordenes"].add(f["orden"].id)
    for d in (*por_tecnico.values(), *por_tipo.values()):
        d["n"] = len(d["ordenes"])
        d["por_orden"] = d["valor"] / d["n"] if d["n"] else None
    deposito = sum((lote.cantidad_disponible * lote.costo_unitario
                   for lote in LoteIngreso.objects.filter(cantidad_disponible__gt=0)), Decimal("0"))
    costos = dict(Material.objects.values_list("id", "costo_unitario"))
    en_tecnicos = sum((max(Decimal("0"), q) * costos.get(mid, 0) for mid, q in total_en_tecnicos().items()), Decimal("0"))
    meses = [sumar_meses(mes, -i) for i in range(5, -1, -1)]
    g = grafico("bar", [m.strftime("%m/%Y") for m in meses], [
        {"nombre": "Comprado", "datos": [_valor_compras(compras(m, fin_de_mes(m))) for m in meses], "serie": 1},
        {"nombre": "Usado en órdenes", "datos": [sum((f["valor"] for f in consumos(m, fin_de_mes(m))), Decimal("0"))
                                                 for m in meses], "serie": 3}], formato="pesos")
    return render(request, "finanzas/materiales.html", {
        **_nav_mes(mes), "total_compras": _valor_compras(comprado), "total_consumo": sum((f["valor"] for f in usados), Decimal("0")),
        "deposito": deposito, "en_tecnicos": en_tecnicos, "paradas": sum((f["valor"] for f in partes_paradas()), Decimal("0")),
        "por_material": sorted(por_material.items(), key=lambda x: -x[1][1])[:12],
        "por_tecnico": sorted(por_tecnico.values(), key=lambda x: -x["valor"])[:15],
        "por_tipo": sorted(por_tipo.values(), key=lambda x: -x["valor"]), "g": g,
        "compras": comprado.annotate(total=F("cantidad") * F("costo_unitario")).order_by("-fecha")[:20]})


# ------------------------------------------------------------------ reintegros, presupuesto, configuración
@requiere_rol(*ROLES)
def gastos_campo(request):
    """Revisión de gastos que cargan los técnicos al cerrar llamadas (reintegros)."""
    if request.method == "POST":
        g = get_object_or_404(GastoOrden, pk=request.POST.get("gasto"))
        g.estado = "aprobado" if request.POST.get("accion") == "aprobar" else "rechazado"
        g.save()  # el egreso se actualiza solo (rechazado = se quita)
        notificar(g.tecnico, f"Gasto {'aprobado' if g.estado == 'aprobado' else 'rechazado'}: {g.descripcion}",
                  pesos(g.monto) + (f" · {request.POST.get('motivo')}" if request.POST.get("motivo") else ""), "/app/")
        messages.success(request, f"Gasto {g.get_estado_display().lower()}.")
        return redirect("finanzas:gastos_campo")
    estado = request.GET.get("estado", "pendiente")
    qs = GastoOrden.objects.select_related("tecnico", "orden", "orden__tipo").order_by("-fecha")
    if estado:
        qs = qs.filter(estado=estado)
    por_tecnico = (GastoOrden.objects.filter(estado="aprobado", fecha__gte=inicio_mes(timezone.localdate()))
                   .values("tecnico__apellido", "tecnico__nombre").annotate(t=Sum("monto"), n=Count("id")).order_by("-t"))
    return render(request, "finanzas/gastos_campo.html", {"gastos": qs[:200], "estado": estado,
                                                           "por_tecnico": por_tecnico})


@requiere_rol(*ROLES)
def presupuestos(request):
    mes = _mes(request)
    meses = [sumar_meses(mes, i) for i in range(3)]
    cats = list(CategoriaEgreso.objects.all())
    if request.method == "POST":
        if request.POST.get("accion") == "copiar":
            anterior = sumar_meses(mes, -1)
            n = 0
            for p in Presupuesto.objects.filter(mes=anterior):
                _, creado = Presupuesto.objects.get_or_create(categoria=p.categoria, mes=mes, defaults={"monto": p.monto})
                n += creado
            messages.success(request, f"Copiados {n} presupuestos de {anterior:%m/%Y}.")
        else:
            errores = 0
            for c in cats:
                for m in meses:
                    v = _dec(request.POST.get(f"p_{c.id}_{m:%Y%m}"))
                    if v is False:
                        errores += 1
                    elif v is None:
                        Presupuesto.objects.filter(categoria=c, mes=m).delete()
                    else:
                        Presupuesto.objects.update_or_create(categoria=c, mes=m, defaults={"monto": v})
            messages.error(request, f"{errores} valor(es) no son números.") if errores else messages.success(
                request, "Presupuestos guardados.")
        return redirect(f"{request.path}?mes={mes:%Y-%m}")
    actuales = {(p.categoria_id, p.mes): p.monto for p in Presupuesto.objects.filter(mes__in=meses)}
    filas = [{"c": c, "valores": [(m, actuales.get((c.id, m))) for m in meses]} for c in cats]
    totales = [sum((actuales.get((c.id, m)) or 0) for c in cats) for m in meses]
    return render(request, "finanzas/presupuestos.html", {
        "filas": filas, "meses": meses, "mes": mes, "totales": totales, "anterior": sumar_meses(mes, -1),
        "comparacion": presupuesto_vs_real(mes)})


@requiere_rol(*ROLES)
def configuracion(request):
    par = Parametros.actual()
    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "categoria":
            from django.utils.text import slugify
            nombre = request.POST.get("nombre", "").strip()
            if nombre:
                CategoriaEgreso.objects.get_or_create(nombre=nombre, defaults={"codigo": slugify(nombre)[:30]})
        elif accion == "tolerancia":
            c = get_object_or_404(CategoriaEgreso, pk=request.POST.get("categoria"))
            if request.POST.get("tolerancia", "").isdigit():
                c.tolerancia_presupuesto = int(request.POST["tolerancia"])
                c.save(update_fields=["tolerancia_presupuesto"])
        elif accion == "costo":
            monto = _dec(request.POST.get("monto"))
            cat = CategoriaEgreso.objects.filter(pk=request.POST.get("categoria")).first()
            if cat and monto:
                CostoFijo.objects.create(categoria=cat, descripcion=request.POST.get("descripcion", "")[:150], monto_mensual=monto)
        elif accion in ("costo_editar", "costo_baja"):
            cf = get_object_or_404(CostoFijo, pk=request.POST.get("costo"))
            if accion == "costo_baja":
                cf.activo = not cf.activo
            elif _dec(request.POST.get("monto")):
                cf.monto_mensual = _dec(request.POST.get("monto"))
            cf.save()
        elif accion == "proveedor":
            p = get_object_or_404(Proveedor, pk=request.POST.get("proveedor"))
            p.cuit, p.contacto = request.POST.get("cuit", "")[:13], request.POST.get("contacto", "")[:120]
            p.categoria = CategoriaEgreso.objects.filter(pk=request.POST.get("categoria")).first()
            p.save()
        elif accion == "sueldos":
            for campo in ("horas_mensuales", "recargo_extra_50", "recargo_extra_100", "presentismo_tardanzas_max"):
                if request.POST.get(campo, "").isdigit():
                    setattr(par, campo, int(request.POST[campo]))
            for campo in ("adicional_presentismo", "cargas_sociales"):
                v = _dec(request.POST.get(campo))
                if v not in (None, False):
                    setattr(par, campo, v)
            par.save()
        messages.success(request, "Guardado.")
        return redirect("finanzas:configuracion")
    return render(request, "finanzas/configuracion.html", {
        "categorias": CategoriaEgreso.objects.annotate(n=Count("egresos")),
        "costos": CostoFijo.objects.select_related("categoria").order_by("-activo", "descripcion"),
        "proveedores": Proveedor.objects.annotate(n=Count("comprobantes"), t=Sum("comprobantes__monto")).order_by("-t"),
        "par": par})


# ------------------------------------------------------------------ Excel
def _libro(titulo, cabecera, filas, moneda_cols=(), anchos=()):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = titulo[:31]
    ws.append(cabecera)
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2A78D6")
    for f in filas:
        ws.append(f)
    for col in moneda_cols:
        for (c,) in ws.iter_rows(min_row=2, min_col=col, max_col=col):
            c.number_format = '"$"#,##0.00'
    for i, a in enumerate(anchos, 1):
        ws.column_dimensions[chr(64 + i)].width = a
    ws.freeze_panes = "A2"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _descarga(contenido, nombre):
    resp = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return resp


def _excel_comprobantes(qs, mes):
    filas = [[e.fecha, e.get_tipo_comprobante_display(), e.numero_comprobante,
              e.proveedor_ref.nombre if e.proveedor_ref else e.proveedor, e.proveedor_ref.cuit if e.proveedor_ref else "",
              e.categoria.nombre, e.descripcion, float(e.monto), e.vencimiento, "Sí" if e.pagado else "No", e.fecha_pago,
              e.get_medio_pago_display() if e.medio_pago else "", "Automático" if e.automatico else "Manual",
              "Sí" if e.comprobante else "No"] for e in qs.select_related("categoria", "proveedor_ref")]
    filas.append(["", "", "", "", "", "", "TOTAL", f"=SUM(H2:H{len(filas) + 1})"])
    return _descarga(_libro(f"Comprobantes {mes:%m-%Y}", ["Fecha", "Tipo", "Número", "Proveedor", "CUIT", "Categoría",
                                                         "Concepto", "Total", "Vence", "Pagado", "Fecha de pago",
                                                         "Medio", "Origen", "Archivo"], filas, (8,),
                            (11, 13, 16, 24, 14, 20, 40, 14, 11, 8, 12, 14, 11, 8)),
                     f"comprobantes_{mes:%Y_%m}.xlsx")


def _excel_novedades(liqs, mes):
    filas = [[liq.persona.legajo, liq.persona.apellido, liq.persona.nombre, liq.persona.dni, liq.persona.get_rol_display(),
              liq.persona.categoria_laboral, float(liq.basico), liq.dias_trabajados, liq.faltas_injustificadas,
              float(liq.dias_descuento), float(liq.horas_extra_50), float(liq.horas_extra_100),
              float(liq.monto_horas_extra), float(liq.presentismo), float(liq.otros_adicionales),
              float(liq.descuento_dias), float(liq.otros_descuentos), float(liq.bruto), float(liq.cargas_sociales),
              float(liq.costo_total), float(liq.multas), liq.get_estado_display(), liq.observaciones] for liq in liqs]
    cab = ["Legajo", "Apellido", "Nombre", "DNI", "Rol", "Categoría", "Básico", "Días trabajados", "Faltas injustif.",
           "Días a descontar", "HE 50% (h)", "HE 100% (h)", "Monto HE", "Presentismo", "Otros adicionales",
           "Descuento días", "Otros descuentos", "Bruto", "Cargas sociales", "Costo empresa",
           "Multas (informativo)", "Estado", "Observaciones"]
    return _descarga(_libro(f"Novedades {mes:%m-%Y}", cab, filas, (7, 13, 14, 15, 16, 17, 18, 19, 20, 21)),
                     f"novedades_sueldos_{mes:%Y_%m}.xlsx")
