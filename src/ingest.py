"""Ingesta de ofertas de empleo tech desde la API de Adzuna (ver ADR-006).

Guarda las ofertas crudas en ``raw_ofertas`` y, salvo ``--skip-extract``,
las clasifica con el LLM en ``raw_ofertas_clasificadas``.
"""

import argparse
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import duckdb
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

if __package__ in (None, ""):
    # Permite ejecutarlo como `python src/ingest.py` (así lo lanza el workflow).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import PROJECT_ROOT, connect, create_raw_tables
from src.extract import clasificar_ofertas_pendientes

logger = logging.getLogger(__name__)

ADZUNA_BASE_URL = "https://api.adzuna.com/v1/api/jobs"
USER_AGENT = "DevRadar/0.1 (+https://github.com/maar11-dev/DevRadar)"
FUENTE = "adzuna"

DEFAULT_COUNTRY = "es"
DEFAULT_CATEGORY = "it-jobs"
DEFAULT_PAGES = 5
DEFAULT_MAX_DAYS_OLD = 7
RESULTS_PER_PAGE = 50

CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "adzuna"
CACHE_RETENTION_DAYS = 14

REQUEST_TIMEOUT_SECONDS = 30
# El plan gratuito permite 25 peticiones/minuto: 3 s entre peticiones deja margen.
MIN_SECONDS_BETWEEN_REQUESTS = 3.0
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 120.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class AdzunaError(RuntimeError):
    """Error al consultar la API de Adzuna (el mensaje nunca incluye credenciales)."""


class RateLimiter:
    """Garantiza un intervalo mínimo entre peticiones consecutivas."""

    def __init__(self, min_interval_seconds: float) -> None:
        """Crea el limitador.

        Args:
            min_interval_seconds: Segundos mínimos entre dos peticiones.
        """
        self.min_interval_seconds = min_interval_seconds
        self._last_request = None

    def wait(self) -> None:
        """Espera lo necesario antes de la siguiente petición."""
        if self._last_request is not None:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.min_interval_seconds:
                time.sleep(self.min_interval_seconds - elapsed)
        self._last_request = time.monotonic()


def _backoff_seconds(attempt: int, retry_after: str | None = None) -> float:
    """Espera antes del siguiente intento: Retry-After o backoff exponencial con jitter."""
    if retry_after and retry_after.strip().isdigit():
        return min(float(retry_after), BACKOFF_MAX_SECONDS)
    delay = BACKOFF_BASE_SECONDS * 2**attempt + random.uniform(0, 1)
    return min(delay, BACKOFF_MAX_SECONDS)


def get_json_with_retries(
    session: requests.Session,
    url: str,
    params: dict,
    rate_limiter: RateLimiter,
) -> dict:
    """Hace un GET que devuelve JSON, con límite de frecuencia y reintentos.

    Reintenta con backoff exponencial ante errores de red, timeouts, 429 y 5xx.
    Los mensajes de error no incluyen la URL completa, porque sus parámetros
    pueden contener credenciales.

    Args:
        session: Sesión HTTP a reutilizar.
        url: URL sin parámetros.
        params: Parámetros de la query (pueden incluir credenciales).
        rate_limiter: Limitador compartido entre peticiones.

    Returns:
        Cuerpo de la respuesta decodificado.

    Raises:
        AdzunaError: Si la respuesta no es válida o se agotan los reintentos.
    """
    path = urlsplit(url).path
    last_error = ""
    for attempt in range(MAX_ATTEMPTS):
        rate_limiter.wait()
        retry_after = None
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = type(exc).__name__
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError:
                    raise AdzunaError(f"Respuesta no JSON de {path}") from None
            if response.status_code not in RETRYABLE_STATUS_CODES:
                raise AdzunaError(
                    f"HTTP {response.status_code} en {path}"
                    + (
                        " (revisa ADZUNA_APP_ID/ADZUNA_APP_KEY)"
                        if response.status_code in {401, 403}
                        else ""
                    )
                )
            last_error = f"HTTP {response.status_code}"
            retry_after = response.headers.get("Retry-After")

        if attempt < MAX_ATTEMPTS - 1:
            delay = _backoff_seconds(attempt, retry_after)
            logger.warning(
                "%s en %s; reintento %d/%d en %.1f s",
                last_error,
                path,
                attempt + 1,
                MAX_ATTEMPTS - 1,
                delay,
            )
            time.sleep(delay)
    raise AdzunaError(f"Agotados los reintentos en {path} (último error: {last_error})")


