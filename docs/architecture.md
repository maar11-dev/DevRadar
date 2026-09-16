# Arquitectura

## Visión general

DevRadar es un pipeline ELT (Extract-Load-Transform) orientado a analizar la demanda de tecnologías en el mercado laboral. Se ha diseñado deliberadamente **sin infraestructura propia**: todos los componentes corren en servicios gestionados o gratuitos, orquestados desde GitHub Actions.

## Diagrama de flujo

```mermaid
flowchart LR
    A[Fuente de ofertas de empleo] -->|scraping / API| B[Raw storage]
    B --> C[Extracción de skills con LLM - Groq]
    C --> D[(DuckDB)]
    D --> E[dbt: staging]
    E --> F[dbt: intermediate]
    F --> G[dbt: marts]
    G --> H[Dashboard Streamlit]
    I[GitHub Actions - cron diario] -.orquesta.-> A
    I -.orquesta.-> C
    I -.orquesta.-> E
```

## Componentes

### 1. Ingesta (`src/ingest.py`)
Obtiene ofertas de empleo de la fuente configurada (API o scraping respetuoso: `robots.txt`, límite de frecuencia de peticiones, caché en disco para evitar reprocesar ofertas ya vistas). El resultado crudo se guarda tal cual en una tabla `raw_ofertas` de DuckDB, sin transformar, para preservar la trazabilidad del dato original.

### 2. Extracción de entidades con LLM (`src/extract.py`)
Cada oferta pasa por un LLM (Groq por defecto; Ollama local soportado como alternativa para desarrollo offline) con un prompt estructurado que devuelve JSON con:
- Tecnologías mencionadas en el título o la descripción (dbt las normaliza después contra el catálogo controlado, ver ADR-009)
- Nivel de seniority (junior / mid / senior, si es inferible)
- Modalidad (remoto / híbrido / presencial)
- Rango salarial, si aparece explícito

El resultado se guarda como `raw_ofertas_clasificadas`, manteniendo también el JSON crudo del LLM (del que dbt toma la lista de tecnologías) y la versión del prompt usada. Con `--reclasificar-sin-tecnologias` se vuelven a procesar las ofertas sin tecnologías de prompts anteriores.

### 3. Transformación con dbt (`dbt_project/`)

Estructura en tres capas, siguiendo convención estándar de dbt:

- **`staging`** (`stg_ofertas`): limpieza básica — normalización de fechas, tipado de columnas, deduplicado por ID de oferta y de anuncios repetidos con el mismo título y empresa (ADR-011), lista cruda de tecnologías del LLM (ADR-009) y salario del LLM o, si no hay, el de Adzuna en rango anual plausible (ADR-010).
- **`intermediate`** (`int_tecnologias_por_oferta`): "explota" el array de tecnologías detectadas por oferta en una fila por combinación (oferta, tecnología) y lo normaliza contra el seed `catalogo_tecnologias`, de modo que los cambios del catálogo se aplican a todas las ofertas en el siguiente `dbt build`.
- **`marts`**:
  - `demanda_tecnologias_mensual`: nº y % de ofertas que mencionan cada tecnología, por mes (el % se calcula sobre las ofertas con al menos una tecnología detectada, ver ADR-007).
  - `salarios_por_tecnologia`: media/mediana salarial cuando el dato existe (extraído por el LLM o publicado por Adzuna, ver ADR-010).
  - `tendencia_modalidad`: evolución de remoto/híbrido/presencial en el tiempo.
  - `cobertura_extraccion_mensual`: ofertas clasificadas y % sin ninguna tecnología detectada, por mes.

### 4. Orquestación (`.github/workflows/pipeline.yml`)
Un workflow de GitHub Actions con `schedule: cron` ejecuta a diario (ADR-012), en orden: restauración de la base desde la rama `data` → ingesta → extracción LLM → `dbt seed` → `dbt run` → `dbt test` → publicación de la base en la rama `data`. Si algún test de dbt falla, el workflow falla y no se publican los datos nuevos, evitando que el dashboard muestre información inconsistente. La publicación solo hace commit si el contenido de la base ha cambiado (ADR-008).

### 5. Visualización (`dashboard/app.py`)
Streamlit lee directamente los marts de DuckDB (en local, `DBT_DUCKDB_PATH` o `data/devradar.duckdb`; desplegado en Streamlit Community Cloud, la base publicada en la rama `data`, ver ADR-008) y expone:
- Ranking de tecnologías más demandadas, filtrable por rango de fechas.
- Evolución temporal de una tecnología concreta.
- Comparativa de modalidad de trabajo y salarios cuando el dato está disponible.

## Modelo de datos (resumen)

| Tabla | Capa | Grano |
|---|---|---|
| `raw_ofertas` | raw | 1 fila = 1 oferta cruda |
| `raw_ofertas_clasificadas` | raw | 1 fila = 1 oferta + JSON del LLM |
| `stg_ofertas` | staging | 1 fila = 1 oferta limpia |
| `int_tecnologias_por_oferta` | intermediate | 1 fila = (oferta, tecnología) |
| `demanda_tecnologias_mensual` | marts | 1 fila = (tecnología, mes) |
| `salarios_por_tecnologia` | marts | 1 fila = (tecnología, mes) |
| `tendencia_modalidad` | marts | 1 fila = (modalidad, mes) |
| `cobertura_extraccion_mensual` | marts | 1 fila = mes |

## Consideraciones de escalabilidad

El volumen esperado (cientos de ofertas al día) no justifica herramientas de procesamiento distribuido: DuckDB gestiona sin problema varios millones de filas en una sola máquina. Si el volumen creciera significativamente, el punto de migración natural sería sustituir DuckDB por BigQuery o Snowflake manteniendo los mismos modelos dbt (cambio de adaptador, no de lógica).