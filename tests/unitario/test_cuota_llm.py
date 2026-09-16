"""Tests unitarios de los límites de Groq (sin red: el cliente se simula, ADR-012)."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import duckdb
import groq
import httpx
import pytest

from src import extract
from src.db import create_raw_tables

RESPUESTA = json.dumps({"tecnologias": ["Python"]})


def _rate_limit(mensaje: str, retry_after: str = "7") -> groq.RateLimitError:
    respuesta = httpx.Response(
        429,
        headers={"retry-after": retry_after},
        request=httpx.Request(
            "POST", "https://api.groq.com/openai/v1/chat/completions"
        ),
    )
    return groq.RateLimitError(mensaje, response=respuesta, body=None)


def _completion(texto: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=texto))]
    )


@pytest.fixture
def cliente_groq():
    cliente = MagicMock()
    with patch.object(extract, "_get_groq_client", return_value=cliente):
        yield cliente.chat.completions.create


@patch("src.extract.time.sleep")
def test_limite_diario_detiene_sin_reintentar(sleep, cliente_groq):
    cliente_groq.side_effect = _rate_limit(
        "Rate limit reached ... on tokens per day (TPD): Limit 200000"
    )

    with pytest.raises(extract.LLMQuotaExhaustedError):
        extract._call_groq("prompt", "openai/gpt-oss-20b")

    assert cliente_groq.call_count == 1
    sleep.assert_not_called()


@patch("src.extract.time.sleep")
def test_limite_por_minuto_espera_y_reintenta(sleep, cliente_groq):
    cliente_groq.side_effect = [
        _rate_limit("Rate limit reached ... on tokens per minute (TPM)"),
        _completion(RESPUESTA),
    ]

    assert extract._call_groq("prompt", "openai/gpt-oss-20b") == RESPUESTA
    assert cliente_groq.call_count == 2
    sleep.assert_called_once_with(7.0)


@patch("src.extract.time.sleep")
def test_error_persistente_se_propaga_tras_los_reintentos(sleep, cliente_groq):
    cliente_groq.side_effect = _rate_limit("... tokens per minute (TPM)", "500")

    with pytest.raises(groq.RateLimitError):
        extract._call_groq("prompt", "openai/gpt-oss-20b")

    assert cliente_groq.call_count == extract.GROQ_MAX_ATTEMPTS
    # Retry-After se limita para no bloquear la ejecución.
    assert {c.args[0] for c in sleep.call_args_list} == {extract.GROQ_MAX_WAIT_SECONDS}


@patch("src.extract.time.sleep")
@patch("src.extract.llamar_llm")
def test_clasificacion_se_detiene_sin_error_al_agotar_la_cuota(
    llamar_llm, _sleep, monkeypatch, capsys
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    llamar_llm.side_effect = [
        RESPUESTA,
        extract.LLMQuotaExhaustedError("Cuota diaria de Groq agotada"),
    ]
    with duckdb.connect(":memory:") as con:
        create_raw_tables(con)
        con.executemany(
            "insert into raw_ofertas (id, titulo, descripcion, fecha_publicacion) "
            "values (?, 't', 'd', ?)",
            [("1", "2026-09-03"), ("2", "2026-09-02"), ("3", "2026-09-01")],
        )

        assert extract.clasificar_ofertas_pendientes(con) == (1, 0)
        guardadas = con.execute(
            "select id_oferta, error from raw_ofertas_clasificadas"
        ).fetchall()

    # Solo se guarda la oferta clasificada: las demás siguen pendientes, sin
    # filas de error que las marquen como intentadas.
    assert guardadas == [("1", None)]
    aviso = capsys.readouterr().out
    assert aviso.startswith("::warning::")
    assert "tras 1 ofertas; 2 quedan pendientes" in aviso
