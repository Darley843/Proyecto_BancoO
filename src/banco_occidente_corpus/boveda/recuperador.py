"""Recuperador híbrido de la Bóveda: vectorial + BM25 con pesos configurables.

El orden final lo decide `EnsembleRetriever`. La consulta se vectoriza una sola
vez por búsqueda, y `puntaje` se calcula contra los vectores que ya están
guardados en el índice, de modo que significa siempre `1 - distancia coseno`,
también para los fragmentos que solo devolvió BM25. El módulo no hace red propia:
embeddings y almacén se inyectan.

`fragmentos_extra` permite añadir fragmentos que no están en el índice (la demo
de blindaje del caso 5): su vector se calcula una vez al construir y
`AlmacenConExtras` los hace competir por coseno con los guardados, sin escribir
en Qdrant, Chroma ni en el JSONL.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever

from ..config import Config
from ..texto import normalizar
from .almacen import AlmacenVectorial, Coincidencia, crear_almacen
from .configuracion import ConfiguracionRecuperacion, cargar_configuracion_recuperacion
from .embeddings import crear_embeddings
from .fragmentos import Alcance
from .indice import comprobar_almacen, leer_fragmentos
from .tipos import Fragmento

#: k mínimo con el que se consultan los recuperadores antes de fusionar.
K_MINIMO: int = 5


class AlmacenBusqueda(Protocol):
    """Parte del almacén vectorial que necesita el recuperador: buscar y vectores."""

    def buscar(
        self,
        vector: Sequence[float],
        k: int = 5,
        filtro: Mapping[str, Any] | None = None,
    ) -> list[Coincidencia]:
        """Devuelve las k coincidencias más cercanas por distancia coseno."""
        ...

    def vectores(self, ids: Sequence[str]) -> dict[str, list[float]]:
        """Devuelve los vectores guardados de los ids originales que existan."""
        ...


@dataclass(frozen=True, slots=True)
class VectorExtra:
    """Fragmento que no vive en el índice, con su vector ya calculado."""

    fragmento: Fragmento
    vector: tuple[float, ...]


class AlmacenConExtras:
    """Consulta un almacén y hace competir vectores extra con los guardados.

    Los vectores extra se ordenan por su coseno real junto a las coincidencias
    del almacén y solo sobreviven si entran en el top k, igual que un fragmento
    indexado. El almacén y el disco no se modifican: es una capa de lectura en
    memoria, pensada para el fragmento de prueba de la demo de blindaje.
    """

    def __init__(self, base: AlmacenBusqueda, extras: Sequence[VectorExtra]) -> None:
        """Guarda el almacén real y los vectores calculados fuera del índice."""
        self._base = base
        self._extras = tuple(extras)

    def buscar(
        self,
        vector: Sequence[float],
        k: int = 5,
        filtro: Mapping[str, Any] | None = None,
    ) -> list[Coincidencia]:
        """Devuelve el top k fusionando el almacén con los vectores extra."""
        if k <= 0:
            raise ValueError("k debe ser mayor que cero")
        if filtro:
            coincidencias = list(self._base.buscar(vector, k=k, filtro=filtro))
        else:
            coincidencias = list(self._base.buscar(vector, k=k))
        for extra in self._extras:
            metadatos = _metadatos(extra.fragmento)
            if filtro and any(metadatos.get(clave) != valor for clave, valor in filtro.items()):
                continue
            coincidencias.append(
                Coincidencia(
                    id=extra.fragmento.id,
                    documento=extra.fragmento.texto,
                    metadatos=metadatos,
                    distancia=1.0 - _similitud_coseno(vector, extra.vector),
                )
            )
        coincidencias.sort(key=lambda coincidencia: coincidencia.distancia)
        return coincidencias[:k]

    def vectores(self, ids: Sequence[str]) -> dict[str, list[float]]:
        """Devuelve los vectores del almacén más los extra que estén en `ids`."""
        guardados = self._base.vectores(ids)
        pedidos = set(ids)
        for extra in self._extras:
            if extra.fragmento.id in pedidos:
                guardados[extra.fragmento.id] = list(extra.vector)
        return guardados


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
        almacen: AlmacenBusqueda,
        embeddings: Embeddings,
        fragmentos: Sequence[Fragmento],
        configuracion: ConfiguracionRecuperacion | None = None,
        *,
        fragmentos_extra: Sequence[Fragmento] = (),
    ) -> None:
        """Prepara los dos recuperadores y el conjunto de fragmentos del alcance.

        Args:
            almacen: índice vectorial ya construido.
            embeddings: proveedor de embeddings (con o sin prefijos).
            fragmentos: fragmentos del alcance activo, fuente de BM25.
            configuracion: k y pesos; se cargan del TOML si falta.
            fragmentos_extra: fragmentos que no están en el índice (demo de
                blindaje). Su vector se calcula una sola vez aquí y entra en
                ambas ramas como si estuvieran indexados.
        """
        if not fragmentos:
            raise ValueError("El recuperador necesita al menos un fragmento indexado")
        ajustes = configuracion or cargar_configuracion_recuperacion()
        extras = tuple(fragmentos_extra)
        todos = [*fragmentos, *extras]
        self._embeddings = embeddings
        self._por_id = {fragmento.id: fragmento for fragmento in todos}
        self._documentos = [
            Document(page_content=fragmento.texto, metadata=_metadatos(fragmento))
            for fragmento in todos
        ]
        self._k = max(ajustes.k, K_MINIMO)
        self._almacen: AlmacenBusqueda = almacen
        if extras:
            vectores = embeddings.embed_documents([extra.texto for extra in extras])
            self._almacen = AlmacenConExtras(
                almacen,
                tuple(
                    VectorExtra(fragmento=extra, vector=tuple(vector))
                    for extra, vector in zip(extras, vectores, strict=True)
                ),
            )
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
    fragmentos_extra: Sequence[Fragmento] = (),
) -> RecuperadorHibrido:
    """Construye el recuperador con los fragmentos y el índice del alcance.

    Args:
        config: configuración con las rutas del corpus.
        alcance: alcance indexado que se quiere consultar.
        configuracion: k y pesos; se cargan del TOML si falta.
        embeddings: proveedor alternativo; por defecto Ollama.
        almacen: almacén alternativo; por defecto el motor de `[almacen].tipo`.
        fragmentos_extra: fragmentos en memoria que no están en el índice; su
            vector se calcula una vez y compite con los indexados sin escribir
            en el almacén. La Sucursal lo usa solo para la demo de blindaje.

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
    return RecuperadorHibrido(
        destino, proveedor, fragmentos, configuracion, fragmentos_extra=fragmentos_extra
    )


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
