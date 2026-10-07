# Arquitectura técnica

## Visión general

```
 Celular (técnicos / supervisores)        PC (gerencia / administración / supervisores)
   PWA /app/  ───────────┐                  ┌──────────  /tablero/   /admin/
                         ▼                  ▼
                 ┌────────────────────────────────┐
                 │   Django 5.2 (Python 3.13)     │──── tarea diaria (cron/systemd):
                 │   un módulo (app) por área     │     encuestas + alertas
                 └───────────────┬────────────────┘
                                 ▼
                 ┌────────────────────────────────┐
                 │ PostgreSQL 16                   │
                 │  public.*   tablas del sistema  │
                 │  powerbi.*  vistas planas  ─────┼──► Power BI (usuario sólo lectura)
                 └────────────────────────────────┘
```

## Módulos (apps de Django)

| App | Contenido |
|---|---|
| `core` | Parámetros del sistema, zonas, personas (técnicos/supervisores), clientes, alertas, roles. |
| `operaciones` | Tipos de tarea, jornadas (personal en calle), órdenes de trabajo. |
| `inventario` | Materiales, lotes de ingreso (FIFO), salidas, materiales por tipo de tarea, demanda comercial. `services.py`: FIFO, antigüedad, stock diario, previsión. |
| `supervision` | Informes de control, acciones correctivas, objetivos del supervisor, encuesta diaria. `evaluacion.py`: puntaje de supervisores. |
| `incidentes` | Siniestros con recomendación de acción legal. |
| `herramientas` | EPP / herramientas / críticos y sus asignaciones con vencimiento. |
| `capacitacion` | Competencias, cursos, capacitaciones, evaluaciones. `evaluacion.py`: diagnóstico y riesgo de técnicos. |
| `flota` | Vehículos, tipos de service, services realizados, cálculo del próximo service. |
| `finanzas` | Categorías, egresos (automáticos por señales), costos fijos, proyección. |
| `tablero` | Pantallas de escritorio, planificación/capacidad, automatización diaria, exportación Power BI, generador de datos demo. |
| `movil` | App de campo (PWA): vistas, formularios, manifest y service worker. |

## Cálculos clave

**Stock FIFO y antigüedad** (`inventario/services.py`): cada ingreso es un lote con
fecha. Las salidas descuentan del lote más viejo. Días en stock = hoy − fecha del lote,
para los lotes con saldo. Aviso ≥ 45 días, crítico ≥ 60 (parámetros).

**Stock diario vs. personal en calle**: consumo por técnico-día = consumo de los
últimos 30 días completos ÷ jornadas en calle en ese período. Consumo esperado hoy =
eso × técnicos en calle hoy. Días de cobertura = stock ÷ consumo esperado.

**Capacidad** (`tablero/planificacion.py`): cuadrillas = técnicos ÷ técnicos por
cuadrilla; hectáreas = cuadrillas × (5–6); clientes = mín(hectáreas × densidad de la
zona, técnicos × clientes por técnico).

**Probabilidad de decodificador**: modelo Beta-Binomial. Prior = punto medio de los
escenarios (55 %) con peso de 20 clientes; se suma lo observado en los últimos 90
días. Se informa media e intervalo del 90 %.

**Diagnóstico de técnicos** (`capacitacion/evaluacion.py`), ventana de 90 días:
- Productividad = OT completadas ÷ días en calle, relativa a la mediana del equipo
  (score = índice × 70, la mediana vale 70).
- Calidad = retrabajos causados, órdenes fallidas y puntaje en controles.
- Disciplina = sanciones por cada 30 días (apercibimiento 2, multa 3, suspensión 5,
  recapacitación 0,5, charla 0).
- Seguridad = siniestros (leve 1, grave 3, crítico 6) y EPP obligatorio faltante.
- Tendencia = productividad del último tercio de la ventana vs. el primero.
- Riesgo = 100 − (0,20·prod + 0,30·cal + 0,25·disc + 0,25·seg).

**Evaluación de supervisores** (`supervision/evaluacion.py`), 30 días: imagen (encuesta),
control en calle (informes/día vs. 4 y calidad de documentación), gestión de desvíos
(% con acción y días de respuesta) y objetivos cumplidos.

**Egresos automáticos** (`finanzas/signals.py`): al guardar un lote de stock, un
service, una entrega de EPP o el costo real de un siniestro, se crea o actualiza su
egreso (clave única `origen`). Al borrarlo, se borra el egreso.

**Alertas** (`tablero/automatizacion.py` + `core/services.SincronizadorAlertas`):
cada ejecución recalcula las condiciones; abre, actualiza o cierra alertas sin duplicar.

## Seguridad y privacidad
- Acceso por rol (`core/roles.py`): técnico, supervisor, gerencia. El supervisor ve sólo su equipo.
- La encuesta usa un token UUID por técnico y día; no requiere login para poder enviarse por mensaje.
  El supervisor nunca ve respuestas individuales.
- El service worker de la PWA sólo guarda archivos estáticos (no páginas con datos personales).
- Power BI usa un usuario PostgreSQL de sólo lectura limitado al esquema `powerbi`.
- Exportaciones CSV: sesión de gerencia o `?token=` (variable `POWERBI_TOKEN`).

## Instalación en servidor (producción)

1. Servidor Linux con Docker (o PostgreSQL 16 instalado) y Python 3.12+.
2. `.env` con `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` larga y aleatoria, `DJANGO_ALLOWED_HOSTS=<dominio>`,
   credenciales de PostgreSQL y `POWERBI_TOKEN`.
3. `pip install -r requirements.txt gunicorn`, `manage.py migrate`, `manage.py collectstatic`,
   `manage.py createsuperuser`.
4. Servir con **gunicorn** detrás de **nginx** con HTTPS (obligatorio: la cámara y el GPS
   del celular y la instalación de la PWA sólo funcionan en HTTPS). nginx sirve `/static/` y `/media/`.
5. Programar la tarea diaria, por ejemplo con cron a las 21:00:
   ```
   0 21 * * * cd /opt/virguel && .venv/bin/python manage.py tareas_diarias >> /var/log/virguel.log 2>&1
   ```
6. Backup diario de PostgreSQL (`pg_dump`) y de la carpeta `media/` (fotos de informes).
