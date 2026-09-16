"""Normalización de tecnologías detectadas por el LLM contra el catálogo controlado."""

import csv
from pathlib import Path

DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent
    / "dbt_project"
    / "seeds"
    / "catalogo_tecnologias.csv"
)


def _normalize_key(value: str) -> str:
    """Convierte una variante a la forma usada como clave del catálogo."""
    return " ".join(value.strip().lower().split())


def normalizar_tecnologias(tecnologias: list[str], catalogo: dict) -> list[str]:
    """Mapea las tecnologías detectadas a su nombre canónico.

    La búsqueda no distingue mayúsculas ni espacios sobrantes. Las tecnologías
    que no están en el catálogo se descartan y los duplicados se eliminan
    conservando el orden de primera aparición.

    Args:
        tecnologias: Nombres de tecnologías tal como los devuelve el LLM.
        catalogo: Diccionario ``variante -> nombre canónico``; las variantes
            deben estar en minúsculas (ver ``load_catalog``).

    Returns:
        Lista de nombres canónicos, sin duplicados.
    """
    result: list[str] = []
    seen: set[str] = set()
    for tech in tecnologias:
        if not isinstance(tech, str):
            continue
        canonical = catalogo.get(_normalize_key(tech))
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def load_catalog(path: Path | str = DEFAULT_CATALOG_PATH) -> dict[str, str]:
    """Carga el catálogo de tecnologías desde el seed CSV de dbt.

    El CSV debe tener las columnas ``variante`` y ``nombre_canonico``. Cada
    nombre canónico se registra también como variante de sí mismo, para que
    se reconozca aunque no aparezca listado explícitamente.

    Args:
        path: Ruta al CSV. Por defecto, ``dbt_project/seeds/catalogo_tecnologias.csv``.

    Returns:
        Diccionario ``variante en minúsculas -> nombre canónico``.

    Raises:
        FileNotFoundError: Si el archivo no existe.
        ValueError: Si faltan las columnas esperadas.
    """
    catalog: dict[str, str] = {}
    with open(path, encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        required = {"variante", "nombre_canonico"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"El catálogo {path} debe tener las columnas {sorted(required)}"
            )
        for row in reader:
            variant = (row["variante"] or "").strip()
            canonical = (row["nombre_canonico"] or "").strip()
            if not variant or not canonical:
                continue
            catalog[_normalize_key(variant)] = canonical
            catalog.setdefault(_normalize_key(canonical), canonical)
    return catalog
