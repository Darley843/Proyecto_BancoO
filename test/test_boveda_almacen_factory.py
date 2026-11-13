"""Pruebas de la fábrica de almacenes y de los límites de importación."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from banco_occidente_corpus.boveda.almacen import (
    ChromaAlmacen,
    QdrantAlmacen,
    cerrar_almacen,
    crear_almacen,
    crear_almacen_en,
    crear_almacen_en_ruta,
)
from banco_occidente_corpus.boveda.configuracion import (
    ConfiguracionAlmacen,
    cargar_configuracion_almacen,
)
from banco_occidente_corpus.boveda.fragmentos import ruta_fragmentos
from banco_occidente_corpus.boveda.indice import (
    comprobar_almacen,
    construir_indice,
    escribir_metadatos,
)
from banco_occidente_corpus.boveda.tipos import Fragmento
from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.utils import write_jsonl

RAIZ = Path(__file__).resolve().parents[1]
SCRIPTS = RAIZ / ".opencode" / "skills" / "boveda-rag" / "scripts"


def make_config(tmp_path: Path) -> Config:
    """Crea una configuración aislada en tmp_path."""
    return Config(
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
            knowledge=tmp_path / "data/knowledge",
        )
    )


def fila_fragmento(identificador: str) -> dict[str, Any]:
    """Construye una fila con la forma del JSONL de fragmentos."""
    return asdict(
        Fragmento(
            id=identificador,
            texto="Cuota de manejo de la tarjeta",
            url="https://www.bancodeoccidente.com.co/productos",
            titulo="Productos",
            seccion="oferta",
            encabezado="Tarjetas",
            tipo="pagina",
            tokens=8,
        )
    )


def test_cargar_configuracion_almacen_por_defecto() -> None:
    """Sin archivo o sin tabla, el motor es Qdrant."""
    assert cargar_configuracion_almacen(Path("no-existe.toml")).tipo == "qdrant"


def test_cargar_configuracion_almacen_lee_chroma(tmp_path: Path) -> None:
    """La tabla [almacen] permite elegir Chroma."""
    ruta = tmp_path / "sucursal.toml"
    ruta.write_text('[almacen]\ntipo = "chroma"\n', encoding="utf-8")

    assert cargar_configuracion_almacen(ruta).tipo == "chroma"


def test_cargar_configuracion_almacen_rechaza_tipo(tmp_path: Path) -> None:
    """Un motor desconocido falla con un mensaje que nombra las opciones."""
    ruta = tmp_path / "sucursal.toml"
    ruta.write_text('[almacen]\ntipo = "faiss"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="qdrant, chroma"):
        cargar_configuracion_almacen(ruta)


def test_crear_almacen_usa_la_configuracion_y_la_ruta(tmp_path: Path) -> None:
    """La fábrica devuelve Qdrant en data/boveda/qdrant y Chroma bajo demanda."""
    config = make_config(tmp_path)

    qdrant = crear_almacen(config, configuracion=ConfiguracionAlmacen("qdrant"))
    chroma = crear_almacen(config, configuracion=ConfiguracionAlmacen("chroma"))

    assert isinstance(qdrant, QdrantAlmacen)
    assert qdrant.ruta == tmp_path / "data/boveda/qdrant"
    assert isinstance(chroma, ChromaAlmacen)
    assert chroma.ruta == tmp_path / "data/boveda/chroma"


def test_crear_almacen_en_usa_el_nombre_del_motor(tmp_path: Path) -> None:
    """Cada motor vive en su propia carpeta dentro del índice."""
    assert crear_almacen_en(tmp_path, "qdrant").ruta == tmp_path / "qdrant"  # type: ignore[attr-defined]
    assert crear_almacen_en(tmp_path, "chroma").ruta == tmp_path / "chroma"  # type: ignore[attr-defined]


def test_comprobar_almacen_acepta_indice_sin_campo(tmp_path: Path) -> None:
    """Un indice.json anterior a la migración se considera compatible."""
    config = make_config(tmp_path)
    escribir_metadatos(
        config.paths.root / "data/boveda",
        {
            "modelo": "nomic-embed-text-v2-moe",
            "prefijos": True,
            "alcance": "base",
            "fragmentos": 0,
            "dimension": 4,
        },
    )

    assert comprobar_almacen(config) is not None


def test_comprobar_almacen_detecta_motor_distinto(tmp_path: Path) -> None:
    """Un índice Chroma con la configuración en Qdrant explica qué hacer."""
    config = make_config(tmp_path)
    escribir_metadatos(
        config.paths.root / "data/boveda",
        {
            "modelo": "nomic-embed-text-v2-moe",
            "prefijos": True,
            "alcance": "base",
            "fragmentos": 0,
            "dimension": 4,
            "almacen": "chroma",
        },
    )

    with pytest.raises(ValueError, match="make migrar-qdrant"):
        comprobar_almacen(config)


class AlmacenFalso:
    """Almacén mínimo que registra si `construir_indice` lo cierra."""

    def __init__(self) -> None:
        """Inicializa el registro de vida."""
        self.tipo = "qdrant"
        self.reinicios = 0
        self.cerrada = False
        self._ids: list[str] = []

    def reiniciar(self) -> None:
        """Cuenta el reinicio y vacía el registro."""
        self.reinicios += 1
        self._ids = []

    def agregar(
        self,
        ids: list[str],
        vectores: list[list[float]],
        documentos: list[str],
        metadatos: list[dict[str, Any]],
    ) -> None:
        """Guarda los ids insertados."""
        assert len(ids) == len(vectores) == len(documentos) == len(metadatos)
        self._ids.extend(ids)

    def contar(self) -> int:
        """Devuelve los ids registrados."""
        return len(self._ids)

    def cerrar(self) -> None:
        """Marca el almacén como cerrado."""
        self.cerrada = True


def test_construir_indice_cierra_el_almacen_creado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El store que abre `construir_indice` se cierra al terminar."""
    config = make_config(tmp_path)
    write_jsonl(ruta_fragmentos(config, "base"), [fila_fragmento("frag:a")])
    falso = AlmacenFalso()
    monkeypatch.setattr("banco_occidente_corpus.boveda.indice.crear_almacen", lambda _config: falso)

    construir_indice(
        config,
        "base",
        embeddings=DeterministicFakeEmbedding(size=4),
    )

    assert falso.reinicios == 1
    assert falso.cerrada is True


