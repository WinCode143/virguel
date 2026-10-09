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

---

## 2026-10-07 — Sesión 1, tercera parte: reorientación a CONTROL DE PERSONAL

**Aclaración del usuario:** "no es un tema de hectáreas, es un sistema de control de personal".
También preguntó qué existe: app móvil (sí, PWA), sitio web (sí), dashboards (sí) y
**mails con partes (no existía → se agregó)**.

### Hecho
- Nueva app **`personal`**: `Asistencia` (fichada entrada/salida con GPS, minutos tarde,
  horas y horas extra), `Novedad` (enfermedad, ART, vacaciones, licencia, franco,
  injustificada, suspensión; con certificado y aprobación), `Feriado`, `TipoDocumento` y
  `DocumentoPersonal` (vencimientos).
- Persona: horario de entrada/salida, trabaja sábados, motivo de egreso. Parámetros:
  tolerancia de llegada tarde, horas de jornada, mails del parte, **hectáreas opcionales (apagado)**.
- **App móvil**: fichar entrada/salida (técnicos y supervisores) con ubicación y hora real del
  celular (sirve sin señal); "Mi asistencia"; avisar ausencia con foto del certificado;
  el supervisor aprueba avisos y ve en vivo quién falta de su equipo.
- **Escritorio**: Asistencia de hoy, Presentismo y ausencias (CSV para liquidación), Legajos
  (ficha integral), Documentación, Dotación y rotación, Parte diario. El Resumen arranca con
  los indicadores de personal.
- **Parte diario por mail** (`personal/parte.py`, `manage.py enviar_parte`): HTML + texto,
  general para gerencia y por equipo para cada supervisor; se envía con la tarea de la noche.
  Funciona con cualquier SMTP (Gmail, Outlook, correo propio).
- Alertas de personal: 3+ faltas sin justificar en 30 días, 6+ llegadas tarde, avisos sin
  aprobar hace 2+ días, documentación obligatoria faltante o vencida.
- La asistencia **suma a la disciplina** en el diagnóstico de técnicos.
- Power BI: vistas `powerbi.personal`, `powerbi.asistencia`, `powerbi.novedades`.
- Datos demo: 5.000+ fichadas con tardanzas según perfil, 330 novedades, feriados,
  administrativos, egresos del último año y documentación con vencimientos.

### Decisiones
| Decisión | Motivo |
|---|---|
| Presente = fichó **o** tuvo jornada en calle | Evita marcar faltas falsas si un técnico trabajó pero olvidó fichar. |
| No se cuentan faltas antes de que el sistema registre asistencia, ni el día en curso | Detectado por los tests: sin esto, al arrancar todos figuraban "ausentes sin aviso". |
| El empleado sólo puede avisar ausencias justificables | "Injustificada" y "suspensión" las carga la empresa. |
| Fichada con la hora del celular (máx. 7 días atrás) | Sin señal la fichada llega tarde, pero debe registrar la hora real. |
| Vista previa del parte en un iframe del mismo origen | La protección anti-clickjacking (DENY) lo dejaba en blanco; se habilitó sólo `SAMEORIGIN` para esa vista. |
| Dependencias de migraciones fijas | Las vistas de Power BI dependían de "__latest__" y se rompieron al agregar migraciones nuevas. |

### Calidad
- Tests: **37**, todos pasan (nuevos: tardanza y horas extra, presentismo con feriado/vacaciones/
  enfermedad/falta, sin control no hay faltas, fichada con hora del celular, permisos del
  supervisor sobre avisos y legajos, aviso con certificado, capacidad sin hectáreas).
- Revisión visual de todas las pantallas nuevas (escritorio y celular).

---

## 2026-10-07 — Sesión 1, cuarta parte: la app del técnico

El usuario revisó qué ve un técnico y pidió: historial de órdenes, ver sus sanciones y
controles, notificaciones, ficha completa de la orden, repensar los datos del cierre,
**partes a cargo del técnico descontadas al usarlas**, **pedido de partes**, métricas de
rendimiento y **evaluación semanal del supervisor**.

### Hecho
- **Cierre de orden rediseñado**: empezar/terminar (tiempo automático), motivo de no resolución,
  materiales precargados según el tipo de trabajo y elegidos de su stock, series, foto,
  conformidad con firma en pantalla (canvas → PNG), ubicación al cerrar.
