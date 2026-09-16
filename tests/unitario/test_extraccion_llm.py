"""Tests unitarios del parseo de la respuesta del LLM (mockeada, sin llamar a Groq)."""

import json
from unittest.mock import patch

from src.extract import extraer_datos_oferta


@patch("src.extract.llamar_llm")
def test_extrae_campos_esperados(
    mock_llamar_llm, oferta_ejemplo, respuesta_llm_ejemplo
):
    mock_llamar_llm.return_value = json.dumps(respuesta_llm_ejemplo)

    resultado = extraer_datos_oferta(oferta_ejemplo)

    assert resultado["tecnologias"] == ["Python", "dbt", "Airflow"]
    assert resultado["seniority"] == "senior"
    assert resultado["modalidad"] == "remoto"
    mock_llamar_llm.assert_called_once()


@patch("src.extract.llamar_llm")
def test_maneja_respuesta_json_malformada_sin_lanzar_excepcion(
    mock_llamar_llm, oferta_ejemplo
):
    mock_llamar_llm.return_value = "esto no es json"

    resultado = extraer_datos_oferta(oferta_ejemplo)

    # Ante una respuesta inválida del LLM, se espera un resultado "vacío"
    # controlado, no una excepción que tumbe el pipeline completo.
    assert resultado["tecnologias"] == []
    assert resultado.get("error") is not None
