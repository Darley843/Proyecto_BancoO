"""Pruebas sin red del recuperador híbrido: pesos, puntaje y contrato.

No se llama a Ollama: los embeddings se inyectan con `DeterministicFakeEmbedding`
y el almacén vectorial es un doble en memoria.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings

from banco_occidente_corpus.boveda.almacen import Coincidencia
from banco_occidente_corpus.boveda.configuracion import (
    ConfiguracionRecuperacion,
    cargar_configuracion_recuperacion,
)
from banco_occidente_corpus.boveda.recuperador import (
    RecuperadorHibrido,
    _similitud_coseno,
    _tokenizar,
)
from banco_occidente_corpus.boveda.tipos import Fragmento, Recuperador

URL = "https://www.bancodeoccidente.com.co/tarifas"


class AlmacenFalso:
    """Almacén vectorial que devuelve un orden fijo y guarda los vectores."""

    def __init__(
        self,
        coincidencias: Sequence[Coincidencia],
        fragmentos: Sequence[Fragmento] = (),
    ) -> None:
        """Guarda el orden fijo y los vectores de los fragmentos."""
        self._coincidencias = list(coincidencias)
        self._proveedor = DeterministicFakeEmbedding(size=8)
        self._vectores = {
            fragmento.id: self._proveedor.embed_documents([fragmento.texto])[0]
            for fragmento in fragmentos
        }
        self.k: int | None = None

    def crear(self) -> None:
        """No hace nada: el almacén ya existe."""

    def agregar(
        self,
        ids: Sequence[str],
        vectores: Sequence[Sequence[float]],
        documentos: Sequence[str],
        metadatos: Sequence[dict[str, Any]],
    ) -> None:
        """No inserta: el doble se construye con las coincidencias."""

    def buscar(self, vector: Sequence[float], k: int = 5) -> list[Coincidencia]:
        """Devuelve el orden fijo recortado a k."""
        self.k = k
        return self._coincidencias[:k]

    def vectores(self, ids: Sequence[str]) -> dict[str, list[float]]:
        """Devuelve los vectores guardados de los ids que existan."""
        return {
            identificador: self._vectores[identificador]
            for identificador in ids
            if identificador in self._vectores
        }

    def contar(self) -> int:
        """Devuelve el número de coincidencias del doble."""
        return len(self._coincidencias)

    def reiniciar(self) -> None:
        """No hace nada."""


def fragmento(
    identificador: str,
    texto: str,
    *,
    seccion: str = "oferta",
    encabezado: str = "Tarjetas",
    tokens: int = 20,
) -> Fragmento:
    """Construye un fragmento de prueba."""
    return Fragmento(
        id=identificador,
        texto=texto,
        url=URL,
        titulo="Tarifas",
        seccion=seccion,
        encabezado=encabezado,
        tipo="pagina",
        tokens=tokens,
    )


def coincidencia(fragmento_base: Fragmento, distancia: float) -> Coincidencia:
    """Construye una coincidencia vectorial para el fragmento."""
    return Coincidencia(
        id=fragmento_base.id,
        documento=fragmento_base.texto,
        metadatos={
            "url": fragmento_base.url,
            "titulo": fragmento_base.titulo,
            "seccion": fragmento_base.seccion,
            "encabezado": fragmento_base.encabezado,
            "tipo": fragmento_base.tipo,
            "tokens": fragmento_base.tokens,
        },
        distancia=distancia,
    )


def crear(
    fragmentos: Sequence[Fragmento],
    coincidencias: Sequence[Coincidencia],
    *,
    k: int = 5,
    peso_vectorial: float = 0.5,
    peso_bm25: float = 0.5,
) -> RecuperadorHibrido:
    """Crea el recuperador con dobles y la configuración pedida."""
    return RecuperadorHibrido(
        AlmacenFalso(coincidencias, fragmentos),
        DeterministicFakeEmbedding(size=8),
        fragmentos,
        ConfiguracionRecuperacion(k=k, peso_vectorial=peso_vectorial, peso_bm25=peso_bm25),
    )


def test_peso_vectorial_ordena_por_similitud() -> None:
    """Con todo el peso en el vector, manda el orden del almacén."""
    cerca = fragmento("A", "manejo de la tarjeta de credito")
    lejos = fragmento("B", "cuota de manejo de la tarjeta")
    recuperador = crear([cerca, lejos], [coincidencia(cerca, 0.1), coincidencia(lejos, 0.6)])

    resultados = recuperador.buscar("cuota de manejo", k=2)

    assert resultados[0].id == "A"


def test_peso_bm25_ordena_por_terminos() -> None:
    """Con todo el peso en BM25, manda la presencia de los términos."""
    cerca = fragmento("A", "manejo de la tarjeta de credito")
    lejos = fragmento("B", "cuota cuota de manejo y debito")
    recuperador = crear(
        [cerca, lejos],
        [coincidencia(cerca, 0.1), coincidencia(lejos, 0.6)],
        peso_vectorial=0.0,
        peso_bm25=1.0,
    )

    resultados = recuperador.buscar("cuota", k=2)

    assert resultados[0].id == "B"


def test_puntaje_es_coseno_para_todos_los_candidatos() -> None:
    """Los fragmentos que solo devuelve BM25 también traen puntaje coseno."""
    cerca = fragmento("A", "cuota de manejo de la tarjeta")
    solo_bm25 = fragmento("C", "cuota cuota cuota de manejo y debito")
    recuperador = crear(
        [cerca, solo_bm25],
        [coincidencia(cerca, 0.1)],
        peso_vectorial=0.3,
        peso_bm25=0.7,
    )

    resultados = recuperador.buscar("cuota cuota", k=5)

    assert {resultado.id for resultado in resultados} == {"A", "C"}
    assert all(0.0 <= resultado.puntaje <= 1.0 for resultado in resultados)
    embeddings = DeterministicFakeEmbedding(size=8)
    esperado = _similitud_coseno(
        embeddings.embed_query("cuota cuota"), embeddings.embed_documents([cerca.texto])[0]
    )
    assert resultados[0].puntaje == pytest.approx(esperado)


class EmbeddingsContador(Embeddings):
    """Proveedor que cuenta cuántas veces vectoriza consultas y documentos."""

    def __init__(self, size: int = 8) -> None:
        """Prepara el proveedor determinista y los contadores en cero."""
        self._base = DeterministicFakeEmbedding(size=size)
        self.consultas = 0
        self.documentos = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Cuenta la llamada y delega en el proveedor determinista."""
        self.documentos += 1
        return self._base.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        """Cuenta la llamada y delega en el proveedor determinista."""
        self.consultas += 1
        return self._base.embed_query(text)


