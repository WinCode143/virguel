"""Metas y semáforos: gerencia fija las generales; cada supervisor puede ajustar las de su equipo."""
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from core.models import CambioMeta, Indicador, MetaEquipo, Parametros, Persona
from core.roles import GERENCIA, SUPERVISOR, persona_de, requiere_rol, rol_de

SECCIONES = [("mando", "Tablero de mando", "Lo que se ve en el Resumen."),
             ("tecnico", "Técnicos (IPT)", "Indicadores de productividad de cada técnico."),
             ("supervisor", "Supervisores (IGS)", "Indicadores de gestión de cada supervisor (sólo gerencia).")]


def _dec(v):
    try:
        return Decimal(str(v).replace(".", "").replace(",", ".")) if "," in str(v) else Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _fmt(meta, lim):
    return f"meta {meta.normalize():f} / límite {lim.normalize():f}"


@requiere_rol(GERENCIA, SUPERVISOR)
def metas(request):
    es_ger = rol_de(request.user) == GERENCIA
    supervisores = Persona.objects.filter(rol="supervisor", activo=True).order_by("apellido")
    if es_ger:
        eq_id = request.GET.get("equipo") or request.POST.get("equipo") or ""
        equipo = get_object_or_404(supervisores, pk=eq_id) if eq_id else None
    else:
        equipo = persona_de(request.user)  # el supervisor sólo edita su equipo
    roles_editables = {"mando", "tecnico", "supervisor"} if es_ger else {"mando", "tecnico"}
    if equipo is not None and es_ger is False:
        roles_editables = {"mando", "tecnico"}

    if request.method == "POST":
        errores, cambios = [], 0
        alcance = f"equipo de {equipo.apellido}" if equipo else "general"
        with transaction.atomic():
            for i in Indicador.objects.filter(activo=True, rol__in=roles_editables):
                meta, lim = request.POST.get(f"meta_{i.id}", "").strip(), request.POST.get(f"lim_{i.id}", "").strip()
                if equipo is not None and not meta and not lim:
                    borradas, _ = MetaEquipo.objects.filter(supervisor=equipo, indicador=i).delete()
                    if borradas:
                        CambioMeta.objects.create(usuario=request.user, indicador=i, alcance=alcance,
                                                  antes="propia", despues="usa la general")
                        cambios += 1
                    continue
                if not meta and not lim:
                    continue
                m, lv = _dec(meta), _dec(lim)
                if m is None or lv is None:
                    errores.append(f"{i.nombre}: completá meta y límite con números.")
                    continue
                if (m <= lv) if i.mayor_es_mejor else (m >= lv):
                    errores.append(f"{i.nombre}: la meta debe ser {'mayor' if i.mayor_es_mejor else 'menor'} que el límite rojo.")
                    continue
                if equipo is None:
                    if (i.meta, i.minimo) != (m, lv):
                        CambioMeta.objects.create(usuario=request.user, indicador=i, alcance=alcance,
                                                  antes=_fmt(i.meta, i.minimo), despues=_fmt(m, lv))
                        i.meta, i.minimo = m, lv
                        cambios += 1
                    peso = request.POST.get(f"peso_{i.id}")
                    if peso is not None and peso.isdigit() and int(peso) != i.peso and i.rol != "mando":
                        CambioMeta.objects.create(usuario=request.user, indicador=i, alcance=alcance,
                                                  antes=f"peso {i.peso}", despues=f"peso {peso}")
                        i.peso = int(peso)
                        cambios += 1
                    i.save()
                else:
                    actual = MetaEquipo.objects.filter(supervisor=equipo, indicador=i).first()
                    antes = _fmt(actual.meta, actual.minimo) if actual else "usa la general"
                    if not actual or (actual.meta, actual.minimo) != (m, lv):
                        MetaEquipo.objects.update_or_create(supervisor=equipo, indicador=i,
                                                            defaults={"meta": m, "minimo": lv})
                        CambioMeta.objects.create(usuario=request.user, indicador=i, alcance=alcance, antes=antes,
                                                  despues=_fmt(m, lv))
                        cambios += 1
            if es_ger and equipo is None:
                p = Parametros.actual()
                for campo in ("indice_verde", "indice_rojo", "deuda_dias_aviso", "deuda_dias_critico"):
                    v = request.POST.get(campo, "")
                    if v.isdigit():
                        setattr(p, campo, int(v))
                if p.indice_rojo >= p.indice_verde or p.deuda_dias_aviso >= p.deuda_dias_critico:
                    errores.append("Umbrales: el valor para rojo debe quedar más lejos que el de amarillo/verde.")
                else:
                    p.save()
            if errores:
                transaction.set_rollback(True)
        for e in errores:
            messages.error(request, e)
        if not errores:
            messages.success(request, f"{cambios} cambio(s) guardado(s)." if cambios else "Sin cambios.")
        destino = request.path + (f"?equipo={equipo.id}" if es_ger and equipo else "")
        return redirect(destino)

    propias = {m.indicador_id: m for m in MetaEquipo.objects.filter(supervisor=equipo)} if equipo else {}
    secciones = []
    for rol, titulo, ayuda in SECCIONES:
        if rol == "supervisor" and not es_ger:
            continue
        filas = []
        for i in Indicador.objects.filter(rol=rol, activo=True).order_by("orden", "id"):
            propia = propias.get(i.id)
            efectiva = i
            if propia:
                efectiva = Indicador(meta=propia.meta, minimo=propia.minimo, mayor_es_mejor=i.mayor_es_mejor, unidad=i.unidad)
            filas.append({"i": i, "propia": propia, "regla": efectiva.regla()})
        secciones.append({"rol": rol, "titulo": titulo, "ayuda": ayuda, "filas": filas,
                          "editable": rol in roles_editables and (es_ger or equipo is not None)})
    return render(request, "tablero/metas.html", {
        "secciones": secciones, "equipo": equipo, "supervisores": supervisores, "es_ger": es_ger,
        "editando_general": es_ger and equipo is None, "p": Parametros.actual(),
        "cambios": CambioMeta.objects.select_related("indicador", "usuario")[:25],
        "desactivados": Indicador.objects.filter(activo=False) if es_ger else []})


