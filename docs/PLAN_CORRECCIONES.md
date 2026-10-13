# Plan de ejecución — Revisión funcional y técnica del 12/10/2026

Fuente: *Virguel — Revisión funcional y técnica* (v0.1, 12/10/2026), sobre el commit
`8c735c6`. Este plan convierte los hallazgos H01–H10 y el "orden recomendado" en
tareas concretas, con archivos afectados, criterio de aceptación y dependencias.

**Regla general para todo el plan:** cada hallazgo se cierra primero con un **test que
reproduce el escenario de la revisión y falla**, después el arreglo, y recién ahí el
test pasa. Los escenarios de la revisión quedan como pruebas de regresión en
`tests/` (sugerido: un archivo por fase, `tests/test_fase1_*.py`, etc.).

Leyenda de prioridad (de la revisión): **P1** = corregir antes de usar el flujo con datos
reales para decisiones. **P2** = limitación importante para consolidar el producto.

---

## Estado de ejecución (13/10/2026)

Rama `claude/laughing-goldberg-he8mh1`. Suite: **148 tests en PostgreSQL**, todos pasan (89 originales +
59 de regresión en `tests/test_revision.py`), también en CI (`.github/workflows/tests.yml`).

| Ítem | Estado | Notas |
|---|---|---|
| 0.1 Test frágil | ✅ Hecho | Serie inequívoca en la prueba de visibilidad. |
| 0.2 CI en PostgreSQL | ✅ Hecho | Corre la suite y verifica migraciones pendientes. |
| 0.3 Preguntas a la empresa | ⏳ **Esperando respuestas** | Ver lista abajo y `REQUERIMIENTOS.md`. |
| 1.1 H01 Archivos privados | ✅ Hecho | `core/archivos.py`; Caddy ya no expone `/media/` (verificado con Docker/Caddy). |
| 1.2 H05 Importación | ✅ Hecho | Conflictos registrados, sin duplicar stock, "Reabrir orden" auditado. |
| 1.3 H06 Sin señal | ✅ Hecho | Idempotencia + confirmación explícita; verificado en navegador. |
| 2.1 H02 Devoluciones | ✅ Hecho | `ConsumoLote`, origen del lote, comando `recalcular_devoluciones`. Punto 5 (desde cuándo cuentan los 60 días en el técnico) espera decisión. |
| 2.2 Custodia herramientas/EPP | ✅ Hecho | `CompraElemento`; "decodificadores de Claro" espera respuesta (pregunta 6). |
| 3.1 Catálogo de causas | ✅ Hecho | Valores iniciales a validar (pregunta 4). |
| 3.2 H03 | ✅ Hecho | |
| 3.3 H04 | ✅ Hecho | Usa el `tipo` del informe como tipo de problema. |
| 3.4 H09 | ✅ Hecho | Pesos versionados; v2 a validar (pregunta 4). |
| 4 H07 Finanzas | ✅ Hecho (genérico) | Falta: liquidación esperada de Claro calculada desde las órdenes y comparador de "alternativas de pago" (preguntas 1 y 3). |
| 5.1 H10 Historia | ✅ Hecho | `Intento` y `AsignacionSupervisor`. Cuadrillas: espera pregunta 7. Consumos ligados a orden/técnico/fecha (no a la visita). |
| 5.2 H08 Previsión | ✅ Hecho | Con `CompraEnCamino`. |
| 6 Validación | ✅ Hecho | PostgreSQL, despliegue Docker + Caddy, recorrido con Playwright (`scripts/recorrido_navegador.js`, 51/51), rendimiento < 2 s por pantalla con los datos de demo. |

## Resumen

| Fase | Contenido | Hallazgos | Depende de | Esfuerzo estimado |
|---|---|---|---|---|
| 0 | Preparación: test frágil, CI, decisiones con la empresa | — | — | 1–2 días |
| 1 | Registros fiables: archivos privados, importación, offline | H01, H05, H06 | 0 | 5–7 días |
| 2 | Inventario: devoluciones, trazabilidad, custodia vs. compra | H02 (+ base de H08) | 1 | 5–7 días |
| 3 | Evaluación e indicadores: causas, efectividad, suficiencia de evidencia | H03, H04, H09 | 0 (catálogo de causas) | 6–8 días |
| 4 | Finanzas: ingresos, cobros, pagos parciales, caja | H07 | 0 (respuestas de la empresa) | 7–10 días |
| 5 | Historia operacional y abastecimiento | H10, H08 | 2, 3 | 7–10 días |
| 6 | Validación en PostgreSQL, despliegue y navegador | todos | 1–5 | 3–5 días |

