"""Pruebas de punta a punta del generador de contexto (sin red)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from banco_occidente_corpus import config
from banco_occidente_corpus.contexto import main
from banco_occidente_corpus.gold import render_document
from banco_occidente_corpus.utils import write_jsonl

#: Variables que permiten redirigir cada capa fuera de data/.
_VARIABLES_RUTA = (
    "CORPUS_RAW_DIR",
    "CORPUS_PROCESSED_DIR",
    "CORPUS_GOLD_DIR",
    "CORPUS_KNOWLEDGE_DIR",
    "CORPUS_NEWS_DIR",
    "CORPUS_CONTEXTO_DIR",
    "CORPUS_CONTEXTO_CONFIG",
)


@pytest.fixture
def proyecto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Aisla PROJECT_ROOT y las rutas por entorno para no tocar data/ real."""
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    for nombre in _VARIABLES_RUTA:
        monkeypatch.delenv(nombre, raising=False)
    return tmp_path


def _page(
    root: Path,
    pid: str,
    titulo: str,
    seccion: str,
    cuerpo: str,
    *,
    tipo: str = "",
    fecha: str = "",
) -> dict[str, Any]:
    """Escribe una pagina Gold minima y devuelve su fila de corpus.jsonl."""
    destino = root / "data/gold/pages"
    destino.mkdir(parents=True, exist_ok=True)
    url = f"https://www.bancodeoccidente.com.co/{pid}"
    meta: dict[str, object] = {
        "fuente": url,
        "titulo": titulo,
        "seccion": seccion,
        "empresa": "Banco de Occidente",
        "fecha_captura": "2026-10-23",
        "idioma": "es",
        "tokens": 0,
        "hash": "0" * 8,
        "palabras": 0,
        "metodo": "trafilatura",
    }
    if tipo:
        meta["tipo"] = tipo
    if fecha:
        meta["fecha_publicacion"] = fecha
    ruta = destino / f"{pid}.md"
    ruta.write_text(render_document(meta, cuerpo), encoding="utf-8", newline="\n")
    return {
        "id": pid,
        "fuente": url,
        "titulo": titulo,
        "seccion": seccion,
        "empresa": "Banco de Occidente",
        "fecha_captura": "2026-10-23",
        "idioma": "es",
        "tokens": 10,
        "palabras": 5,
        "hash": "0" * 64,
        "archivo": ruta.relative_to(root).as_posix(),
    }


def _gold(proyecto: Path) -> None:
    """Gold minimo: una pagina del sitio y una ficha de prensa."""
    filas = [
        _page(
            proyecto,
            "quienes-somos",
            "Quiénes Somos",
            "identidad",
            "Banco fundado en 1965 en Cali. Más de 60 años de experiencia.",
        ),
        _page(
            proyecto,
            "noticia-2026-01-01-ejemplo",
            "Ficha de prensa",
            "presencia",
            "El banco anuncio una iniciativa para sus clientes.",
            tipo="noticia",
            fecha="2026-01-01",
        ),
    ]
    write_jsonl(proyecto / "data/gold/corpus.jsonl", filas)


def _manifest(proyecto: Path) -> dict[str, Any]:
    """Lee el manifest generado en data/contexto."""
    return json.loads((proyecto / "data/contexto/manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- contexto


def test_contexto_main_punta_a_punta(proyecto: Path) -> None:
    # Arrange: Gold minimo con una pagina del sitio y una ficha de prensa.
    _gold(proyecto)

    # Act
    codigo = main([])

    # Assert: archivo y manifest generados dentro de tmp_path, con ambas fichas.
    assert codigo == 0
    archivo = proyecto / "data/contexto/contexto_banco.md"
    assert archivo.exists()
    assert (proyecto / "data/contexto/manifest.json").exists()

    md = archivo.read_text(encoding="utf-8")
    assert "## Quiénes Somos" in md
    assert "## Ficha de prensa" in md

    manifest = _manifest(proyecto)
    assert manifest["config"]["incluir_noticias"] is True
    assert manifest["paginas"] == {"leidas": 2, "incluidas": 2, "excluidas": 0}
    assert {fila["id"] for fila in manifest["incluidas"]} == {
        "quienes-somos",
        "noticia-2026-01-01-ejemplo",
    }


def test_contexto_main_sin_noticias(proyecto: Path) -> None:
    # Arrange: mismo Gold, pero la corrida excluye las fichas de noticias.
    _gold(proyecto)

    # Act
    codigo = main(["--sin-noticias"])

    # Assert: la ficha no entra y el manifest explica el motivo.
    assert codigo == 0
    md = (proyecto / "data/contexto/contexto_banco.md").read_text(encoding="utf-8")
    assert "## Quiénes Somos" in md
    assert "## Ficha de prensa" not in md

    manifest = _manifest(proyecto)
    assert manifest["config"]["incluir_noticias"] is False
    assert manifest["paginas"] == {"leidas": 2, "incluidas": 1, "excluidas": 1}
    assert manifest["incluidas"][0]["id"] == "quienes-somos"
    assert manifest["excluidas"][0]["motivo"] == "ficha_excluida"


def test_contexto_main_config_alternativa_y_max_tokens(proyecto: Path) -> None:
    # Arrange: config propia en tmp y una sola pagina Gold.
    _gold(proyecto)
    config_path = proyecto / "contexto.toml"
    config_path.write_text(
        "\n".join(
            [
                "max_tokens = 5000",
                "incluir_noticias = false",
                "boilerplate_ratio = 0.10",
                "",
                "[secciones]",
                "identidad = 1",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )

    # Act
    codigo = main(
        [
            "--config-contexto",
            str(config_path),
            "--max-tokens",
            "1000000",
            "--sin-noticias",
        ]
    )

    # Assert: manda la config indicada y el tope de la linea de comandos.
    assert codigo == 0
    manifest = _manifest(proyecto)
    assert manifest["max_tokens"] == 1000000
    assert manifest["config"]["incluir_noticias"] is False
    assert manifest["config"]["secciones"] == {"identidad": 1}


def test_contexto_main_sin_gold_devuelve_1(proyecto: Path) -> None:
    # Arrange: no hay data/gold/corpus.jsonl.

    # Act
    codigo = main([])

    # Assert: error controlado y sin archivos a medias.
    assert codigo == 1
    assert not (proyecto / "data/contexto/contexto_banco.md").exists()
    assert not (proyecto / "data/contexto/manifest.json").exists()


def test_contexto_main_presupuesto_imposible_devuelve_error(proyecto: Path) -> None:
    # Arrange: Gold valido y un tope que no alcanza ni para el preambulo.
    _gold(proyecto)

    # Act
    codigo = main(["--max-tokens", "1"])

    # Assert: codigo distinto de cero y ningun archivo escrito.
    assert codigo != 0
    assert not (proyecto / "data/contexto/contexto_banco.md").exists()
    assert not (proyecto / "data/contexto/manifest.json").exists()
