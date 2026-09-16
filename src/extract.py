"""Extracción de datos estructurados de ofertas de empleo mediante un LLM.

Proveedor configurable con ``LLM_PROVIDER`` (``groq`` por defecto u ``ollama``),
ver ADR-002 en docs/decisions.md.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import duckdb
from dotenv import load_dotenv

if __package__ in (None, ""):
    # Permite ejecutarlo como `python src/extract.py` (así lo lanza el workflow).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import connect, create_raw_tables
from src.normalize import load_catalog, normalizar_tecnologias

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "groq"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
DEFAULT_OLLAMA_MODEL = "llama3.1"
MAX_DESCRIPTION_CHARS = 6000
LLM_TIMEOUT_SECONDS = 60
# El plan gratuito de Groq limita a 8000 tokens/minuto y cada oferta consume
# unos 550: 6 s entre llamadas (~10/min) deja margen.
SECONDS_BETWEEN_CALLS = 6.0
# Se guarda con cada clasificación; incrementarla al cambiar PROMPT_TEMPLATE de
# forma que merezca reclasificar ofertas antiguas (ADR-009).
PROMPT_VERSION = "2"

SENIORITY_ALIASES = {
    "junior": "junior",
    "mid": "mid",
    "semi-senior": "mid",
    "semisenior": "mid",
    "intermedio": "mid",
    "senior": "senior",
}
MODALIDAD_ALIASES = {
    "remoto": "remoto",
    "remote": "remoto",
    "teletrabajo": "remoto",
    "hibrido": "hibrido",
    "híbrido": "hibrido",
    "hybrid": "hibrido",
    "presencial": "presencial",
    "on-site": "presencial",
    "onsite": "presencial",
    "on site": "presencial",
}

SYSTEM_PROMPT = (
    "Eres un extractor de información de ofertas de empleo tecnológicas. "
    "Respondes únicamente con un objeto JSON válido, sin texto adicional."
)

PROMPT_TEMPLATE = """Analiza la siguiente oferta de empleo y devuelve un objeto JSON con exactamente estas claves:

- "tecnologias": lista de tecnologías, lenguajes, frameworks, bases de datos, herramientas o plataformas mencionadas, con su nombre habitual (p. ej. "Python", "React", "AWS"). Revisa también el título: si nombra una tecnología o disciplina técnica, inclúyela (p. ej. "Machine Learning Engineer" → "Machine Learning", "Consultor SAP" → "SAP", "Líder de IA Generativa" → "IA generativa"). Incluye disciplinas técnicas concretas como "Machine Learning", "IA", "Cloud" o "DevOps", pero no habilidades blandas, idiomas, sectores ni nombres de empresas. Lista vacía si no hay ninguna.
- "seniority": "junior", "mid" o "senior" si se puede inferir; null si no.
- "modalidad": "remoto", "hibrido" o "presencial" si se puede inferir; null si no.
- "salario_min": salario anual bruto mínimo en euros como número, solo si aparece explícito; null si no.
- "salario_max": salario anual bruto máximo en euros como número, solo si aparece explícito; null si no.

No inventes datos que no estén en la oferta.

Título: {titulo}

