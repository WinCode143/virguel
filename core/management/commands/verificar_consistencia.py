"""Verifica que los datos sean coherentes entre sí (después de migrar, restaurar un respaldo o importar).

Uso:  python manage.py verificar_consistencia
Sale con código 1 si encuentra contradicciones; los avisos (datos a revisar, no errores) no fallan.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Count, F, Q, Sum


class Command(BaseCommand):
    help = "Comprueba invariantes de inventario, pañol, reservas, visitas y dinero."

    def handle(self, *args, **opts):
        from finanzas.models import Ingreso
        from herramientas.models import Elemento, MovimientoPanol
        from inventario.models import LoteIngreso, ReservaMaterial, UnidadEquipo
        from operaciones.models import Intento, ParticipacionVisita
        from supervision.models import InformeControl

        errores, avisos = [], []

        # Inventario: ningún lote negativo ni con más disponible que lo ingresado
        n = LoteIngreso.objects.filter(Q(cantidad_disponible__lt=0) | Q(cantidad_disponible__gt=F("cantidad"))).count()
        if n:
            errores.append(f"{n} lote(s) con cantidad disponible fuera de rango")
        # Reservas: lo entregado no supera lo reservado; lo comprometido no supera el stock del depósito
        n = ReservaMaterial.objects.filter(cantidad_entregada__gt=F("cantidad")).count()
        if n:
            errores.append(f"{n} reserva(s) con más entregado que reservado")
        stock = dict(LoteIngreso.objects.values_list("material").annotate(t=Sum("cantidad_disponible")))
        for mid, q in (ReservaMaterial.objects.filter(estado="activa").values_list("material")
                       .annotate(t=Sum(F("cantidad") - F("cantidad_entregada")))):
            if (q or 0) > (stock.get(mid) or 0):
                avisos.append(f"material {mid}: reservado pendiente {q} > stock en depósito {stock.get(mid) or 0}")
        # Equipos por serie: una unidad fuera del depósito no cuenta en sus lotes
        n = UnidadEquipo.objects.exclude(ubicacion="deposito").filter(en_stock=True).count()
        if n:
            errores.append(f"{n} equipo(s) fuera del depósito marcados como parte de su stock")
        n = UnidadEquipo.objects.filter(ubicacion="deposito", en_stock=True).exclude(
            condicion__in=("nuevo", "usado_ok")).count()
        if n:
            errores.append(f"{n} equipo(s) no utilizables contados en el stock del depósito")
        # Pañol: el stock de cada elemento coincide con su libro de movimientos
        libro = dict(MovimientoPanol.objects.values_list("elemento").annotate(t=Sum("cantidad")))
        for el in Elemento.objects.all():
            if libro.get(el.id) is not None and libro[el.id] != el.stock:
                errores.append(f"pañol {el.codigo}: stock {el.stock} ≠ libro {libro[el.id]}")
        # Visitas: un único ejecutor vigente por visita, y es Intento.tecnico
        for it in Intento.objects.filter(tecnico__isnull=False).annotate(
                n=Count("participantes", filter=Q(participantes__funcion="ejecutor"))).filter(n__gt=1)[:50]:
            errores.append(f"visita {it.pk}: más de un ejecutor")
        n = ParticipacionVisita.objects.filter(funcion="ejecutor").exclude(persona_id=F("intento__tecnico_id")).count()
        if n:
            errores.append(f"{n} participación(es) de ejecutor que no coinciden con el técnico de la visita")
        n = InformeControl.objects.filter(visita_ambigua=True).count()
        if n:
            avisos.append(f"{n} informe(s) de control anteriores con visita ambigua (revisar a mano)")
        # Incidentes: lo recuperado declarado coincide con los recuperos documentados del expediente
        from incidentes.models import ActuacionIncidente, Siniestro
        rec = dict(ActuacionIncidente.objects.filter(tipo="recupero", monto__isnull=False).values_list("siniestro")
                   .annotate(t=Sum("monto")))
        for s in Siniestro.objects.filter(pk__in=rec):
            if rec[s.pk] != s.monto_recuperado:
                avisos.append(f"siniestro {s.numero}: recuperos documentados {rec[s.pk]} ≠ recuperado {s.monto_recuperado}")
        # Dinero: un ingreso no tiene saldo negativo (cobrado de más)
        for i in Ingreso.objects.all():
            if i.saldo < Decimal("0"):
                errores.append(f"ingreso {i.pk} con saldo negativo ({i.saldo})")

        for a in avisos:
            self.stdout.write(self.style.WARNING(f"AVISO  {a}"))
        for e in errores:
            self.stdout.write(self.style.ERROR(f"ERROR  {e}"))
        if errores:
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(f"Datos consistentes ({len(avisos)} aviso(s) para revisar)."))