Las fases 3 y 4 pueden avanzar en paralelo con la 2 cuando la empresa haya respondido
las preguntas de la fase 0.

---

## Fase 0 — Preparación

### 0.1 Corregir el test con falso positivo
- `tests/test_negocio.py:873-878`: la prueba de visibilidad de partes del supervisor
  busca la ausencia de `"Z9"` en todo el HTML y puede chocar con el token CSRF.
- Cambio: usar un número de serie largo e inequívoco (p. ej. `"SERIE-AJENA-0001"`) o
  verificar sobre el contexto/queryset de la vista en vez del HTML completo.
- Aceptación: la suite completa pasa 10 veces seguidas.

### 0.2 Integración continua
- Agregar `.github/workflows/tests.yml`: `manage.py test` sobre **PostgreSQL** (servicio
  en el workflow), así también corren las migraciones del esquema `powerbi` que hoy se
  excluyen en SQLite.
- Aceptación: el workflow está en verde en `master`.

### 0.3 Preguntas que debe responder la empresa (Adrián / Franco)
Sin estas respuestas, las fases 3 y 4 se implementan con supuestos explícitos que
después habrá que revisar.

1. **Ingresos:** ¿cómo liquida Claro? (frecuencia, por orden/por puntos/por baremo,
   retenciones, plazo de cobro, débitos por calidad). ¿Hay otros ingresos?
2. **Caja:** saldos iniciales por cuenta (banco, efectivo), y si hay que manejar más de
   una cuenta o moneda.
3. **Deudas y alternativas de pago:** ¿qué deudas existen (proveedores, AFIP/ARCA,
   préstamos, planes de cuotas)? ¿Qué se entiende por "alternativas de pago"?
4. **Evaluación:** ¿qué motivos de no resolución se consideran atribuibles al técnico?
   ¿Qué pesos quiere la empresa para cada dimensión? ¿Las recapacitaciones deben
   restar puntos?
5. **Uso laboral de los diagnósticos:** confirmar que el diagnóstico es un **apoyo** a la
   supervisión y no una decisión automática (cambia textos y advertencias en pantalla).
6. **Custodia de equipos:** ¿los decodificadores y equipos son propiedad de Claro o de
   la empresa? ¿Se rinden a Claro?
7. **Cuadrillas:** ¿los técnicos trabajan solos o en cuadrillas? ¿Cambian de supervisor
   con frecuencia?

Registrar las respuestas en `docs/REQUERIMIENTOS.md` (sección "Aclaraciones") y
corregir la línea 7 ("la empresa no vende: finanzas maneja sólo egresos").

---

## Fase 1 — Registros fiables (P1)

### 1.1 H01 — Archivos privados detrás de la autorización del ERP
**Problema:** `deploy/Caddyfile` (líneas 8–11) y `config/urls.py:32` sirven `/media/`
sin pasar por Django. Ahí quedan certificados, legajos, recibos, firmas y fotos.

Archivos con `FileField` a proteger:
| Modelo | Campo | Ruta |
|---|---|---|
| `personal.Novedad` | `certificado` | `certificados/` |
| `personal.DocumentoPersonal` | `archivo` | `legajos/` |
| `finanzas.Liquidacion` | `recibo` | `recibos/` |
| `finanzas.Egreso` | `comprobante` | `egresos/` |
| `operaciones.OrdenTrabajo` | `foto_trabajo`, `firma` | `ordenes/`, `firmas/` |
| `supervision.InformeControl` | `foto` | `informes/` |
| mails del parte diario | — | `media/mails/` |

Tareas:
1. Crear `core/archivos.py` con una vista `descargar(request, app, modelo, pk, campo)`
   que: exige sesión, resuelve el objeto, aplica una función de permiso por modelo
   (reutilizando las reglas de rol ya existentes: gerencia ve todo; supervisor, su
   equipo; técnico, lo suyo; contabilidad, finanzas) y responde con
   `X-Accel-Redirect`/`X-Sendfile` en producción o `FileResponse` en desarrollo.
2. Reemplazar en las plantillas los `{{ obj.campo.url }}` por una etiqueta/filtro
   `{% url_archivo obj "campo" %}` que apunte a esa vista.
