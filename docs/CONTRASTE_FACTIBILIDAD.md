# Contraste con el modelo de referencia (13/10/2026) — factibilidad y estado

Respuesta al documento *Virguel — Modelo de referencia y contraste* (criterios B01–B40, paquetes
M01–M08, verificaciones V01–V12). Para cada criterio: qué se hizo, cómo se comprueba y qué queda
pendiente. Las pruebas automáticas están en `tests/test_contraste.py` (más el resto de la suite:
204 pruebas, todas en verde) y el recorrido en navegador en `scripts/recorrido_navegador.js`.

> **Corrección (15/10/2026).** La revisión externa del 15/10 reprodujo 15 contradicciones (U01–U15,
> agrupadas en H01–H11) que esta versión del documento daba por resueltas: la tabla de abajo
> **declaraba más de lo comprobado**. Las 11 causas se corrigieron y cada escenario quedó como prueba
> automática en `tests/test_revision_1015.py` (U01–U15 con el resultado esperado y los controles
> K01–K02); ver la sección *Revisión del 15/10* al final. Una verificación V marcada «cumple» significa
> que sus casos conocidos tienen prueba, no que no pueda haber otros: los escenarios nuevos se agregan
> a las pruebas a medida que aparecen.

**Resumen de factibilidad.** Todo el documento es implementable sobre la base actual (Django +
PostgreSQL + PWA) sin cambiar de arquitectura. Los 13 criterios P0 (contradicciones) están
corregidos con prueba. De los P1, la gran mayoría está implementada; lo que queda abierto no depende
de programar sino de **reglas de la empresa** (sección 5.3 del documento): esos puntos funcionan
hoy con **valores de prueba explícitos**, marcados como provisorios, que la empresa tiene que
reemplazar. B40 (IA) es una extensión P2: se hizo el primer paso sin IA (preparación de visita) y
se dejó la estructura para agregarla después.

Estados: **Hecho** = implementado y con prueba · **Hecho con valores de prueba** = funciona, pero
con una regla o dato que la empresa debe confirmar · **Parcial** = lo esencial está; falta una parte
que se indica · **Propuesta** = diseñado, no construido.

## M01 — Integridad, autoridad y dinero (P0)

| Criterio | Estado | Qué se hizo | Prueba |
|---|---|---|---|
| B13 Saldo inicial y recepción sin compra | Hecho | Lotes con origen *apertura* o *custodia* (no cuentan como compra ni como egreso). La importación de stock pide el origen. | `AperturaStockTests` |
| B14 Conservación del pañol y custodia | Hecho | Libro de movimientos del pañol (`MovimientoPanol`): entregas, devoluciones, bajas y compras dejan rastro; el saldo se reconstruye. | `PanolTests` |
| B25 Supervisor sin evidencia | Hecho | Sin jornadas, informes, encuestas ni objetivos el puntaje queda «sin evidencia suficiente», no 10/100. | `SupervisorSinEvidenciaTests` |
| B27 Incidente, vínculo y atribución | Hecho | Estar vinculado no es causar: la atribución tiene estado (pendiente/confirmada/descartada), fundamento, autor y fecha; sólo la confirmada afecta la evaluación. | `IncidenteAtribucionTests` |
| B29 Mantenimiento con base y plan aplicable | Hecho | Planes por vehículo; sin fecha/km base el service figura «sin base», nunca «al día». | `MantenimientoTests` |
| B31 Estimación, liquidación y cobro | Hecho con valores de prueba | Estimación versionada; la liquidación confirmada de Claro reemplaza a la estimada; recalcular nunca reescribe lo confirmado ni lo cobrado (V07: 100 → 80 → cobro 80 = saldo 0). Tarifas y % de retención son de prueba. | `LiquidacionConfirmadaTests` |
| B32 Obligación distinta del pago | Hecho | Un egreso nace *pendiente*; sólo un `Pago` con cuenta y fecha lo cancela (V07: 100 → paga 30 → saldo 70). | `LiquidacionConfirmadaTests` |
| B33 Costo de consumo distinto de caja futura | Hecho | La caja proyectada usa compras netas (lo que falta comprar) y no vuelve a contar el stock ya pagado (V08). | `CajaVsCostoTests` |
| B36 Operaciones repetidas y fallas intermedias | Hecho | Cada envío offline es idempotente por UUID + huella del contenido, en una sola transacción; el mismo UUID con otro contenido → conflicto 409; una falla intermedia no deja nada a medias. | `OfflineAtomicoTests` |
| B37 Datos offline, sesión y conflicto | Hecho | El service worker borra las pantallas guardadas al cambiar de cuenta; los pendientes de otro usuario no se envían; vencen a los 7 días. | recorrido navegador §3–4 (V10) |
| B38 Permisos por función y ámbito | Hecho | `is_staff` ya no da gerencia: el rol sale del grupo o de la ficha de la persona; sin rol no hay acceso. | `PermisosTests` |
| B02 Orden, visita e historia corregible | Hecho | La visita se crea con un servicio explícito y no se reescribe: las correcciones son *rectificaciones* con motivo y autor (V01). | `HistoriaRectificableTests` |
| B22 Acción indicada, ejecutada y verificada | Hecho | Una acción indicada y no cumplida no cuenta como desvío corregido. | `AccionPendienteTests` |

