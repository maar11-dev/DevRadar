"""Fixtures compartidas entre tests unitarios e de integración."""

import pytest


@pytest.fixture
def oferta_ejemplo() -> dict:
    """Una oferta de empleo cruda, tal como llegaría de la fuente de datos."""
    return {
        "id": "12345",
        "titulo": "Senior Data Engineer",
        "descripcion": (
            "Buscamos Data Engineer con experiencia en Python, dbt y Airflow. "
            "Modalidad remota. Salario: 45.000-55.000€."
        ),
        "fecha_publicacion": "2026-09-10",
        "empresa": "Empresa Ejemplo S.L.",
    }


@pytest.fixture
def respuesta_llm_ejemplo() -> dict:
    """Salida simulada del LLM para la oferta_ejemplo, sin llamar a la API real."""
    return {
        "tecnologias": ["Python", "dbt", "Airflow"],
        "seniority": "senior",
        "modalidad": "remoto",
        "salario_min": 45000,
        "salario_max": 55000,
    }


@pytest.fixture
def catalogo_tecnologias() -> dict:
    """Catálogo controlado de normalización: variante -> nombre canónico."""
    return {
        "python": "Python",
        "dbt": "dbt",
        "dbt-core": "dbt",
        "airflow": "Airflow",
        "apache airflow": "Airflow",
        "react": "React",
        "reactjs": "React",
        "react.js": "React",
    }
