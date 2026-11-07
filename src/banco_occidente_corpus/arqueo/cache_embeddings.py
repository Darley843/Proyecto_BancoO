"""Cache en memoria de embeddings para una corrida del Arqueo.

El recuperador hibrido vectoriza la consulta y los fragmentos del top en cada
busqueda. En el barrido las mismas preguntas se buscan en cada configuracion, asi
que sin cache se repiten cientos de llamadas a Ollama con los mismos textos.
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings


class EmbeddingsEnCache(Embeddings):
    """Envuelve un proveedor y guarda cada vector por tipo de llamada y texto.

    Consultas y documentos van en caches separadas porque el proveedor puede
    aplicar prefijos distintos a cada uno (nomic usa search_query y
    search_document). La cache vive solo durante la corrida.

    Args:
        base: proveedor real de embeddings (Ollama o uno de pruebas).
    """

    def __init__(self, base: Embeddings) -> None:
        self._base = base
        self._consultas: dict[str, list[float]] = {}
        self._documentos: dict[str, list[float]] = {}
        self.llamadas = 0

    def embed_query(self, text: str) -> list[float]:
        """Devuelve el vector de la consulta, calculandolo solo la primera vez.

        Args:
            text: consulta a vectorizar.

        Returns:
            Una copia del vector guardado.
        """
        if text not in self._consultas:
            self.llamadas += 1
            self._consultas[text] = self._base.embed_query(text)
        return list(self._consultas[text])

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Devuelve los vectores de los textos y vectoriza solo los que faltan.

        Args:
            texts: textos de los fragmentos, en el orden en que se piden.

        Returns:
            Una copia de cada vector, en el mismo orden que ``texts``.
        """
        faltantes = list(dict.fromkeys(t for t in texts if t not in self._documentos))
        if faltantes:
            self.llamadas += 1
            vectores = self._base.embed_documents(faltantes)
            self._documentos.update(zip(faltantes, vectores, strict=True))
        return [list(self._documentos[t]) for t in texts]
