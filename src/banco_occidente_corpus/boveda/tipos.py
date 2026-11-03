"""Tipos compartidos de la Bóveda: fragmento recuperable y contrato del recuperador."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

TipoFragmento = Literal["pagina", "pdf", "video", "hecho verificado"]


@dataclass(frozen=True, slots=True)
class Fragmento:
    """Unidad recuperable del corpus, con su fuente y su similitud."""

    id: str
    texto: str
    url: str
    titulo: str
    seccion: str
    encabezado: str
    tipo: TipoFragmento
    tokens: int
    puntaje: float = 0.0


class Recuperador(Protocol):
    """Contrato de cualquier recuperador de la Bóveda."""

    def buscar(self, consulta: str, k: int = 5) -> list[Fragmento]:
        """Devuelve hasta k fragmentos ordenados por relevancia."""
        ...