- **Stock por técnico** (`inventario/stock_tecnico.py`): entregas (salen de los lotes del depósito
  por FIFO), consumo en órdenes (no vuelve a tocar el depósito), devoluciones (vuelven como lote),
  partes paradas por FIFO, faltante para sus órdenes. El stock diario suma depósito + técnicos.
- **Pedidos de partes**: técnico → supervisor (aprueba en la app) → depósito (entrega en el escritorio).
- **Notificaciones**: modelo `Notificacion` + Web Push con claves VAPID (`manage.py generar_claves_push`).
  Disparadores: orden asignada (una sola notificación por técnico en la asignación masiva),
  control recibido, acción correctiva, pedido nuevo/aprobado/rechazado/listo, recordatorio semanal.
- **Evaluación semanal del supervisor**: una por semana y técnico; entra al puntaje del supervisor
  (promedio con la encuesta diaria, que ahora se puede apagar).
- Pantallas nuevas en la app: ficha de orden, historial, mis partes, pedir partes, mi legajo,
  mi rendimiento, evaluar a mi supervisor, notificaciones, menú "Yo"; para el supervisor, pedidos
  del equipo. En el escritorio: pedidos de partes y partes en manos de técnicos.
- Datos demo: entregas semanales a técnicos y consumo desde su stock (85.000 movimientos),
  teléfonos de clientes, motivos de no resolución, evaluaciones semanales, pedidos en curso,
  técnicos "de riesgo" que acumulan partes sin usar.

### Problemas encontrados y corregidos
- Al reemplazar la vista de la orden se borraron por accidente "Mi EPP" y "Mi desempeño";
  se detectó enseguida y se restauraron.
- Demo: consumos fraccionarios de equipos (0,2 módems) y redondeo de entregas que generaba
  alertas falsas de "usó sin tenerlo a su cargo" → unidades enteras y redondeo hacia arriba.
- El cierre sin `_momento_cliente` (sólo fecha) no respetaba la fecha de carga → corregido.

### Calidad
- Tests: **46**, todos pasan (nuevos: cierre que descuenta del stock del técnico, motivo
  obligatorio, tiempo medido, pedido → aprobación → entrega, permisos de supervisor sobre pedidos,
  partes paradas FIFO, faltante para órdenes, devolución, evaluación semanal única y su efecto
  en el puntaje, notificaciones).
- Nueva dependencia: **pywebpush**.

---

## 2026-10-07 — Sesión 1, quinta parte: métricas de productividad

Pedido del usuario: "hay que inventar métricas para medir la productividad de los técnicos y
los supervisores". Se diseñó un sistema de indicadores documentado en **`docs/METRICAS.md`**.

### Hecho
- Modelo **`core.Indicador`** (meta, mínimo, peso, unidad, sentido) editable en el admin;
  catálogo inicial cargado por migración: 13 indicadores de técnico y 13 de supervisor.
- Motor **`tablero/metricas.py`**: valores por persona y período, puntos 0–100 lineales
  entre mínimo y meta, índice ponderado **IPT** (técnicos) e **IGS** (supervisores),
  fortalezas/debilidades y mediana del grupo como referencia.
- Indicadores clave nuevos: **eficiencia de la jornada en horas estándar**, **resuelto en
  primera visita**, cumplimiento de agenda, no resueltas *evitables*, cierres documentados,
  **cierres en el domicilio (GPS)**, consumo vs. estándar, demora en arrancar; para
  supervisores: **cobertura de control**, **efectividad de las correcciones**, mejora del
  equipo, **tiempo de respuesta** a avisos y pedidos.
- Nuevos datos para medirlos: fecha de resolución de avisos y pedidos; coordenadas de clientes.
- Pantallas: Índice de técnicos (ranking), Índice de supervisores (comparativo con fortalezas
  y debilidades), ficha por persona con evolución semanal del índice. En la app: IPT en
  "Mi rendimiento" y IGS en "Indicadores" del supervisor.
- Datos demo: cierres con foto/firma/GPS e inicio de trabajo (últimos 45 días), tiempos de
  respuesta por supervisor, efecto de las correcciones (excepto en técnicos de riesgo).