## M02 — Orden, visita y equipo

| Criterio | Estado | Qué se hizo / qué falta |
|---|---|---|
| B01 Ingreso de órdenes e importaciones | Hecho | Huella del archivo (avisa si se repite), resultado por fila, órdenes cerradas protegidas, reapertura sólo explícita y auditada; la demanda se actualiza en lugar de duplicarse (`ImportacionTrazableTests`). |
| B03 Cuadrillas y participación histórica | Hecho | Cuadrillas, miembros y participación por visita (ejecutor/ayudante) guardada en el momento (`CuadrillasTests`). |
| B06 Cierre y estados separados | Hecho | Resultado de la visita, revisión técnica y aceptación de Claro son estados distintos; una visita rechazada no se estima como cobrable. |
| B07 Evidencia y consumo por visita | Hecho | Series, foto, firma, conformidad, GPS, consumos y gastos quedan en la visita, no sólo en la orden (`EvidenciaPorVisitaTests`). |

## M03 — Recursos: equipos, materiales y EPP

| Criterio | Estado | Qué se hizo / qué falta |
|---|---|---|
| B08 Equipos por serie, propiedad y condición | Hecho | `UnidadEquipo` + libro de movimientos: depósito → técnico → cliente → retiro → revisión; conserva propietario e historia. |
| B09 Reservas de materiales | Hecho | Reservas por orden; la entrega consume la reserva; la previsión descuenta lo reservado. |
| B10 Recetas condicionadas | Hecho con valores de prueba | Receta «siempre / por equipo / si hay recambio»; lo desconocido se estima con probabilidades configurables (de prueba). La misma regla rige la previsión, el faltante del técnico y la preparación de visita. |
| B11 Pedido neto y horizonte | Hecho con valores de prueba | Necesidad inmediata vs. backlog, stock + custodia + en camino − reservado; el horizonte «inmediato» (días) es un parámetro (`AbastecimientoTests`). |
| B12 Antigüedad con relojes distintos | Hecho con valores de prueba | Antigüedad original y permanencia en la ubicación; qué reloj activa los 60 días es un parámetro a confirmar (`RelojesAntiguedadTests`). |
| B15 Rotura temprana y recambio | Hecho | Reporte de condición desde la app, reposición por el libro del pañol (`RoturaYEppTests`). |
| B16 EPP según tarea | Hecho con valores de prueba | Requisitos de EPP por tipo de tarea; la agenda no asigna a quien le falta EPP vigente y dice por qué. La demo trae requisitos **inventados** (arnés y casco), visibles en *Capacitación → Requisitos* con cuántos del equipo cumplen. |

## M04 — Competencias, calidad y supervisión

