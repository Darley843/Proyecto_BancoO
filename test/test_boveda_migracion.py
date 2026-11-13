"""Pruebas sin red de la migración de Chroma a Qdrant."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from banco_occidente_corpus.boveda import __main__ as boveda_main
from banco_occidente_corpus.boveda.almacen import ChromaAlmacen, QdrantAlmacen
from banco_occidente_corpus.boveda.fragmentos import ruta_fragmentos
from banco_occidente_corpus.boveda.indice import (
    escribir_metadatos,
    metadatos_fragmento,
    ruta_metadatos,
)
from banco_occidente_corpus.boveda.migracion import (
    ResumenMigracion,
    migrar_a_qdrant,
)
from banco_occidente_corpus.boveda.tipos import Fragmento
from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.utils import write_jsonl

URL = "https://www.bancodeoccidente.com.co/productos"


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


def fragmento(identificador: str, seccion: str = "oferta") -> Fragmento:
    """Construye un fragmento tipado para la migración."""
    return Fragmento(
        id=identificador,
        texto=f"Texto de {identificador}",
        url=URL,
        titulo="Productos",
        seccion=seccion,
        encabezado="Tarjetas",
        tipo="pagina",
        tokens=8,
    )


def preparar_fuente(
    config: Config,
    fragmentos: list[Fragmento],
    *,
    insertados: int | None = None,
    dimension_metadatos: int | None = None,
) -> ChromaAlmacen:
    """Escribe fragmentos e índice de Chroma con vectores ya calculados."""
    carpeta = config.paths.root / "data" / "boveda"
    write_jsonl(ruta_fragmentos(config, "base"), [asdict(f) for f in fragmentos])
    fuente = ChromaAlmacen(carpeta / "chroma")
    total = len(fragmentos) if insertados is None else insertados
    fuente.agregar(
        [f.id for f in fragmentos[:total]],
        [[float(numero + 1), 1.0, 0.0, 0.0] for numero in range(total)],
        [f.texto for f in fragmentos[:total]],
        [metadatos_fragmento(f) for f in fragmentos[:total]],
    )
    escribir_metadatos(
        carpeta,
        {
            "modelo": "nomic-embed-text-v2-moe",
            "prefijos": True,
            "alcance": "base",
            "fragmentos": len(fragmentos),
            "dimension": dimension_metadatos or 4,
        },
    )
    return fuente


def test_migracion_copia_vectores_sin_recalcular(tmp_path: Path) -> None:
    """Los vectores pasan de Chroma a Qdrant y el id original se conserva."""
    config = make_config(tmp_path)
    fragmentos = [fragmento("frag:a", "identidad"), fragmento("frag:b", "tarifas")]
    fuente = preparar_fuente(config, fragmentos)
    destino = QdrantAlmacen()
    try:
        resumen = migrar_a_qdrant(config, destino=destino)

        assert resumen.fragmentos == 2
        assert resumen.dimension == 4
        assert destino.contar() == 2
        assert destino.vectores(["frag:b"])["frag:b"] == pytest.approx(
            [2.0 / 5**0.5, 1.0 / 5**0.5, 0.0, 0.0]
        )
        coincidencias = destino.buscar([1.0, 1.0, 0.0, 0.0], k=2)
        assert {c.id for c in coincidencias} == {"frag:a", "frag:b"}
        assert all("texto" not in c.metadatos for c in coincidencias)
        assert fuente.contar() == 2
    finally:
        destino.cerrar()

    metadatos = json.loads(ruta_metadatos(config).read_text(encoding="utf-8"))
    assert metadatos["almacen"] == "qdrant"
    assert metadatos["dimension"] == 4
    assert metadatos["fragmentos"] == 2
    assert metadatos["modelo"] == "nomic-embed-text-v2-moe"


def test_migracion_sin_chroma_falla_con_mensaje(tmp_path: Path) -> None:
    """Sin la colección de Chroma no hay nada que migrar."""
    config = make_config(tmp_path)
    fragmentos = [fragmento("frag:a")]
    write_jsonl(ruta_fragmentos(config, "base"), [asdict(f) for f in fragmentos])
    escribir_metadatos(
        config.paths.root / "data" / "boveda",
        {
            "modelo": "nomic-embed-text-v2-moe",
            "prefijos": True,
            "alcance": "base",
            "fragmentos": 1,
            "dimension": 4,
        },
    )

    with pytest.raises(FileNotFoundError, match="nada que migrar"):
        migrar_a_qdrant(config, destino=QdrantAlmacen())


def test_migracion_con_conteo_incoherente_no_toca_el_destino(tmp_path: Path) -> None:
    """Si Chroma no tiene todos los fragmentos, Qdrant conserva su contenido."""
    config = make_config(tmp_path)
    fragmentos = [fragmento("frag:a"), fragmento("frag:b")]
    preparar_fuente(config, fragmentos, insertados=1)
    destino = QdrantAlmacen()
    try:
        destino.agregar(["previo"], [[1.0, 0.0]], ["previo"], [{"tipo": "pagina"}])

        with pytest.raises(ValueError, match="1 vectores"):
            migrar_a_qdrant(config, destino=destino)

        assert destino.contar() == 1
        assert destino.vectores(["previo"])["previo"] == pytest.approx([1.0, 0.0])
    finally:
        destino.cerrar()


def test_migracion_detecta_dimension_incoherente(tmp_path: Path) -> None:
    """La dimensión de indice.json debe coincidir con los vectores de Chroma."""
    config = make_config(tmp_path)
    preparar_fuente(config, [fragmento("frag:a")], dimension_metadatos=8)

    with pytest.raises(ValueError, match="dimensión"):
        migrar_a_qdrant(config, destino=QdrantAlmacen())


def test_migracion_es_idempotente(tmp_path: Path) -> None:
    """Dos corridas dejan el mismo conteo, sin duplicados."""
    config = make_config(tmp_path)
    fragmentos = [fragmento("frag:a"), fragmento("frag:b")]
    preparar_fuente(config, fragmentos)
    destino = QdrantAlmacen()
    try:
        primera = migrar_a_qdrant(config, destino=destino)
        segunda = migrar_a_qdrant(config, destino=destino)

        assert primera.fragmentos == segunda.fragmentos == 2
        assert destino.contar() == 2
    finally:
        destino.cerrar()


def test_cli_migrar_qdrant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """El subcomando imprime el resumen y devuelve cero."""
    config = make_config(tmp_path)
    resumen = ResumenMigracion(
        fragmentos=2,
        dimension=4,
        alcance="base",
        ruta_origen=tmp_path / "data/boveda/chroma",
        ruta_destino=tmp_path / "data/boveda/qdrant",
    )
    monkeypatch.setattr(boveda_main, "load_config", lambda: config)
    monkeypatch.setattr(boveda_main, "migrar_a_qdrant", lambda _config: resumen)

    assert boveda_main.main(["migrar-qdrant"]) == 0
    salida = capsys.readouterr().out
    assert "Fragmentos copiados: 2" in salida
    assert "No se recalcularon embeddings" in salida
