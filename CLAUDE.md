# CLAUDE.md

Contexto e instrucciones para trabajar en este repositorio con Claude Code.

## Qué es este proyecto

DevRadar es un pipeline ELT que analiza la demanda de tecnologías en ofertas de empleo tech: scraping → extracción de skills con LLM (Groq/Ollama) → transformación con dbt sobre DuckDB → dashboard en Streamlit. Todo orquestado con GitHub Actions, sin Docker ni servidor propio. Ver [`docs/architecture.md`](docs/architecture.md) para el detalle completo y [`docs/decisions.md`](docs/decisions.md) para el porqué de cada elección técnica.

## Comandos habituales

```bash
# Instalar dependencias
pip install -r requirements.txt

# Ejecutar el pipeline completo en local
python src/ingest.py
python src/extract.py
cd dbt_project && dbt run && dbt test

# Levantar el dashboard
streamlit run dashboard/app.py

# Tests
pytest tests/unitario
pytest tests/integracion

# Formateo y linting
black .
ruff check .
```

## Convenciones a respetar

- Seguir siempre las reglas de [`reglas de seguridad/coding-rules.md`](reglas%20de%20seguridad/coding-rules.md): nunca escribir claves en código, respetar límites de scraping, mantener tests de dbt en verde.
- Los modelos dbt siguen la estructura `staging` → `intermediate` → `marts`; no crear modelos fuera de esa jerarquía sin justificarlo en `docs/decisions.md`.
- Las tecnologías detectadas por el LLM deben normalizarse contra el catálogo controlado antes de llegar a los marts.
- Cualquier cambio que afecte a una decisión de arquitectura ya documentada debe reflejarse como una entrada nueva en `docs/decisions.md`, no sobrescribiendo las anteriores.

## Qué evitar

- No añadir Docker ni dependencias que requieran contenedores: es una restricción intencional del proyecto (entorno de desarrollo sin Docker disponible).
- No sustituir GitHub Actions por otro orquestador sin registrar la decisión en `docs/decisions.md`.
- No hacer commit de archivos `.env`, credenciales, ni de la base `.duckdb` con datos reales de producción.