### Decisiones y calibración
| Decisión | Motivo |
|---|---|
| Productividad en horas estándar, no en cantidad de órdenes | Evita premiar trabajos fáciles. |
| Separar no resueltas evitables de externas | No castigar al técnico por clientes ausentes o clima. |
| Indicadores sin datos suficientes no cuentan | No castigar ni premiar por falta de información (p. ej. < 3 desvíos). |
| Cobertura de control con peso 15 | En la primera calibración el supervisor ausente salía **primero**: casi no controlaba y por eso "resolvía" el 100 % de sus pocos desvíos. Con este ajuste queda último, como corresponde. |
| Presentismo del equipo sólo informativo | Se superponía con faltas sin aviso (lo que sí depende del supervisor). |

### Problema encontrado y corregido
- **El usuario de gerencia no tenía permisos en la carga de datos (admin)**: cualquier link
  "cargar/editar" le daba acceso denegado. Nuevo comando `manage.py configurar_grupos`
  (Gerencia, Administración, Supervisores, Técnicos con sus permisos); se ejecuta al generar
  datos demo y al arrancar en producción (Dockerfile).

### Calidad
- Tests: **54**, todos pasan (nuevos: puntos lineales, eficiencia en horas estándar, primera
  visita, no resueltas evitables, GPS en sitio, consumo vs. estándar, índice del supervisor y
  tiempo de respuesta, acceso de gerencia a la configuración de metas).
- Pendiente con datos reales: calibrar tiempos estándar por tipo de trabajo y metas
  (ver `docs/METRICAS.md`).

---

## 2026-10-07 — Sesión 1, sexta parte: panel general, gráficos y Excel

El usuario preguntó si había panel general, por técnico y por supervisor (había los dos
últimos; el general estaba a medias) y pidió que **se pueda exportar a Excel y tenga un
apartado gráfico**.

### Hecho
- **Panel general de productividad** (`/tablero/productividad/general/`, sólo gerencia):
  IPT e IGS promedio, tendencia, técnicos por nivel, "dónde está el problema de la empresa"
  (indicadores donde el valor típico está lejos de la meta), evolución semanal, cada indicador
  contra su meta, comparación por equipo y por zona, los 5 mejores y los 5 más bajos.
  La evolución se guarda 30 min en caché (calcularla tarda ~4 s).
- **Gráficos**: 5 en el panel general; en el panel de supervisores, IGS por supervisor y puntos
  por área de gestión (resultados, control y corrección, personas y clima, gestión).
- **Exportar a Excel** (`tablero/exportar_excel.py`, botón en los tres paneles): hojas Resumen,
  **Gráficos** (4 gráficos nativos de Excel, editables), Indicadores empresa, Técnicos,
  Supervisores, Por equipo, Por zona y Evolución; semáforo con colores y formato condicional.
  El supervisor exporta sólo su equipo.
- Verificado abriendo el Excel con LibreOffice y renderizándolo: los gráficos se dibujan.

### Problemas encontrados y corregidos
- La exportación fallaba si algún supervisor no tenía datos todavía (promedio de lista vacía).
  Lo detectó el test nuevo.
- En los gráficos horizontales con muchas barras se salteaban etiquetas → se muestran todas.
- En el gráfico de Excel los técnicos quedaban invertidos (peor arriba) → el mejor arriba.

### Calidad
- Tests: **55**, todos pasan.

---

## 2026-10-07 — Sesión 1, séptima parte: rediseño de interfaz, modo oscuro y orden

Pedido: "mejorá la UI/UX de la aplicación, la web y todo el proyecto, agregá modo oscuro, ordená todo".

### Hecho
- **Sistema de diseño nuevo** (`static/css/app.css`): tokens de color claro/oscuro, tipografía Inter,
  tarjetas, tablas con encabezado fijo, estados con fondo suave + forma + texto, foco de teclado
  visible, botones con estados, avisos tipo "toast" que se cierran solos, estilos de impresión.
- **Modo oscuro con selector** (claro / oscuro / automático) en escritorio, app, login y carga de
  datos; se recuerda por dispositivo, se aplica antes de pintar (sin parpadeo) y los gráficos se
  redibujan con los colores del tema.
