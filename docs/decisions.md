# Registro de decisiones técnicas (ADR)

Este documento recoge las decisiones de diseño relevantes del proyecto, el contexto en el que se tomaron y las alternativas consideradas. El objetivo es que cualquier persona que revise el repo entienda el *por qué*, no solo el *qué*.

---

## ADR-001: DuckDB como motor analítico, en lugar de PostgreSQL

**Contexto**: El proyecto necesita un almacén analítico para las transformaciones dbt, pero no se dispone de un servidor propio ni de Docker para levantar una base de datos gestionada.

**Decisión**: Usar DuckDB (archivo local embebido) con el adaptador `dbt-duckdb`.

**Alternativas consideradas**:
- PostgreSQL/PostGIS: requiere un servidor gestionado (coste) o Docker (no disponible en este entorno).
- BigQuery/Snowflake: viable pero añade dependencia de cuenta cloud y gestión de credenciales adicional para un proyecto de portfolio.

**Consecuencias**: El archivo `.duckdb` **no se versiona** (está en `.gitignore`): se regenera en cada corrida del pipeline a partir de la ingesta y las transformaciones de dbt, por lo que no hay conexión persistente que mantener ni riesgo de subir datos reales al repositorio. Si el proyecto creciera en volumen o usuarios concurrentes, sería el primer componente a migrar.

---

## ADR-002: Groq como proveedor de LLM por defecto, con Ollama como alternativa local

**Contexto**: Se necesita clasificar y extraer entidades de las ofertas de empleo mediante un LLM, dentro de un pipeline que se ejecuta de forma automática en GitHub Actions (sin GPU disponible).

**Decisión**: Usar la API de Groq como proveedor por defecto en producción; mantener soporte para Ollama local como alternativa para desarrollo y pruebas offline.

**Alternativas consideradas**:
- Ollama en GitHub Actions: descartado, los runners no tienen GPU y el procesamiento sería demasiado lento para un cron automatizado.
- Ejecutar el LLM manualmente en máquina local: descartado por romper la automatización completa del pipeline, objetivo central del proyecto.

**Consecuencias**: Se introduce una dependencia externa (API key de Groq, gestionada como secret) y un límite de peticiones gratuitas a vigilar. A cambio, el pipeline es 100% autónomo.

---

## ADR-003: GitHub Actions como orquestador, en lugar de Airflow

**Contexto**: Se necesita programar la ejecución periódica del pipeline sin infraestructura propia.

**Decisión**: Usar GitHub Actions con un trigger `schedule` (cron).

**Alternativas consideradas**:
- Apache Airflow: requiere un servidor o contenedor donde correr el scheduler, no viable en este entorno sin Docker.
- Airflow gestionado (MWAA/Cloud Composer): añade coste y complejidad desproporcionados para el volumen del proyecto.

**Consecuencias**: Se pierde la gestión de dependencias entre tareas más rica de Airflow (DAGs complejos, reintentos configurables por tarea, pools), pero se gana simplicidad y coste cero. Para un pipeline lineal como este, es suficiente.

---

## ADR-004: dbt para las transformaciones, en lugar de scripts SQL sueltos

**Contexto**: Las transformaciones podrían escribirse como scripts SQL ejecutados directamente contra DuckDB.

**Decisión**: Usar dbt-core para modelar las transformaciones en capas (staging/intermediate/marts) con tests declarativos.

**Alternativas consideradas**:
- Scripts SQL + Python: más rápido de escribir inicialmente, pero sin control de dependencias entre modelos, sin tests integrados y sin documentación autogenerada.

**Consecuencias**: Se añade una curva de aprendizaje inicial (estructura de proyecto dbt, `ref()`, `sources`), pero se gana trazabilidad de linaje (`dbt docs generate`), tests de calidad de datos versionados junto al código, y una estructura que escala mejor si se añaden más fuentes de datos.

---

## ADR-005: Streamlit para el dashboard, en lugar de Metabase

**Contexto**: Se necesita una capa de visualización final sobre los marts de dbt.

**Decisión**: Usar Streamlit.

**Alternativas consideradas**:
- Metabase Cloud (tier gratuito): más rápido de configurar para dashboards estándar, pero menos flexible para visualizaciones personalizadas y no demuestra habilidad de desarrollo Python.
- Looker Studio: requiere conectores específicos y cuenta de Google Cloud.

**Consecuencias**: Requiere más código propio que una herramienta de BI, pero permite total control sobre la interacción y demuestra capacidad de construir la capa de presentación además del pipeline de datos.