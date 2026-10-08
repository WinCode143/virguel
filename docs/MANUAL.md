# Manual de uso por rol

Al iniciar sesión, cada persona entra automáticamente a su versión del sistema.

---

## Técnico — app en el celular (`/app/`)

**Instalarla:** abrir la dirección del sistema en el navegador del celular, iniciar
sesión y elegir *"Agregar a pantalla de inicio"* / *"Instalar app"*.

Día típico:
1. **Fichar entrada**: el botón registra la hora y la ubicación del celular. Si usa
   vehículo, se elige y se cargan los km. Si llega después del horario + 10 minutos,
   queda como llegada tarde.
2. **Mis órdenes pendientes** → **Cerrar** cada una: resultado (completada / no se
   pudo / reprogramar), minutos, si el cliente pidió decodificador y cuántos se
   instalaron, y los materiales usados (se descuentan del stock automáticamente).
3. **Incidente**: ante cualquier daño (rotura en una casa, caño pinchado, choque,
   lesión) reportarlo en el momento.
4. **Fichar salida**: hora y ubicación (y km si usó vehículo). Se calculan las horas y las horas extra.
6. **¿No vas a ir?** En **Asistencia → Avisar ausencia / pedir licencia**: tipo (enfermedad,
   ART, licencia, vacaciones, franco), fechas y foto del certificado. El supervisor lo aprueba.
5. **Encuesta del día**: 4 preguntas con estrellas sobre el trato del supervisor.
   Es confidencial: el supervisor sólo ve promedios.

**Sin señal:** la app sigue funcionando. Lo que se cargue queda guardado en el celular
y se envía solo cuando vuelve la conexión (aparece un aviso con los envíos pendientes).
No cerrar sesión mientras haya envíos pendientes.

Otras secciones: **Mi EPP** (confirmar recepción, ver vencimientos) y **Mi desempeño**.

### Novedades para el técnico (versión 3)
- **Abrir una orden** muestra la ficha completa: cliente, botón **Llamar**, **Cómo llegar** (Google Maps)
  y las visitas anteriores a ese cliente.
- **▶ Empezar trabajo** al llegar: el tiempo se mide solo.
- **Cerrar la orden**: resultado y, si no se pudo, el **motivo**; materiales usados (vienen precargados
  y se descuentan de **sus partes**); números de serie instalados y retirados; foto del trabajo;
  nombre, DNI y **firma del cliente con el dedo**; la ubicación se toma sola.
- **Mis partes**: lo que tiene a su cargo, lo que le falta para sus órdenes, partes sin usar hace mucho,
  y **Pedir partes** (o "Pedir lo que me falta", que arma el pedido solo). Ve el estado de cada pedido.
- **Yo**: mi rendimiento (meta de hoy, últimos 30 días contra el equipo, motivos de órdenes no
  resueltas, evolución semanal), **evaluar a mi supervisor** (una vez por semana, confidencial),
  historial de órdenes, mi legajo (controles y sanciones recibidas), mi EPP y notificaciones.
- **🔔 Notificaciones**: órdenes nuevas, pedidos aprobados o listos, controles y sanciones registradas,
  recordatorio de la evaluación semanal. Se pueden activar para que lleguen al celular.

## Supervisor — app en el celular + tablero en la PC

En el celular (`/app/`):
- **Fichar entrada y salida** igual que los técnicos.
- **Asistencia del equipo hoy**: quién no fichó y no avisó, quién llegó tarde.
- **Ausencias**: aprobar o rechazar los avisos de su equipo (con el certificado a la vista).
- **Pedidos de partes** de su equipo: aprobar o rechazar (luego el depósito entrega).
- **Nuevo control**: elegir técnico (y orden), tipo de control, puntaje 1–5, si hubo
  desvío, descripción y **foto**. La ubicación se toma sola. Descripción + foto +
  ubicación + orden = mejor calidad de documentación.
- Si marcó un desvío, el sistema lleva directo a **Acción correctiva**:
  recapacitación, charla, apercibimiento, multa o suspensión.
- **Mis objetivos de hoy**: cargar el resultado de lo que pidió gerencia.
- **Desvíos sin acción**: lista de lo pendiente de resolver.
- **Mis indicadores**: su puntaje general, nota de su equipo, informes por día, etc.

En la PC (`/tablero/`): los mismos tableros que gerencia pero **sólo con su equipo**
(sin finanzas ni la evaluación de otros supervisores).

