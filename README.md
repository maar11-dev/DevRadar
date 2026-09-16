# DevRadar

> Pipeline de datos automatizado que analiza la demanda de tecnologías en el mercado laboral tech, combinando scraping, extracción con LLM, transformación con dbt y visualización interactiva.

![status](https://img.shields.io/badge/status-en%20desarrollo-yellow)
![python](https://img.shields.io/badge/python-3.11-blue)
![dbt](https://img.shields.io/badge/dbt-DuckDB-orange)

## 📋 Descripción

DevRadar ingiere ofertas de empleo tech de forma periódica, extrae las tecnologías y condiciones mencionadas mediante un LLM, y las transforma en métricas agregadas (demanda por tecnología, evolución mensual, salarios) para responder a una pregunta simple: **¿qué tecnologías se piden realmente ahora mismo?**

Todo el pipeline corre de forma autónoma en la nube, sin infraestructura propia que mantener.

## 🏗️ Arquitectura

```
Scraping/API ofertas → Extracción de skills (LLM) → dbt (staging → intermediate → marts) → Dashboard
                              ↑                              ↑
                        GitHub Actions (orquestación semanal, sin servidor propio)
```

Detalle completo de componentes y decisiones de diseño en [`docs/architecture.md`](docs/architecture.md).

## 🛠️ Stack tecnológico

| Capa | Tecnología |
|---|---|
| Ingesta | Python, `requests`, `beautifulsoup4` |
| Extracción de entidades | LLM vía Groq API (con soporte opcional para Ollama local) |
| Transformación | dbt-core + dbt-duckdb |
| Almacenamiento | DuckDB |
| Orquestación | GitHub Actions (cron semanal) |
| Visualización | Streamlit |
| Calidad de datos | dbt tests |

## 📁 Estructura del repositorio

```
DevRadar/
├── docs/
│   ├── architecture.md      # Arquitectura y modelo de datos detallados
│   └── decisions.md         # Registro de decisiones técnicas (ADR)
├── reglas de seguridad/
│   └── coding-rules.md      # Convenciones de código y seguridad
├── tests/
│   ├── integracion/         # Tests end-to-end del pipeline
│   └── unitario/            # Tests unitarios de funciones de extracción/transformación
├── dbt_project/             # Modelos dbt (staging, intermediate, marts)
├── src/                     # Código de ingesta y extracción con LLM
├── dashboard/               # App de Streamlit
├── .github/workflows/       # Definición del cron de GitHub Actions
├── .gitignore
├── CLAUDE.md
└── README.md
```

## 🚀 Puesta en marcha local

```bash
# Clonar e instalar dependencias
git clone <url-del-repo>
cd DevRadar
pip install -r requirements.txt

# Configurar variables de entorno: copiar .env.example como .env y rellenar
# GROQ_API_KEY, ADZUNA_APP_ID y ADZUNA_APP_KEY

# Descargar ofertas de Adzuna y clasificarlas con el LLM
python src/ingest.py            # opciones: --pages N, --country es, --skip-extract
python src/extract.py           # reprocesa solo las ofertas pendientes o fallidas

# Ejecutar las transformaciones dbt (seed del catálogo + modelos + tests)
cd dbt_project
dbt build
cd ..

# Levantar el dashboard
streamlit run dashboard/app.py
```

## ⏱️ Ejecución automatizada

El pipeline completo se ejecuta semanalmente vía GitHub Actions (`.github/workflows/pipeline.yml`), sin necesidad de infraestructura propia. La API key de Groq se gestiona como *secret* del repositorio (ver [`reglas de seguridad/coding-rules.md`](reglas%20de%20seguridad/coding-rules.md)).

## ✅ Testing

```bash
# Tests unitarios
pytest tests/unitario

# Tests de integración (requieren credenciales configuradas)
pytest tests/integracion

# Tests de calidad de datos
cd dbt_project && dbt test
```

## 🗺️ Roadmap

- [ ] Ampliar fuentes de ofertas (más de un portal)
- [ ] Añadir detección de rango salarial normalizado
- [ ] Histórico de tendencias a más de 12 meses
- [ ] Alertas automáticas ante cambios bruscos de demanda

## 📄 Licencia

MIT