3. Caddy: eliminar el `handle_path /media/*` público. Opción recomendada: Django
   responde con `FileResponse` (volumen chico) o usar `reverse_proxy` + header de
   redirección interna de Caddy. Mover los archivos a un directorio **no** servido
   (`/srv/privado`).
4. `config/urls.py`: dejar `static(MEDIA_URL…)` solo con `DEBUG` y apuntando a la vista
   protegida, no al servidor de archivos.
5. Cabeceras `Cache-Control: private, no-store` en las respuestas de archivos y en las
   páginas con datos personales; en `logout` limpiar cachés del service worker /
   IndexedDB del usuario (ver 1.3).

Aceptación (tests):
- Sin sesión → 302 a login (o 404) para cada tipo de archivo.
- Técnico A no puede bajar el certificado del técnico B → 403/404.
- Supervisor solo baja archivos de su equipo; gerencia baja todo.
- Ningún template contiene `.url` de un campo privado (test que recorre templates).

### 1.2 H05 — La importación no reabre órdenes cerradas
**Problema:** `tablero/importar.py`, `imp_ordenes()` (≈ líneas 182–194):
`update_or_create` fuerza `estado = asignada/pendiente` en cada carga.

Tareas:
1. Separar alta y actualización: si la orden no existe, se crea como hoy. Si existe:
   - Estados terminales (`completada`, `fallida`) → **no** se tocan estado, técnico,
     fechas ni datos de cierre. La fila se registra como **conflicto** si el archivo trae
     valores distintos.
   - Estados abiertos → se actualizan solo campos planificables (tipo, cliente, zona,
     fecha programada, técnico, observaciones), sin bajar un estado más avanzado.
2. Nuevo modelo `tablero.Importacion` (usuario, fecha, tipo, archivo, totales) y
   `tablero.ConflictoImportacion` (importación, fila, número, campo, valor actual,
   valor importado). Mostrar los conflictos en el resultado de la carga.
3. Reapertura administrativa explícita: acción "Reabrir orden" solo para gerencia, con
   motivo obligatorio y registro en `NotaOrden`/auditoría.
4. Revisar con el mismo criterio `imp_clientes` y `imp_stock` (este último crea lotes
   cada vez: reimportar el mismo archivo duplica stock y egresos → detectar por
   `remito` + material + fecha).

Aceptación:
- Reimportar una orden completada la deja completada y genera un conflicto.
- Reimportar el mismo archivo de stock dos veces no duplica lotes ni egresos.
- Reabrir manualmente deja rastro (quién, cuándo, por qué).

### 1.3 H06 — La sincronización offline no borra envíos rechazados
**Problema:** `static/js/offline.js` (líneas 65–72) borra el pendiente ante cualquier
respuesta que no sea 403/login, incluso 400/404/500 o un 200 con el formulario con errores.

Tareas:
1. Cada envío guardado lleva un `_id_operacion` (UUID generado en el celular).
2. Servidor: modelo `core.OperacionOffline(id_operacion, usuario, url, recibida, resultado)`
   y un decorador/middleware para las vistas con `data-offline` que:
   - si el `id_operacion` ya fue aceptado, responde de nuevo "aceptado" sin repetir la
     operación (idempotencia: evita fichadas o consumos dobles);
   - cuando la petición viene de la sincronización (header `X-Virguel-Sync: 1`),
     responde **JSON** `{ok: true}` o `{ok: false, errores: {...}}` en vez de HTML.
3. Cliente: borrar el pendiente **solo** con `ok: true`. Con errores de validación →
   marcarlo como "con error" y mostrarlo en la app para corregirlo o descartarlo
   explícitamente. Con 5xx o sin red → reintentar más tarde con espera creciente.
   Con 403/login → conservar (como hoy).
4. Los pendientes se guardan asociados al usuario; al cerrar sesión o cambiar de cuenta
   no se envían con la sesión de otro usuario (se avisa y se conservan para su dueño).

Aceptación:
- Tests de servidor: reenvío del mismo `id_operacion` no duplica el registro; un
  formulario inválido devuelve `ok: false`.
- Prueba en navegador (Playwright, fase 6): sin red → guardar; volver la red con un
  500 → el pendiente sigue; con 200 OK → se borra; cambiar de usuario → no se envía.

---

## Fase 2 — Inventario y custodia (P1)

