# CaféNorte - Reto Técnico de Data Solutions Engineer

Pipeline de datos que consolida las ventas físicas (POS) y de e-commerce (Shopify) de CaféNorte, el inventario físico, catálogo y costos del ERP, y los tipos de cambio oficiales en un único modelo analítico. A partir de ese modelo se responden cuatro preguntas de negocio.

## 1. Resumen del proyecto

El pipeline integra cuatro fuentes:

| Fuente | Archivo | Descripción |
|---|---|---|
| Ventas físicas POS | `sales.csv` | Transacciones de punto de venta en 40 tiendas |
| Inventario / catálogo / costo del ERP | `inventory.json` | ERP legado: catálogo de productos, `sku_mappings`, registros diarios de inventario e historial de costos |
| Órdenes de e-commerce | `ecommerce_orders.parquet` | Órdenes de Shopify |
| Tipos de cambio | `exchange_rates.csv` | Tipos de cambio diarios usados para normalizar a MXN los ingresos de e-commerce en otras monedas |

`exchange_rates.csv` no aparece entre las tres fuentes descritas en la narrativa original del reto, pero el responsable del reto confirmó que forma parte del material oficial. Esta solución lo utiliza en Q3 para convertir a MXN las ventas de e-commerce registradas en USD o EUR.

**Tecnologías**

- Python 3.11
- pandas 3.0.2
- DuckDB 1.5.5
- pyarrow 25.0.1
- pytest 9.1.1

El volumen suministrado es pequeño/mediano para un flujo analítico local: la tabla más grande tiene aproximadamente 230 mil filas y el objetivo es responder cuatro consultas de negocio, no operar un servicio en tiempo real. DuckDB permite ejecutar SQL analítico dentro del mismo proceso sin añadir infraestructura distribuida innecesaria para el alcance del reto.

## Estructura del repositorio

```text
cafenorte-data-challenge/
├── data/
│   ├── raw/            # archivos fuente del reto (excluidos de Git)
│   └── processed/      # cafenorte.duckdb (generado, excluido de Git)
├── docs/
│   └── aws_proposal.md          # propuesta de arquitectura AWS
├── scripts/
│   ├── run_pipeline.py             # punto de entrada por línea de comandos
│   └── validate_data_assumptions.py
├── src/
│   ├── load.py                     # carga de fuentes
│   ├── reconcile.py                # conciliación de identificadores de producto
│   ├── transform.py                # construcción del modelo analítico
│   ├── business_questions.py       # consultas Q1-Q4 en DuckDB
│   └── pipeline.py                 # orquestación y persistencia
├── tests/
│   ├── test_reconciliation.py
│   ├── test_transformations.py
│   └── test_business_questions.py
├── AI_LOG.md
├── README.md
└── requirements.txt
```

## 2. Cómo ejecutar

Coloca estos cuatro archivos en `data/raw/`:

- `sales.csv`
- `inventory.json`
- `ecommerce_orders.parquet`
- `exchange_rates.csv`

Después, desde la raíz del repositorio:

```bash
pip install -r requirements.txt
python scripts/run_pipeline.py
python -m pytest -q
```

`scripts/run_pipeline.py` reconstruye `data/processed/cafenorte.duckdb` de principio a fin a partir de las fuentes: carga, conciliación, transformación y persistencia.

La solución se validó también desde una clonación limpia del repositorio. La suite completa termina con **41 pruebas aprobadas (`41 passed`)**.

## 3. Flujo del pipeline

```text
load_sources()                              (src/load.py)
        ↓
build_product_bridge() + reconcile_*()      (src/reconcile.py)
        ↓
build_analytical_model()                    (src/transform.py)
        ↓
persist_analytical_model()  → cafenorte.duckdb   (src/pipeline.py)
        ↓
get_q1..q4_*()                              (src/business_questions.py)
```

`build_analytical_model()` produce seis tablas:

