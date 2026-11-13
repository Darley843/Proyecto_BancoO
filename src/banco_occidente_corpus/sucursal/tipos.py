"""Tipos de la Sucursal: el turno que recibe cada pregunta."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: Letras del digiturno: Bóveda, Tablero o rechazo.
Letra = Literal["B", "T", "X"]


@dataclass(frozen=True, slots=True)
class Turno:
    """Turno asignado a una pregunta, con su letra y el motivo.

    ``motivo_residual`` solo se usa cuando el motivo empieza por ``perfil:``:
    guarda el motivo de la pregunta que sigue después del perfil para que el
    nodo ``perfil`` sepa a qué ruta mandarla. No se expone en la API.
    """

    numero: int
    letra: Letra
    motivo: str
    motivo_residual: str = ""
