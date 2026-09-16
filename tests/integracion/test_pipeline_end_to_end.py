"""Test de integración: valida el pipeline completo sobre una base DuckDB temporal.

No llama a la API de Groq real (se mockea la extracción); si en el futuro se
quiere probar contra la API real, marcar ese test aparte con:
    @pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="requiere API key")

Ejecutar con: pytest tests/integracion
"""
import subprocess
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest


@pytest.fixture
def db_temporal(tmp_path):
    """Base DuckDB aislada para no tocar datos reales durante el test."""
    ruta_db = tmp_path / "test_devradar.duckdb"
    con = duckdb.connect(str(ruta_db))
    yield con, ruta_db
    con.close()


@patch("src.extract.llamar_llm")
def test_pipeline_completo_genera_marts_esperados(
    mock_llamar_llm, db_temporal, oferta_ejemplo, respuesta_llm_ejemplo
):
    """
    Simula: 1 oferta cruda -> extracción (mockeada) -> carga en DuckDB
    -> dbt run -> dbt test, y comprueba que el mart final tiene datos.
    """
    import json

    mock_llamar_llm.return_value = json.dumps(respuesta_llm_ejemplo)

    con, ruta_db = db_temporal

    # 1. Carga de la oferta cruda (simulando el resultado de la ingesta)
    con.execute("CREATE TABLE raw_ofertas AS SELECT * FROM (VALUES (?, ?, ?, ?, ?)) "
                "AS t(id, titulo, descripcion, fecha_publicacion, empresa)",
                [oferta_ejemplo["id"], oferta_ejemplo["titulo"],
                 oferta_ejemplo["descripcion"], oferta_ejemplo["fecha_publicacion"],
                 oferta_ejemplo["empresa"]])

    # 2. Ejecutar dbt contra esa base temporal
    #    (requiere que dbt_project/profiles.yml permita apuntar a --target test
    #     con `path: {{ env_var('DBT_DUCKDB_PATH') }}`)
    resultado = subprocess.run(
        ["dbt", "run", "--target", "test"],
        cwd=Path(__file__).parent.parent.parent / "dbt_project",
        env={"DBT_DUCKDB_PATH": str(ruta_db)},
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, resultado.stderr

    # 3. Verificar que el mart final tiene la tecnología esperada
    filas = con.execute(
        "SELECT tecnologia FROM demanda_tecnologias_mensual WHERE tecnologia = 'Python'"
    ).fetchall()
    assert len(filas) > 0