"""Embeddings locales de la Bóveda: Ollama con prefijos de tarea opcionales.

No hay clave ni costo: el modelo corre en Ollama. El destino por defecto es
`http://127.0.0.1:11434`, pero `base_url` es configurable y toda petición lleva
un `timeout` explícito para que una Ollama colgada no bloquee `make indice`. El
proveedor es inyectable para que las pruebas usen `DeterministicFakeEmbedding` y
nunca llamen a Ollama.
"""

from __future__ import annotations

from typing import Any

from langchain_core.embeddings import Embeddings

from .configuracion import (
    PREFIJO_CONSULTA,
    PREFIJO_DOCUMENTO,
    ConfiguracionEmbeddings,
    cargar_configuracion_embeddings,
)


class EmbeddingsConPrefijos(Embeddings):
    """Envuelve un proveedor de embeddings y aplica los prefijos de nomic."""

    def __init__(self, base: Embeddings, *, prefijos: bool = True) -> None:
        """Guarda el proveedor subyacente y la bandera de prefijos."""
        self._base = base
        self._prefijos = prefijos

    @property
    def prefijos(self) -> bool:
        """Indica si los prefijos están activos."""
        return self._prefijos

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vectoriza documentos con el prefijo `search_document: `."""
        return self._base.embed_documents([self._documento(texto) for texto in texts])

    def embed_query(self, text: str) -> list[float]:
        """Vectoriza una consulta con el prefijo `search_query: `."""
        return self._base.embed_query(self._consulta(text))

    def _documento(self, texto: str) -> str:
        """Aplica el prefijo de documento si está activo."""
        return f"{PREFIJO_DOCUMENTO}{texto}" if self._prefijos else texto

    def _consulta(self, texto: str) -> str:
        """Aplica el prefijo de consulta si está activo."""
        return f"{PREFIJO_CONSULTA}{texto}" if self._prefijos else texto


def opciones_ollama(configuracion: ConfiguracionEmbeddings) -> dict[str, Any]:
    """Devuelve los parámetros de `OllamaEmbeddings`, con timeout garantizado.

    Args:
        configuracion: parámetros del plano de embeddings.

    Returns:
        Diccionario con modelo, `base_url` y `client_kwargs` con el timeout.
    """
    return {
        "model": configuracion.modelo,
        "base_url": configuracion.base_url,
        "client_kwargs": {"timeout": configuracion.timeout},
    }


def crear_embeddings(
    configuracion: ConfiguracionEmbeddings | None = None,
    *,
    base: Embeddings | None = None,
    **opciones: Any,
) -> Embeddings:
    """Devuelve el proveedor de embeddings de la Bóveda.

    Args:
        configuracion: parámetros del plano de embeddings; se cargan del TOML si falta.
        base: proveedor alternativo (pruebas); si se indica, no se crea Ollama.
        **opciones: parámetros adicionales para `OllamaEmbeddings` (por ejemplo `num_ctx`).

    Returns:
        Un `Embeddings` que aplica los prefijos cuando la configuración lo pide.
    """
    ajustes = configuracion or cargar_configuracion_embeddings()
    if base is None:
        from langchain_ollama import OllamaEmbeddings

        parametros = opciones_ollama(ajustes)
        parametros.update(opciones)
        parametros["client_kwargs"] = {
            "timeout": ajustes.timeout,
            **dict(parametros.get("client_kwargs") or {}),
        }
        base = OllamaEmbeddings(**parametros)
    if not ajustes.prefijos:
        return base
    return EmbeddingsConPrefijos(base, prefijos=True)