| Tabla | Granularidad | Filas |
|---|---|---:|
| `dim_product` | producto canónico (`product_id` = `sku_erp`) | 70 |
| `dim_store` | tienda física | 40 |
| `fact_sales` | una transacción física o de e-commerce | 96,437 (`physical`: 86,490; `ecommerce`: 9,947) |
| `fact_inventory` | tienda × producto × día | 230,776 |
| `fact_product_cost` | producto × fecha de vigencia del costo | 282 |
| `fact_exchange_rate` | fecha × moneda (USD/EUR) | 730 |

`fact_sales` conserva `amount_native` y `currency` por transacción. La conversión a MXN de las ventas de e-commerce en USD/EUR se realiza en Q3 mediante `fact_exchange_rate`.

## 4. Reconciliación de productos

`product_id` (`sku_erp`) es el identificador canónico de producto.

La conciliación en `src/reconcile.py` sigue esta prioridad:

1. **Mapeo explícito:** usa `inventory.json → sku_mappings`.
2. **Respaldo numérico:** solo cuando no existe un mapeo explícito y el componente numérico del identificador corresponde de forma única a un producto del ERP.
3. No se usa coincidencia difusa por nombre.

El método aplicado queda registrado en `dim_product` mediante `pos_mapping_method` y `shopify_mapping_method`, con los valores `explicit`, `inferred_numeric_pattern` o `not_observed`.

**Cobertura final**

- 70 de 70 SKUs de POS reconciliados con un `sku_erp`.
- 0 ventas físicas sin reconciliar.
- Los 33 productos de Shopify observados se reconcilian con un `sku_erp`.

La conciliación de Shopify permite identificar qué producto se vendió, pero no qué inventario surtió la orden. Esa diferencia es relevante para Q1.

## 5. Pregunta de negocio 1 - Rotación de inventario

*Top 10 SKUs por rotación de inventario en los últimos 6 meses.*

- **Período:** del 2025-10-01 al 2026-03-31, ambas fechas incluidas.
- **Alcance:** tiendas físicas. Solo participan ventas de pares tienda-SKU que también tienen una serie de inventario observable durante el período.
- **Fórmula:** `inventory_turnover = physical_units_sold_from_inventory_observable_store_product_pairs / average_inventory_units`
- **Inventario:** para cada par tienda-SKU con registros de inventario en el período, se promedian únicamente las lecturas numéricas. El valor `0` sí participa en el promedio; `N/A`/`NULL` no se reemplaza por cero ni se interpola. Después se suman los promedios de tienda a nivel de SKU.
- **Ventas físicas:** solo se incluyen las unidades vendidas de pares tienda-SKU con inventario observable. No se estima inventario para los pares que tienen ventas pero no una serie de inventario.
- **E-commerce:** no participa en Q1. Durante el período se vendieron 6,627 unidades por e-commerce, pero la fuente no identifica qué tienda, almacén u origen de inventario surtió esas órdenes. Sumarlas al numerador implicaría compararlas contra inventario físico de tiendas sin una relación demostrada.
- **`tipo_comprobante`:** los códigos I, E, P, N y T se cuentan tal como fueron registrados, sin filtrar ni invertir el signo.

Las letras de `tipo_comprobante` coinciden con códigos usados en el catálogo CFDI del SAT, pero los datos de CaféNorte no demuestran que esa sea su semántica. En los datos suministrados, los cinco códigos tienen cantidades y montos positivos y no muestran un patrón que permita identificar devoluciones, cancelaciones o ajustes. Por ello se conservan tal como llegan.

**Cobertura del cálculo:** de 44,336 unidades físicas vendidas durante el período, 20,318 (45.83%) corresponden a pares tienda-SKU con una serie de inventario observable y participan en Q1. Las 24,018 restantes (54.17%) corresponden a pares sin una serie de inventario observable y quedan fuera de este cálculo. Esta ausencia no se interpreta como desabasto, error de extracción ni falta de inventario, porque los datos suministrados no permiten determinar su causa.

El resultado representa rotación de inventario de tiendas físicas, no una rotación omnicanal ni de toda la compañía.

**Resultado final:**

