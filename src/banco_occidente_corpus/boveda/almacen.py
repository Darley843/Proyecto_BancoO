"""Almacén vectorial de la Bóveda: contrato mínimo y persistencia con Chroma.

El protocolo permite sustituir Chroma en las pruebas y en el Arqueo sin tocar
`indice.py`. La colección se crea con distancia coseno fijada al crearla.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

#: Nombre de la colección por defecto dentro de Chroma.
COLECCION_POR_DEFECTO: str = "boveda"
#: Métrica exigida por el diseño; se fija en los metadatos de la colección.
METRICA_POR_DEFECTO: str = "cosine"


@dataclass(frozen=True, slots=True)
class Coincidencia:
    """Fragmento devuelto por el almacén, con su distancia y su similitud."""

    id: str
    documento: str
    metadatos: dict[str, Any]
    distancia: float

    @property
    def similitud(self) -> float:
        """Similitud coseno equivalente a `1 - distancia`."""
        return 1.0 - self.distancia


class AlmacenVectorial(Protocol):
    """Contrato de un almacén de vectores persistente."""

    def crear(self) -> None:
        """Crea la colección si no existe."""
        ...

    def agregar(
        self,
        ids: Sequence[str],
        vectores: Sequence[Sequence[float]],
        documentos: Sequence[str],
        metadatos: Sequence[dict[str, Any]],
    ) -> None:
        """Inserta vectores con su documento y sus metadatos."""
        ...

    def buscar(self, vector: Sequence[float], k: int = 5) -> list[Coincidencia]:
        """Devuelve las k coincidencias más cercanas por distancia coseno."""
        ...

    def vectores(self, ids: Sequence[str]) -> dict[str, list[float]]:
        """Devuelve los vectores guardados de los ids que existan."""
        ...

    def contar(self) -> int:
        """Devuelve el número de vectores almacenados."""
        ...

    def reiniciar(self) -> None:
        """Borra todos los vectores y vuelve a crear la colección vacía."""
        ...


class ChromaAlmacen:
    """Almacén persistente en `data/boveda/chroma` con métrica coseno."""

    def __init__(
        self,
        ruta: Path,
        coleccion: str = COLECCION_POR_DEFECTO,
        metrica: str = METRICA_POR_DEFECTO,
    ) -> None:
        """Guarda la ruta y los metadatos con los que se creará la colección."""
        self._ruta = ruta
        self._nombre = coleccion
        self._metrica = metrica
        self._cliente: Any | None = None
        self._coleccion: Any | None = None

    @property
    def ruta(self) -> Path:
        """Ruta en disco del índice de Chroma."""
        return self._ruta

    @property
    def coleccion(self) -> str:
        """Nombre de la colección."""
        return self._nombre

    @property
    def metrica(self) -> str:
        """Métrica de distancia con la que se crea la colección."""
        return self._metrica

    def crear(self) -> None:
        """Crea la colección con la métrica configurada y sin embedder propio."""
        if self._coleccion is not None:
            return
        self._ruta.mkdir(parents=True, exist_ok=True)
        if self._cliente is None:
            import chromadb

            self._cliente = chromadb.PersistentClient(path=str(self._ruta))
        self._coleccion = self._cliente.get_or_create_collection(
            name=self._nombre,
            metadata={"hnsw:space": self._metrica},
            embedding_function=None,
        )

    def agregar(
        self,
        ids: Sequence[str],
        vectores: Sequence[Sequence[float]],
        documentos: Sequence[str],
        metadatos: Sequence[dict[str, Any]],
    ) -> None:
        """Inserta un lote de vectores ya calculados."""
        if not (len(ids) == len(vectores) == len(documentos) == len(metadatos)):
            raise ValueError("ids, vectores, documentos y metadatos deben tener el mismo tamaño")
        if not ids:
            return
        self.crear()
        assert self._coleccion is not None
        self._coleccion.add(
            ids=list(ids),
            embeddings=[list(vector) for vector in vectores],
            documents=list(documentos),
            metadatas=list(metadatos),
        )

    def buscar(self, vector: Sequence[float], k: int = 5) -> list[Coincidencia]:
        """Devuelve las k coincidencias más cercanas, con distancia coseno."""
        if k <= 0:
            raise ValueError("k debe ser mayor que cero")
        self.crear()
        assert self._coleccion is not None
        resultado = self._coleccion.query(
            query_embeddings=[list(vector)],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )
        ids = resultado.get("ids", [[]])[0]
        documentos = resultado.get("documents", [[]])[0]
        metadatos = resultado.get("metadatas", [[]])[0]
        distancias = resultado.get("distances", [[]])[0]
        return [
            Coincidencia(
                id=str(identificador),
                documento=str(documento or ""),
                metadatos=dict(datos or {}),
                distancia=float(distancia),
            )
            for identificador, documento, datos, distancia in zip(
                ids, documentos, metadatos, distancias, strict=True
            )
        ]

    def vectores(self, ids: Sequence[str]) -> dict[str, list[float]]:
        """Lee del índice los vectores ya guardados, sin llamar al modelo."""
        if not ids:
            return {}
        self.crear()
        assert self._coleccion is not None
        resultado = self._coleccion.get(ids=list(ids), include=["embeddings"])
        identificadores = resultado.get("ids")
        incrustaciones = resultado.get("embeddings")
        if not identificadores or incrustaciones is None:
            return {}
        return {
            str(identificador): [float(valor) for valor in vector]
            for identificador, vector in zip(identificadores, incrustaciones, strict=True)
        }

    def contar(self) -> int:
        """Cuenta los vectores de la colección."""
        self.crear()
        assert self._coleccion is not None
        return int(self._coleccion.count())

    def metrica_almacenada(self) -> str:
        """Devuelve la métrica que declara la colección ya creada en Chroma."""
        self.crear()
        assert self._coleccion is not None
        return str((self._coleccion.metadata or {}).get("hnsw:space", ""))

    def reiniciar(self) -> None:
        """Borra la colección y la vuelve a crear vacía con la misma métrica."""
        self.crear()
        assert self._cliente is not None
        assert self._coleccion is not None
        self._cliente.delete_collection(self._nombre)
        self._coleccion = None
        self.crear()
