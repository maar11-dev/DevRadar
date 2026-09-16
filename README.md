# Rama `data`

Rama generada automáticamente por el workflow **DevRadar Pipeline**; no la edites a mano.

- `devradar.duckdb`: base con las tablas crudas, el catálogo y los marts de dbt.
- `devradar.sha256`: huella del contenido, usada para no publicar si nada ha cambiado.

El dashboard desplegado en Streamlit Community Cloud descarga `devradar.duckdb` de esta rama.
Ver ADR-008 en `docs/decisions.md` (rama `main`).

Datos de ofertas: Jobs by Adzuna (https://www.adzuna.es) · The Adzuna API.
