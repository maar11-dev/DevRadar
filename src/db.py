"""Acceso a la base DuckDB compartida por el pipeline y por dbt."""

import os
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "devradar.duckdb"

RAW_OFERTAS_DDL = """
create table if not exists raw_ofertas (
    id varchar primary key,
    titulo varchar,
    descripcion varchar,
    fecha_publicacion varchar,
    empresa varchar,
    ubicacion varchar,
    url varchar,
    categoria varchar,
    salario_min_anunciado double,
    salario_max_anunciado double,
    fuente varchar,
    fecha_ingesta timestamp,
    payload json
)
"""

RAW_OFERTAS_CLASIFICADAS_DDL = """
create table if not exists raw_ofertas_clasificadas (
    id_oferta varchar not null,
    tecnologias varchar[],
    seniority varchar,
    modalidad varchar,
    salario_min double,
    salario_max double,
    error varchar,
    respuesta_llm varchar,
    proveedor_llm varchar,
    modelo_llm varchar,
    fecha_extraccion timestamp not null,
    version_prompt varchar
)
"""

# Columnas añadidas después de la primera publicación de la base: las bases
# restauradas desde la rama `data` no las tienen (ADR-009).
RAW_MIGRATIONS = (
    "alter table raw_ofertas_clasificadas add column if not exists version_prompt varchar",
)


def get_db_path() -> Path:
    """Devuelve la ruta de la base DuckDB.

    Usa ``DBT_DUCKDB_PATH`` si está definida y no vacía; si no, la misma ruta
    por defecto que ``dbt_project/profiles.yml`` (``data/devradar.duckdb``).

    Returns:
        Ruta absoluta del archivo ``.duckdb``.
    """
    configured = os.getenv("DBT_DUCKDB_PATH", "").strip()
    return Path(configured).resolve() if configured else DEFAULT_DB_PATH


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Abre una conexión a la base del pipeline.

    Args:
        read_only: Si es ``True``, abre la base en solo lectura (dashboard).

    Returns:
        Conexión DuckDB. El llamante es responsable de cerrarla.
    """
    path = get_db_path()
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def create_raw_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Crea las tablas crudas si todavía no existen y añade columnas nuevas.

    Args:
        con: Conexión DuckDB con permisos de escritura.
    """
    con.execute(RAW_OFERTAS_DDL)
    con.execute(RAW_OFERTAS_CLASIFICADAS_DDL)
    for migration in RAW_MIGRATIONS:
        con.execute(migration)
