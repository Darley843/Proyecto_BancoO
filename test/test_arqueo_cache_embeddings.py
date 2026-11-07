"""Pruebas de la cache de embeddings del Arqueo."""

from __future__ import annotations

from langchain_core.embeddings import Embeddings

from banco_occidente_corpus.arqueo.cache_embeddings import EmbeddingsEnCache


class Contador(Embeddings):
    """Proveedor falso que registra cada llamada."""

    def __init__(self) -> None:
        self.consultas: list[str] = []
        self.lotes: list[list[str]] = []

    def embed_query(self, text: str) -> list[float]:
        """Vectoriza la consulta y registra el texto recibido."""
        self.consultas.append(text)
        return [float(len(text)), 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vectoriza el lote y registra los textos recibidos."""
        self.lotes.append(list(texts))
        return [[float(len(t)), 0.0] for t in texts]


def test_consulta_repetida_se_vectoriza_una_vez() -> None:
    """La misma consulta se vectoriza una sola vez."""
    base = Contador()
    cache = EmbeddingsEnCache(base)

    primero = cache.embed_query("cuota de manejo")
    segundo = cache.embed_query("cuota de manejo")

    assert primero == segundo == [15.0, 1.0]
    assert base.consultas == ["cuota de manejo"]
    assert cache.llamadas == 1


def test_documentos_solo_vectoriza_los_faltantes_y_respeta_el_orden() -> None:
    """Solo vectoriza los documentos nuevos y conserva el orden pedido."""
    base = Contador()
    cache = EmbeddingsEnCache(base)

    cache.embed_documents(["a", "bb"])
    vectores = cache.embed_documents(["bb", "ccc", "a", "ccc"])

    assert base.lotes == [["a", "bb"], ["ccc"]]
    assert vectores == [[2.0, 0.0], [3.0, 0.0], [1.0, 0.0], [3.0, 0.0]]
    assert cache.llamadas == 2


def test_documentos_ya_guardados_no_llaman_al_proveedor() -> None:
    """Los documentos ya guardados no vuelven a llamar al proveedor."""
    base = Contador()
    cache = EmbeddingsEnCache(base)

    cache.embed_documents(["a"])
    cache.embed_documents(["a", "a"])

    assert base.lotes == [["a"]]


def test_consulta_y_documento_con_el_mismo_texto_no_se_mezclan() -> None:
    """Consulta y documento con el mismo texto usan caches distintas."""
    base = Contador()
    cache = EmbeddingsEnCache(base)

    consulta = cache.embed_query("tarifas")
    (documento,) = cache.embed_documents(["tarifas"])

    assert consulta != documento
    assert base.consultas == ["tarifas"]
    assert base.lotes == [["tarifas"]]


def test_devuelve_copias_que_no_alteran_la_cache() -> None:
    """Devuelve copias: mutarlas no altera la cache."""
    cache = EmbeddingsEnCache(Contador())

    vector = cache.embed_query("x")
    vector.append(99.0)

    assert cache.embed_query("x") == [1.0, 1.0]