class IndicadorForm(forms.ModelForm):
    class Meta:
        model = Indicador
        fields = ["rol", "nombre", "descripcion", "unidad", "mayor_es_mejor", "meta", "minimo", "peso", "activo"]
        labels = {"rol": "Dónde se usa", "mayor_es_mejor": "Más es mejor (desmarcado: menos es mejor)",
                  "descripcion": "Qué mide y cómo se obtiene", "minimo": "Límite (rojo)",
                  "peso": "Peso en el índice (0 = sólo informativo)"}
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["rol"].disabled = True  # no se puede mover un indicador existente de lugar
        for campo in ("meta", "minimo"):
            self.fields[campo].localize = True

    def clean(self):
        d = super().clean()
        m, lim = d.get("meta"), d.get("minimo")
        if m is not None and lim is not None:
            if (m <= lim) if d.get("mayor_es_mejor") else (m >= lim):
                self.add_error("minimo", "El límite rojo tiene que estar del lado 'malo' de la meta.")
        return d


@requiere_rol(GERENCIA)
def indicador(request, pk=None):
    """Alta, edición, desactivación y borrado de indicadores (sólo gerencia)."""
    from django.utils.text import slugify
    i = get_object_or_404(Indicador, pk=pk) if pk else None
    if request.method == "POST":
        accion = request.POST.get("accion")
        if i and accion == "eliminar":
            if i.tipo != "manual":
                messages.error(request, "Los indicadores del sistema no se eliminan: desactivalos.")
            else:
                CambioMeta.objects.create(usuario=request.user, indicador=i, alcance="general", antes=i.nombre,
                                          despues="eliminado")
                i.delete()
                messages.success(request, "Indicador eliminado.")
                return redirect("tablero:metas")
            return redirect("tablero:indicador", pk=i.pk)
        f = IndicadorForm(request.POST, instance=i)
        if f.is_valid():
            antes = (f"{i.nombre} · meta {i.meta.normalize():f}/{i.minimo.normalize():f} · peso {i.peso}"
                     f"{'' if i.activo else ' · desactivado'}") if i else "—"
            nuevo = f.save(commit=False)
            if not i:
                base = "manual-" + slugify(nuevo.nombre)[:30]
                codigo, k = base, 1
                while Indicador.objects.filter(codigo=codigo).exists():
                    k += 1
                    codigo = f"{base}-{k}"
                nuevo.codigo, nuevo.tipo = codigo, Indicador.Tipo.MANUAL
                nuevo.orden = 100
            nuevo.save()
            CambioMeta.objects.create(usuario=request.user, indicador=nuevo, alcance="general", antes=antes,
                                      despues=f"{nuevo.nombre} · meta {nuevo.meta.normalize():f}/{nuevo.minimo.normalize():f}"
                                              f" · peso {nuevo.peso}{'' if nuevo.activo else ' · desactivado'}")
            messages.success(request, "Indicador creado: ahora cargá sus valores." if not i else "Indicador guardado.")
            return redirect("tablero:indicador_valores", pk=nuevo.pk) if not i else redirect("tablero:metas")
    else:
        f = IndicadorForm(instance=i, initial={} if i else {"rol": request.GET.get("rol", "tecnico"), "peso": 5})
    return render(request, "tablero/indicador_form.html", {"form": f, "i": i})