Descripción:
{descripcion}
"""


class LLMConfigurationError(RuntimeError):
    """Error de configuración del proveedor LLM (no se reintenta ni se ignora)."""


def _get_provider() -> str:
    """Devuelve el proveedor configurado en ``LLM_PROVIDER``."""
    provider = os.getenv("LLM_PROVIDER", "").strip().lower() or DEFAULT_PROVIDER
    if provider not in {"groq", "ollama"}:
        raise LLMConfigurationError(
            f"LLM_PROVIDER no válido: {provider!r} (usa 'groq' u 'ollama')"
        )
    return provider


def _get_model(provider: str) -> str:
    """Devuelve el modelo configurado para el proveedor indicado."""
    if provider == "groq":
        return os.getenv("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODEL
    return os.getenv("OLLAMA_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL


@lru_cache(maxsize=1)
def _get_groq_client():
    """Crea (una sola vez) el cliente de Groq a partir de ``GROQ_API_KEY``."""
    from groq import Groq

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise LLMConfigurationError(
            "Falta GROQ_API_KEY (defínela en .env o como secret del repositorio)"
        )
    # El cliente ya reintenta con backoff exponencial ante 429 y errores 5xx.
    return Groq(api_key=api_key, max_retries=4, timeout=LLM_TIMEOUT_SECONDS)


def _call_groq(prompt: str, model: str) -> str:
    """Envía el prompt a Groq en modo JSON y devuelve el texto de respuesta."""
    extra_args = {}
    if model.startswith("openai/gpt-oss"):
        # Modelos de razonamiento: "low" reduce ~60 % los tokens generados sin
        # cambiar el resultado de la extracción. Otros modelos rechazan el parámetro.
        extra_args["reasoning_effort"] = "low"
    response = _get_groq_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
        **extra_args,
    )
    return response.choices[0].message.content or ""


def _call_ollama(prompt: str, model: str) -> str:
    """Envía el prompt a un servidor Ollama local y devuelve el texto de respuesta."""
    from ollama import Client

    host = os.getenv("OLLAMA_HOST", "").strip() or None
    response = Client(host=host, timeout=LLM_TIMEOUT_SECONDS).chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        format="json",
        options={"temperature": 0},
    )
    return response["message"]["content"] or ""


def llamar_llm(prompt: str) -> str:
    """Envía un prompt al proveedor LLM configurado.

    Args:
        prompt: Texto completo que se envía como mensaje del usuario.

    Returns:
        Texto devuelto por el modelo (se espera un objeto JSON).

    Raises:
        LLMConfigurationError: Si el proveedor o sus credenciales no están bien
            configurados.
        Exception: Errores de red o de la API del proveedor.
    """
    provider = _get_provider()
    model = _get_model(provider)
    if provider == "groq":
        return _call_groq(prompt, model)
    return _call_ollama(prompt, model)


def _build_prompt(oferta: dict) -> str:
    """Construye el prompt de extracción para una oferta."""
    descripcion = (oferta.get("descripcion") or "")[:MAX_DESCRIPTION_CHARS]
    return PROMPT_TEMPLATE.format(
        titulo=oferta.get("titulo") or "", descripcion=descripcion
    )


def _parse_json_object(text: str) -> dict:
    """Extrae el objeto JSON de la respuesta, tolerando bloques ```json```."""
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text or "")
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise TypeError("la respuesta del LLM no es un objeto JSON")
    return data


def _to_salary(value) -> float | None:
    """Convierte un salario a número positivo, o ``None`` si no es válido."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        value = re.sub(r"[^\d.,]", "", value).replace(".", "").replace(",", ".")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _normalize_choice(value, aliases: dict[str, str]) -> str | None:
    """Mapea un valor categórico a su forma canónica, o ``None``."""
    if not isinstance(value, str):
        return None
    return aliases.get(value.strip().lower())


@lru_cache(maxsize=1)
def _get_catalog() -> dict[str, str]:
    """Carga (una sola vez) el catálogo de producción."""
    return load_catalog()


def _empty_result(error: str, respuesta_llm: str | None = None) -> dict:
    """Resultado controlado cuando la extracción falla."""
    return {
        "tecnologias": [],
        "seniority": None,
        "modalidad": None,
        "salario_min": None,
        "salario_max": None,
        "error": error,
        "respuesta_llm": respuesta_llm,
    }


def extraer_datos_oferta(oferta: dict) -> dict:
    """Extrae tecnologías, seniority, modalidad y salario de una oferta.

    Nunca lanza excepción por respuestas inválidas del LLM ni por errores de
    red: en ese caso devuelve ``tecnologias=[]`` y una clave ``error`` con el
    motivo, para que el pipeline pueda continuar con el resto de ofertas.

    Args:
        oferta: Oferta cruda con, al menos, ``titulo`` y ``descripcion``.

    Returns:
        Diccionario con ``tecnologias`` (normalizadas contra el catálogo),
        ``seniority``, ``modalidad``, ``salario_min``, ``salario_max``,
        ``error`` (``None`` si todo fue bien) y ``respuesta_llm`` (texto crudo).

    Raises:
        LLMConfigurationError: Si el proveedor LLM no está bien configurado.
    """
    try:
        respuesta = llamar_llm(_build_prompt(oferta))
    except LLMConfigurationError:
        raise
    except Exception as exc:  # noqa: BLE001 - cualquier fallo del proveedor
        logger.warning("Fallo al llamar al LLM: %s", type(exc).__name__)
        return _empty_result(f"llm_error: {type(exc).__name__}: {exc}")

    try:
        data = _parse_json_object(respuesta)
    except (ValueError, TypeError) as exc:  # JSONDecodeError hereda de ValueError
        return _empty_result(f"json_invalido: {exc}", respuesta)

    tecnologias = data.get("tecnologias")
    if not isinstance(tecnologias, list):
        tecnologias = []

    salario_min = _to_salary(data.get("salario_min"))
    salario_max = _to_salary(data.get("salario_max"))
    if salario_min and salario_max and salario_min > salario_max:
        salario_min, salario_max = salario_max, salario_min

    return {
        "tecnologias": normalizar_tecnologias(tecnologias, _get_catalog()),
        "seniority": _normalize_choice(data.get("seniority"), SENIORITY_ALIASES),
        "modalidad": _normalize_choice(data.get("modalidad"), MODALIDAD_ALIASES),
        "salario_min": salario_min,
        "salario_max": salario_max,
        "error": None,
        "respuesta_llm": respuesta,
    }