## Gerencia y administración — escritorio (`/tablero/`)

| Pantalla | Para qué |
|---|---|
| **Panel general** | Productividad de toda la empresa: promedios, tendencia, dónde está el problema, por equipo y por zona, con gráficos. Botón **Exportar a Excel** (con hoja de gráficos). |
| **Índice de técnicos (IPT)** | Ranking de productividad con cada indicador contra su meta. Clic → ficha con evolución. |
| **Índice de supervisores (IGS)** | Comparativo de supervisores con fortalezas y aspectos a mejorar. |
| **Asistencia de hoy** | Presentes, tarde, ausentes con aviso y sin aviso, por persona y por equipo. |
| **Presentismo y ausencias** | Por período: presentismo, faltas justificadas/injustificadas, tardanzas, horas extra. Descarga CSV para liquidación de sueldos. |
| **Legajos** | Ficha completa de cada persona. |
| **Parte diario (mail)** | Vista previa del mail de cada noche y envío manual. |
| **Documentación** | Documentos obligatorios faltantes o vencidos. |
| **Dotación y rotación** | Altas, bajas, motivos de egreso, antigüedad. |
| **Resumen** | Foto del día: técnicos en calle, capacidad, stock parado, probabilidad de decodificador, técnicos en riesgo, siniestros, egresos, alertas. |
| **Alertas** | Todo lo que requiere atención, generado cada noche. Se cierran solas cuando se corrige la causa. |
| **1 · Asignar órdenes** | Propuesta automática de reparto de órdenes pendientes según la capacidad real de cada técnico; se revisa y confirma. |
| **1 · Operación diaria** | Órdenes por día y resultado, personal en calle, hectáreas, productividad por técnico y por tipo de tarea. |
| **5 · Técnicos y riesgo** | Diagnóstico de cada técnico (capacitar / riesgo alto / observación / adecuado), puntajes y motivos. Clic en un nombre → ficha con su curva de 6 meses, sanciones, siniestros, capacitaciones y EPP. |
| **5 · Capacitación** | A quién capacitar y si las capacitaciones dadas mejoraron la productividad. |
| **2 · Supervisores** | Puntaje por eje, encuesta, informes, desvíos resueltos, objetivos y comentarios anónimos. |
| **3 · Incidentes y daños** | Siniestros por mes y gravedad, costos, abiertos con la acción recomendada, reincidentes. |
| **4 · Herramientas y EPP** | Quién no tiene su EPP completo o vigente, vencimientos, pañol. |
| **6 · Flota** | Próximo service de cada vehículo (por km y fecha), VTV, seguro y costos. |
| **8 · Stock y demanda** | Stock vs. técnicos en calle (días de cobertura), antigüedad de lotes, compras necesarias según demanda comercial. |
| **7 · Finanzas** | Egresos reales por categoría y proyección a 3 meses. |
| **9 · Planificación** | Simulador: técnicos, hectáreas, zona, % de decodificadores → clientes atendibles, déficit de técnicos por día, decodificadores y materiales necesarios. |
| **2 · Encuestas del día** | Enviar el link de la encuesta a cada técnico por WhatsApp con un clic. |
| **8 · Pedidos de partes** | El depósito entrega lo pedido por los técnicos (ajustando cantidades). |
| **8 · Partes en manos de técnicos** | Qué tiene cada técnico, partes paradas, entregas y devoluciones manuales. |
| **Power BI / exportar** | Instrucciones y descargas CSV. |
| **Importar Excel / CSV** | Carga inicial masiva con plantillas descargables. |
| **Carga de datos (admin)** | Alta y edición de todo: personas, vehículos, materiales, ingresos de stock, demanda comercial, capacitaciones, objetivos de supervisores, parámetros. |

### Cargas que hace administración
- **Horario de cada persona** (en su ficha) y **feriados** del año.
- **Novedades** que no avisa el empleado (ausencia injustificada, suspensión) y aprobación de licencias.
- **Documentos del legajo** con su vencimiento, y los tipos de documento obligatorios.
- **Mails del parte diario** en Parámetros del sistema; el mail de cada supervisor en su ficha.
- **Personas** (con su usuario) y supervisor asignado a cada técnico.
- **Ingresos de stock** (cada ingreso es un lote: fecha, cantidad, costo, remito).
- **Demanda comercial prevista** (clientes por día y tipo de tarea).
- **Materiales por tipo de tarea** (cuánto consume cada tarea: base de la previsión).
- **Órdenes de trabajo** asignadas a cada técnico.
- **Objetivos diarios** de los supervisores.
- **Entregas de EPP**, **services** de vehículos, **capacitaciones**, **costos fijos**.
- **Parámetros del sistema**: 60 días de stock, 5–6 ha, técnicos por cuadrilla,
  clientes por técnico, 50 %/60 % de decodificadores, ventana de evaluación.


