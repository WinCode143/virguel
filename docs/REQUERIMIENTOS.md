# Requerimientos de Virguel y cómo los resuelve el sistema

Fuente: dos textos del cliente (uno por temas y uno por módulos del ERP), con
varios puntos repetidos. Se unificaron en los 9 módulos de abajo.

Restricciones del cliente:
- **La empresa no vende**: finanzas maneja sólo egresos y proyección de gastos.
- **No se integra con Oracle**: todo dato sale del relevamiento interno (carga en el
  sistema, app móvil de técnicos y supervisores).
- Se menciona **Power BI** como herramienta de análisis: el sistema calcula los
  indicadores y además los expone para Power BI.

---

## 1. Operación y gestión de técnicos
| Pedido | Implementación |
|---|---|
| Medir la productividad diaria del personal en calle | `operaciones.Jornada` (quién salió a la calle cada día) + `OrdenTrabajo` (qué hizo). Tablero **1 · Operación diaria**: OT por día y resultado, técnicos en calle, hectáreas, ranking por técnico. |
| Capacidad real de trabajo | Capacidad = técnicos en calle → cuadrillas × hectáreas/día × densidad de clientes, con tope de visitas por técnico (`tablero/planificacion.py`). Se compara contra lo realmente completado (gráfico del Resumen). |
| (agregado) Asignar el trabajo según la capacidad real | Asignación automática de órdenes por zona y capacidad individual (`tablero/asignacion.py`). |
| Control del rendimiento según tareas asignadas | Minutos reales vs. estándar por tipo de tarea; efectividad (completadas / ejecutadas); retrabajos. |

## 2. Supervisión y calidad
| Pedido | Implementación |
|---|---|
| Encuesta diaria automatizada: técnicos califican el trato de su supervisor | `supervision.EncuestaSupervisor`. Se genera sola al cerrar la jornada en la app y en la tarea nocturna. Se responde con un link (sirve por WhatsApp/SMS, sin login) con estrellas: trato, claridad, apoyo, presencia + comentario. **Confidencial**: el supervisor sólo ve promedios. |
| Medir carácter e imagen del supervisor automáticamente | Eje "Imagen / trato" del puntaje del supervisor + evolución semanal + alertas si la nota baja de 3/5. |
| Analizar tareas y objetivos diarios del supervisor | `TareaSupervisor` (gerencia asigna, el supervisor reporta el resultado desde la app). Las que quedan sin reportar se cierran como "no cumplidas". |
| Auditoría por cantidad y calidad de informes subidos a la app | `InformeControl` desde la app móvil con foto (cámara), ubicación GPS y orden asociada. **Calidad de documentación** 0–100 (descripción, foto, ubicación, orden). Objetivo de referencia: 4 informes/día. |
| Si detecta problemas y qué solución aplica (recapacitó al día siguiente, apercibimiento, multa…) | `AccionCorrectiva` ligada al informe. Se mide % de desvíos con acción y **días hasta la acción**. La app muestra al supervisor los desvíos que aún no resolvió. |

## 3. Incidentes y daños
| Pedido | Implementación |
|---|---|
| Conteo mensual de fallas graves (roturas en casas, caños pinchados…) con responsabilidad civil | `incidentes.Siniestro` (tipo, gravedad, responsabilidad civil, costos, estado legal, resolución). Técnicos y supervisores los reportan desde la app. Tablero **3** con conteo mensual por gravedad. |
| Saber cómo y cuándo accionar legalmente o mitigar gastos | Cada siniestro muestra una **recomendación de acción** según gravedad, costo y responsabilidad (reparación propia / acuerdo / aseguradora / legales). Alertas de siniestros abiertos > 30 días y de 3+ graves en el mes. Reincidentes por técnico. |
| Plan de acción y mitigación de costos | Campos causa raíz, plan de acción, costo estimado/real, monto recuperado (seguro, descuentos). |

## 4. Herramientas, EPP y materiales críticos
| Pedido | Implementación |
|---|---|
| Control y asignación de EPP, herramientas y materiales críticos | `herramientas.Elemento` (vida útil, obligatorio) y `Asignacion` (entrega, vencimiento automático, estado, conformidad firmada en la app). Tablero **4**: cumplimiento por técnico, vencimientos, pañol. El EPP faltante/vencido baja el puntaje de seguridad del técnico. |