def test_buscar_vectoriza_la_consulta_una_sola_vez() -> None:
    """La búsqueda pide un embedding de consulta y ninguno de documento."""
    fragmentos = [
        fragmento("A", "cuota de manejo de la tarjeta de credito"),
        fragmento("B", "linea de atencion al cliente"),
    ]
    embeddings = EmbeddingsContador()
    recuperador = RecuperadorHibrido(
        AlmacenFalso([coincidencia(item, 0.1) for item in fragmentos], fragmentos),
        embeddings,
        fragmentos,
        ConfiguracionRecuperacion(k=5, peso_vectorial=0.6, peso_bm25=0.4),
    )

    resultados = recuperador.buscar("cuota de manejo", k=2)

    assert resultados
    assert embeddings.consultas == 1
    assert embeddings.documentos == 0


def test_puntaje_recalcula_si_el_indice_no_guarda_el_vector() -> None:
    """Con Gold más nuevo que Chroma, el texto ausente se vectoriza al vuelo."""
    cercano = fragmento("A", "cuota de manejo")
    recuperador = RecuperadorHibrido(
        AlmacenFalso([coincidencia(cercano, 0.1)]),
        DeterministicFakeEmbedding(size=8),
        [cercano],
        ConfiguracionRecuperacion(k=5, peso_vectorial=1.0, peso_bm25=0.0),
    )

    resultados = recuperador.buscar("cuota", k=1)

    proveedor = DeterministicFakeEmbedding(size=8)
    esperado = _similitud_coseno(
        proveedor.embed_query("cuota"), proveedor.embed_documents([cercano.texto])[0]
    )
    assert len(resultados) == 1
    assert resultados[0].puntaje == pytest.approx(esperado)


def test_buscar_sin_k_devuelve_como_maximo_cinco() -> None:
    """El contrato limita el resultado por defecto a cinco fragmentos."""
    fragmentos = [
        fragmento(f"F{indice}", f"cuota de manejo numero {indice}") for indice in range(8)
    ]
    recuperador = crear(
        fragmentos, [coincidencia(item, 0.1 * indice) for indice, item in enumerate(fragmentos)]
    )

    resultados = recuperador.buscar("cuota")

    assert len(resultados) <= 5


def test_buscar_rechaza_k_no_positivo() -> None:
    """k debe ser mayor que cero."""
    recuperador = crear([fragmento("A", "cuota")], [coincidencia(fragmento("A", "cuota"), 0.1)])

    with pytest.raises(ValueError, match="k"):
        recuperador.buscar("cuota", k=0)


