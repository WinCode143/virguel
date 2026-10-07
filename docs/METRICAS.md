# Métricas de productividad — técnicos y supervisores

Este documento define **qué se mide, cómo se calcula y por qué**. Las metas, mínimos y
pesos son un punto de partida: se ajustan sin programar en **Carga de datos → Indicadores
de productividad**. Se calculan en `tablero/metricas.py`.

## Principios de diseño

1. **Medir trabajo, no cantidad de órdenes.** Cada tipo de trabajo tiene un tiempo
   estándar (una instalación vale más que un retiro). Contar órdenes premia elegir las
   fáciles; medir **horas estándar producidas** no.
2. **Separar lo que depende de la persona de lo que no.** "Cliente ausente", "clima" o
   "problema de red" no se le cuentan al técnico; "faltó material" sí (debió pedirlo).
3. **Calidad junto a cantidad.** Si alguien es rápido pero hay que volver a corregir su
   trabajo, el indicador de primera visita lo compensa.
4. **Difícil de manipular.** La ubicación GPS al cerrar, la foto, la firma del cliente y el
   tiempo medido con "Empezar trabajo" hacen que los datos no dependan sólo de lo que el
   técnico escribe.
5. **El supervisor se mide por su equipo y por su gestión**, no por cuántos formularios carga.
6. **Comparar con una meta y con el grupo.** Cada ficha muestra la meta y la mediana del
   plantel, para distinguir "le va mal a él" de "le va mal a todos" (problema de proceso).

## Cómo se arma el índice

- Cada indicador tiene una **meta** (vale 100 puntos) y un **mínimo aceptable** (vale 0).
  Entre ambos, los puntos son proporcionales. Por ejemplo, con meta 70 % y mínimo 40 %,
  55 % vale 50 puntos.
- En los indicadores donde "menos es mejor" (consumo, demoras, faltas), la meta es el valor
  bajo y el mínimo el valor alto tolerable.
- El índice (0–100) es el **promedio ponderado por peso** de los indicadores con datos.
  Peso 0 = sólo informativo.
- Semáforo: verde ≥ 75, amarillo ≥ 55, rojo < 55 (índice); por indicador, verde ≥ 80 puntos,
  amarillo ≥ 50, rojo < 50.
- Período por defecto: últimos 30 días (se puede ver 60 o 90).
- Si un indicador no tiene datos suficientes, queda "sin datos" y no cuenta (no castiga ni premia).

---

## IPT — Índice de Productividad del Técnico

| Indicador | Cálculo | Meta | Mínimo | Peso | Por qué |
|---|---|---|---|---|---|
| **Eficiencia de la jornada** | Horas estándar de las órdenes completadas ÷ horas trabajadas (fichada de entrada a salida). | 70 % | 40 % | 25 | El corazón de la productividad: cuánto trabajo útil sale de cada hora pagada. Incluye traslados y tiempos muertos. |
| **Resuelto en la primera visita** | Órdenes completadas sin visita de corrección posterior. | 95 % | 80 % | 20 | Equilibra la velocidad: hacer rápido y mal genera retrabajos que cuestan otra visita. |
| **Cumplimiento de la agenda** | Órdenes asignadas para días ya terminados, resueltas o intentadas ese mismo día. | 90 % | 70 % | 10 | Que el cliente sea atendido el día prometido. |
| **Calidad en los controles** | Puntaje promedio del supervisor en los controles en calle (5/5 = 100 %). | 90 % | 60 % | 10 | Mirada externa de la calidad del trabajo. |
| **No resueltas por causa propia** | Órdenes no resueltas por "faltó material" u "otro" ÷ ejecutadas. | ≤ 2 % | 10 % | 5 | Sólo lo evitable por el técnico (pedir partes a tiempo, planificar). |
| **Órdenes por día vs. el equipo** | Órdenes completadas por día en calle, como % de la mediana del plantel. | 100 % | 60 % | 5 | Referencia simple y entendible; pesa poco porque no distingue tipos de trabajo. |
| **Cierres documentados** | Completadas con foto y conformidad del cliente (nombre o firma). | 90 % | 50 % | 5 | Respaldo ante reclamos y siniestros. |
| **Cierres en el domicilio** | Cierres con GPS a menos de 300 m del domicilio del cliente. | 95 % | 70 % | 5 | Verifica que el trabajo se cerró en el lugar. |
| **Consumo de materiales vs. estándar** | Costo de materiales usados ÷ costo estándar del tipo de trabajo (sin decodificadores). | ≤ 100 % | 130 % | 5 | Detecta desperdicio o desvío de materiales. |
| **Puntualidad** | Días fichados sin llegada tarde. | 97 % | 85 % | 5 | Disciplina básica. |
| **Presentismo** | Días trabajados ÷ días que debía trabajar (sin vacaciones ni francos). | 97 % | 85 % | 5 | Disponibilidad. |
| *Demora en arrancar* | Minutos promedio entre la fichada y el inicio del primer trabajo. | 30 min | 75 min | info | Muestra tiempo muerto al empezar el día. |
| *Tiempo por orden vs. estándar* | Minutos reales ÷ minutos estándar. | 100 % | 140 % | info | Ya está dentro de la eficiencia. |

