"""Pruebas sin red de la normalizacion compartida de texto."""

from __future__ import annotations

import unicodedata

import pytest

from banco_occidente_corpus import texto
from banco_occidente_corpus.arqueo.metricas import acierta_terminos
from banco_occidente_corpus.asistente import evaluacion
from banco_occidente_corpus.asistente.evaluacion import contar_terminos

#: Muestras con mayusculas, tildes y formas compuesta y descompuesta.
MUESTRAS = [
    "LÍNEA de atención",
    "petición",
    unicodedata.normalize("NFD", "petición"),
    "ÁÉÍÓÚÜÑ",
    "PQR sin tildes",
    "",
]


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("LÍNEA", "linea"),
        ("petición", "peticion"),
        (unicodedata.normalize("NFD", "petición"), "peticion"),
        ("ÁÉÍÓÚÜÑ", "aeiouun"),
        ("PQR", "pqr"),
        ("", ""),
    ],
)
def test_normalizar_quita_tildes_y_mayusculas(entrada: str, esperado: str) -> None:
    """``normalizar`` aplica ``casefold``, NFKD y elimina marcas combinantes."""
    # Act
    resultado = texto.normalizar(entrada)

    # Assert
    assert resultado == esperado


def test_evaluacion_reutiliza_la_misma_funcion() -> None:
    """``evaluacion._normalizar`` es exactamente ``texto.normalizar``."""
    # Assert
    assert evaluacion._normalizar is texto.normalizar


@pytest.mark.parametrize("muestra", MUESTRAS)
def test_evaluacion_y_texto_dan_la_misma_salida(muestra: str) -> None:
    """La evaluacion y el modulo compartido normalizan igual cada muestra."""
    # Act
    desde_evaluacion = evaluacion._normalizar(muestra)
    desde_texto = texto.normalizar(muestra)

    # Assert
    assert desde_evaluacion == desde_texto


@pytest.mark.parametrize(
    ("respuesta", "grupos"),
    [
        ("La LÍNEA de atención es 018000.", (("linea",), ("018000",))),
        ("Radica la queja en el PQR.", (("pqr",), ("018000",))),
        ("La petición se radica por el canal.", (("peticion",),)),
        ("Sin coincidencias.", (("cuota",), ("tarifa",))),
    ],
)
def test_acierta_terminos_equivale_a_contar_terminos(
    respuesta: str,
    grupos: tuple[tuple[str, ...], ...],
) -> None:
    """``acierta_terminos`` es True solo si ``contar_terminos`` halla todos los grupos."""
    # Act
    acierto = acierta_terminos(respuesta, grupos)
    encontrados = contar_terminos(respuesta, grupos)

    # Assert
    assert acierto is (encontrados == len(grupos))