def test_cerrar_registro_suelta_los_almacenes_abiertos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La red de atexit cierra el registro y libera la carpeta para otro consumidor."""
    from banco_occidente_corpus.boveda import almacen as modulo

    monkeypatch.setattr(modulo, "_REGISTRO_QDRANT", {})
    ruta = tmp_path / "qdrant"
    abierto = crear_almacen_en_ruta(ruta)
    abierto.agregar(["frag:a"], [[1.0, 0.0]], ["a"], [{"seccion": "oferta"}])

    modulo._cerrar_registro()

    assert modulo._REGISTRO_QDRANT == {}
    reabierto = crear_almacen_en_ruta(ruta)
    try:
        assert reabierto is not abierto
        assert reabierto.contar() == 1
    finally:
        cerrar_almacen(reabierto)


def test_solo_almacen_importa_los_clientes_vectoriales() -> None:
    """Ni Chroma ni Qdrant se importan fuera de `almacen.py`."""
    infracciones: list[str] = []
    for ruta in [*RAIZ.joinpath("src").rglob("*.py"), *SCRIPTS.glob("*.py")]:
        if ruta.name == "almacen.py":
            continue
        texto = ruta.read_text(encoding="utf-8")
        if "import chromadb" in texto or "from chromadb" in texto:
            infracciones.append(f"{ruta}: chromadb")
        if "import qdrant_client" in texto or "from qdrant_client" in texto:
            infracciones.append(f"{ruta}: qdrant_client")

    assert infracciones == []
