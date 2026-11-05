"""Tipos de la Sucursal: el turno que recibe cada pregunta."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: Letras del digiturno: Bóveda, Tablero o rechazo.
Letra = Literal["B", "T", "X"]


@dataclass(frozen=True, slots=True)
class Turno:
    """Turno asignado a una pregunta, con su letra y el motivo."""

    numero: int
    letra: Letra
    motivo: str
