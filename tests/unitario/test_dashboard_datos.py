"""Tests unitarios de la carga de datos del dashboard (sin red ni Streamlit en marcha)."""

from unittest.mock import MagicMock

import duckdb
import pandas as pd
import pytest

from dashboard import app
from src.publish_db import content_fingerprint


def _crear_base(ruta, titulo):
    with duckdb.connect(str(ruta)) as con:
        con.execute("create table t as select ? as titulo", [titulo])
    return content_fingerprint(ruta)


@pytest.fixture
def github_simulado(monkeypatch, tmp_path):
    """Sirve el contenido de ``publicado['db']`` como si fuera la rama data."""
    publicado = {}
    peticiones = []

    def get(url, **_kwargs):
        peticiones.append(url)
        respuesta = MagicMock()
        respuesta.__enter__.return_value = respuesta
        respuesta.raise_for_status.return_value = None
        respuesta.iter_content.return_value = [publicado["db"].read_bytes()]
        return respuesta

    monkeypatch.setattr(app.requests, "get", get)
    monkeypatch.setattr(app, "DOWNLOAD_DIR", tmp_path / "descargas")
    app.descargar_base_publicada.clear()
    yield publicado, peticiones
    app.descargar_base_publicada.clear()


def test_solo_descarga_de_nuevo_cuando_cambia_la_huella(github_simulado, tmp_path):
    publicado, peticiones = github_simulado
    publicado["db"] = tmp_path / "v1.duckdb"
    huella_v1 = _crear_base(publicado["db"], "v1")

    ruta_1 = app.descargar_base_publicada("https://x/devradar.duckdb", huella_v1)
    ruta_1b = app.descargar_base_publicada("https://x/devradar.duckdb", huella_v1)
    assert ruta_1 == ruta_1b
    assert len(peticiones) == 1
    assert ruta_1.endswith("devradar.duckdb")

    publicado["db"] = tmp_path / "v2.duckdb"
    huella_v2 = _crear_base(publicado["db"], "v2")
    ruta_2 = app.descargar_base_publicada("https://x/devradar.duckdb", huella_v2)

    assert len(peticiones) == 2
    assert content_fingerprint(ruta_2) == huella_v2
    # La versión anterior se borra para no acumular archivos.
    assert not (tmp_path / "descargas" / huella_v1[:16]).exists()


def test_contenido_desactualizado_no_se_cachea(github_simulado, tmp_path):
    publicado, peticiones = github_simulado
    publicado["db"] = tmp_path / "v1.duckdb"
    _crear_base(publicado["db"], "v1")
    # La huella ya es la nueva, pero la CDN aún sirve la base antigua.
    huella_nueva = "f" * 64

    for _ in range(2):
        with pytest.raises(app.BaseDesactualizada) as error:
            app.descargar_base_publicada("https://x/devradar.duckdb", huella_nueva)
        assert content_fingerprint(error.value.ruta) == content_fingerprint(
            publicado["db"]
        )

    # Cada carga vuelve a intentarlo hasta que la CDN sirva la versión nueva.
    assert len(peticiones) == 2


def test_reparto_modalidad_suma_el_periodo_en_orden_fijo():
    modalidad = pd.DataFrame(
        {
            "modalidad": ["presencial", "hibrido", "remoto", "hibrido"],
            "mes": pd.to_datetime(
                ["2026-08-01", "2026-08-01", "2026-09-01", "2026-09-01"]
            ),
            "num_ofertas": [1, 2, 1, 4],
        }
    )

    reparto = app.reparto_modalidad(modalidad)

    assert reparto[["etiqueta", "num_ofertas", "pct_ofertas"]].values.tolist() == [
        ["Remoto", 1, 12.5],
        ["Híbrido", 6, 75.0],
        ["Presencial", 1, 12.5],
    ]