### 2.1 H02 — La devolución conserva antigüedad y no genera compra
**Problema:** `inventario/stock_tecnico.py`, `devolver()` crea un `LoteIngreso` nuevo
con fecha de hoy y costo actual; `finanzas/signals.py`, `egreso_de()`, convierte todo
`LoteIngreso` en egreso de "compras-stock".

Tareas:
1. `LoteIngreso`: agregar `origen` (`compra`, `devolucion`, `ajuste`, `importacion_inicial`)
   y `lote_origen` (FK opcional al lote del que salieron las unidades).
2. `Salida` y `MovimientoStockTecnico`: registrar de qué lote(s) salieron las unidades
   (tabla intermedia `ConsumoLote(salida, lote, cantidad, costo_unitario)` alimentada
   por `registrar_salida` FIFO). Así la entrega al técnico conserva fecha y costo de origen.
3. `devolver()`: reingresar las unidades devolviendo cantidad a los **lotes de origen**
   (o creando un lote `origen=devolucion` con la **fecha de ingreso y costo del lote
   original**), según LIFO de lo entregado a ese técnico.
4. `finanzas/signals.py`: solo `origen=compra` genera egreso. Devoluciones, ajustes y
   transferencias internas, nunca.
5. `partes_paradas()`: usar la fecha de ingreso original, no la de la entrega, si la
   empresa confirma que los 60 días se cuentan desde la compra (pregunta para fase 0).
6. Script de recálculo `manage.py recalcular_devoluciones --dry-run`: busca lotes con
   `proveedor="Devolución …"`, los reclasifica y elimina los egresos generados por ellos,
   con informe previo. Solo se ejecuta si ya hay datos reales cargados.

Aceptación (escenario de la revisión): ingreso 10 u × 100 hace 90 días → gasto 1.000;
entregar 4, devolver 2 → egresos totales siguen en **1.000**, el lote devuelto conserva
la fecha de hace 90 días y el costo 100.

### 2.2 Custodia de herramientas y EPP
**Problema relacionado:** `egreso_de()` genera un egreso por cada `Asignacion` de
herramientas/EPP, aunque sea el mismo elemento que pasa de una persona a otra.

Tareas:
1. Separar **compra** del elemento (egreso) de **asignación** (custodia, sin egreso).
2. Asignación de un elemento ya comprado → sin egreso; consumo/rotura → baja de
   inventario, sin egreso nuevo (el gasto ya se registró al comprar).
3. Si se confirma que los equipos (decodificadores) son de Claro: marcarlos como
   "en custodia de terceros", sin valor en el costo de la empresa.

Aceptación: reasignar un mismo taladro tres veces genera un solo egreso.

---

## Fase 3 — Evaluación e indicadores (P1/P2)

### 3.1 Catálogo común de causas (base para H03 y H10)
1. Reemplazar los `choices` de `OrdenTrabajo.motivo_no_resuelto` por un modelo
   `operaciones.MotivoNoResolucion(codigo, nombre, atribucion)` con
   `atribucion ∈ {tecnico, cliente, empresa/suministro, externo, a_investigar}`.
   Migración de datos que conserva los códigos actuales.
2. Valores iniciales (a validar con la empresa): `cliente_ausente → cliente`,
   `direccion → cliente`, `clima → externo`, `problema_red → externo`,
   `rechazo → a_investigar`, `falta_material → a_investigar` (puede ser un pedido no
   atendido), `otro → a_investigar`.
3. Campo `atribucion_confirmada` en la orden para que el supervisor confirme o corrija
   la atribución.
4. Un único módulo `core/criterios.py` que usen **tanto** `capacitacion/evaluacion.py`
   como `tablero/metricas.py` (IPT/IGS) para decidir qué cuenta como falla del técnico.

### 3.2 H03 — La calidad no penaliza clientes ausentes
- `capacitacion/evaluacion.py`: `fallidas` pasa a contar solo órdenes con atribución
  `tecnico` (confirmada o por catálogo). Las `a_investigar` se muestran aparte y no
  restan.
- `tablero/metricas.py`: misma función de clasificación.
- Aceptación (escenario de la revisión): dos técnicos con 5 trabajos exitosos; uno con
  5 fallidas por cliente ausente → ambos con calidad 100 y "Adecuado".

### 3.3 H04 — Efectividad de acciones correctivas
**Problema:** `tablero/metricas.py` (≈ líneas 289–298) cuenta como efectiva una acción sin
nuevo desvío en 30 días, aunque no se haya cumplido ni controlado después.

