"""Pruebas sin red del indice en carpetas arbitrarias y del indice sin prefijos.

Los embeddings se inyectan con `DeterministicFakeEmbedding` o con un espia, y
Chroma se crea en `tmp_path`. No se llama a Ollama.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings

from banco_occidente_corpus.arqueo import experimentos as modulo_experimentos
from banco_occidente_corpus.arqueo.experimentos import (
    NOMBRE_HUELLA,
    carpeta_sin_prefijos,
    construir_indice_sin_prefijos,
)
from banco_occidente_corpus.boveda.almacen import ChromaAlmacen
from banco_occidente_corpus.boveda.configuracion import ConfiguracionEmbeddings
from banco_occidente_corpus.boveda.fragmentos import ruta_fragmentos
from banco_occidente_corpus.boveda.indice import (
    ResumenIndice,
    construir_indice_en,
    leer_metadatos,
)
from banco_occidente_corpus.boveda.tipos import Fragmento
from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.utils import write_jsonl

URL = "https://www.bancodeoccidente.com.co/productos"


def make_config(tmp_path: Path) -> Config:
    """Crea una configuracion aislada en tmp_path."""
    return Config(
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
            knowledge=tmp_path / "data/knowledge",
        )
    )


class EspiaEmbeddings(Embeddings):
    """Proveedor de pruebas que registra los textos que recibe.

    `documentos` acumula los textos indexados y `consultas`, las preguntas.
    """

    def __init__(self, dimension: int = 4) -> None:
        """Guarda la dimensión y los registros de lo recibido."""
        self.dimension = dimension
        self.documentos: list[str] = []
        self.consultas: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Registra los textos de documento y devuelve vectores fijos."""
        self.documentos.extend(texts)
        return [[1.0] * self.dimension for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        """Registra la consulta y devuelve un vector fijo."""
        self.consultas.append(text)
        return [1.0] * self.dimension


def fila_fragmento(identificador: str, texto: str = "Cuota de manejo") -> dict[str, Any]:
    """Construye una fila con la forma del JSONL de fragmentos."""
    return {
        "id": identificador,
        "texto": texto,
        "url": URL,
        "titulo": "Productos",
        "seccion": "oferta",
        "encabezado": "Tarjetas",
        "tipo": "pagina",
        "tokens": 8,
        "puntaje": 0.0,
    }


def fragmento(identificador: str, texto: str = "Cuota de manejo") -> Fragmento:
    """Construye el fragmento tipado que recibe `construir_indice_en`."""
    return Fragmento(**fila_fragmento(identificador, texto))


def test_construir_indice_en_escribe_en_la_carpeta_pedida(tmp_path: Path) -> None:
    """El indice nuevo declara su carpeta y no toca data/boveda."""
    # Arrange
    fragmentos = [
        fragmento("frag:a"),
        fragmento("frag:b", "Apertura de cuenta"),
    ]
    carpeta = tmp_path / "indices" / "extra"
    almacen = ChromaAlmacen(carpeta / "chroma")

    # Act
    resumen = construir_indice_en(
        carpeta,
        fragmentos,
        alcance="base",
        ajustes=ConfiguracionEmbeddings(prefijos=False),
        embeddings=DeterministicFakeEmbedding(size=4),
        almacen=almacen,
    )

    # Assert
    assert resumen.ruta_metadatos == carpeta / "indice.json"
    assert resumen.ruta_almacen == carpeta / "chroma"
    assert almacen.contar() == 2
    metadatos = json.loads((carpeta / "indice.json").read_text(encoding="utf-8"))
    assert metadatos["prefijos"] is False
    assert metadatos["fragmentos"] == 2
    assert metadatos["dimension"] == 4
    assert not (tmp_path / "data" / "boveda" / "indice.json").exists()


def test_leer_metadatos_devuelve_none_si_falta(tmp_path: Path) -> None:
    """Sin indice.json no hay metadatos."""
    assert leer_metadatos(tmp_path / "sin-indice") is None


def test_indice_sin_prefijos_se_construye_y_se_reutiliza(tmp_path: Path) -> None:
    """La segunda llamada reutiliza el indice y no vuelve a vectorizar."""
    # Arrange
    config = make_config(tmp_path)
    write_jsonl(
        ruta_fragmentos(config, "base"),
        [fila_fragmento("frag:a"), fila_fragmento("frag:b", "Apertura")],
    )
    espia = EspiaEmbeddings()

    # Act
    primero = construir_indice_sin_prefijos(
        config,
        "base",
        embeddings=espia,
        configuracion=ConfiguracionEmbeddings(prefijos=True),
    )
    vectorizados = len(espia.documentos)
    segundo = construir_indice_sin_prefijos(
        config,
        "base",
        embeddings=espia,
        configuracion=ConfiguracionEmbeddings(prefijos=True),
    )

    # Assert
    assert vectorizados == 2
    assert len(espia.documentos) == 2
    assert primero.ruta_almacen == segundo.ruta_almacen
    assert primero.ruta_almacen == carpeta_sin_prefijos(config) / "qdrant"
    metadatos = leer_metadatos(carpeta_sin_prefijos(config))
    assert metadatos is not None
    assert metadatos["prefijos"] is False
    assert metadatos["fragmentos"] == 2
    assert (carpeta_sin_prefijos(config) / NOMBRE_HUELLA).exists()


def test_indice_sin_prefijos_se_reconstruye_si_se_pide(tmp_path: Path) -> None:
    """La bandera reconstruir vuelve a vectorizar aunque exista el indice."""
    # Arrange
    config = make_config(tmp_path)
    write_jsonl(ruta_fragmentos(config, "base"), [fila_fragmento("frag:a")])
    espia = EspiaEmbeddings()
    construir_indice_sin_prefijos(config, "base", embeddings=espia)

    # Act
    construir_indice_sin_prefijos(
        config,
        "base",
        embeddings=espia,
        reconstruir=True,
    )

    # Assert
    assert len(espia.documentos) == 2


def test_indice_sin_prefijos_detecta_cambio_de_fragmentos(tmp_path: Path) -> None:
    """Si el JSONL crece, el indice anterior deja de ser compatible."""
    # Arrange
    config = make_config(tmp_path)
    write_jsonl(ruta_fragmentos(config, "base"), [fila_fragmento("frag:a")])
    espia = EspiaEmbeddings()
    construir_indice_sin_prefijos(config, "base", embeddings=espia)
    write_jsonl(
        ruta_fragmentos(config, "base"),
        [fila_fragmento("frag:a"), fila_fragmento("frag:b")],
    )

    # Act
    resumen = construir_indice_sin_prefijos(config, "base", embeddings=espia)

    # Assert
    assert len(espia.documentos) == 3
    assert resumen.fragmentos == 2


def test_indice_sin_prefijos_se_reconstruye_si_cambia_el_texto(tmp_path: Path) -> None:
    """Con el mismo numero de fragmentos, otro texto invalida la huella."""
    # Arrange
    config = make_config(tmp_path)
    write_jsonl(
        ruta_fragmentos(config, "base"),
        [fila_fragmento("frag:a"), fila_fragmento("frag:b", "Apertura")],
    )
    espia = EspiaEmbeddings()
    construir_indice_sin_prefijos(config, "base", embeddings=espia)
    write_jsonl(
        ruta_fragmentos(config, "base"),
        [fila_fragmento("frag:a"), fila_fragmento("frag:b", "Apertura modificada")],
    )

    # Act
    resumen = construir_indice_sin_prefijos(config, "base", embeddings=espia)

    # Assert
    assert len(espia.documentos) == 4
    assert resumen.fragmentos == 2


def test_indice_sin_prefijos_se_reconstruye_si_falta_la_huella(tmp_path: Path) -> None:
    """Un indice viejo sin huella.txt no se puede reutilizar."""
    # Arrange
    config = make_config(tmp_path)
    write_jsonl(ruta_fragmentos(config, "base"), [fila_fragmento("frag:a")])
    espia = EspiaEmbeddings()
    construir_indice_sin_prefijos(config, "base", embeddings=espia)
    (carpeta_sin_prefijos(config) / NOMBRE_HUELLA).unlink()

    # Act
    construir_indice_sin_prefijos(config, "base", embeddings=espia)

    # Assert
    assert len(espia.documentos) == 2


class AlmacenQueCuentaCierre:
    """Almacén mínimo que registra si el experimento lo cierra."""

    def __init__(self) -> None:
        """Inicializa el registro de cierre."""
        self.cerrada = False

    def cerrar(self) -> None:
        """Marca el almacén como cerrado."""
        self.cerrada = True


def test_indice_sin_prefijos_cierra_el_almacen_que_abre(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El almacén extra se cierra en finally aunque no lo reciba quien llama."""
    config = make_config(tmp_path)
    write_jsonl(ruta_fragmentos(config, "base"), [fila_fragmento("frag:a")])
    espia = AlmacenQueCuentaCierre()
    carpeta = carpeta_sin_prefijos(config)

    def construir_falso(
        _carpeta: Path,
        fragmentos: Sequence[Fragmento],
        **kwargs: object,
    ) -> ResumenIndice:
        """Devuelve el resumen sin abrir un almacén real."""
        assert kwargs["almacen"] is espia
        assert len(fragmentos) == 1
        return ResumenIndice(
            alcance="base",
            modelo="nomic-embed-text-v2-moe",
            prefijos=False,
            fragmentos=1,
            dimension=4,
            ruta_metadatos=carpeta / "indice.json",
            ruta_almacen=carpeta / "qdrant",
        )

    monkeypatch.setattr(modulo_experimentos, "crear_almacen_en", lambda *_args, **_kwargs: espia)
    monkeypatch.setattr(modulo_experimentos, "construir_indice_en", construir_falso)

    construir_indice_sin_prefijos(config, "base", embeddings=EspiaEmbeddings())

    assert espia.cerrada is True


def test_construir_indice_en_sin_config_mapa_no_escribe_el_mapa(tmp_path: Path) -> None:
    """El indice extra no debe sobrescribir el mapa del indice principal."""
    # Arrange
    carpeta = tmp_path / "indices" / "extra"

    # Act
    construir_indice_en(
        carpeta,
        [fragmento("frag:a"), fragmento("frag:b", "Apertura")],
        alcance="base",
        ajustes=ConfiguracionEmbeddings(prefijos=False),
        embeddings=DeterministicFakeEmbedding(size=4),
    )

    # Assert
    assert not (tmp_path / "data" / "boveda" / "mapa.json").exists()


def test_construir_indice_en_con_config_mapa_escribe_el_mapa(tmp_path: Path) -> None:
    """El indice principal si escribe el mapa en la carpeta de datos."""
    # Arrange
    config = make_config(tmp_path)
    carpeta = tmp_path / "indices" / "principal"

    # Act
    construir_indice_en(
        carpeta,
        [fragmento("frag:a"), fragmento("frag:b", "Apertura")],
        alcance="base",
        ajustes=ConfiguracionEmbeddings(prefijos=False),
        embeddings=DeterministicFakeEmbedding(size=4),
        config_mapa=config,
    )

    # Assert
    ruta = tmp_path / "data" / "boveda" / "mapa.json"
    assert ruta.exists()
    mapa = json.loads(ruta.read_text(encoding="utf-8"))
    assert len(mapa["puntos"]) == 2


def test_construir_indice_en_rechaza_lista_vacia(tmp_path: Path) -> None:
    """Sin fragmentos el error explica que no hay nada que indexar."""
    with pytest.raises(ValueError, match="No hay fragmentos"):
        construir_indice_en(
            tmp_path / "vacio",
            [],
            alcance="base",
            ajustes=ConfiguracionEmbeddings(),
            embeddings=DeterministicFakeEmbedding(size=4),
        )
