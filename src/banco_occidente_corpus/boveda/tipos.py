"""Tipos compartidos de la Bóveda: fragmento recuperable y contrato del recuperador."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

#: Tipos de fragmento. ``prueba`` solo existe en memoria para la demo de
#: blindaje del caso 5: nunca se escribe en el JSONL de fragmentos ni en el índice.
TipoFragmento = Literal["pagina", "pdf", "video", "hecho verificado", "prueba"]


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


@runtime_checkable
class Recuperador(Protocol):
    """Contrato de cualquier recuperador de la Bóveda."""

    def buscar(self, consulta: str, k: int = 5) -> list[Fragmento]:
        """Devuelve hasta k fragmentos ordenados por relevancia."""
        ...