def test_similitud_coseno_acota_a_cero_y_uno() -> None:
    """La similitud se acota a [0, 1] aunque el coseno sea negativo."""
    assert _similitud_coseno([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert _similitud_coseno([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert _similitud_coseno([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_tokenizar_normaliza_palabras() -> None:
    """La tokenización pasa a minúsculas, quita tildes y descarta signos."""
    assert _tokenizar("¿Cuál es la línea telefónica?") == [
        "cual",
        "es",
        "la",
        "linea",
        "telefonica",
    ]


def test_bm25_encuentra_fragmento_con_tilde() -> None:
    """BM25 compara palabras normalizadas: «linea atencion» halla «Línea de atención»."""
    objetivo = fragmento("A", "Línea de atención: 018000 123 456")
    relleno = [
        fragmento("B", "cuota de manejo de la tarjeta de credito"),
        fragmento("C", "tasa de interes del credito de vivienda"),
        fragmento("D", "requisitos para abrir una cuenta de ahorros"),
        fragmento("E", "red de oficinas y cajeros en el pais"),
    ]
    fragmentos = [objetivo, *relleno]
    recuperador = crear(
        fragmentos,
        [coincidencia(item, 0.9 if item.id == "A" else 0.5) for item in fragmentos],
        peso_vectorial=0.0,
        peso_bm25=1.0,
    )

    resultados = recuperador.buscar("linea atencion", k=2)

    assert resultados[0].id == "A"


class RecuperadorSimulado:
    """Doble mínimo que cumple el contrato sin heredar de una clase concreta."""

    def buscar(self, consulta: str, k: int = 5) -> list[Fragmento]:
        """Devuelve una lista vacía."""
        return []


def test_recuperador_cumple_el_protocolo() -> None:
    """El recuperador híbrido y un doble satisfacen `Recuperador`."""
    recuperador = crear([fragmento("A", "cuota")], [coincidencia(fragmento("A", "cuota"), 0.1)])

    assert isinstance(recuperador, Recuperador)
    assert isinstance(RecuperadorSimulado(), Recuperador)


def test_config_recuperacion_por_defecto(tmp_path: Path) -> None:
    """Sin sección `[recuperacion]` se usan los valores por defecto."""
    ruta = tmp_path / "sucursal.toml"
    ruta.write_text("[embeddings]\n", encoding="utf-8")

    ajustes = cargar_configuracion_recuperacion(ruta)

    assert ajustes == ConfiguracionRecuperacion(k=5, peso_vectorial=0.6, peso_bm25=0.4)


def test_config_recuperacion_lee_pesos(tmp_path: Path) -> None:
    """Los pesos y el k salen del TOML."""
    ruta = tmp_path / "sucursal.toml"
    ruta.write_text(
        "[recuperacion]\nk = 8\npeso_vectorial = 0.2\npeso_bm25 = 0.8\n",
        encoding="utf-8",
    )

    ajustes = cargar_configuracion_recuperacion(ruta)

    assert ajustes == ConfiguracionRecuperacion(k=8, peso_vectorial=0.2, peso_bm25=0.8)


@pytest.mark.parametrize(
    "contenido",
    [
        "[recuperacion]\nk = 0\n",
        "[recuperacion]\nk = -1\n",
        '[recuperacion]\nk = "cinco"\n',
        "[recuperacion]\npeso_vectorial = -0.1\n",
        "[recuperacion]\npeso_vectorial = 0\npeso_bm25 = 0\n",
    ],
)
def test_config_recuperacion_invalida(tmp_path: Path, contenido: str) -> None:
    """k no positivo, pesos negativos o suma cero se rechazan."""
    ruta = tmp_path / "sucursal.toml"
    ruta.write_text(contenido, encoding="utf-8")

    with pytest.raises(ValueError):
        cargar_configuracion_recuperacion(ruta)


def test_pesos_no_normalizados_se_aceptan() -> None:
    """Pesos 1 y 3 se normalizan internamente y no rompen EnsembleRetriever."""
    cerca = fragmento("A", "cuota de manejo de la tarjeta")
    lejos = fragmento("B", "cuota cuota cuota manejo tarjeta debito")
    recuperador = crear(
        [cerca, lejos],
        [coincidencia(cerca, 0.1), coincidencia(lejos, 0.6)],
        peso_vectorial=1.0,
        peso_bm25=3.0,
    )

    resultados = recuperador.buscar("cuota", k=2)

    assert len(resultados) == 2
    assert all(math.isfinite(resultado.puntaje) for resultado in resultados)