- **Menú reorganizado por tarea** (sin la numeración del pedido original): Inicio, Personal,
  Productividad, Desempeño y calidad, Operación, Inventario, Recursos, Administración. Grupos
  plegables con íconos, el grupo actual abierto y memoria de los grupos abiertos.
- **Barra superior fija**: buscador de personas (atajo `/`), alertas, tema y usuario.
- **Íconos SVG propios** (49) en lugar de emojis/caracteres; componentes de plantilla `{% icono %}`,
  `{% nav %}` y `{% grupo_abierto %}` (`core/templatetags/ui.py`).
- **App de campo**: encabezado fijo con "volver", barra inferior con íconos y aviso de pendientes,
  botones más grandes, tarjetas de acción con íconos, tema.
- **Login** rediseñado; **carga de datos (admin)** con la identidad de Virguel, tema sincronizado,
  link "volver al sistema", secciones con nombres claros y en el mismo orden que el menú.
- Títulos de pantallas sin la numeración "1 ·", "5 ·", etc. Índice de documentación `docs/README.md`.

### Problemas encontrados y corregidos
- Un reemplazo automático rompió la primera línea de dos plantillas de la app; se detectó al
  compilar todas las plantillas y se corrigió.
- El título de la carga de datos salía amarillo en modo oscuro.

### Calidad
- Todas las plantillas compilan; 55 tests pasan; revisión visual en claro y oscuro (escritorio,
  celular, login y carga de datos).

---

## 2026-10-07 — Sesión 1, octava parte: login, credenciales, partes adeudadas y semáforos

Pedido: sistema de login, manejo de credenciales para gerencia, aviso diario de partes adeudadas
con días sin regularizar, información para gerente y supervisor con semáforos según objetivos y
una forma de fijar los límites; "pensá en cosas que se me pudieron pasar".

### Hecho
- **Login**: ingreso con usuario, **legajo o DNI**; bloqueo 15 min tras 5 intentos; registro de
  accesos (ingresos, salidas, fallidos, bloqueos, blanqueos, cambios de rol con IP y dispositivo);
  **cambio de clave obligatorio** en el primer ingreso y tras un blanqueo; "olvidé mi clave" por mail;
  clave mínima de 8 caracteres; al cambiar la clave se cierran las otras sesiones.
- **Credenciales** (`/personal/usuarios/`): crear acceso, **blanquear** (clave temporal legible que
  se muestra una sola vez + envío por WhatsApp), desbloquear, dar de baja/reactivar, roles, historial.
  Supervisores: sólo blanquear/desbloquear a su equipo. **Baja automática del acceso al egresar.**
- **Rol Depósito**: sólo inventario, pedidos, partes de técnicos y herramientas.
- **Aviso de privacidad** (Ley 25.326) que técnicos y supervisores aceptan antes de usar la app
  (GPS, fotos, horarios). Texto a validar por legales.
- **Partes adeudadas** (`inventario/deudas.py`): equipos retirados a clientes sin devolver (nuevo
  modelo `EquipoRetirado`, se crea al cerrar la orden con series retiradas), partes usadas sin cargo
  y partes paradas. Días sin regularizar con semáforo (amarillo > 2 días, rojo > 5; configurable).
  Aviso **cada mañana** al técnico y resumen al supervisor (`manage.py recordatorios`); banner en
  la app; pantalla de regularización para depósito (`/tablero/partes-adeudadas/`).
- **Programador** (`manage.py programador`): corre 07:30 recordatorios y 21:00 tarea diaria
  (reemplaza el bucle de shell del servicio de producción).
- **Semáforos con metas**: regla única (verde = cumple la meta; amarillo = dentro del límite;
  rojo = más allá del límite). **Tablero de mando** en el Resumen con 13 indicadores (presentismo,
  sin aviso, tardanzas, órdenes vs. capacidad, IPT, IGS, riesgo, partes adeudadas, siniestros,
  documentación, stock parado, alertas). **Metas y semáforos** (`/tablero/metas/`): gerencia fija
  metas generales, de cada equipo, pesos y umbrales; el supervisor fija las de su equipo (no las que
  lo evalúan a él). Validación de coherencia y **registro de cambios**.

### Problemas encontrados y corregidos
- El campo de metas no admitía valores mayores a 999.999 (falló al cargar el límite de stock parado).
- "Órdenes vs. capacidad (hoy)" siempre daba rojo durante el día → se mide el último día completo.
- Cuentas existentes no deben verse obligadas a cambiar la clave: sólo las creadas o blanqueadas.

