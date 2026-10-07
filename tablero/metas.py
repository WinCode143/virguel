"""Metas y semáforos: gerencia fija las generales; cada supervisor puede ajustar las de su equipo."""
from decimal import Decimal, InvalidOperation

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
        for i in Indicador.objects.filter(rol=rol, activo=True):
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
        "cambios": CambioMeta.objects.select_related("indicador", "usuario")[:25]})
