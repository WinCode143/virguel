# Manual de uso por rol

Al iniciar sesión, cada persona entra automáticamente a su versión del sistema.

---

## Técnico — app en el celular (`/app/`)

**Instalarla:** abrir la dirección del sistema en el navegador del celular, iniciar
sesión y elegir *"Agregar a pantalla de inicio"* / *"Instalar app"*.

Día típico:
1. **Iniciar jornada**: elegir vehículo (si usa) y kilómetros al salir. Esto informa
   que está en calle (base del cálculo de stock diario y capacidad).
2. **Mis órdenes pendientes** → **Cerrar** cada una: resultado (completada / no se
   pudo / reprogramar), minutos, si el cliente pidió decodificador y cuántos se
   instalaron, y los materiales usados (se descuentan del stock automáticamente).
3. **Incidente**: ante cualquier daño (rotura en una casa, caño pinchado, choque,
   lesión) reportarlo en el momento.
4. **Terminar el día**: km al volver y hectáreas recorridas.
5. **Encuesta del día**: 4 preguntas con estrellas sobre el trato del supervisor.
   Es confidencial: el supervisor sólo ve promedios.

**Sin señal:** la app sigue funcionando. Lo que se cargue queda guardado en el celular
y se envía solo cuando vuelve la conexión (aparece un aviso con los envíos pendientes).
No cerrar sesión mientras haya envíos pendientes.

Otras secciones: **Mi EPP** (confirmar recepción, ver vencimientos) y **Mi desempeño**.

## Supervisor — app en el celular + tablero en la PC

En el celular (`/app/`):
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
| **Resumen** | Foto del día: técnicos en calle, capacidad, stock parado, probabilidad de decodificador, técnicos en riesgo, siniestros, egresos, alertas. |
| **Alertas** | Todo lo que requiere atención, generado cada noche. Se cierran solas cuando se corrige la causa. |
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
| **Power BI / exportar** | Instrucciones y descargas CSV. |
| **Importar Excel / CSV** | Carga inicial masiva con plantillas descargables. |
| **Carga de datos (admin)** | Alta y edición de todo: personas, vehículos, materiales, ingresos de stock, demanda comercial, capacitaciones, objetivos de supervisores, parámetros. |

### Cargas que hace administración
- **Personas** (con su usuario) y supervisor asignado a cada técnico.
- **Ingresos de stock** (cada ingreso es un lote: fecha, cantidad, costo, remito).
- **Demanda comercial prevista** (clientes por día y tipo de tarea).
- **Materiales por tipo de tarea** (cuánto consume cada tarea: base de la previsión).
- **Órdenes de trabajo** asignadas a cada técnico.
- **Objetivos diarios** de los supervisores.
- **Entregas de EPP**, **services** de vehículos, **capacitaciones**, **costos fijos**.
- **Parámetros del sistema**: 60 días de stock, 5–6 ha, técnicos por cuadrilla,
  clientes por técnico, 50 %/60 % de decodificadores, ventana de evaluación.
