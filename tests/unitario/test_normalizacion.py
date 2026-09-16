"""Tests unitarios: funciones puras, sin red ni base de datos.

Ejecutar con: pytest tests/unitario
"""

from src.normalize import normalizar_tecnologias


def test_normaliza_variantes_al_nombre_canonico(catalogo_tecnologias):
    entrada = ["python", "REACT.JS", "Apache Airflow"]
    resultado = normalizar_tecnologias(entrada, catalogo_tecnologias)
    assert resultado == ["Python", "React", "Airflow"]


def test_ignora_tecnologias_fuera_de_catalogo(catalogo_tecnologias):
    entrada = ["python", "cobol-experimental-2000"]
    resultado = normalizar_tecnologias(entrada, catalogo_tecnologias)
    assert resultado == ["Python"]


def test_no_duplica_tecnologias_repetidas(catalogo_tecnologias):
    entrada = ["python", "Python", "PYTHON"]
    resultado = normalizar_tecnologias(entrada, catalogo_tecnologias)
    assert resultado == ["Python"]


def test_devuelve_lista_vacia_si_no_hay_tecnologias(catalogo_tecnologias):
    assert normalizar_tecnologias([], catalogo_tecnologias) == []