@requiere_rol(GERENCIA, SUPERVISOR)
def indicador_valores(request, pk):
    """Carga mensual de un indicador manual: por técnico, por supervisor o de la empresa."""
    from datetime import date

    from django.utils import timezone

    from core.models import ValorIndicador
    from finanzas.proyeccion import inicio_mes, sumar_meses
    i = get_object_or_404(Indicador, pk=pk, tipo="manual")
    es_ger = rol_de(request.user) == GERENCIA
    if not es_ger and i.rol == "supervisor":
        messages.error(request, "Ese indicador lo carga gerencia.")
        return redirect("tablero:metas")
    try:
        periodo = inicio_mes(date.fromisoformat(request.GET.get("mes", request.POST.get("mes", "")) + "-01"))
    except ValueError:
        periodo = inicio_mes(timezone.localdate())
    if i.rol == "mando":
        personas = [] if es_ger else [persona_de(request.user)]
    elif i.rol == "tecnico":
        personas = Persona.objects.filter(rol="tecnico", activo=True).order_by("apellido")
        if not es_ger:
            personas = personas.filter(supervisor=persona_de(request.user))
    else:
        personas = Persona.objects.filter(rol="supervisor", activo=True).order_by("apellido")
    claves = [None] if i.rol == "mando" and es_ger else [p.id for p in personas]
    if request.method == "POST":
        n = 0
        for pid in claves:
            v = request.POST.get(f"v_{pid or 'empresa'}", "").strip().replace(",", ".")
            if not v:
                ValorIndicador.objects.filter(indicador=i, persona_id=pid, periodo=periodo).delete()
                continue
            try:
                ValorIndicador.objects.update_or_create(indicador=i, persona_id=pid, periodo=periodo,
                                                        defaults={"valor": Decimal(v), "cargado_por": request.user})
                n += 1
            except InvalidOperation:
                messages.error(request, f"«{v}» no es un número.")
        messages.success(request, f"{n} valor(es) guardado(s) para {periodo:%m/%Y}.")
        return redirect(f"{request.path}?mes={periodo:%Y-%m}")
    actuales = {v.persona_id: v.valor for v in ValorIndicador.objects.filter(indicador=i, periodo=periodo)}
    filas = [{"clave": "empresa", "nombre": "Toda la empresa", "valor": actuales.get(None)}] if None in claves else [
        {"clave": p.id, "nombre": f"{p.apellido}, {p.nombre}", "valor": actuales.get(p.id),
         "estado": i.estado(actuales.get(p.id))} for p in personas]
    for f in filas:
        f.setdefault("estado", i.estado(f["valor"]))
    return render(request, "tablero/indicador_valores.html", {
        "i": i, "filas": filas, "periodo": periodo, "anterior": sumar_meses(periodo, -1),
        "siguiente": sumar_meses(periodo, 1)})
