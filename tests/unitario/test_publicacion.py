"""Tests unitarios de la preparación de la base para la rama ``data``."""

import duckdb

from src.db import create_raw_tables
from src.publish_db import compact_copy, content_fingerprint


def _crear_base(ruta, filas):
    with duckdb.connect(str(ruta)) as con:
        create_raw_tables(con)
        con.executemany("insert into raw_ofertas (id, titulo) values (?, ?)", filas)
        con.execute("create view v_ofertas as select id from raw_ofertas")


def test_huella_solo_depende_del_contenido(tmp_path):
    a, b = tmp_path / "a.duckdb", tmp_path / "b.duckdb"
    _crear_base(a, [("1", "Data Engineer"), ("2", "Backend")])
    # Mismos datos insertados en otro orden y con operaciones intermedias.
    _crear_base(b, [("2", "Backend"), ("1", "Data Engineer"), ("3", "temporal")])
    with duckdb.connect(str(b)) as con:
        con.execute("delete from raw_ofertas where id = '3'")

    assert content_fingerprint(a) == content_fingerprint(b)


def test_huella_cambia_si_cambian_los_datos(tmp_path):
    a, b = tmp_path / "a.duckdb", tmp_path / "b.duckdb"
    _crear_base(a, [("1", "Data Engineer")])
    _crear_base(b, [("1", "Data Engineer (remoto)")])

    assert content_fingerprint(a) != content_fingerprint(b)


def test_copia_compacta_conserva_datos_vistas_y_clave_primaria(tmp_path):
    origen, copia = tmp_path / "origen.duckdb", tmp_path / "pub" / "copia.duckdb"
    _crear_base(origen, [("1", "Data Engineer")])

    compact_copy(origen, copia)

    assert content_fingerprint(copia) == content_fingerprint(origen)
    with duckdb.connect(str(copia)) as con:
        assert con.execute("select count(*) from v_ofertas").fetchone() == (1,)
        # La clave primaria se conserva: la ingesta restaurada no duplica ofertas.
        con.execute("insert or ignore into raw_ofertas (id, titulo) values ('1', 'x')")
        assert con.execute("select count(*) from raw_ofertas").fetchone() == (1,)
