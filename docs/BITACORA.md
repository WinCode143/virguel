# Bitácora del proyecto — ERP / Tablero de control Virguel

Registro cronológico de lo que se fue haciendo, decisiones tomadas y por qué.
Formato: fecha · qué se hizo · decisiones / notas.

---

## 2026-10-07 — Sesión 1: arranque del proyecto

### Requerimiento recibido
Dos textos del cliente (Virguel) con el alcance. Se consolidaron en 9 módulos
(ver `docs/REQUERIMIENTOS.md`). Puntos clave: la empresa **no vende** y **no se
integra con Oracle**: todos los datos salen del relevamiento interno.

### Decisiones de arquitectura
| Decisión | Motivo |
|---|---|
| **Django 5.2 (Python 3.13)** como base | Un ERP es mayormente ABM + reglas + reportes. Django trae ORM, migraciones, panel de administración, usuarios/permisos y formularios listos: ahorra meses frente a armar todo a mano. |
| **PostgreSQL 16** desde el inicio (pedido del usuario) | Base robusta, multiusuario, la misma que se usará en producción. Power BI se conecta nativamente a PostgreSQL. |
| PostgreSQL propio en **Docker**, puerto **5434** | Los puertos 5432/5433 de la máquina ya los usan otros proyectos; se aísla con contenedor `virguel-postgres` y volumen `virguel_pgdata`. |
| Una **app de Django por módulo** del ERP | Mantiene separado cada módulo (1 a 9) y facilita que crezcan por separado. |
| **Parámetros de negocio editables** (`core.Parametros`) | Los supuestos del cliente (60 días de stock, 5–6 ha/día, 50 % vs 60 % de decodificadores, ventana de evaluación) cambian; se ajustan desde el admin sin tocar código. |
| **Stock por lotes con FIFO** | La "antigüedad de stock" sólo se puede medir si cada ingreso es un lote con fecha; las salidas consumen primero lo más viejo. |
| **Egresos automáticos** por señales | Compras de stock, services, entregas de EPP y costos de siniestros generan su egreso solos: finanzas se alimenta de la operación (no hay ingresos por ventas). |
| **Alertas centralizadas** (`core.Alerta`) idempotentes | Las tareas diarias abren/actualizan/cierran alertas sin duplicarlas. |
| **Tres "caras" del sistema según rol** (pedido del usuario) | Técnicos → app móvil (PWA instalable en el celular). Supervisores → app móvil (modo supervisor) + tableros de su equipo. Gerencia/Administración → aplicación de escritorio completa. Se redirige automáticamente al iniciar sesión. |

### Hecho
- Repositorio git, entorno virtual con `uv`, Django + psycopg 3.
- `docker-compose.yml` con PostgreSQL 16; `.env` (no versionado) y `.env.example`.
- Modelos de datos de los 9 módulos + maestros y migraciones aplicadas en PostgreSQL.

### Núcleo de cálculo
- **Evaluación de técnicos** (`capacitacion/evaluacion.py`): 4 dimensiones (productividad
  relativa a la mediana, calidad, disciplina, seguridad) + tendencia → diagnóstico
  (capacitar / riesgo alto / observación / aprendizaje / mejora / adecuado) y riesgo 0–100.
- **Evaluación de supervisores** (`supervision/evaluacion.py`): imagen (encuesta),
  control en calle, gestión de desvíos, objetivos.
- **Planificación** (`tablero/planificacion.py`): hectáreas → clientes → decodificadores;
  probabilidad de decodificador con modelo Beta-Binomial (supuesto 50–60 % corregido con datos reales).
- **Stock** (`inventario/services.py`): FIFO, antigüedad por lote, stock diario vs. técnicos
  en calle con días de cobertura, previsión por demanda comercial.
- **Finanzas** (`finanzas/proyeccion.py` + `signals.py`): egresos automáticos y proyección a 3 meses.
- **Automatización diaria** (`manage.py tareas_diarias`): encuestas, cierre de objetivos
  vencidos y alertas de los 6 módulos.

### Interfaces
- **Escritorio** (gerencia): 12 pantallas (Resumen, Alertas y una por módulo) con gráficos
  Chart.js usando una paleta validada para daltonismo, modo claro/oscuro, tabla de datos
  debajo de cada gráfico y estados siempre con ícono + texto.
- **App móvil PWA** (técnicos y supervisores): instalable, con cámara y GPS para informes.
- **Admin de Django** configurado para toda la carga de datos.
- **Power BI**: 12 vistas SQL en el esquema `powerbi` + CSV por web + usuario de sólo lectura.

### Decisiones durante la sesión
| Decisión | Motivo |
|---|---|
| Al iniciar sesión se redirige según rol (y el supervisor en celular va a la app) | Pedido del usuario: la información llega distinto a técnicos, supervisores y gerencia. |
| Encuesta por link con token, sin login | Para poder enviarla por WhatsApp/SMS y que responder sea inmediato. |
| Encuesta confidencial (supervisor sólo ve promedios) | Si el técnico teme represalias, la encuesta no sirve. |
| Charla y recapacitación casi no penalizan la disciplina | Son formativas; penalizarlas desalienta a los supervisores a corregir. Se detectó al calibrar con datos demo (técnicos normales salían "en observación"). |
| Disciplina medida por cada 30 días | Que el puntaje no dependa del largo de la ventana elegida. |
| Service worker sólo cachea archivos estáticos | Evitar que queden datos personales guardados en celulares compartidos. |
| Chart.js servido localmente (no CDN) | Que el sistema funcione aunque no haya acceso a internet externo. |