Tareas:
1. `supervision.AccionCorrectiva`: estados `indicada → ejecutada (cumplida=True, fecha)
   → verificada (control posterior)` y resultado `efectiva / no efectiva / no verificado`.
2. Recalcular `efectividad_correccion`:
   - entran al cálculo solo acciones **cumplidas**;
   - "efectiva" exige al menos N controles posteriores (parámetro, p. ej. 2) en los 30
     días siguientes sin desvío **del mismo tipo de problema**;
   - sin controles suficientes → "no verificado" (se informa aparte, no suma).
3. Agregar `tipo_desvio` a `InformeControl` para medir recurrencia del problema pertinente.
4. Mostrar en el tablero: indicadas / ejecutadas / verificadas / efectivas.

Aceptación: tres acciones de hace 40 días sin cumplir y sin controles → efectividad
"sin dato" (no 100 %), y aparecen como "no verificadas".

### 3.4 H09 — Diagnósticos con evidencia suficiente
1. Umbrales mínimos por dimensión en `core.Parametros` (p. ej. ≥ 10 jornadas y ≥ 20
   órdenes para productividad; ≥ 2 controles para calidad).
2. Nuevo diagnóstico `SIN_EVIDENCIA = "Sin evidencia suficiente"`; los puntajes de una
   dimensión sin datos quedan en `None` y se muestran como "—", no como número.
3. Separar formación de sanción: `recapacitacion` y `charla` con peso 0 en disciplina
   (dimensión "Formación recibida" aparte), si la empresa lo confirma.
4. Versionar criterios: modelo `CriterioEvaluacion(version, pesos, umbrales, vigente_desde)`;
   cada `EvaluacionHistorica` guarda la versión usada.
5. Unificar con IPT/IGS el tratamiento de valores faltantes (mismo criterio en ambos motores).
6. Textos en pantalla: "índice orientativo, no es una probabilidad de riesgo"; el
   diagnóstico "Riesgo alto – evaluar desvinculación" se renombra a algo como
   "Requiere revisión del supervisor" hasta validar los pesos con la empresa.
7. Evaluación retrospectiva: comando que recalcula evaluaciones pasadas con la versión
   nueva y compara contra lo que pasó realmente (para calibrar pesos con la empresa).

Aceptación: persona con 0 jornadas y 0 órdenes → "Sin evidencia suficiente", sin puntajes.

---

## Fase 4 — Finanzas completas (H07)

Requiere las respuestas 1–3 de la fase 0.

1. **Corregir el requisito**: `docs/REQUERIMIENTOS.md` y docstring de
   `finanzas/proyeccion.py` ("flujo solo de salida").
2. **Ingresos y cuentas por cobrar:** modelos `Ingreso` (cliente pagador —Claro—,
   período, concepto, monto devengado, fecha esperada de cobro) y `Cobro` (ingreso,
   fecha, monto, cuenta). Opcional: generar la liquidación esperada de Claro a partir
   de las órdenes completadas y su baremo (si la empresa lo confirma), y conciliarla con
   la liquidación real (débitos por calidad, retenciones).
3. **Pagos parciales y cuotas:** modelo `Pago(egreso, fecha, monto, medio, cuenta)`;
   `Egreso.pagado` y `fecha_pago` pasan a ser **calculados** (saldo = monto − pagos).
   `PlanCuotas(egreso o deuda, cantidad, vencimientos)`. Migración: cada egreso con
   `pagado=True` genera un `Pago` por el total en `fecha_pago`.
4. **Deudas:** `Deuda` (acreedor, capital, interés, plan de cuotas) para préstamos y
   planes fiscales; alternativas de pago = comparar planes (contado vs. cuotas) con su
   costo financiero.
5. **Caja:** `Cuenta` (banco/efectivo) con saldo inicial; `MovimientoCaja` derivado de
   cobros y pagos. Proyección por fecha: saldo inicial + cobros esperados − pagos
   comprometidos (vencimientos, cuotas, sueldos, costos fijos) + presupuesto no
   comprometido marcado como estimado.
6. **Separar tres capas** en pantallas y reportes: presupuesto (plan), obligación
   devengada (egreso/ingreso) y movimiento efectivo (pago/cobro).
7. Exportar las nuevas tablas a las vistas de Power BI.

