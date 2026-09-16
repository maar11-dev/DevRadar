"""Test de integración de las reglas de staging (ADR-009, ADR-010 y ADR-011).

Carga filas crudas directamente en una base DuckDB temporal (sin LLM) y
comprueba el resultado de dbt: normalización desde la respuesta cruda del LLM,
salarios de Adzuna solo en rango anual y deduplicación de anuncios repetidos.

Ejecutar con: pytest tests/integracion
"""

import json

import duckdb

from src.db import create_raw_tables
from tests.integracion.test_pipeline_end_to_end import _run_dbt


def _respuesta(tecnologias, salario_min=None, salario_max=None):
    return json.dumps(
        {
            "tecnologias": tecnologias,
            "seniority": None,
            "modalidad": None,
            "salario_min": salario_min,
            "salario_max": salario_max,
        }
    )


def test_staging_normaliza_deduplica_y_filtra_salarios(tmp_path):
    ruta_db = tmp_path / "devradar.duckdb"
    # id, titulo, fecha, empresa, salario mínimo y máximo publicados por Adzuna
    ofertas = [
        ("A", "Embedded Engineer", "2026-09-10", "Acme", 40000, 50000),
        ("B", "Data Engineer", "2026-09-11", "Beta", None, None),
        ("C", "Data Engineer", "2026-09-12", "Beta", 90000, 90000),  # repite B
        ("D", "QA Engineer", "2026-09-12", "Delta", 3000, 3000),  # mensual
    ]
    # id, lista normalizada en Python (catálogo antiguo), respuesta cruda,
    # salario mínimo y máximo extraídos por el LLM
    clasificaciones = [
        ("A", [], _respuesta(["Embedded  Linux", "Yocto", "Desconocida"]), None, None),
        ("B", [], _respuesta([]), None, None),
        ("C", ["Python"], _respuesta(["Python"], 30000, 40000), 30000, 40000),
        ("D", ["Selenium"], _respuesta(["Selenium"]), None, None),
    ]

    with duckdb.connect(str(ruta_db)) as con:
        create_raw_tables(con)
        con.executemany(
            "insert into raw_ofertas (id, titulo, fecha_publicacion, empresa, "
            "salario_min_anunciado, salario_max_anunciado) values (?, ?, ?, ?, ?, ?)",
            ofertas,
        )
        con.executemany(
            "insert into raw_ofertas_clasificadas (id_oferta, tecnologias, "
            "respuesta_llm, salario_min, salario_max, fecha_extraccion) "
            "values (?, ?, ?, ?, ?, now())",
            clasificaciones,
        )

    _run_dbt("build", ruta_db=ruta_db)

    with duckdb.connect(str(ruta_db), read_only=True) as con:
        staging = con.execute(
            "select id_oferta, fuente_salario, salario_min, salario_max "
            "from stg_ofertas order by id_oferta"
        ).fetchall()
        tecnologias = con.execute(
            "select id_oferta, tecnologia from int_tecnologias_por_oferta "
            "order by id_oferta, tecnologia"
        ).fetchall()
        cobertura = con.execute(
            "select total_ofertas_clasificadas, ofertas_sin_tecnologia "
            "from cobertura_extraccion_mensual"
        ).fetchall()

    # B y C son el mismo anuncio: se conserva C, que tiene tecnologías.
    # A toma el salario de Adzuna; C, el del LLM aunque Adzuna publique otro;
    # el de D (mensual) queda fuera del rango anual y se descarta.
    assert staging == [
        ("A", "adzuna", 40000.0, 50000.0),
        ("C", "llm", 30000.0, 40000.0),
        ("D", None, None, None),
    ]
    # El catálogo actual reconoce variantes que la lista de Python había descartado.
    assert tecnologias == [
        ("A", "Linux"),
        ("A", "Yocto"),
        ("C", "Python"),
        ("D", "Selenium"),
    ]
    assert cobertura == [(3, 0)]