| Criterio | Estado | Qué se hizo / qué falta |
|---|---|---|
| B17 Competencias que afectan la asignación | Hecho con valores de prueba | Requisitos de competencia por tipo de tarea (nivel mínimo, admite tutela); la agenda no propone a quien no está habilitado y dice por qué. La demo trae requisitos **inventados**. |
| B18 Formación y evaluación separadas | Hecho | Asistir no aprueba: la aprobación tiene evaluador, fecha y evidencia; las competencias vencen (`FormacionTests`). |
| B19 Plan de mejora y período de prueba | Hecho | Plan individual con objetivos, apoyos, plazos y resultado. |
| B20 Inspecciones y defectos observables | Hecho | **Nuevo:** plantillas de control versionadas (punto, criterio, defecto tipificado, crítico). Un punto crítico que no cumple es desvío. La «calidad del informe» se renombró a *completitud documental* (`PlantillaInspeccionTests`). Pantalla propia *Plantillas de control* (puntos, versiones, defectos más encontrados). La demo trae una plantilla y resultados **inventados**. |
| B21 Cobertura y selección | Hecho | **Nuevo:** motivo de cada control (programado / aleatorio / sospecha / reclamo); los de sospecha o reclamo no entran en la calidad general; el supervisor ve quién de su equipo trabajó y no tuvo control en la semana (`MotivoSeleccionTests`). |
| B23 Objetivos del supervisor verificados | Hecho | **Nuevo:** criterio de aceptación, evidencia, estados sin reporte / reportado / verificado / rechazado; sólo lo verificado por un tercero cuenta; lo vencido sin reporte cuenta 0; la meta se versiona; nadie verifica lo propio (`ObjetivosVerificadosTests`). Pantalla propia *Objetivos a verificar* para gerencia (verificar/rechazar con nota y asignar objetivos). |
| B24 Encuesta, suficiencia y confidencialidad | Hecho con valores de prueba | Mínimos de respuestas y de personas para mostrar resultados (parámetros de prueba). |
| B26 Resultados comparables | Hecho (calibración con datos reales pendiente) | Diccionario y fuente única (ver B35); el índice se presenta como resumen para ordenar la revisión, no como aptitud. **Nuevo:** *Calibrar pesos* simula otros pesos sin guardarlos, muestra cuánto cambia el orden (Spearman) y qué indicadores tienen pocos datos o no distinguen (`CalibracionPesosTests`). Acordar los pesos definitivos requiere meses de datos reales. |
| B28 Gestión de incidentes y costos | Hecho | **Nuevo:** cronología del expediente (denuncia, aseguradora, descargo, peritaje, pagos, recupero) con responsable y plazo; alerta cuando un plazo vence (`ActuacionesIncidenteTests`). Ficha propia de cada incidente con su expediente, alta de actuaciones y «plazo cumplido»; el listado muestra el próximo plazo. La demo trae actuaciones **inventadas**. |

## M05 — Flota y agenda

| Criterio | Estado | Qué se hizo / qué falta |
|---|---|---|
| B04 Programación ejecutable | Hecho con valores de prueba | La agenda se arma por minutos (estándar + traslado promedio), no por cupo de órdenes, y explica cada bloqueo (`AgendaEjecutableTests`). |
| B05 Disponibilidad integrada | Hecho | Licencias y novedades aprobadas, vehículo en taller, competencia y EPP pueden impedir la asignación; una novedad pendiente deja al técnico «pendiente», no disponible automáticamente. |
| B30 Kilometraje e indisponibilidad | Hecho | Lecturas de odómetro únicas por vehículo/fecha (no por participante); km/día desde las lecturas (`OdometroTests`). |

## M06 — Administración coherente

| Criterio | Estado | Qué se hizo / qué falta |
|---|---|---|
| B34 Deudas, cuotas, urgencia y caja | Hecho con valores de prueba | Prioridad y motivo en cada obligación; la caja muestra lo a pagar por prioridad; transferencias entre cuentas propias no alteran la caja total (`TransferenciasTests`); comparador de alternativas de pago con tasa de descuento de prueba. |

## M07 — Datos, reglas e interfaces