def _get_credentials() -> dict[str, str]:
    """Lee las credenciales de Adzuna de las variables de entorno."""
    app_id = os.getenv("ADZUNA_APP_ID", "").strip()
    app_key = os.getenv("ADZUNA_APP_KEY", "").strip()
    if not app_id or not app_key:
        raise AdzunaError(
            "Faltan ADZUNA_APP_ID/ADZUNA_APP_KEY (defínelas en .env o como secrets)"
        )
    return {"app_id": app_id, "app_key": app_key}


def _clean_url(url: str | None) -> str | None:
    """Quita la query de la URL (los parámetros utm_* incluyen el id de la app)."""
    if not url:
        return None
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _limpiar_oferta(oferta: dict) -> dict:
    """Elimina de una oferta de Adzuna los campos que identifican la aplicación."""
    limpia = {k: v for k, v in oferta.items() if k not in {"adref", "__CLASS__"}}
    limpia["redirect_url"] = _clean_url(oferta.get("redirect_url"))
    return limpia


def _cache_path(country: str, category: str, max_days_old: int, page: int) -> Path:
    """Ruta de caché de una página: una por día, para no repetir peticiones."""
    name = f"{datetime.now(timezone.utc):%Y%m%d}_{country}_{category}_{max_days_old}d_p{page}.json"
    return CACHE_DIR / name


def _prune_cache() -> None:
    """Borra de la caché los archivos más antiguos que ``CACHE_RETENTION_DAYS``."""
    if not CACHE_DIR.exists():
        return
    limit = time.time() - CACHE_RETENTION_DAYS * 86400
    for path in CACHE_DIR.glob("*.json"):
        if path.stat().st_mtime < limit:
            path.unlink(missing_ok=True)


def descargar_pagina(
    session: requests.Session,
    rate_limiter: RateLimiter,
    country: str,
    category: str,
    page: int,
    max_days_old: int,
) -> dict:
    """Descarga una página de resultados de Adzuna, usando la caché en disco si existe.

    Args:
        session: Sesión HTTP a reutilizar.
        rate_limiter: Limitador compartido entre peticiones.
        country: Código de país de Adzuna (p. ej. ``es``).
        category: Etiqueta de categoría de Adzuna (p. ej. ``it-jobs``).
        page: Número de página, empezando en 1.
        max_days_old: Antigüedad máxima de las ofertas en días.

    Returns:
        Diccionario con ``count`` (total de ofertas) y ``results`` (ofertas de
        la página, ya sin campos identificativos de la aplicación).
    """
    cache_file = _cache_path(country, category, max_days_old, page)
    if cache_file.exists():
        logger.info("Página %d leída de caché", page)
        return json.loads(cache_file.read_text(encoding="utf-8"))

    params = {
        **_get_credentials(),
        "results_per_page": RESULTS_PER_PAGE,
        "category": category,
        "max_days_old": max_days_old,
        "sort_by": "date",
    }
    data = get_json_with_retries(
        session, f"{ADZUNA_BASE_URL}/{country}/search/{page}", params, rate_limiter
    )
    pagina = {
        "count": data.get("count", 0),
        "results": [_limpiar_oferta(o) for o in data.get("results", [])],
    }

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = cache_file.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(pagina, ensure_ascii=False), encoding="utf-8")
    tmp_file.replace(cache_file)
    return pagina


