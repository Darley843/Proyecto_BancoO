"""Selección del voluntario por fila y silla, sin datos personales.

En vivo se usa ``secrets.SystemRandom``; en las pruebas se inyecta una semilla o
un generador para que la misma selección se repita. La selección no se guarda,
no se envía al modelo y no identifica a nadie: solo dice qué silla pasa.

Las pruebas viven en ``test/test_escena_voluntario.py``.
"""

from __future__ import annotations

import random
import secrets
import tomllib
from pathlib import Path
from typing import Protocol

from .contratos import SeleccionVoluntario

RUTA_CONFIG = Path(__file__).resolve().parents[3] / "config" / "escena.toml"
FILAS_POR_DEFECTO = 8
SILLAS_POR_DEFECTO = 6
MAXIMO_FILAS = 100
MAXIMO_SILLAS = 100


class GeneradorAzar(Protocol):
    """Lo mínimo que se le pide a un generador: elegir un entero en un rango."""

    def randint(self, a: int, b: int) -> int:
        """Devuelve un entero entre ``a`` y ``b``, ambos incluidos."""


def rangos_voluntario(ruta: Path | None = None) -> tuple[int, int]:
    """Lee las filas y sillas del salón desde ``config/escena.toml``.

    Args:
        ruta: archivo alternativo de la escena.

    Returns:
        Las filas y las sillas, en ese orden.

    Raises:
        ValueError: si los valores no son enteros entre 1 y 100.
    """
    archivo = Path(ruta) if ruta is not None else RUTA_CONFIG
    filas = FILAS_POR_DEFECTO
    sillas = SILLAS_POR_DEFECTO
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    seccion = datos.get("voluntario", {})
    if isinstance(seccion, dict):
        filas = int(seccion.get("filas", filas))
        sillas = int(seccion.get("sillas", sillas))
    if not 1 <= filas <= MAXIMO_FILAS:
        raise ValueError(f"las filas del voluntario deben estar entre 1 y {MAXIMO_FILAS}")
    if not 1 <= sillas <= MAXIMO_SILLAS:
        raise ValueError(f"las sillas del voluntario deben estar entre 1 y {MAXIMO_SILLAS}")
    return filas, sillas


def seleccionar_voluntario(
    *,
    filas: int | None = None,
    sillas: int | None = None,
    semilla: int | None = None,
    generador: GeneradorAzar | None = None,
    fila: int | None = None,
    silla: int | None = None,
    ruta: Path | None = None,
) -> SeleccionVoluntario:
    """Elige una fila y una silla, al azar o a mano, sin guardar nada.

    Args:
        filas: filas del salón; por defecto las del TOML.
        sillas: sillas por fila; por defecto las del TOML.
        semilla: semilla para repetir la selección en pruebas.
        generador: generador ya construido; no se puede combinar con `semilla`.
        fila: fila elegida a mano; exige también `silla`.
        silla: silla elegida a mano; exige también `fila`.
        ruta: archivo alternativo de la escena.

    Returns:
        La selección, con su método (`azar` o `manual`).

    Raises:
        ValueError: si los rangos no son válidos, si se combinan `semilla` y
            `generador`, o si la selección manual está incompleta o fuera de
            rango.
    """
    if semilla is not None and generador is not None:
        raise ValueError("usa una semilla o un generador, no los dos")
    if filas is None or sillas is None:
        leidas = rangos_voluntario(ruta)
        total_filas = filas if filas is not None else leidas[0]
        total_sillas = sillas if sillas is not None else leidas[1]
    else:
        total_filas, total_sillas = filas, sillas
    if not 1 <= total_filas <= MAXIMO_FILAS or not 1 <= total_sillas <= MAXIMO_SILLAS:
        raise ValueError("las filas y sillas deben estar entre 1 y 100")
    manual = fila is not None or silla is not None
    if manual:
        if fila is None or silla is None:
            raise ValueError("la selección manual exige fila y silla")
        if not 1 <= fila <= total_filas or not 1 <= silla <= total_sillas:
            raise ValueError("la fila o la silla está fuera del rango del salón")
        return SeleccionVoluntario(
            fila=fila,
            silla=silla,
            filas=total_filas,
            sillas=total_sillas,
            metodo="manual",
        )
    azar: GeneradorAzar = generador or (
        random.Random(semilla) if semilla is not None else secrets.SystemRandom()
    )
    return SeleccionVoluntario(
        fila=azar.randint(1, total_filas),
        silla=azar.randint(1, total_sillas),
        filas=total_filas,
        sillas=total_sillas,
        metodo="azar",
    )
