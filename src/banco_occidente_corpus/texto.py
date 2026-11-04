"""Normalizacion de texto compartida por la evaluacion y el Arqueo."""

from __future__ import annotations

import unicodedata


def normalizar(texto: str) -> str:
    """Minusculas y sin tildes, para comparar terminos.

    Aplica ``casefold`` y la forma NFKD, y elimina las marcas combinantes, de
    modo que «LÍNEA», «línea» y «linea» quedan iguales.
    """
    descompuesto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))