| Criterio | Estado | Qué se hizo / qué falta |
|---|---|---|
| B35 Diccionario de indicadores y versiones | Hecho | **Nuevo:** pantalla *Productividad → Diccionario de indicadores*: población, numerador, denominador, ventana, fuente, qué pasa si falta el dato; cada cambio de meta/límite/peso sube la versión y queda en el historial. Prueba de que app y escritorio dan los mismos valores (V12) (`DiccionarioIndicadoresTests`). Los textos iniciales se generaron de las descripciones y conviene que la empresa los revise. |
| B39 Reglas y procedencia | Hecho con valores de prueba | Tarifas de Claro con vigencia y marca «provisoria» (una tarifa nueva no revaloriza lo confirmado); importaciones con huella; parámetros de prueba marcados. |

## M08 — Asistencia (P2)

| Criterio | Estado | Qué se hizo / qué falta |
|---|---|---|
| B40 Asistencia con IA incorporable | Parcial (primer paso sin IA) | **Nuevo:** tarjeta *Preparar la visita* en cada orden abierta: antecedentes del cliente (visitas, motivos, notas, incidentes), retrabajo de qué orden, qué llevar (receta con su condición, stock del técnico, reservas) y cada aviso dice su fuente. No decide ni modifica nada; funciona sin conexión a ningún servicio de IA (`PreparacionVisitaTests`). **Propuesta** para una segunda etapa: dictado del cierre como *borrador* que el técnico revisa (resultado, series, consumos) antes de confirmar, y consulta del procedimiento vigente. Requiere decidir proveedor, costo y tratamiento de datos personales, y cargar los procedimientos de la empresa. |

## Verificaciones V01–V12

| | Estado | Dónde |
|---|---|---|
| V01 Orden, varias visitas, participantes | Cumple (tras H01/H06) | `HistoriaRectificableTests`, `CuadrillasTests`, `VisitasTests` (U08, U09) |
| V02 Cierre concurrente y reintento | Cumple (tras H07) | `OfflineAtomicoTests`, `OfflineTests` (U10, U11, K02), `EnvioConcurrenteTests` (dos envíos simultáneos en PostgreSQL) |
| V03 Inventario y custodia | Cumple (tras H02/H03/H10) | `PanolTests`, `AperturaStockTests`, `ReservasTests` (U01–U03), `EquiposYFechasTests` (U04, U05) |
| V04 Trabajo preparado | Cumple (tras H04/H09/H11) | `AgendaEjecutableTests`, `AgendaMaterialTests` (U12), U06, U15 |
| V05 Calidad verificable | Cumple (tras H01) | `PlantillaInspeccionTests`, `AccionPendienteTests`, `ObjetivosVerificadosTests`, U09 |
| V06 Evaluación con evidencia | Cumple | `SupervisorSinEvidenciaTests`, `IncidenteAtribucionTests` |
| V07 Dinero confirmado | Cumple (tras H05) | `LiquidacionConfirmadaTests`, `LiquidacionCeroTests` (U07, K01) |
| V08 Caja y abastecimiento | Cumple | `CajaVsCostoTests`, `TransferenciasTests` |
| V09 Flota con base | Cumple | `MantenimientoTests`, `OdometroTests` |
| V10 Permisos y copia offline | Cumple | `PermisosTests`, recorrido navegador §4 |
| V11 Importación y vigencias | Cumple | `ImportacionTrazableTests`, `LiquidacionConfirmadaTests` |
| V12 Coherencia de pantallas | Cumple | `DiccionarioIndicadoresTests` |

## Revisión del 15/10: hallazgos y corrección

