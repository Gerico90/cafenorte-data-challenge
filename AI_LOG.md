# AI_LOG

## Propósito

Este documento registra cómo se usaron herramientas de IA durante el desarrollo del reto técnico de Data Solutions Engineer para CaféNorte: qué se pidió, qué respondió la IA, qué decisión tomé con cada respuesta y por qué. La responsabilidad final sobre el pipeline, las definiciones de negocio y los resultados publicados en README.md es mía.

---

## 1. Herramientas utilizadas

- **Claude Code**, en una sesión principal de orquestación (modelo/versión no registrado de forma verificable) que delegó tareas acotadas a subagentes especializados de solo lectura, cada uno con mandato de independent agent review sobre un aspecto distinto del pipeline o de la definición de negocio:
  - **Workflow Architect** — auditoría independiente de la base de datos/pipeline, y resolución final de la definición de Q1.
  - **Data Engineer** — segunda revisión independiente de la base de datos, ingesta y reconciliación.
  - **Supply Chain Strategist** — revisión de la definición de negocio de "rotación de inventario" para Q1.
  - **Analytics Reporter** — revisión adversarial/independiente de la propuesta anterior.
- **ChatGPT**, usado como apoyo de razonamiento y planeación general del reto (separación de entregables, secuencia de trabajo). Modelo/versión no registrado de forma verificable; no se afirma una versión específica.

No se listan otros agentes especializados (p. ej. Code Reviewer, Project Manager) porque no hay evidencia en el historial del proyecto de que hayan sido invocados para este reto.

---

## 2. Flujo de trabajo / orquestación

La sesión principal (yo, como responsable de decisión) actuó como orquestador: nunca aceptó una conclusión de negocio de un subagente solo porque el código corriera o los tests pasaran. El patrón seguido, de forma consistente en las decisiones ambiguas, fue:

**hecho observado → interpretación → decisión metodológica → implementación → tests → validación de reconstrucción limpia.**

Para las decisiones donde la semántica de negocio era ambigua (agregación de inventario en Q1, tratamiento de `N/A`, inclusión de Shopify, `tipo_comprobante`, margen en Q4), se comisionaron revisiones independientes de segunda opinión a un tipo de agente distinto del que produjo la primera propuesta, con mandato explícito de cuestionarla en lugar de confirmarla. En al menos dos casos documentados (inclusión de Shopify en Q1, y una verificación posterior de cobertura de reconciliación para Q4) la primera conclusión resultó incorrecta y fue revertida por evidencia nueva, no aceptada por defecto (ver sección 4).

No se narra aquí la secuencia completa de todas las revisiones internas realizadas durante el desarrollo; se documentan solo los prompts y decisiones más representativos.

---

## 3. Prompts clave

### Prompt 1 — Fundamento de datos y reconciliación de producto

**Prompt (resumen del mandato encomendado, independent agent review):**
Auditoría independiente y de solo lectura del pipeline de datos (`src/load.py`, `src/reconcile.py`, `src/transform.py`, `src/pipeline.py`), recalculando cada cifra directamente desde los archivos crudos y la base DuckDB persistida, sin modificar ningún archivo del repositorio.

**Resumen de la respuesta de la IA:**
Confirmó que el orden "explícito primero, numérico como fallback" sí estaba implementado en el código. Encontró que `exchange_rates.csv` existía en `data/raw/` pero no estaba documentado ni usado por el pipeline, pese a ser necesario para normalizar ingresos de e-commerce en moneda distinta a MXN. También identificó 4 filas de `sku_mappings` con `sku_erp` nulo que quedaban descartadas del bucket "explícito" y caían al fallback numérico.

**Mi acción:** ACEPTADO (para `exchange_rates.csv`) / registrado como limitación conocida (para las 4 filas con `sku_erp` nulo, sin cambiar el comportamiento porque el resultado numérico coincide).