## Ingreso y claves
- Se entra con **usuario, legajo o DNI**. Tras 5 intentos fallidos el acceso se bloquea 15 minutos.
- La primera vez (o después de un blanqueo) el sistema pide elegir una clave propia.
- ¿Te olvidaste la clave? Con mail cargado: "¿Olvidaste tu clave?" en el ingreso. Si no, tu supervisor
  o gerencia la blanquean (te pasan una clave temporal por WhatsApp).
- Gerencia gestiona todos los accesos en **Administración → Usuarios y accesos**; el **Registro de
  accesos** muestra ingresos, intentos fallidos y bloqueos.

## Partes adeudadas
- Al cerrar una orden con equipos retirados (series), quedan **a cargo del técnico** hasta que el
  depósito los recibe.
- Cada mañana el técnico recibe un aviso con lo que debe y hace cuántos días; el supervisor, el
  resumen de su equipo. El depósito regulariza en **Inventario → Partes adeudadas**.

## Metas y semáforos
- 🟢 cumple la meta · 🟡 no la cumple pero está dentro del límite · 🔴 más allá del límite.
- **Productividad → Metas y semáforos**: gerencia fija metas generales, por equipo, pesos y umbrales;
  cada supervisor puede fijar las de su equipo. Todo cambio queda registrado.


## Contabilidad (rol Contabilidad y gerencia) — menú Finanzas
- **Resumen**: el gasto del mes en 4 bloques — **sueldos y cargas**, **horas extra**, **materiales**
  y **otros gastos** — más "Para hacer" (facturas vencidas o por vencer, sueldos sin aprobar,
  reintegros por revisar, comprobantes sin archivo), gráfico de 6 meses, presupuesto con semáforo y
  proyección.
- **Comprobantes y pagos**: facturas, tickets, recibos y notas de crédito. "Cargar comprobante": subir
  foto o PDF, tipo, número, fecha, proveedor (si es nuevo se crea con su CUIT y la próxima vez se
  propone su categoría), total (se puede escribir `125.000,50`), vencimiento y pago. La vista
  **A pagar** lista lo pendiente ordenado por vencimiento (rojo vencido, amarillo por vencer) y se
  marca "Pagado" con el medio de pago. Excel con todo para el contador.
- **Sueldos y horas extra**: "Generar liquidaciones del mes" arma una por empleado con su básico,
  horas extra (de las fichadas: lunes a sábado al 50 %, domingos y feriados al 100 %), presentismo,
  descuento por faltas sin justificar y días de suspensión, y el costo con cargas sociales. Se pueden
  agregar otros adicionales/descuentos mientras está en borrador; luego **Aprobar** (pasa a gasto),
  **Pagada** y subir el **recibo firmado**. "Novedades para el estudio" baja el Excel. "Sueldos
  básicos" para cargar o cambiar el básico de cada persona. Las **multas se muestran pero no se
  descuentan** (art. 131 de la Ley de Contrato de Trabajo). Es una pre-liquidación: el recibo legal
  (aguinaldo, retenciones, F.931) lo sigue haciendo el estudio contable. Los supervisores no ven sueldos.
- **Materiales**: comprado vs. usado en órdenes (valorizado a costo), costo por técnico y por tipo de
  trabajo, lo más usado, valor del stock en depósito y en técnicos, partes paradas.
- **Reintegros a técnicos**: aprobar o rechazar los gastos que cargan los técnicos al cerrar llamadas.
- **Presupuesto**: monto previsto por categoría para este mes y los dos siguientes.
- **Configuración**: parámetros de sueldos (horas mensuales, recargos, presentismo, cargas sociales),
  proveedores (CUIT, contacto, categoría habitual), costos fijos y categorías con su tolerancia.

## Crear o modificar indicadores (gerencia) — Productividad → Metas y semáforos
- "Editar" en cada indicador: nombre, descripción, meta, límite, peso; desmarcar "Activo" lo saca de uso.
- "Nuevo indicador": para medir algo que el sistema no registra; se carga su valor cada mes en
  "cargar valores" (el supervisor carga los de su equipo).
