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
| `personal` | **Control de personal**: fichadas (asistencia), novedades/licencias, feriados, documentos del legajo. `indicadores.py`: presentismo, ausentismo, estado del día, dotación/rotación. `parte.py`: parte diario por mail. |
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

**Presentismo** (`personal/indicadores.py`): días esperados = laborables según el horario de
cada persona (lun–vie, + sábado si corresponde), sin feriados, entre su ingreso y su egreso, y
desde que el sistema empezó a registrar asistencia. Presente = fichó o tuvo jornada en calle.
Día sin presencia: justificada si hay novedad justificada; si no, injustificada. Vacaciones y
francos no cuentan para el presentismo. El día en curso no cuenta como falta.

**Parte diario por mail**: configurar SMTP en `.env` (`EMAIL_HOST`, `EMAIL_PORT`,
`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`, `URL_SISTEMA`). Sirve Gmail
(con "contraseña de aplicación"), Outlook/Office 365 o el correo de la empresa. Sin SMTP los
mails se guardan como archivos en `media/mails/`. Se envía con la tarea diaria o con
`manage.py enviar_parte`.

## Seguridad y privacidad
- Acceso por rol (`core/roles.py`): técnico, supervisor, gerencia. El supervisor ve sólo su equipo.
- La encuesta usa un token UUID por técnico y día; no requiere login para poder enviarse por mensaje.
  El supervisor nunca ve respuestas individuales.
- El service worker de la PWA sólo guarda archivos estáticos (no páginas con datos personales).
- Power BI usa un usuario PostgreSQL de sólo lectura limitado al esquema `powerbi`.
- Exportaciones CSV: sesión de gerencia o `?token=` (variable `POWERBI_TOKEN`).

## Instalación en servidor (producción)

Requisitos: un servidor Linux con Docker, un dominio apuntando a su IP y los puertos 80/443 abiertos.

```bash
git clone <repositorio> /opt/virguel && cd /opt/virguel
cp .env.example .env
# Editar .env: DJANGO_DEBUG=0, DJANGO_SECRET_KEY (larga y aleatoria),
#              POSTGRES_PASSWORD, POWERBI_TOKEN
DOMINIO=erp.virguel.com.ar docker compose -f deploy/docker-compose.prod.yml up -d --build
docker compose -f deploy/docker-compose.prod.yml exec web python manage.py createsuperuser
```

Qué levanta (`deploy/docker-compose.prod.yml`):
| Servicio | Función |
|---|---|
| `db` | PostgreSQL 16 con volumen persistente. |
| `web` | Django con **gunicorn** (aplica migraciones al arrancar). |
| `tareas` | `manage.py programador`: 07:30 recordatorios (partes adeudadas) y 21:00 tarea diaria (encuestas, alertas, parte por mail). Horarios con `HORA_RECORDATORIOS` / `HORA_TAREAS`. |
| `caddy` | Proxy con **HTTPS automático** (Let's Encrypt), sirve estáticos y fotos. HTTPS es obligatorio: sin él no funcionan la cámara, el GPS ni la instalación de la app en el celular. |

Backups: `deploy/backup.sh /ruta/backups` (base + fotos, conserva 30 días). Programarlo en el cron del servidor:
```
30 2 * * * /opt/virguel/deploy/backup.sh /opt/backups
```

Power BI: abrir el puerto de PostgreSQL sólo hacia la IP de la oficina (o usar el gateway de Power BI) y
crear el usuario de lectura con `docker compose ... exec web python manage.py crear_lector_powerbi --password ...`.

Verificado: la imagen se construye y corre con `DEBUG=0` (gunicorn, cabeceras de seguridad, login obligatorio).
`manage.py check --deploy` sólo deja dos avisos opcionales de HSTS (subdominios / preload) que dependen del dominio del cliente.