### Calidad
- Tests: **71**, todos pasan (login por legajo/DNI, bloqueo, blanqueo + cambio obligatorio, permisos
  de supervisor sobre credenciales, baja por egreso, privacidad, rol depósito, partes adeudadas y su
  regularización, aviso diario, metas de equipo y registro, validaciones, tablero de mando).

---

## 2026-10-07 — Cómo ver el sistema

- `scripts/ver.sh`: levanta PostgreSQL y el servidor (escuchando en la red local), abre el escritorio
  en Firefox y la app en una ventana de Chromium con tamaño y perfil de celular (sesión separada).
- `scripts/capturas.py`: galería con las 60 pantallas (escritorio, app del técnico, app del supervisor,
  modo oscuro) en `capturas/index.html` (no se versiona). Verificado: las 60 rutas responden 200.
- Nota: al levantar, Docker recreó el contenedor de la base por cambios en `.env`; los datos están en
  el volumen `virguel_pgdata` y se conservaron.

---

## 2026-10-07 — La llamada (orden) como en la app que usan hoy

El usuario mostró capturas de la app actual (estilo Oracle Field Service: "Details" + "Debrief").

### Hecho
- **Ficha de la llamada** (`/app/orden/<id>/`): primero la tarea (tipo, número, estado, fecha); luego
  el contacto del cliente (nombre, teléfono para llamar, **mail** nuevo, dirección, cómo llegar);
  **LOM** = pedido de partes asociado a la llamada, precargado con lo que lleva el trabajo menos lo
  que el técnico ya tiene; **Notas**: indicación de despacho, notas de esta llamada y de visitas
  anteriores de otros técnicos al mismo cliente, y se pueden agregar notas.
- **Debrief** (`/app/orden/<id>/cierre/`) por solapas: Resultado · **Material** (partes de su stock,
  sin número de serie; equipos retirados opcional) · **Nota** (qué se hizo + foto) · **Viaje y trabajo**
  (tiempo de viaje, de trabajo y de retorno) · **Gastos** (qué se compró, monto y foto de la factura;
  genera el egreso "gastos de campo" y queda para revisión/reintegro) · **Conformidad** (nombre,
  apellido, DNI opcional y firma).
- Modelos nuevos: `NotaOrden`, `GastoOrden`; campos `Cliente.email`, `OrdenTrabajo.minutos_viaje`,
  `minutos_retorno`, `conforme_apellido`; `PedidoMaterial.orden`. En la carga de datos, notas y
  gastos dentro de la orden y revisión de gastos.
- Compatibilidad: un cierre enviado a la dirección anterior (p. ej. guardado sin señal) se procesa igual.
- Tests: **75**, todos pasan.

---

## 2026-10-07 — Contabilidad e indicadores editables

Pedidos: "en finanzas veo la información pero no cómo cargar ni quién la maneja" y
"metas y semáforos no permite editar/eliminar las métricas en sí".

### Hecho
- **Rol Contabilidad** (usuario demo `contable`): entra directo a su área y no ve personal ni evaluaciones.
- **Área Finanzas** (`/finanzas/`, gerencia y contabilidad): panel con **presupuesto vs. gastado con
  semáforo** (verde ≤ presupuesto, amarillo hasta + tolerancia por categoría, rojo excedido) y proyección;
  **egresos** con filtros, carga/edición/eliminación de los manuales (proveedor, N° de factura, archivo),
  y exportación a Excel; **reintegros** de gastos de campo (aprobar/rechazar con aviso al técnico;
  rechazado = se quita el egreso); **presupuestos** mensuales por categoría (copiar el mes anterior);
  **costos fijos y categorías**.
- **Indicadores editables** (`/tablero/metas/`, gerencia): editar nombre, descripción, unidad, sentido,
  meta, límite y peso; **desactivar/reactivar** (los del sistema) y **eliminar** (los manuales); **crear
  indicadores de carga manual** (técnico, supervisor o tablero de mando) con **carga mensual de valores**
  (el supervisor puede cargar los de su equipo). Entran al semáforo, a los índices IPT/IGS y al Resumen.
  Todo cambio queda en el registro.
