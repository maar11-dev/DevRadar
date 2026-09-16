"""Tests unitarios de la reclasificación de ofertas sin tecnologías (ADR-009)."""

import json
from unittest.mock import patch

import duckdb

from src.db import create_raw_tables
from src.extract import PROMPT_VERSION, clasificar_ofertas_pendientes

RESPUESTA = json.dumps(
    {
        "tecnologias": ["Python"],
        "seniority": None,
        "modalidad": None,
        "salario_min": None,
        "salario_max": None,
    }
)


def _base_con_clasificaciones(con):
    """Cuatro ofertas con distinto estado de clasificación."""
    create_raw_tables(con)
    con.executemany(
        "insert into raw_ofertas (id, titulo, descripcion) values (?, ?, ?)",
        [
            (i, f"Oferta {i}", "texto")
            for i in ("vacia_v1", "vacia_v2", "con_tec", "nueva")
        ],
    )
    filas = [
        # Sin tecnologías y clasificada con el prompt anterior (sin versión).
        ("vacia_v1", [], '{"tecnologias": []}', None),
        # Sin tecnologías, pero ya con el prompt actual: no se repite.
        ("vacia_v2", [], '{"tecnologias": []}', PROMPT_VERSION),
        # Con tecnologías crudas (aunque ninguna esté en el catálogo).
        ("con_tec", [], '{"tecnologias": ["Yocto"]}', None),
    ]
    con.executemany(
        "insert into raw_ofertas_clasificadas (id_oferta, tecnologias, respuesta_llm, "
        "version_prompt, fecha_extraccion) values (?, ?, ?, ?, ?)",
        [(*f, "2026-09-01 00:00:00") for f in filas],
    )


def _ids_reclasificados(con):
    return [
        fila[0]
        for fila in con.execute(
            "select id_oferta from raw_ofertas_clasificadas "
            "where fecha_extraccion > '2026-09-02' order by id_oferta"
        ).fetchall()
    ]


@patch("src.extract.time.sleep")
@patch("src.extract.llamar_llm", return_value=RESPUESTA)
def test_por_defecto_solo_clasifica_ofertas_nuevas(_llm, _sleep):
    with duckdb.connect(":memory:") as con:
        _base_con_clasificaciones(con)
        assert clasificar_ofertas_pendientes(con) == (1, 0)
        assert _ids_reclasificados(con) == ["nueva"]


@patch("src.extract.time.sleep")
@patch("src.extract.llamar_llm", return_value=RESPUESTA)
def test_reclasifica_solo_vacias_de_prompts_anteriores(_llm, _sleep):
    with duckdb.connect(":memory:") as con:
        _base_con_clasificaciones(con)
        assert clasificar_ofertas_pendientes(
            con, reclasificar_sin_tecnologias=True
        ) == (2, 0)
        nuevas = con.execute(
            "select id_oferta, version_prompt from raw_ofertas_clasificadas "
            "where fecha_extraccion > '2026-09-02' order by id_oferta"
        ).fetchall()
        # Una segunda ejecución ya no encuentra nada que reclasificar.
        assert clasificar_ofertas_pendientes(
            con, reclasificar_sin_tecnologias=True
        ) == (0, 0)

    assert nuevas == [("nueva", PROMPT_VERSION), ("vacia_v1", PROMPT_VERSION)]


def test_migracion_anade_columnas_a_bases_antiguas():
    with duckdb.connect(":memory:") as con:
        # Esquema de la base publicada antes de añadir version_prompt.
        con.execute(
            "create table raw_ofertas_clasificadas (id_oferta varchar not null, "
            "tecnologias varchar[], error varchar, respuesta_llm varchar, "
            "fecha_extraccion timestamp not null)"
        )
        create_raw_tables(con)
        create_raw_tables(con)  # idempotente
        columnas = [
            fila[0]
            for fila in con.execute(
                "select column_name from information_schema.columns "
                "where table_name = 'raw_ofertas_clasificadas'"
            ).fetchall()
        ]
    assert "version_prompt" in columnas
