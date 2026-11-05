"""Búsqueda y comparación deterministas sobre las filas del Tablero.

No hay modelo ni red: solo normalización de texto y comparación de valores.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ..texto import normalizar
from .tipos import Fila

#: Sufijo de franquicia que se ignora al emparejar dos filas.
_FRANQUICIA = re.compile(r"\s*\((visa|mastercard)\)\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Comparacion:
    """Diferencias entre dos grupos de filas del Tablero."""

    solo_izquierda: tuple[Fila, ...]
    solo_derecha: tuple[Fila, ...]
    distintas: tuple[tuple[Fila, Fila], ...]

    @property
    def vacia(self) -> bool:
        """Indica si los dos grupos son equivalentes."""
        return not (self.solo_izquierda or self.solo_derecha or self.distintas)


def buscar_filas(filas: Sequence[Fila], consulta: str, categoria: str | None = None) -> list[Fila]:
    """Filtra por concepto y, opcionalmente, por categoría.

    Args:
        filas: filas del Tablero.
        consulta: términos a buscar en concepto y categoría.
        categoria: texto que debe aparecer en la categoría, si se indica.

    Returns:
        Las filas que contienen todos los términos, en el orden original.
    """
    terminos = normalizar(consulta).split()
    objetivo = normalizar(categoria) if categoria else ""
    resultado: list[Fila] = []
    for fila in filas:
        texto = normalizar(f"{fila.concepto} {fila.categoria}")
        if not all(termino in texto for termino in terminos):
            continue
        if objetivo and objetivo not in normalizar(fila.categoria):
            continue
        resultado.append(fila)
    return resultado


def comparar_filas(izquierda: Sequence[Fila], derecha: Sequence[Fila]) -> Comparacion:
    """Compara dos grupos y devuelve filas exclusivas y valores distintos."""
    mapa_izquierda = _por_concepto(izquierda)
    mapa_derecha = _por_concepto(derecha)
    solo_izquierda = tuple(
        fila for clave, fila in mapa_izquierda.items() if clave not in mapa_derecha
    )
    solo_derecha = tuple(
        fila for clave, fila in mapa_derecha.items() if clave not in mapa_izquierda
    )
    distintas: list[tuple[Fila, Fila]] = []
    for clave, fila in mapa_izquierda.items():
        otra = mapa_derecha.get(clave)
        if otra is not None and _valores(fila) != _valores(otra):
            distintas.append((fila, otra))
    return Comparacion(
        solo_izquierda=solo_izquierda,
        solo_derecha=solo_derecha,
        distintas=tuple(distintas),
    )


def _por_concepto(filas: Sequence[Fila]) -> dict[str, Fila]:
    """Indexa por concepto sin franquicia; conserva la primera aparición."""
    mapa: dict[str, Fila] = {}
    for fila in filas:
        clave = _FRANQUICIA.sub("", normalizar(fila.concepto)).strip()
        mapa.setdefault(clave, fila)
    return mapa


def _valores(fila: Fila) -> tuple[str, str, str]:
    """Valores que definen si dos filas son equivalentes."""
    return (fila.valor, fila.moneda, fila.periodicidad)