def clasificar_ofertas_pendientes(
    con: duckdb.DuckDBPyConnection,
    limit: int | None = None,
    reclasificar_sin_tecnologias: bool = False,
) -> tuple[int, int]:
    """Clasifica las ofertas de ``raw_ofertas`` que aún no tienen extracción válida.

    Cada intento se guarda en ``raw_ofertas_clasificadas``; las ofertas cuyo
    último intento falló se vuelven a procesar en la siguiente ejecución.

    Args:
        con: Conexión DuckDB con permisos de escritura.
        limit: Máximo de ofertas a procesar (``None`` para todas).
        reclasificar_sin_tecnologias: Si es ``True``, procesa además las ofertas
            cuya última extracción correcta no devolvió ninguna tecnología y se
            hizo con una versión anterior del prompt (``PROMPT_VERSION``).

    Returns:
        Tupla ``(procesadas, con_error)``.

    Raises:
        RuntimeError: Si todas las ofertas procesadas fallaron, para que el
            workflow no publique datos vacíos en silencio.
    """
    create_raw_tables(con)
    query = """
        with ultima_correcta as (
            select
                id_oferta,
                coalesce(
                    len(try_cast(json_extract(
                        try_cast(respuesta_llm as json), '$.tecnologias'
                    ) as varchar[])),
                    len(tecnologias)
                ) as num_tecnologias,
                version_prompt
            from raw_ofertas_clasificadas
            where error is null
            qualify row_number() over (
                partition by id_oferta order by fecha_extraccion desc
            ) = 1
        )
        select cast(o.id as varchar), o.titulo, o.descripcion
        from raw_ofertas as o
        left join ultima_correcta as c
            on c.id_oferta = cast(o.id as varchar)
        where c.id_oferta is null
            or (
                ?
                and coalesce(c.num_tecnologias, 0) = 0
                and coalesce(c.version_prompt, '1') <> ?
            )
        order by o.fecha_publicacion desc nulls last
    """
    if limit is not None:
        query += f" limit {int(limit)}"
    pending = con.execute(
        query, [reclasificar_sin_tecnologias, PROMPT_VERSION]
    ).fetchall()

    provider = _get_provider() if pending else None
    model = _get_model(provider) if provider else None
    failures = 0
    for index, (id_oferta, titulo, descripcion) in enumerate(pending):
        if index and provider == "groq":
            time.sleep(SECONDS_BETWEEN_CALLS)
        result = extraer_datos_oferta(
            {"id": id_oferta, "titulo": titulo, "descripcion": descripcion}
        )
        if result["error"]:
            failures += 1
            logger.warning("Oferta %s sin clasificar: %s", id_oferta, result["error"])
        con.execute(
            """
            insert into raw_ofertas_clasificadas (
                id_oferta, tecnologias, seniority, modalidad, salario_min,
                salario_max, error, respuesta_llm, proveedor_llm, modelo_llm,
                fecha_extraccion, version_prompt
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                id_oferta,
                result["tecnologias"],
                result["seniority"],
                result["modalidad"],
                result["salario_min"],
                result["salario_max"],
                result["error"],
                result["respuesta_llm"],
                provider,
                model,
                datetime.now(timezone.utc).replace(tzinfo=None),
                PROMPT_VERSION,
            ],
        )

    if pending and failures == len(pending):
        raise RuntimeError(
            f"Fallaron las {failures} extracciones; revisa el proveedor LLM"
        )
    logger.info("Clasificadas %d ofertas (%d con error)", len(pending), failures)
    return len(pending), failures


def main() -> None:
    """Punto de entrada: clasifica las ofertas pendientes de la base DuckDB."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=None, help="máximo de ofertas a procesar"
    )
    parser.add_argument(
        "--reclasificar-sin-tecnologias",
        action="store_true",
        help="volver a clasificar las ofertas sin tecnologías de un prompt anterior",
    )
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    with connect() as con:
        clasificar_ofertas_pendientes(
            con,
            limit=args.limit,
            reclasificar_sin_tecnologias=args.reclasificar_sin_tecnologias,
        )


if __name__ == "__main__":
    main()
