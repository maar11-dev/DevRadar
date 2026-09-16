"""Tests unitarios de la ingesta de Adzuna (sin red: la sesión HTTP se simula)."""

from unittest.mock import MagicMock

import duckdb
import pytest
import requests

from src import ingest

CREDENCIALES = {"ADZUNA_APP_ID": "id-secreto", "ADZUNA_APP_KEY": "clave-secreta"}


def _respuesta(status: int, body: dict | None = None, headers: dict | None = None):
    respuesta = MagicMock()
    respuesta.status_code = status
    respuesta.json.return_value = body or {}
    respuesta.headers = headers or {}
    return respuesta


@pytest.fixture(autouse=True)
def entorno_aislado(monkeypatch, tmp_path):
    """Credenciales falsas, caché temporal y sin esperas reales."""
    for nombre, valor in CREDENCIALES.items():
        monkeypatch.setenv(nombre, valor)
    monkeypatch.setattr(ingest, "CACHE_DIR", tmp_path / "cache")
    esperas = []
    monkeypatch.setattr(ingest.time, "sleep", esperas.append)
    return esperas


@pytest.fixture
def oferta_adzuna() -> dict:
    return {
        "id": "5886144196",
        "adref": "token-de-la-app",
        "title": "<strong>Data Engineer</strong>",
        "description": "Python y <strong>dbt</strong>",
        "created": "2026-09-16T14:23:32Z",
        "company": {"display_name": "Empresa Ejemplo"},
        "location": {"display_name": "Madrid"},
        "category": {"tag": "it-jobs"},
        "redirect_url": "https://www.adzuna.es/details/5886144196?utm_source=id-secreto",
        "salary_min": 40000,
    }


def test_reintenta_con_backoff_ante_429_y_errores_de_red(entorno_aislado):
    sesion = MagicMock()
    sesion.get.side_effect = [
        _respuesta(429, headers={"Retry-After": "7"}),
        requests.ConnectionError("fallo con app_key=clave-secreta"),
        _respuesta(200, {"count": 0, "results": []}),
    ]

    datos = ingest.get_json_with_retries(
        sesion,
        "https://api.example/x",
        {"app_key": "clave-secreta"},
        ingest.RateLimiter(0),
    )

    assert datos == {"count": 0, "results": []}
    assert sesion.get.call_count == 3
    # Primero respeta Retry-After; después, backoff exponencial (2 * 2**1 + jitter).
    assert entorno_aislado[0] == 7
    assert 4 <= entorno_aislado[1] <= 5


def test_error_definitivo_no_expone_credenciales():
    sesion = MagicMock()
    sesion.get.side_effect = requests.ConnectionError("url?app_key=clave-secreta")

    with pytest.raises(ingest.AdzunaError) as error:
        ingest.get_json_with_retries(
            sesion,
            "https://api.example/x",
            {"app_key": "clave-secreta"},
            ingest.RateLimiter(0),
        )

    assert sesion.get.call_count == ingest.MAX_ATTEMPTS
    assert "clave-secreta" not in str(error.value)


def test_no_reintenta_errores_de_autenticacion():
    sesion = MagicMock()
    sesion.get.return_value = _respuesta(401)

    with pytest.raises(ingest.AdzunaError, match="ADZUNA_APP_ID"):
        ingest.get_json_with_retries(
            sesion, "https://api.example/x", {}, ingest.RateLimiter(0)
        )

    assert sesion.get.call_count == 1


def test_descargar_pagina_usa_cache_y_limpia_identificadores(oferta_adzuna):
    sesion = MagicMock()
    sesion.get.return_value = _respuesta(200, {"count": 1, "results": [oferta_adzuna]})
    limitador = ingest.RateLimiter(0)

    primera = ingest.descargar_pagina(sesion, limitador, "es", "it-jobs", 1, 7)
    segunda = ingest.descargar_pagina(sesion, limitador, "es", "it-jobs", 1, 7)

    assert sesion.get.call_count == 1
    assert primera == segunda
    oferta = primera["results"][0]
    assert "adref" not in oferta
    assert oferta["redirect_url"] == "https://www.adzuna.es/details/5886144196"
    cache = next(ingest.CACHE_DIR.glob("*.json")).read_text(encoding="utf-8")
    assert "secret" not in cache


def test_falla_sin_credenciales(monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_KEY")
    with pytest.raises(ingest.AdzunaError, match="ADZUNA_APP_KEY"):
        ingest.descargar_pagina(
            MagicMock(), ingest.RateLimiter(0), "es", "it-jobs", 1, 7
        )


def test_guardar_ofertas_crudas_no_duplica(oferta_adzuna):
    with duckdb.connect(":memory:") as con:
        assert ingest.guardar_ofertas_crudas(con, [oferta_adzuna]) == 1
        assert ingest.guardar_ofertas_crudas(con, [oferta_adzuna]) == 0

        fila = con.execute(
            "select titulo, descripcion, empresa, url, salario_min_anunciado, payload "
            "from raw_ofertas"
        ).fetchone()

    titulo, descripcion, empresa, url, salario, payload = fila
    assert (titulo, descripcion, empresa) == (
        "Data Engineer",
        "Python y dbt",
        "Empresa Ejemplo",
    )
    assert url == "https://www.adzuna.es/details/5886144196"
    assert salario == 40000
    assert "secret" not in payload