- Datos demo: presupuestos, egresos manuales con comprobante, indicadores "Reclamos de clientes"
  (por técnico) y "Satisfacción de clientes" (empresa).
- Tests: **82**, todos pasan.

---

## 2026-10-07 — Contabilidad simplificada: sueldos, horas extra, materiales y comprobantes

Pedido: "mejora todo lo contable, simplifica, sueldo por empleado, horas extras, materiales,
carga de facturas, recibos, etc."

### Hecho
- **Menú Finanzas reordenado**: Resumen · Comprobantes y pagos · Sueldos y horas extra · Materiales ·
  Reintegros · Presupuesto · Configuración.
- **Resumen en 4 bloques** (sueldos, horas extra, materiales, otros) con "Para hacer" y gráfico apilado
  de 6 meses.
- **Comprobantes**: modelo `Proveedor` (CUIT, contacto, categoría habitual; migración que convierte los
  proveedores escritos a mano); `Egreso` con tipo (factura/ticket/recibo/nota de crédito), vencimiento,
  pagado, fecha y medio de pago. Cuentas a pagar con semáforo de vencimiento. Números en formato
  argentino (`125.000,50`).
- **Sueldos** (`finanzas/sueldos.py`, modelo `Liquidacion`): `Persona.sueldo_basico` y
  `categoria_laboral`; parámetros de liquidación en `Parametros`. Horas extra desde las fichadas
  (domingo/feriado al 100 %), presentismo, descuento de faltas injustificadas y días de suspensión
  (`AccionCorrectiva.dias_suspension`), cargas sociales. **Multas sólo informativas (art. 131 LCT)**.
  Flujo borrador → aprobada (genera el egreso "Sueldos y cargas" a fin de mes) → pagada + recibo firmado.
  Excel de novedades para el estudio contable. La proyección usa el costo del último mes liquidado
  (se quitó el costo fijo "Sueldos" de la demo).
- **Materiales**: compras vs. consumo valorizado, costo por técnico / tipo de trabajo / material,
  stock inmovilizado.
- Demo: básicos por persona, liquidaciones (pagadas, la del mes anterior aprobada, la actual en
  borrador), proveedores con CUIT, facturas pendientes con vencimiento, suspensiones con días.
- Tests: **86**, todos pasan.

---

## 2026-10-07 — Campos numéricos: montos con "$" y partes sólo enteras

Pedido: "hay tablas que permiten poner letras donde sólo van números; en partes sólo van enteros;
los precios deben llevar símbolo pesos".

### Hecho
- `core/numeros.py`: `a_decimal` (acepta `125.000,50`, `125000.50`, `$ 10.000`), `a_entero`,
  `CampoPesos` y `CampoCantidad` (sólo enteros ≥ 0). Se usan en el cierre de llamadas (material y
  gastos), pedido de partes, siniestro desde la app, comprobantes, depósito (entregas, devoluciones,
  regularizaciones) y sueldos/presupuesto/configuración.
- Carga de datos (admin): toda cantidad de partes es entera y todo costo/monto se carga como pesos,
  sin tocar cada pantalla (`instalar_en_admin`, regla por nombre de campo).
- `static/js/numeros.js`: `data-moneda` muestra "$" fijo, separa miles y no deja tipear letras;
  `data-numero` sólo números; `data-entero` sólo enteros. Si algo inválido llega al envío, avisa en el
  campo. Las cantidades que la app propone (receta del trabajo, faltantes) se redondean hacia arriba.
- Mensajes con importes en formato argentino ($ 125.000). Caché de la app v4 para que los celulares
  tomen los cambios.
- Tests: **89**, todos pasan.

## 2026-10-08 — Repositorio en GitHub para compartir

### Pedido
"Subir el repo con instrucciones de uso a GitHub para que lo baje un compañero".

### Hecho
- Repositorio **privado** https://github.com/WinCode143/virguel (rama `master`). El `.env`, `media/`
  y `capturas/` no se suben (están en `.gitignore`).
- README: nueva sección "Bajarlo y correrlo en otra PC" con pasos para Linux/Mac y Windows usando
  `venv` + `pip` (sin depender de `uv`), cómo actualizar con `git pull` y problemas comunes.
- Para que el compañero pueda bajarlo hay que invitarlo como colaborador (repo privado).