## 5. Capacitación y competencias
| Pedido | Implementación |
|---|---|
| Power BI no debe medir sólo si es productivo hoy, sino su capacidad a largo plazo | Evaluación con ventana de 90 días (configurable) y **tendencia** (último tercio vs. primer tercio). Ficha del técnico con su curva semanal vs. el promedio del equipo. |
| Detectar si rinde bajo por falta de capacitación en producción… | **Diagnóstico automático** (`capacitacion/evaluacion.py`): baja productividad con calidad, disciplina y seguridad en orden → "Necesita capacitación en producción". |
| …o si es un desastre en todo lo demás y un riesgo (desvincular) | Falla en 2+ dimensiones, o ya fue capacitado en producción y no mejoró → "Riesgo alto – evaluar desvinculación". Otros estados: "En observación", "En curva de aprendizaje" (< 60 días), "En mejora tras capacitación". |
| Nivel de riesgo operativo de cada persona | **Riesgo 0–100** = 100 − (20 % productividad + 30 % calidad + 25 % disciplina + 25 % seguridad). Alto ≥ 50. |
| (agregado) ¿La capacitación sirve? | Tablero **5 · Capacitación**: productividad 30 días antes vs. 30 días después de cada capacitación. |

## 6. Flota / vehículos
| Pedido | Implementación |
|---|---|
| Agenda y seguimiento automatizado de services | `flota.Vehiculo`, `TipoService` (cada X km y/o Y días), `ServiceRealizado`. El km se actualiza solo con la jornada del técnico. El próximo service se estima por km recorridos por día y por fecha (lo que ocurra primero). Alertas de service, VTV y seguro. |

## 7. Finanzas y flujo de fondos
| Pedido | Implementación |
|---|---|
| Proyección de egresos según movimiento de materiales y logística, sin ingresos | Egresos **automáticos** desde compras de stock, services, EPP y siniestros + costos fijos mensuales. Proyección a 3 meses: demanda comercial × materiales por tarea × costo, services que vencen, EPP que vence, siniestros abiertos (`finanzas/proyeccion.py`). |

## 8. Inventario, demanda y abastecimiento
| Pedido | Implementación |
|---|---|
| Antigüedad de stock: evitar materiales/equipos parados más de 60 días | Stock **por lote con fecha** y consumo **FIFO**. Semáforo: aviso a los 45 días, crítico a los 60 (configurables). Valor inmovilizado por tramo de antigüedad. |
| Stock diario cruzado con el personal en calle | Para cada material: stock, stock por técnico, consumo por técnico/día (histórico), consumo diario esperado con los técnicos de hoy y **días de cobertura**. Alerta si alcanza para menos de 7 días. |
| Previsión de materiales según demanda comercial | `DemandaComercial` (clientes previstos por día/tipo de tarea) × `RecetaMaterial` (materiales por tipo de tarea) → necesidad, faltante y costo de compra. |

## 9. Análisis transversal / pantalla gerencial
| Pedido | Implementación |
|---|---|
| Hectáreas cubiertas por día (5 a 6) | Parámetro editable (5–6 ha por cuadrilla) + valor real relevado por los técnicos al cerrar la jornada. |
| Cantidad de clientes que se pueden atender (ej. 6) | Clientes atendibles = mín(hectáreas × densidad de la zona, técnicos × 6 visitas). |
| Probabilidad de que pidan decodificador (50 % vs 60 %) | Escenarios bajo/alto editables + **estimación con datos reales** (modelo Beta-Binomial: parte del supuesto 55 % y se corrige con cada orden). Decodificadores necesarios vs. stock. |
| Pantalla gerencial que cruce todo | **Resumen** + **9 · Planificación** (simulador con todos los supuestos, demanda vs. capacidad por día, técnicos necesarios, materiales y decodificadores). |

---

## Puntos ambiguos a confirmar con el cliente
Se resolvieron con un supuesto razonable y **todos son configurables**, pero conviene validarlos:

1. **"5 a 6 hectáreas por día"**: ¿por técnico, por cuadrilla o por todo el equipo? Se asumió **por cuadrilla de 2 técnicos** (parámetro `técnicos por cuadrilla`).
2. **"6 clientes modernos"**: se interpretó como tope de clientes atendibles por técnico por día. "Moderno" quedó como un tipo de cliente (fibra/smart). ¿Es otra cosa?
3. **Densidad de clientes por hectárea** por zona: no fue informada; hay valores de ejemplo por zona.
4. **Decodificadores**: ¿la probabilidad es por cliente o por televisor? Se calculó **por cliente**; el cliente tiene el dato de cantidad de televisores para refinarlo.
5. **Encuesta a supervisores**: se diseñó confidencial (el supervisor ve sólo promedios). Confirmar con RR.HH. / legales.
6. **Multas a técnicos**: se registran con monto; confirmar si deben descontarse en liquidación (hoy no se integran con sueldos).
7. **Umbrales del diagnóstico** (79 % de la mediana, pesos del riesgo): son un punto de partida; conviene calibrarlos con 2–3 meses de datos reales.
8. **Canal de envío de la encuesta**: el link funciona por WhatsApp/SMS; falta definir el proveedor (WhatsApp Business API, Twilio, etc.).