| Rank | product_id | physical_units_sold | avg_inventory_units | inventory_turnover |
|---|---|---:|---:|---:|
| 1 | ERP-PROV-MX-068-C | 369 | 710.32 | 0.519482 |
| 2 | ERP-PROV-MX-015-D | 340 | 684.12 | 0.496989 |
| 3 | ERP-PROV-MX-049-A | 365 | 742.47 | 0.491602 |
| 4 | ERP-PROV-MX-047-B | 343 | 713.32 | 0.480849 |
| 5 | ERP-PROV-MX-067-C | 336 | 720.83 | 0.466130 |
| 6 | ERP-PROV-MX-036-A | 315 | 684.53 | 0.460167 |
| 7 | ERP-PROV-MX-012-B | 241 | 525.94 | 0.458228 |
| 8 | ERP-PROV-MX-059-B | 326 | 726.95 | 0.448451 |
| 9 | ERP-PROV-MX-069-C | 317 | 719.08 | 0.440838 |
| 10 | ERP-PROV-MX-053-A | 291 | 665.03 | 0.437576 |

## 6. Pregunta de negocio 2 - Desabastos de más de 3 días

*Tiendas con desabastos de más de 3 días en el último trimestre.*

- **Período:** del 2026-01-01 al 2026-03-31.
- **Día con desabasto confirmado:** `stock_quantity = 0`.
- **Evento reportado:** al menos 4 días calendario consecutivos con inventario confirmado en cero.
- **`N/A`:** el inventario de ese día es desconocido. Como el evento requiere días consecutivos con inventario confirmado en cero, un `N/A` corta la secuencia.
- Los resultados se reportan por tienda y SKU.

**Resultado final:**

| store_id | product_id | stockout_start | stockout_end | stockout_days |
|---|---|---|---|---:|
| T015 | ERP-PROV-MX-014-D | 2026-02-09 | 2026-02-12 | 4 |
| T023 | ERP-PROV-MX-046-A | 2026-01-25 | 2026-01-28 | 4 |
| T038 | ERP-PROV-MX-040-A | 2026-03-18 | 2026-03-21 | 4 |

## 7. Pregunta de negocio 3 - Crecimiento mensual de ingresos por canal

*Crecimiento mes a mes (MoM) de ventas por canal físico vs. e-commerce en el último año.*

- **Ventas:** se interpreta como ingresos.
- **Período:** 2025-04 a 2026-03.
- **Moneda:** las ventas físicas ya están en MXN. Las ventas de e-commerce en USD/EUR se convierten con `amount_mxn = amount * rate_to_mxn`, usando fecha de transacción + moneda. Se verificó que no existan transacciones USD/EUR sin un tipo de cambio correspondiente.
- **MoM:** `(current_month - previous_month) / previous_month * 100`.
- **Abril de 2025:** el MoM físico usa marzo de 2025 como base. El MoM de e-commerce es `N/A` porque la fuente suministrada no contiene observaciones anteriores a abril de 2025; esto no implica que Shopify haya comenzado a operar en esa fecha.

**Resultado final:**

| month | channel | sales_mxn | mom_pct |
|---|---|---:|---:|
| 2025-04 | ecommerce | 383,213.10 | N/A |
| 2025-04 | physical | 1,673,072.00 | -2.38 |
| 2025-05 | ecommerce | 365,088.20 | -4.73 |
| 2025-05 | physical | 1,796,953.00 | 7.40 |
| 2025-06 | ecommerce | 339,352.30 | -7.05 |
| 2025-06 | physical | 1,712,535.00 | -4.70 |
| 2025-07 | ecommerce | 350,578.50 | 3.31 |
| 2025-07 | physical | 1,790,212.00 | 4.54 |
| 2025-08 | ecommerce | 343,799.80 | -1.93 |
| 2025-08 | physical | 1,778,834.00 | -0.64 |
| 2025-09 | ecommerce | 345,453.80 | 0.48 |
| 2025-09 | physical | 1,684,031.00 | -5.33 |
| 2025-10 | ecommerce | 376,497.20 | 8.99 |
| 2025-10 | physical | 1,817,582.00 | 7.93 |
| 2025-11 | ecommerce | 359,337.60 | -4.56 |
| 2025-11 | physical | 1,680,699.00 | -7.53 |
| 2025-12 | ecommerce | 346,649.20 | -3.53 |
| 2025-12 | physical | 1,778,998.00 | 5.85 |
| 2026-01 | ecommerce | 344,899.10 | -0.50 |
| 2026-01 | physical | 1,713,210.00 | -3.70 |
| 2026-02 | ecommerce | 323,250.60 | -6.28 |
| 2026-02 | physical | 1,576,722.00 | -7.97 |
| 2026-03 | ecommerce | 350,763.40 | 8.51 |
| 2026-03 | physical | 1,718,189.00 | 8.97 |