| Hallazgo | Escenarios | Corrección | Prueba |
|---|---|---|---|
| H01 Un informe antiguo rechazaba una visita nueva | U09 | El informe queda fijado a **su visita** al crearse (`InformeControl.visita`); la revisión técnica se aplica sólo a esa visita y sólo cuando cambia (operación explícita `aplicar_revision`). Los informes anteriores se vincularon si la visita era inequívoca; si no, quedan marcados `visita_ambigua`. | `VisitasTests` |
| H02 Las reservas no protegían la entrega | U01, U02, U03 | `inventario/reservas.py` centraliza reservar, entregar, liberar y reasignar. Ninguna salida toma unidades comprometidas para otra orden (`ReservadoParaOtra`) sin una reasignación explícita; la entrega descuenta la reserva en forma **parcial** (`cantidad_entregada`); un cierre ausente/reprogramado no toca la reserva y uno completado libera lo no entregado, sin consumo ficticio. | `ReservasTests` |
| H03 Equipos por serie y stock agregado desconectados | U04, U05 | La condición de la unidad gobierna los lotes: una unidad que cuenta en el stock del depósito y pasa a defectuosa sale de los lotes (baja); una recuperada que se revisa en condiciones entra. Una serie instalada en otro cliente (o defectuosa/dada de baja) **no se instala**: el cierre se rechaza hasta registrar el retiro. | `EquiposYFechasTests` |
| H04 Una llegada posterior cubría una visita anterior | U06 | La necesidad inmediata se reconcilia fecha por fecha: sólo cuenta lo que está o llega ese día o antes; lo que llega después se muestra como «llega tarde». | `EquiposYFechasTests` |
| H05 Una estimación que bajaba a cero conservaba el saldo | U07 (K01) | Se guarda también la versión cero y el ingreso estimado sin cobros queda en 0; lo confirmado o cobrado se conserva. | `LiquidacionCeroTests` |
| H06 Rectificar el ejecutor no rectificaba las participaciones | U08 | La rectificación reconcilia las participaciones en la misma operación (el ejecutor vigente es uno solo; el anterior queda en el historial). Los compañeros inferidos por cuadrilla quedan **sin confirmar**. | `VisitasTests` |
| H07 Atomicidad del envío directo y huella de archivos | U10, U11 (K02) | El envío inicial (sin cabecera) tiene el mismo contrato que el reintento: si no se acepta, no queda nada. La huella incluye los **bytes** de cada archivo. Dos envíos simultáneos del mismo UUID tienen un único efecto (probado en PostgreSQL con hilos). | `OfflineTests`, `EnvioConcurrenteTests` |
| H08 El cierre precargaba consumos contra la receta | U13 | Servicio común `necesidad_orden` (preparación, pedido LOM y cierre): sin recambio no se precarga el módem; lo estimado no se precarga. | `CierreRecetaTests` |
| H09 La agenda no consultaba el material | U12 | La agenda verifica el material de cada orden en la fecha (su reserva, el stock del técnico, el depósito sin comprometer y las compras que llegan a tiempo) y dice qué falta. El coordinador puede asignarla igual **sólo con motivo**, y queda anotada como excepción. El cupo de órdenes se mantiene como tope adicional a los minutos (se aclara en el código). | `AgendaMaterialTests` |
| H10 Editar una herramienta asignada creaba custodia sin salida | U14 | Cambiar la cantidad de una entrega genera su movimiento (entrega o devolución) o se rechaza si no hay existencias; persona, elemento y origen no se editan. | `PanolTests` (revisión) |
| H11 Una evaluación futura habilitaba antes de su fecha | U15 | La habilitación usa sólo evaluaciones con fecha igual o anterior a la consultada y no vencidas. | `HabilitacionPorFechaTests` |

### Otros puntos que la revisión marcó como parciales o con reservas

