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

---

## ADR-006: API de Adzuna como fuente de ofertas, en lugar de scraping

**Contexto**: El pipeline necesita una fuente periódica y estable de ofertas de empleo tech. Las reglas del proyecto exigen, además, respetar `robots.txt`, limitar la frecuencia de peticiones, cachear en disco y reintentar con backoff exponencial.

**Decisión**: Obtener las ofertas de la API pública de [Adzuna](https://developer.adzuna.com/) (endpoint `jobs/{país}/search`), con España (`es`) como mercado por defecto. Las credenciales (`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`) se leen de variables de entorno y en Actions se inyectan como secrets.

**Alternativas consideradas**:
- Scraping con `requests` + BeautifulSoup de un portal de empleo: descartado. Hace depender el pipeline de `robots.txt` y de las condiciones de cada portal, que pueden prohibir el rastreo en cualquier momento, y de la estructura HTML, que cambia sin aviso y rompe el parser en silencio. Además, obliga a mantener selectores por cada fuente.
- Otras APIs de empleo: muchas exigen acuerdos comerciales o no cubren el mercado español con suficiente volumen.

**Consecuencias**:
- Datos estructurados y estables (id, título, empresa, fecha, ubicación, categoría), sin mantenimiento de parsers.
- Límites del plan gratuito: 25 peticiones/minuto, 250/día y 1000/semana. La ingesta limita el número de páginas por ejecución y espacia las peticiones.
- Los términos de uso permiten la investigación personal y exigen citar a Adzuna como fuente allí donde se publiquen los datos: el dashboard debe incluir esa atribución.
- `robots.txt`: `api.adzuna.com/robots.txt` prohíbe el rastreo a todos los agentes (`Disallow: /`). Se interpreta que `robots.txt` regula el rastreo de páginas web y no el acceso a una API oficial con credenciales, que se rige por sus términos de uso; se mantienen igualmente el límite de frecuencia, la caché en disco y los reintentos con backoff (ver `coding-rules.md`).
- La API devuelve solo los primeros 500 caracteres de la descripción, lo que puede reducir las tecnologías que detecta el LLM. Si resulta ser un problema, se valorará complementar con una segunda fuente (registrándolo en un ADR nuevo).
- Alcance por defecto de cada ejecución: categoría `it-jobs`, ofertas de los últimos 7 días, hasta 5 páginas de 50 resultados (unas 250 ofertas en 5 peticiones), ajustable por línea de comandos.
- Las URLs de las ofertas se guardan sin parámetros de seguimiento (`utm_*`), que incluyen el identificador de la aplicación; la base se publica como artefacto de Actions.
- Los salarios que publica Adzuna se guardan aparte en `raw_ofertas` (`salario_min_anunciado`, `salario_max_anunciado`), pero los marts usan solo el salario extraído por el LLM del texto de la oferta, para no mezclar estimaciones con datos explícitos.

---

## ADR-007: Porcentajes de demanda solo sobre ofertas con tecnologías detectadas

**Contexto**: La API de Adzuna solo entrega los primeros 500 caracteres de la descripción de cada oferta (ver ADR-006). En la primera carga real, 32 de 50 ofertas (64 %) no tenían ninguna tecnología detectada por el LLM, normalmente porque el texto recortado no llega a mencionarlas. Con esas ofertas en el denominador, los porcentajes de demanda salían artificialmente bajos (p. ej. LLM en el 10 % de las ofertas, cuando aparecía en el 28 % de las que sí mencionan alguna tecnología).

**Decisión**:
- En `demanda_tecnologias_mensual`, el porcentaje de cada tecnología se calcula solo sobre las ofertas del mes con al menos una tecnología detectada. La columna del denominador pasa a llamarse `total_ofertas_con_tecnologia_mes`.
- Se añade el mart `cobertura_extraccion_mensual` (1 fila por mes), con las ofertas clasificadas, las que no tienen ninguna tecnología y su porcentaje (`pct_sin_tecnologia`).
- El dashboard muestra ese porcentaje junto a los indicadores principales y en un gráfico mensual, con una nota visible que explica que se debe al límite de 500 caracteres de Adzuna.

**Alternativas consideradas**:
- Mantener todas las ofertas clasificadas en el denominador: descartado, porque mezcla "la oferta no pide esta tecnología" con "no sabemos qué pide la oferta" y subestima la demanda de todas las tecnologías.
- Añadir una fuente con la descripción completa de la oferta (p. ej. visitando la página de detalle o usando otra API): descartado por ahora. Visitar las páginas de detalle sería scraping, con los problemas de `robots.txt` y de cambios de HTML ya descritos en ADR-006, y otra API supondría un nuevo acuerdo de uso y más cuota de LLM. Queda como mejora futura en el Roadmap del README.

**Consecuencias**:
- Los porcentajes de demanda responden a "de las ofertas en las que sabemos qué se pide, ¿cuántas piden X?". Se asume que las ofertas sin tecnologías detectadas se reparten igual que las demás, algo que no está garantizado (p. ej. las descripciones más largas o más técnicas podrían estar sobrerrepresentadas).
- `pct_sin_tecnologia` permite vigilar ese sesgo: si baja al añadir una fuente mejor, los porcentajes de demanda serán más fiables.
- Cambia el nombre de una columna de `demanda_tecnologias_mensual`; el dashboard y el test de integración se han actualizado en el mismo cambio.