Aceptación:
- Un egreso de 1.000 con dos pagos de 400 queda con saldo 200 y "parcialmente pagado".
- La proyección de caja muestra saldo diario/semanal con ingresos y egresos.
- Los egresos existentes migran sin cambiar los totales históricos.

---

## Fase 5 — Historia operacional y abastecimiento (P2)

### 5.1 H10 — Intentos y asignaciones históricas
1. Modelo `operaciones.Intento(orden, numero, tecnico, supervisor_en_ese_momento, fecha,
   resultado, motivo, minutos, materiales…)`. Los datos de cierre que hoy están en
   `OrdenTrabajo` pasan a cada intento; la orden queda con el estado resumido.
2. `MovimientoStockTecnico` y `Salida` de consumo se asocian al intento.
3. `core.AsignacionSupervisor(tecnico, supervisor, desde, hasta)` y, si corresponde,
   `Cuadrilla(integrantes, desde, hasta)`. `Persona.supervisor` sigue como dato actual,
   pero los indicadores de períodos pasados usan la tabla histórica.
4. Migración de datos: un intento por cada orden con fecha de ejecución; una
   asignación de supervisor vigente desde la fecha de ingreso.
5. Adaptar evaluación, métricas e IPT/IGS para leer intentos y la composición histórica.

Aceptación: reasignar una orden fallida a otro técnico conserva el intento fallido en
el historial del primero; cambiar el supervisor de un técnico no cambia los indicadores
del supervisor anterior en meses pasados.

### 5.2 H08 — Previsión de compras con suministro reconciliado
**Problema:** `inventario/services.py`, `prevision_materiales()` usa
`material.stock_actual` (solo depósito); `stock_diario()` sí suma técnicos.

1. Una sola función `suministro_disponible(material, horizonte)` = depósito +
   stock utilizable en técnicos − reservado para sus órdenes del horizonte
   (`faltante_para_ordenes`) + entregas confirmadas de proveedores.
2. `prevision_materiales()` y `stock_diario()` usan esa función y muestran el desglose
   (depósito / técnicos libre / técnicos comprometido / en camino).
3. Demanda: órdenes asignadas + `DemandaComercial` sin contar dos veces lo que ya es orden.
4. Marcar la previsión como **sugerencia** que requiere aprobación antes de pedir.

Aceptación (escenario de la revisión): 10 unidades libres en un técnico, 0 en depósito,
necesidad de 10 → faltante 0; si esas 10 están reservadas para órdenes del técnico →
faltante 10.

---

## Fase 6 — Validación integral

1. Suite completa en **PostgreSQL** (CI de la fase 0), incluidas migraciones `powerbi`.
2. `docker compose up` con el Caddyfile nuevo: comprobar que `/media/...` no responde
   sin sesión y que la descarga protegida funciona.
3. Pruebas de navegador con Playwright (ya disponible en el entorno) por rol:
   gerencia, supervisor, técnico, depósito, contabilidad.
4. Ciclo offline completo: sin red → carga → error del servidor → reintento → éxito;
   cierre de sesión y cambio de cuenta con pendientes.
5. Datos de volumen: generar con el demo un año de operación y medir tiempos de
   tablero, evaluación y previsión (objetivo: < 2 s por pantalla).
6. Actualizar `docs/MANUAL.md`, `docs/METRICAS.md` (definiciones nuevas de calidad,
   efectividad, suficiencia) y `docs/BITACORA.md`.

---

## Orden de entrega sugerido (PRs)

Cada ítem es un PR chico, con su test de regresión:

1. Fase 0.1 + 0.2 (test frágil, CI en PostgreSQL)
2. H01 archivos privados
3. H05 importación sin reapertura + registro de importaciones
4. H06 sincronización offline idempotente
5. H02 devoluciones + trazabilidad de lotes (+ comando de recálculo)
6. Custodia de herramientas/EPP sin egresos repetidos
7. Catálogo de causas + H03
8. H04 efectividad de acciones
9. H09 suficiencia de evidencia y versión de criterios
10. H07 pagos parciales (migración de `pagado`)
11. H07 ingresos, cobros, cuentas y proyección de caja
12. H10 intentos y asignaciones históricas
13. H08 previsión con suministro reconciliado
14. Fase 6: pruebas integrales y documentación

## Fuera de alcance de este plan
- Cambio de stack: la revisión concluye que no es necesario.
- Integración con Oracle: sigue siendo carga e importación de archivos.