## 8. Pregunta de negocio 4 - Productos con margen negativo por tienda

*Productos con margen negativo y las tiendas donde ocurre.*

- **Período:** historial completo de ventas físicas, del 2024-10-01 al 2026-03-31.
- **Supuesto metodológico:** `costo_mxn` se interpreta como costo unitario del producto. La fuente no lo especifica explícitamente.
- **Costo aplicable:** para cada venta se usa la fila más reciente de `cost_history` cuya `fecha_vigencia` sea menor o igual a la fecha de la venta.
- **Cálculo:** costo de la transacción = `cantidad * costo_mxn`; margen = `monto - costo`.
- **Agregación:** tienda + SKU. Una combinación se reporta cuando `margin_mxn < 0`.
- **Cobertura:** 70/70 SKUs de POS reconciliados y 86,490/86,490 ventas físicas con un costo aplicable.

**Resultado:** se identificaron 3 SKUs con margen agregado negativo en cada una de las 40 tiendas, es decir, 120 combinaciones tienda-SKU. Los dos primeros SKUs comparten el mismo `product_name` en el catálogo, pero se mantienen separados porque tienen identificadores `sku_erp` distintos.

| sku_erp | product_name | Tiendas con margen negativo |
|---|---|---|
| ERP-PROV-MX-001-A | Sándwich Comida Caliente | Todas las tiendas (`T001` a `T040`) |
| ERP-PROV-MX-002-B | Sándwich Comida Caliente | Todas las tiendas (`T001` a `T040`) |
| ERP-PROV-MX-015-D | Especial Cafe Molido | Todas las tiendas (`T001` a `T040`) |

`get_q4_negative_margin()` devuelve el detalle completo de las 120 combinaciones con `store_id`, `sku_erp`, `product_name`, `revenue_mxn`, `cost_mxn`, `margin_mxn` y `margin_pct`.

## 9. Supuestos y limitaciones

| # | Enunciado | Tipo |
|---|---|---|
| A1 | La fuente no define la semántica de `tipo_comprobante`; los códigos I/E/P/N/T se conservan tal como fueron registrados. | Interpretación metodológica |
| A2 | `costo_mxn` se interpreta como costo unitario del producto para Q4. | Interpretación metodológica |
| A3 | Q1 solo usa ventas físicas de pares tienda-SKU con una serie de inventario observable; 24,018 de 44,336 unidades físicas (54.17%) quedan fuera del cálculo por no cumplir esa condición. | Limitación |
| A4 | Un `N/A` de inventario se trata como valor desconocido, no como cero. No se interpola ni se sustituye por cero. | Interpretación metodológica |
| A5 | Q1 excluye 6,627 unidades de e-commerce porque la fuente no identifica el origen de inventario que surtió esas órdenes. | Limitación metodológica |
| A6 | La fuente de e-commerce no contiene observaciones anteriores al 2025-04-01; esto no permite inferir cuándo comenzó a operar Shopify. | Limitación |

## 10. Pruebas y reproducibilidad

```bash
python scripts/run_pipeline.py
python -m pytest -q
```

Se validó una reconstrucción limpia desde los archivos fuente:

- Los resultados de Q1, Q2, Q3 y Q4 se reprodujeron exactamente.
- La suite completa termina con **41 pruebas aprobadas (`41 passed`)**.