| Criterio | Corrección | Prueba |
|---|---|---|
| B04/B05 Agenda | Ventanas horarias acordadas con el cliente (la agenda de cada técnico se arma en orden desde su horario de entrada; una orden con ventana sólo entra si se llega a tiempo). Cuadrillas: el ayudante sale con su responsable y no recibe órdenes propias; si el responsable no sale, la cuadrilla tampoco. | `AgendaCompletaTests` |
| B17 Tutela | La ejecución tutelada sólo se asigna con un tutor real ese día: compañero de cuadrilla disponible y habilitado. | `AgendaCompletaTests` |
| B30 Flota | Service programado (`ServiceProgramado`): el vehículo y su técnico quedan sin disponibilidad esos días. | `AgendaCompletaTests` |
| B22 Acciones | Se separan desvíos con acción **indicada**, **ejecutada** y **eficaz verificada**; ya no se llama "corregido" a tener una acción cumplida. | `DesviosYObjetivosTests` |
| B23 Objetivos | Se guarda quién verificó aunque la cuenta de gerencia no tenga ficha de persona, y **sobre qué datos**; si cambian después, la verificación deja de valer (queda en el historial). Lo verificado no se reescribe desde la app. | `DesviosYObjetivosTests` |
| B24 Encuesta | El supervisor evaluado ya no ve quién respondió; los comentarios se muestran sin fecha ni nota, en orden aleatorio y sólo con respuestas de suficientes personas. | `ConfidencialidadEncuestaTests` |
| B35 Indicadores | Las curvas históricas usan el criterio (meta, límite, peso) **vigente en cada fecha** (`Indicador.en`): cambiar hoy una meta no reescribe el pasado. | `ReproducibilidadTests` |
| B39 Reglas | Cada cambio de Parámetros queda registrado (quién, cuándo, antes/después) y se puede consultar el valor vigente en una fecha. | `ReproducibilidadTests` |
| B38 Permisos | Pruebas de acceso por objeto en los flujos nuevos (incidente de otro equipo, objetivos, calibración, plantillas, rectificación). | `AccesoPorObjetoTests` |
| Datos previos | `python manage.py verificar_consistencia` comprueba inventario, reservas, equipos, pañol, visitas y saldos; la migración concilia el stock del pañol que no tenía movimiento en el libro. Se probó migrando una copia de datos generada con la versión anterior (40c2ac9) y restaurando un respaldo. | `VerificarConsistenciaTests` |

Lo que dependía de la empresa ahora tiene **valores inventados** cargados en la demo, marcados
como tales en la pantalla *Productividad → Supuestos e inventados* (y con el aviso general de datos de
demostración): pesos de los índices (calibración simulada, versionada), comparación de técnicos con
los de su misma zona y evidencia mínima, umbrales de la encuesta (5 respuestas de 3 personas),
reglas financieras (retención 3,5 %, cobro a 45 días, retrabajos no pagos, tasa 3 % mensual),
pagos y recuperos de incidentes con su comprobante (inventado) y la política de antigüedad (la
alerta de 60 días cuenta desde el ingreso original). Las metas propias de cada equipo ahora guardan
historial (`VersionMetaEquipo`) y las curvas usan la meta vigente en cada fecha. Para pasar a datos
reales: cargar los valores de la empresa en Parámetros y quitarlos de «valores inventados».

## Lo que necesita la empresa (sección 5.3)

Nada de esto bloquea el sistema: hoy corre con valores de prueba visibles como tales. Para el piloto
conviene reemplazarlos (todos se cargan desde *Parámetros* o el administrador, sin programar):

- **Operación:** tiempos estándar por tipo de tarea y traslado promedio; composición real de
  cuadrillas; ventanas horarias.
- **Calidad y personas:** plantilla de inspección real (puntos, criterios, cuáles son críticos);
  criterio de selección de controles (cuántos aleatorios por técnico y semana); objetivos de los
  supervisores con su criterio de aceptación; competencias por tipo de tarea; mínimos de la encuesta.
- **Recursos y flota:** recetas por tipo de tarea y su condición; probabilidad de recambio y de
  decodificador; qué reloj activa los 60 días (original o permanencia); EPP por tarea; planes de
  mantenimiento por vehículo con su fecha y km base.
- **Finanzas:** tarifas de Claro por vigencia, % de retención y días de cobro; saldos de corte de
  las cuentas; criterios de urgencia para pagar; tasa de descuento para comparar alternativas.

## Datos inventados en la demo

La demo (`generar_demo`) enciende *Parámetros → Datos de demostración*: mientras esté encendido,
**todas las pantallas** (escritorio y app) muestran un aviso de que los datos son inventados, y las
pantallas de requisitos, plantillas, expedientes y calibración lo repiten donde corresponde. Al cargar
los datos reales de la empresa, se apaga ese parámetro.

## Fuera de alcance de esta etapa

- IA (dictado, consulta, agente de agenda): ver B40.
- Acordar los pesos definitivos de los índices: la herramienta existe, pero hacen falta meses de datos reales.