### Datos de demostración
`manage.py generar_demo --reset`: 150 días, 36 técnicos con perfiles (bueno, capacitar,
riesgo, nuevo, mejora), 5 supervisores con perfiles (uno con mal trato, uno ausente),
~20.000 órdenes, ~80.000 movimientos de stock, lotes deliberadamente parados, flota con
services vencidos, siniestros y demanda comercial con un pico de campaña.
**Verificación:** el diagnóstico automático detectó a los 3 técnicos de riesgo, a los
2 ingresantes y a los 2 supervisores problemáticos que se simularon.

### Calidad
- 21 tests automáticos (`tests/test_negocio.py`), todos pasan. Cubren FIFO, antigüedad,
  stock diario, capacidad, probabilidad, diagnóstico de técnicos, supervisores, egresos
  automáticos, alertas, services, permisos por rol, encuesta y cierre de orden desde la app.
- **Bug encontrado por los tests y corregido:** el consumo promedio por técnico incluía
  las jornadas del día en curso (todavía sin consumo), sobreestimando los días de cobertura.
- Revisión visual con capturas en navegador headless (escritorio claro/oscuro y celular).
  Corregido: ejes de gráficos, serie de línea, alineación de tarjetas, números con coma
  decimal en CSS e inputs.
- Linter (ruff) sin errores.

### Pendiente / próximos pasos sugeridos
1. Validar con el cliente los supuestos de `docs/REQUERIMIENTOS.md` (sección "Puntos ambiguos").
2. Envío automático (sin clics) del link de encuesta: hoy es con un clic vía `wa.me`; automatizarlo requiere WhatsApp Business API o SMS.
3. ~~Carga masiva inicial~~ (hecho: importación Excel/CSV).
4. Instalación en servidor: ya está empaquetado (ver `docs/ARQUITECTURA.md`); falta el servidor y el dominio del cliente.
5. Calibrar umbrales del diagnóstico con 2–3 meses de datos reales.
6. ~~Modo sin señal en la app~~ (hecho, ver más abajo).

### Agregados (misma sesión, segunda parte)
- **Encuestas por WhatsApp** (`/tablero/encuestas/`): lista de encuestas del día con botón
  que abre WhatsApp con el mensaje y el link listos (enlaces `wa.me`, sin proveedor pago).
  Supervisores ven sólo su equipo; nunca el contenido de las respuestas.
- **Importación masiva Excel/CSV** (`/tablero/importar/`, `tablero/importar.py`) para la
  carga inicial: personas (crea usuarios y accesos), vehículos, materiales, stock por lote,
  clientes, demanda comercial y órdenes. Plantillas descargables. Todo o nada: si una fila
  falla, no se guarda nada y se lista fila por fila qué corregir. Acepta formato argentino
  (1.500 / 12,50 / dd/mm/aaaa) y separador `,` o `;`.
  Los tests detectaron y se corrigió: "1.500" se leía como 1,5.
- Nueva dependencia: **openpyxl** (lectura de Excel).
- Tests: 25, todos pasan.
- **Modo sin señal en la app** (`static/js/offline.js` + service worker):
  formularios de la app (cerrar orden, jornada, incidente, informe, acción, encuesta)
  se guardan en el celular (IndexedDB, incluidas fotos) si no hay conexión y se reenvían
  solos en orden al volver la señal. El celular manda la fecha real de carga y el servidor
  la respeta (máx. 7 días atrás). Las pantallas de `/app/` quedan disponibles sin señal y
  se borran del celular al cerrar sesión.
  **Probado de punta a punta** en Chromium headless: sin red → queda 1 pendiente y aviso
  visible → vuelve la red → se envía y el servidor registra la orden completada.
- Tests: 26, todos pasan.
- **Seguridad**: revisión propia del código. Corregido un *open redirect* en "Resolver alerta".
  Verificado que un técnico no puede cerrar órdenes ajenas y un supervisor no ve otros equipos.
  Configuración segura automática con `DEBUG=0` (HTTPS, cookies seguras, HSTS, sesión de 12 h).
- **Producción**: `Dockerfile` + `deploy/docker-compose.prod.yml` (PostgreSQL, gunicorn, tarea
  diaria a las 21:00 y Caddy con HTTPS automático) + `deploy/backup.sh`. Imagen construida y
  probada con `DEBUG=0`.
- Tests: 28, todos pasan.
- **Historial semanal de evaluación** (`capacitacion.EvaluacionHistorica`): la tarea diaria
  guarda una foto semanal del diagnóstico de cada técnico. La ficha muestra la evolución del
  riesgo y el listado la variación del último mes ("Δ 4 sem."). Vista `powerbi.evaluacion_historica`.
  Responde al pedido de medir "capacidad a largo plazo" y no sólo el momento.
- **Bug corregido (detectado en la revisión visual):** al evaluar a una sola persona (ficha,
  "Mi desempeño", vista de supervisor) la mediana de referencia se calculaba sólo con esa
  persona, y cualquiera quedaba "al 100 % del equipo". Ahora la referencia es siempre todo el
  plantel activo (`mediana_plantel`). Test agregado.
- El usuario de Power BI recibe permisos por defecto sobre vistas futuras del esquema.
- Tests: 29, todos pasan.
- **Asignación automática de órdenes** (`/tablero/asignacion/`, `tablero/asignacion.py`):
  reparte las órdenes pendientes entre los técnicos según su **capacidad real** (promedio
  de 30 días, mín. 2, tope 6), primero en su zona y después en otras, priorizando retrabajos
  y atrasadas. Excluye ausentes. Gerencia o el supervisor (sólo su equipo) revisan y confirman.
  Las que no entran quedan listadas: indica falta de capacidad. Test agregado (30 tests).
