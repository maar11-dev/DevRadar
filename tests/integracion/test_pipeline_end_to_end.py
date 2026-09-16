"""Test de integración: valida el pipeline completo sobre una base DuckDB temporal.

No llama a la API de Groq real (se mockea la extracción); si en el futuro se
quiere probar contra la API real, marcar ese test aparte con:
    @pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="requiere API key")

Ejecutar con: pytest tests/integracion
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

from src.db import create_raw_tables
from src.extract import clasificar_ofertas_pendientes

DBT_PROJECT_DIR = Path(__file__).resolve().parent.parent.parent / "dbt_project"


def _dbt_executable() -> str:
    """Localiza dbt junto al intérprete actual (venv) o en el PATH."""
    scripts_dir = Path(sys.executable).parent
    for name in ("dbt", "dbt.exe"):
        candidate = scripts_dir / name
        if candidate.exists():
            return str(candidate)
    found = shutil.which("dbt")
    if not found:
        pytest.skip("dbt no está instalado en este entorno")
    return found


def _run_dbt(*args: str, ruta_db: Path) -> None:
    """Ejecuta dbt contra la base temporal heredando el entorno actual (PATH incluido)."""
    env = {
        **os.environ,
        "DBT_DUCKDB_PATH": str(ruta_db),
        "DBT_PROFILES_DIR": str(DBT_PROJECT_DIR),
    }
    resultado = subprocess.run(
        [_dbt_executable(), *args, "--target", "test"],
        cwd=DBT_PROJECT_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


@pytest.fixture
def ruta_db(tmp_path) -> Path:
    """Ruta de una base DuckDB aislada para no tocar datos reales durante el test."""
    return tmp_path / "test_devradar.duckdb"


@patch("src.extract.llamar_llm")
def test_pipeline_completo_genera_marts_esperados(
    mock_llamar_llm, ruta_db, oferta_ejemplo, respuesta_llm_ejemplo
):
    """
    Simula: 2 ofertas crudas (una sin tecnologías detectables) -> extracción
    (mockeada) -> carga en DuckDB -> dbt seed/run/test, y comprueba que los
    marts tienen los datos esperados.
    """
    oferta_sin_tecnologias = {
        **oferta_ejemplo,
        "id": "67890",
        "titulo": "Técnico de soporte",
        "descripcion": "Atención a usuarios en oficina.",
    }
    respuesta_sin_tecnologias = {
        "tecnologias": [],
        "seniority": None,
        "modalidad": None,
        "salario_min": None,
        "salario_max": None,
    }

    def respuesta_simulada(prompt: str) -> str:
        if oferta_sin_tecnologias["titulo"] in prompt:
            return json.dumps(respuesta_sin_tecnologias)
        return json.dumps(respuesta_llm_ejemplo)

    mock_llamar_llm.side_effect = respuesta_simulada

    # 1. Carga de las ofertas crudas (simulando el resultado de la ingesta) y
    #    extracción con el LLM mockeado. La conexión se cierra antes de lanzar
    #    dbt: DuckDB no permite que otro proceso escriba mientras esté abierta.
    with duckdb.connect(str(ruta_db)) as con:
        create_raw_tables(con)
        con.executemany(
            "insert into raw_ofertas (id, titulo, descripcion, fecha_publicacion, empresa) "
            "values (?, ?, ?, ?, ?)",
            [
                [
                    oferta["id"],
                    oferta["titulo"],
                    oferta["descripcion"],
                    oferta["fecha_publicacion"],
                    oferta["empresa"],
                ]
                for oferta in (oferta_ejemplo, oferta_sin_tecnologias)
            ],
        )
        procesadas, con_error = clasificar_ofertas_pendientes(con)

    assert (procesadas, con_error) == (2, 0)
    assert mock_llamar_llm.call_count == 2

    # 2. Ejecutar dbt contra esa base temporal (target `test` de profiles.yml)
    _run_dbt("seed", ruta_db=ruta_db)
    _run_dbt("run", ruta_db=ruta_db)
    _run_dbt("test", ruta_db=ruta_db)

    # 3. Verificar los marts finales
    with duckdb.connect(str(ruta_db), read_only=True) as con:
        demanda = con.execute(
            "select tecnologia, num_ofertas, pct_ofertas "
            "from demanda_tecnologias_mensual order by tecnologia"
        ).fetchall()
        salarios = con.execute(
            "select tecnologia, salario_medio from salarios_por_tecnologia "
            "where tecnologia = 'Python'"
        ).fetchall()
        modalidad = con.execute(
            "select modalidad, num_ofertas from tendencia_modalidad"
        ).fetchall()
        cobertura = con.execute(
            "select total_ofertas_clasificadas, ofertas_sin_tecnologia, pct_sin_tecnologia "
            "from cobertura_extraccion_mensual"
        ).fetchall()

    # La oferta sin tecnologías no cuenta en el denominador de la demanda (ADR-007)...
    assert demanda == [
        ("Airflow", 1, 100.0),
        ("Python", 1, 100.0),
        ("dbt", 1, 100.0),
    ]
    assert salarios == [("Python", 50000.0)]
    assert modalidad == [("remoto", 1)]
    # ...pero sí en la métrica de cobertura de la extracción.
    assert cobertura == [(2, 1, 50.0)]