def descargar_ofertas(
    country: str = DEFAULT_COUNTRY,
    category: str = DEFAULT_CATEGORY,
    pages: int = DEFAULT_PAGES,
    max_days_old: int = DEFAULT_MAX_DAYS_OLD,
) -> list[dict]:
    """Descarga hasta ``pages`` páginas de ofertas recientes de Adzuna.

    Args:
        country: Código de país de Adzuna.
        category: Etiqueta de categoría de Adzuna.
        pages: Número máximo de páginas (``RESULTS_PER_PAGE`` ofertas cada una).
        max_days_old: Antigüedad máxima de las ofertas en días.

    Returns:
        Lista de ofertas de Adzuna, sin duplicados por ``id``.
    """
    _prune_cache()
    ofertas: dict[str, dict] = {}
    rate_limiter = RateLimiter(MIN_SECONDS_BETWEEN_REQUESTS)
    with requests.Session() as session:
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        for page in range(1, pages + 1):
            pagina = descargar_pagina(
                session, rate_limiter, country, category, page, max_days_old
            )
            resultados = pagina["results"]
            for oferta in resultados:
                if oferta.get("id") is not None:
                    ofertas.setdefault(str(oferta["id"]), oferta)
            if not resultados or page * RESULTS_PER_PAGE >= pagina["count"]:
                break
    logger.info(
        "Descargadas %d ofertas de Adzuna (%s/%s)", len(ofertas), country, category
    )
    return list(ofertas.values())


def _html_to_text(value: str | None) -> str | None:
    """Convierte el HTML ligero de Adzuna (p. ej. ``<strong>``) en texto plano."""
    if not value:
        return value
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)


def _to_float(value) -> float | None:
    """Convierte a float, o ``None`` si no es posible."""
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def guardar_ofertas_crudas(con: duckdb.DuckDBPyConnection, ofertas: list[dict]) -> int:
    """Inserta en ``raw_ofertas`` las ofertas que aún no estaban guardadas.

    Args:
        con: Conexión DuckDB con permisos de escritura.
        ofertas: Ofertas tal como las devuelve ``descargar_ofertas``.

    Returns:
        Número de ofertas nuevas insertadas.
    """
    create_raw_tables(con)
    fecha_ingesta = datetime.now(timezone.utc).replace(tzinfo=None)
    filas = [
        (
            str(oferta["id"]),
            _html_to_text(oferta.get("title")),
            _html_to_text(oferta.get("description")),
            oferta.get("created"),
            (oferta.get("company") or {}).get("display_name"),
            (oferta.get("location") or {}).get("display_name"),
            _clean_url(oferta.get("redirect_url")),
            (oferta.get("category") or {}).get("tag"),
            _to_float(oferta.get("salary_min")),
            _to_float(oferta.get("salary_max")),
            FUENTE,
            fecha_ingesta,
            json.dumps(_limpiar_oferta(oferta), ensure_ascii=False),
        )
        for oferta in ofertas
    ]
    if not filas:
        return 0

    antes = con.execute("select count(*) from raw_ofertas").fetchone()[0]
    con.executemany(
        """
        insert or ignore into raw_ofertas (
            id, titulo, descripcion, fecha_publicacion, empresa, ubicacion, url,
            categoria, salario_min_anunciado, salario_max_anunciado, fuente,
            fecha_ingesta, payload
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        filas,
    )
    despues = con.execute("select count(*) from raw_ofertas").fetchone()[0]
    return despues - antes


def main() -> None:
    """Punto de entrada: descarga, guarda y (opcionalmente) clasifica ofertas."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", default=DEFAULT_COUNTRY, help="país de Adzuna")
    parser.add_argument(
        "--category", default=DEFAULT_CATEGORY, help="categoría de Adzuna"
    )
    parser.add_argument(
        "--pages", type=int, default=DEFAULT_PAGES, help="páginas máximas"
    )
    parser.add_argument(
        "--max-days-old",
        type=int,
        default=DEFAULT_MAX_DAYS_OLD,
        help="antigüedad máxima",
    )
    parser.add_argument(
        "--skip-extract", action="store_true", help="no clasificar con el LLM"
    )
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    ofertas = descargar_ofertas(
        args.country, args.category, args.pages, args.max_days_old
    )
    with connect() as con:
        nuevas = guardar_ofertas_crudas(con, ofertas)
        logger.info("Guardadas %d ofertas nuevas en raw_ofertas", nuevas)
        if not args.skip_extract:
            clasificar_ofertas_pendientes(con)


if __name__ == "__main__":
    main()