**Por qué:** las cifras fueron recalculadas de forma independiente contra los archivos crudos, no tomadas de README/AI_LOG. `exchange_rates.csv` fue incorporado como fuente de primer nivel (ver README, sección 1) porque el dueño del reto confirmó que es material oficial requerido para Q3.

---

### Prompt 2 — Definición de "rotación de inventario" en Q1 (doble revisión independiente)

**Prompt (resumen del mandato encomendado, doble independent agent review):**
Se pidió una revisión de negocio (Supply Chain Strategist) sobre si la fórmula de rotación de inventario usada era defendible dado los datos reales, y después una segunda revisión (Analytics Reporter) con mandato de cuestionar de forma adversarial la primera, recalculando cada cifra desde cero contra la base DuckDB.

**Resumen de la respuesta de la IA:**
Ambas revisiones reprodujeron de forma independiente el mismo Top 10 y coincidieron en la fórmula (`unidades vendidas / inventario promedio`), pero la segunda revisión señaló que publicar el Top 10 sin advertir que 54.17% de las unidades físicas quedan fuera del cálculo (por no tener serie de inventario observable) sobreestimaría la precisión del resultado.

**Mi acción:** ACEPTADO, con la advertencia de cobertura incorporada como limitación explícita (ver README, sección 5 y A3).

**Por qué:** las dos revisiones llegaron al mismo número de forma independiente desde datos crudos; la discrepancia relevante no era numérica sino de qué debía divulgarse junto con el resultado.

---

### Prompt 3 — Evidencia sobre `tipo_comprobante`

**Prompt (resumen del mandato encomendado, targeted validation):**
Revisión enfocada únicamente en si los códigos I/E/P/N/T de `sales.csv.tipo_comprobante` debían filtrarse o invertirse en signo para Q1, buscando evidencia estadística, temporal o documental que distinguiera a E/P/N/T de una venta ordinaria.

**Resumen de la respuesta de la IA:**
No encontró ninguna señal (distribución de cantidad/monto, patrón horario, patrón por tienda/SKU, pares de reversión exacta) que distinguiera a E/P/N/T de I. Recomendó contar los cinco códigos como registrados, sin filtrar ni invertir signo, dejando el estatus semántico como abierto para autoridad externa.

**Mi acción:** ACEPTADO.

**Por qué:** la ausencia de evidencia para una interpretación alternativa es, en sí, evidencia suficiente para no introducir una regla de negocio no soportada por los datos (principio ya aplicado en A7 de README).

---

### Prompt 4 — Validación de reproducibilidad end-to-end

**Prompt (excerpt):**
Reconstruir `cafenorte.duckdb` desde cero a partir de las cuatro fuentes crudas (`sales.csv`, `inventory.json`, `ecommerce_orders.parquet`, `exchange_rates.csv`) y confirmar que Q1–Q4 y la suite de pytest se reproducen exactamente como están documentados en README.

**Resumen de la respuesta de la IA:**
Ejecución de `scripts/run_pipeline.py` seguida de `pytest -q` contra la base recién reconstruida; confirmó 36 tests pasando y los cuatro resultados de negocio (Q1–Q4) idénticos a los publicados.

**Mi acción:** ACEPTADO — usado como el gate final antes de considerar cualquier resultado como definitivo.

**Por qué:** cierra el ciclo entre lo documentado y lo que el pipeline realmente produce desde una reconstrucción limpia; no se encontró ninguna discrepancia.

---

## 4. Caso de error de IA (obligatorio)

### Caso principal — premisa incorrecta sobre e-commerce y tienda física (Q1, Shopify)

De forma repetida, la IA introdujo la premisa de que las órdenes de e-commerce debían poder asignarse o conectarse a una tienda física para poder participar en Q1. Esa premisa contaminó el análisis de inclusión de Shopify y produjo, en una revisión independiente dedicada a este punto, una recomendación explícita de **excluir** las unidades de e-commerce del numerador de rotación de inventario, argumentando que no existe un "pool" de inventario e-commerce vinculable al inventario por tienda.

