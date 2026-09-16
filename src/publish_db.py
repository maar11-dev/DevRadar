"""Prepara la base DuckDB para publicarla en la rama ``data`` (ver ADR-008).

Genera una copia compacta de la base y una huella de su contenido. La huella
permite al workflow saber si los datos han cambiado, algo que no se puede
comparar con el archivo binario: dos reconstrucciones con los mismos datos
producen bytes distintos.

Uso: python src/publish_db.py <base origen> <directorio destino>
"""

import argparse
import hashlib
import sys
from pathlib import Path

import duckdb

DB_FILENAME = "devradar.duckdb"
FINGERPRINT_FILENAME = "devradar.sha256"


def _sql_literal(path: Path) -> str:
    """Devuelve la ruta como literal de cadena SQL."""
    return "'" + str(path).replace("'", "''") + "'"


def compact_copy(source: Path, target: Path) -> None:
    """Copia la base a un archivo nuevo, sin el espacio libre acumulado.

    Conserva tablas, vistas y restricciones (p. ej. la clave primaria de
    ``raw_ofertas``, que la ingesta necesita al restaurar la base).

    Args:
        source: Base DuckDB de origen (no se modifica).
        target: Ruta del archivo compacto; se sobrescribe si existe.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    for path in (target, target.with_name(target.name + ".wal")):
        path.unlink(missing_ok=True)
    with duckdb.connect() as con:
        # ATTACH no admite parámetros: se escapa la ruta como literal SQL.
        con.execute(f"attach {_sql_literal(source)} as origen (read_only)")
        con.execute(f"attach {_sql_literal(target)} as destino")
        con.execute("copy from database origen to destino")


def content_fingerprint(path: Path) -> str:
    """Calcula un hash SHA-256 del contenido de todas las tablas de la base.

    Las filas se ordenan antes de calcular el hash, así que el resultado solo
    depende de los datos, no de cómo estén guardados en el archivo.

    Args:
        path: Base DuckDB.

    Returns:
        Hash hexadecimal del contenido.
    """
    digest = hashlib.sha256()
    with duckdb.connect(str(path), read_only=True) as con:
        tables = con.execute(
            "select table_schema, table_name from information_schema.tables "
            "where table_type = 'BASE TABLE' order by 1, 2"
        ).fetchall()
        for schema, table in tables:
            digest.update(f"{schema}.{table}\n".encode())
            rows = con.execute(
                f'select * from "{schema}"."{table}" order by all'
            ).fetchall()
            for row in rows:
                digest.update(repr(row).encode())
                digest.update(b"\n")
    return digest.hexdigest()


def main() -> None:
    """Genera la copia compacta y su huella en el directorio destino."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="base DuckDB generada")
    parser.add_argument("target_dir", type=Path, help="directorio de publicación")
    args = parser.parse_args()

    if not args.source.exists():
        sys.exit(f"No existe la base {args.source}")
    target = args.target_dir / DB_FILENAME
    compact_copy(args.source, target)
    fingerprint = content_fingerprint(target)
    (args.target_dir / FINGERPRINT_FILENAME).write_text(
        fingerprint + "\n", encoding="utf-8"
    )
    size_kb = target.stat().st_size / 1024
    print(f"Base compacta: {target} ({size_kb:.0f} KB), huella {fingerprint[:12]}")


if __name__ == "__main__":
    main()
