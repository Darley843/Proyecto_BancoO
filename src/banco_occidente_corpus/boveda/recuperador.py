"""Recuperador híbrido de la Bóveda: vectorial + BM25 con pesos configurables.

El orden final lo decide `EnsembleRetriever`. La consulta se vectoriza una sola
vez por búsqueda, y `puntaje` se calcula contra los vectores que ya están
guardados en el índice, de modo que significa siempre `1 - distancia coseno`,
también para los fragmentos que solo devolvió BM25. El módulo no hace red propia:
embeddings y almacén se inyectan.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever

from ..config import Config
from ..texto import normalizar
from .almacen import AlmacenVectorial, crear_almacen
from .configuracion import ConfiguracionRecuperacion, cargar_configuracion_recuperacion
from .embeddings import crear_embeddings
from .fragmentos import Alcance
from .indice import comprobar_almacen, leer_fragmentos
from .tipos import Fragmento

#: k mínimo con el que se consultan los recuperadores antes de fusionar.
K_MINIMO: int = 5


class RecuperadorVectorial(BaseRetriever):
    """Adapta el almacén vectorial de la Bóveda al contrato de LangChain."""

    almacen: Any
    embeddings: Any
    k: int = K_MINIMO
    #: Vector de la consulta ya calculado; si falta, se pide a los embeddings.
    vector: Sequence[float] | None = None
    #: Igualdad por campos del payload, por ejemplo `{"seccion": "identidad"}`.
    filtro: Mapping[str, Any] | None = None

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun | None = None,
    ) -> list[Document]:
        """Devuelve los k fragmentos más cercanos del almacén."""
        vector = self.vector if self.vector is not None else self.embeddings.embed_query(query)
        if self.filtro:
            coincidencias = self.almacen.buscar(vector, k=self.k, filtro=self.filtro)
        else:
            coincidencias = self.almacen.buscar(vector, k=self.k)
        return [
            Document(
                page_content=coincidencia.documento,
                metadata={**coincidencia.metadatos, "id": coincidencia.id},
            )
            for coincidencia in coincidencias
        ]


class RecuperadorHibrido:
    """Recuperador que combina similitud vectorial y BM25 con pesos."""

    def __init__(
        self,
        almacen: AlmacenVectorial,
        embeddings: Embeddings,
        fragmentos: Sequence[Fragmento],
        configuracion: ConfiguracionRecuperacion | None = None,
    ) -> None:
        """Prepara los dos recuperadores y el conjunto de fragmentos del alcance.

        Args:
            almacen: índice vectorial ya construido.
            embeddings: proveedor de embeddings (con o sin prefijos).
            fragmentos: fragmentos del alcance activo, fuente de BM25.
            configuracion: k y pesos; se cargan del TOML si falta.
        """
        if not fragmentos:
            raise ValueError("El recuperador necesita al menos un fragmento indexado")
        ajustes = configuracion or cargar_configuracion_recuperacion()
        self._embeddings = embeddings
        self._por_id = {fragmento.id: fragmento for fragmento in fragmentos}
        self._documentos = [
            Document(page_content=fragmento.texto, metadata=_metadatos(fragmento))
            for fragmento in fragmentos
        ]
        self._k = max(ajustes.k, K_MINIMO)
        self._almacen = almacen
        self._pesos = _normalizar_pesos(ajustes)
        self._bm25 = BM25Retriever.from_documents(
            self._documentos, k=self._k, preprocess_func=_tokenizar
        )

    def buscar(self, consulta: str, k: int = 5) -> list[Fragmento]:
        """Devuelve hasta k fragmentos ordenados por relevancia y con puntaje.

        La consulta se vectoriza una sola vez. Ese vector alimenta la búsqueda
        vectorial y, después de la fusión, el `puntaje` de cada candidato se
        calcula con los vectores que ya están guardados en el índice.
        """
        if k <= 0:
            raise ValueError("k debe ser mayor que cero")
        vector_consulta = self._embeddings.embed_query(consulta)
        # El recuperador vectorial se arma por búsqueda para pasarle el vector
        # ya calculado sin compartir estado entre peticiones concurrentes.
        vectorial = RecuperadorVectorial(
            almacen=self._almacen,
            embeddings=self._embeddings,
            k=self._k,
            vector=vector_consulta,
        )
        ensemble = EnsembleRetriever(
            retrievers=[vectorial, self._bm25],
            weights=self._pesos,
        )
        documentos = ensemble.invoke(consulta)[:k]
        if not documentos:
            return []

        vectores = self._vectores_guardados(documentos)
        resultados: list[Fragmento] = []
        for documento in documentos:
            base = self._fragmento(documento)
            vector = vectores.get(base.id)
            puntaje = 0.0 if vector is None else _similitud_coseno(vector_consulta, vector)
            resultados.append(replace(base, puntaje=puntaje))
        return resultados

    def _vectores_guardados(self, documentos: Sequence[Document]) -> dict[str, list[float]]:
        """Lee los vectores de los fragmentos recuperados en el índice.

        Si un fragmento aparece en BM25 pero no en el índice (por ejemplo, con
        Gold más nuevo que Chroma), se vectoriza solo ese texto para no dejar su
        `puntaje` en cero.
        """
        ids = [str(documento.metadata.get("id", "")) for documento in documentos]
        vectores = self._almacen.vectores([identificador for identificador in ids if identificador])
        faltantes = [
            documento
            for documento, identificador in zip(documentos, ids, strict=True)
            if identificador and identificador not in vectores
        ]
        if faltantes:
            calculados = self._embeddings.embed_documents(
                [documento.page_content for documento in faltantes]
            )
            for documento, vector in zip(faltantes, calculados, strict=True):
                vectores[str(documento.metadata.get("id", ""))] = vector
        return vectores

    def _fragmento(self, documento: Document) -> Fragmento:
        """Recupera el fragmento original o lo reconstruye desde sus metadatos."""
        identificador = str(documento.metadata.get("id", ""))
        existente = self._por_id.get(identificador)
        if existente is not None:
            return existente
        return Fragmento(
            id=identificador,
            texto=documento.page_content,
            url=str(documento.metadata.get("url", "")),
            titulo=str(documento.metadata.get("titulo", "")),
            seccion=str(documento.metadata.get("seccion", "")),
            encabezado=str(documento.metadata.get("encabezado", "")),
            tipo=documento.metadata.get("tipo", "pagina"),
            tokens=int(documento.metadata.get("tokens", 0)),
        )


def crear_recuperador(
    config: Config,
    alcance: Alcance = "base",
    *,
    configuracion: ConfiguracionRecuperacion | None = None,
    embeddings: Embeddings | None = None,
    almacen: AlmacenVectorial | None = None,
) -> RecuperadorHibrido:
    """Construye el recuperador con los fragmentos y el índice del alcance.

    Args:
        config: configuración con las rutas del corpus.
        alcance: alcance indexado que se quiere consultar.
        configuracion: k y pesos; se cargan del TOML si falta.
        embeddings: proveedor alternativo; por defecto Ollama.
        almacen: almacén alternativo; por defecto el motor de `[almacen].tipo`.

    Returns:
        Un `RecuperadorHibrido` listo para `buscar`.
    """
    proveedor = embeddings or crear_embeddings()
    if almacen is None:
        comprobar_almacen(config)
        destino = crear_almacen(config)
    else:
        destino = almacen
    fragmentos = leer_fragmentos(config, alcance)
    return RecuperadorHibrido(destino, proveedor, fragmentos, configuracion)


def _tokenizar(texto: str) -> list[str]:
    """Divide el texto en palabras en minúsculas y sin tildes para BM25.

    Args:
        texto: texto original del fragmento o de la consulta.

    Returns:
        Las palabras alfanuméricas normalizadas; el resto de signos se descarta.
    """
    return re.findall(r"\w+", normalizar(texto))


def _normalizar_pesos(configuracion: ConfiguracionRecuperacion) -> list[float]:
    """Normaliza los pesos a suma 1, como exige `EnsembleRetriever`."""
    total = configuracion.peso_vectorial + configuracion.peso_bm25
    if total <= 0:
        raise ValueError("Los pesos del recuperador deben sumar más que cero")
    return [
        configuracion.peso_vectorial / total,
        configuracion.peso_bm25 / total,
    ]


def _metadatos(fragmento: Fragmento) -> dict[str, Any]:
    """Convierte un fragmento en metadatos planos para LangChain."""
    return {
        "id": fragmento.id,
        "url": fragmento.url,
        "titulo": fragmento.titulo,
        "seccion": fragmento.seccion,
        "encabezado": fragmento.encabezado,
        "tipo": fragmento.tipo,
        "tokens": fragmento.tokens,
    }


def _similitud_coseno(izquierda: Sequence[float], derecha: Sequence[float]) -> float:
    """Similitud coseno acotada a [0, 1]."""
    producto = sum(a * b for a, b in zip(izquierda, derecha, strict=True))
    norma_izquierda = math.sqrt(sum(a * a for a in izquierda))
    norma_derecha = math.sqrt(sum(b * b for b in derecha))
    if norma_izquierda == 0 or norma_derecha == 0:
        return 0.0
    return max(0.0, min(1.0, producto / (norma_izquierda * norma_derecha)))
