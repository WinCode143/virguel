"""Componentes de interfaz reutilizables: íconos y menú de navegación."""
from django import template
from django.templatetags.static import static
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def icono(nombre, clase=""):
    return format_html('<svg class="ic {}" aria-hidden="true"><use href="{}#{}"></use></svg>',
                       clase, static("img/iconos.svg"), nombre)


@register.simple_tag(takes_context=True)
def nav(context, vista, texto, nombre_icono, badge=0, *args):
    """Ítem de menú; queda marcado si es la pantalla actual."""
    request = context["request"]
    try:
        url = reverse(vista, args=args)
    except NoReverseMatch:
        return ""
    actual = getattr(request.resolver_match, "view_name", "")
    activo = actual == vista or (vista == "tablero:tecnicos" and actual == "tablero:tecnico")
    marca = format_html('<span class="badge">{}</span>', badge) if badge else ""
    return format_html('<a href="{}" class="nav-item{}"{}>{}<span>{}</span>{}</a>', url,
                       " activo" if activo else "", ' aria-current="page"' if activo else "",
                       icono(nombre_icono), texto, marca)


@register.simple_tag(takes_context=True)
def grupo_abierto(context, *vistas):
    """'open' si la pantalla actual pertenece al grupo (para <details>)."""
    actual = getattr(context["request"].resolver_match, "view_name", "")
    return "open" if actual in vistas or (actual == "tablero:tecnico" and "tablero:tecnicos" in vistas) else ""