**IPT vs. diagnóstico de riesgo:** el IPT mide productividad. El diagnóstico de "Técnicos y
riesgo" (capacitar / evaluar desvinculación) mira además sanciones, siniestros y la tendencia
de 90 días. Se usan juntos: IPT bajo + riesgo bajo = **capacitar**; IPT bajo + riesgo alto =
**evaluar desvinculación**.

---

## IGS — Índice de Gestión del Supervisor

| Indicador | Cálculo | Meta | Mínimo | Peso | Por qué |
|---|---|---|---|---|---|
| **Eficiencia de su equipo** | Promedio de la eficiencia de la jornada de sus técnicos. | 70 % | 45 % | 10 | El resultado productivo de su equipo. |
| **Resuelto en primera visita (equipo)** | Promedio de primera visita de sus técnicos. | 95 % | 80 % | 10 | La calidad de su equipo. |
| **Mejora del equipo** | Órdenes por día del equipo: últimas 4 semanas vs. las 4 anteriores. | +5 % | −10 % | 5 | Un buen supervisor hace crecer a su equipo, no sólo lo mantiene. |
| **Cobertura de control** | Semanas-técnico con al menos un control en calle ÷ semanas-técnico trabajadas. | 100 % | 60 % | 15 | Que ningún técnico pase una semana sin ser controlado. Pesa más porque el supervisor ausente se detecta aquí. |
| **Desvíos resueltos en 2 días** | Desvíos detectados con acción correctiva en ≤ 2 días (con 3+ desvíos). | 90 % | 50 % | 10 | Corregir rápido (recapacitar al día siguiente). |
| **Efectividad de las correcciones** | Técnicos corregidos (hace 30–60 días) que no repitieron un desvío en los 30 días siguientes. | 80 % | 40 % | 10 | No alcanza con sancionar: la corrección tiene que funcionar. |
| **Clima del equipo** | Encuesta diaria + evaluación semanal de sus técnicos, llevadas a 0–100. | 80 % | 50 % | 15 | Trato, claridad, apoyo, justicia: lo que pidió el cliente. |
| **Faltas sin aviso del equipo** | Faltas injustificadas cada 100 jornadas esperadas. | ≤ 0,5 | 3 | 5 | El supervisor debe contener el ausentismo de su gente. |
| **Siniestros del equipo** | Siniestros cada 1000 jornadas en calle. | ≤ 2 | 10 | 5 | Seguridad y responsabilidad civil. |
| **Objetivos cumplidos** | Cumplimiento de los objetivos diarios que asigna gerencia. | 90 % | 50 % | 10 | Ejecuta lo que se le pide. |
| **Tiempo de respuesta a su equipo** | Mediana de horas para aprobar/rechazar avisos de ausencia y pedidos de partes. | ≤ 4 h | 48 h | 5 | Un técnico sin partes o sin respuesta no produce. |
| *Presentismo del equipo* | Promedio de presentismo de sus técnicos. | 96 % | 88 % | info | Contexto. |
| *Su propia puntualidad* | Días fichados sin llegada tarde del supervisor. | 97 % | 85 % | info | Ejemplo. |

---

## Riesgos de manipulación y cómo se cubren

| Riesgo | Mitigación |
|---|---|
| Elegir órdenes fáciles | La eficiencia usa horas estándar por tipo de trabajo. |
| Cerrar rápido sin terminar | Primera visita (retrabajos) + controles del supervisor. |
| Cerrar órdenes sin ir | GPS de cierre vs. domicilio + foto + firma del cliente. |
| Marcar "cliente ausente" para no trabajar | Se ve en "motivos de no resolución"; si un técnico tiene muchos más que el equipo, revisarlo (próxima mejora: indicador de ausentes atípicos). |
| Supervisor que no controla y por eso "no encuentra desvíos" | Cobertura de control con peso alto; la respuesta a desvíos exige 3+ desvíos para contar. |
| Supervisor que presiona para mejorar la encuesta | La evaluación es confidencial y sólo se muestran promedios. |

## Calibración pendiente con datos reales

- **Tiempos estándar de cada tipo de trabajo** (Carga de datos → Tipos de tarea): son la base
  de la eficiencia. Medirlos con 2–4 semanas de "Empezar/terminar trabajo" y ajustar.
- **Metas**: arrancar con la mediana real del plantel como meta durante el primer trimestre y
  subirla gradualmente.
- **Pesos**: validarlos con gerencia (qué importa más para Virguel).