**Por qué era incorrecto:**
- Q1 pide el Top 10 de SKUs, no una atribución de e-commerce a nivel tienda.
- Los productos de e-commerce reconcilian de forma completa al SKU canónico (`sku_erp`); la identidad del producto no depende de una tienda.
- Los datos suministrados no contienen ningún requisito de modelar e-commerce como una tienda física.
- La ausencia de `store_id` en `ecommerce_orders.parquet` no demuestra por sí misma que el canal deba excluirse de un numerador definido a nivel SKU.

**Corrección:** la conclusión de la Auditoría 17 fue **rechazada**. E-commerce se trata como canal independiente; sus unidades participan en Q1 a nivel SKU (ver README, sección 5); no se realiza ninguna asignación a tienda física ni inferencia de punto de cumplimiento (fulfillment) para e-commerce.

Esta corrección se detectó por revisión humana de la granularidad analítica y de la evidencia de origen — no por un test unitario que fallara. Es un ejemplo claro de que el código y los tests pueden ser técnicamente correctos mientras la interpretación de negocio es incorrecta.

### Caso secundario — cobertura de reconciliación mal reportada (Q4)

En una revisión posterior orientada a Q4, un agente examinó únicamente las filas explícitas de `sku_mappings` y reportó 10/70 SKUs de POS sin mapear, contradiciendo la reconciliación canónica ya aceptada (explícito primero, con fallback numérico validado). Una verificación puntual con el agente Data Engineer, aplicando la misma jerarquía explícito-primero + fallback numérico ya validada, mostró 70/70 SKUs reconciliados y 0 filas sin reconciliar. La población corregida sacó a la luz un tercer SKU con margen negativo que la cifra errónea de cobertura había dejado fuera (ver README, sección 8: 3 SKUs, 40/40 tiendas cada uno).

Este segundo caso no quedó registrado en una revisión independiente separada; se documenta aquí como parte del historial de correcciones de esta sesión, no como cita de un documento adicional.

---

## 5. Prácticas de validación

- Perfilado de las fuentes a nivel de origen (conteos, esquemas, cardinalidades, nulos) recalculado de forma independiente contra los archivos crudos, no solo leído del código o de reportes previos.
- Revisiones independientes de agentes distintos para semántica ambigua (rotación de inventario, `N/A`, inclusión de Shopify, `tipo_comprobante`), con mandato de cuestionar la conclusión previa.
- Pruebas dirigidas a casos límite (valores `N/A` en inventario, pares tienda-SKU ausentes, códigos de `tipo_comprobante` distintos de I) antes de fijar el tratamiento definitivo.
- 36 tests de pytest pasando sobre la implementación final.
- Reconstrucción limpia (`scripts/run_pipeline.py`) desde las cuatro fuentes crudas, con Q1–Q4 reproducidos exactamente desde la base DuckDB recién generada.
- Ningún resultado analítico esperado está hardcodeado en la lógica de negocio (`src/business_questions.py`); los valores conocidos se usaron como objetivo de validación externo, no como parte del cálculo.

---

## 6. Autocrítica final

La IA aceleró de forma real el perfilado de fuentes, la exploración de definiciones alternativas, la implementación del pipeline, la generación de tests y la verificación independiente de cifras; sin ella, cubrir la profundidad de ambigüedades de negocio de este reto en el tiempo disponible no habría sido realista. Pero la corrección del resultado final no dependió de que el pipeline corriera o los tests pasaran, sino de decidir qué supuestos eran aceptables, cuestionar interpretaciones causales o de negocio que no tenían soporte en los datos suministrados, rechazar recomendaciones de IA cuando la evidencia no las sostenía (caso Shopify en Q1, cobertura de reconciliación en Q4) y fijar el alcance analítico final. No afirmo haber escrito todo el código a mano — gran parte de la implementación, los tests y las revisiones fueron asistidos por IA — pero la responsabilidad de que la interpretación de negocio coincidiera con la pregunta y con la evidencia disponible, y no solo con lo que técnicamente compilaba, fue mía.
