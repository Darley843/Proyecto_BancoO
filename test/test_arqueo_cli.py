"""Pruebas sin red del comando `make arqueo` y de la CLI del Arqueo.

La corrida completa se hace en `tmp_path` con `DeterministicFakeEmbedding`,
Chroma temporal y las rutas de salida redirigidas. No se llama a Ollama ni a
DeepSeek y no hace falta `DEEPSEEK_API_KEY`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from banco_occidente_corpus.arqueo import informe
from banco_occidente_corpus.arqueo.__main__ import main
from banco_occidente_corpus.boveda.configuracion import ConfiguracionEmbeddings
from banco_occidente_corpus.boveda.fragmentos import ruta_fragmentos
from banco_occidente_corpus.boveda.indice import construir_indice
from banco_occidente_corpus.config import PROJECT_ROOT, Config, Paths
from banco_occidente_corpus.utils import write_jsonl

URL = "https://www.bancodeoccidente.com.co/productos"
MAKEFILE = PROJECT_ROOT / "makefile"
FUENTES_ARQUEO = (
    PROJECT_ROOT / "src" / "banco_occidente_corpus" / "arqueo" / "experimentos.py",
    PROJECT_ROOT / "src" / "banco_occidente_corpus" / "arqueo" / "informe.py",
    PROJECT_ROOT / "src" / "banco_occidente_corpus" / "arqueo" / "__main__.py",
)


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


def fila_fragmento() -> dict[str, Any]:
    """Fragmento minimo con la URL que espera la pregunta de prueba."""
    return {
        "id": "frag:a",
        "texto": "cuota de manejo de la tarjeta",
        "url": URL,
        "titulo": "Productos",
        "seccion": "oferta",
        "encabezado": "Tarjetas",
        "tipo": "pagina",
        "tokens": 8,
        "puntaje": 0.0,
    }


def linea_de_target(nombre: str) -> str:
    """Devuelve la linea de definicion de un target del makefile."""
    patron = re.compile(rf"^{re.escape(nombre)}:.*$", re.MULTILINE)
    coincidencia = patron.search(MAKEFILE.read_text(encoding="utf-8"))
    assert coincidencia is not None
    return coincidencia.group(0)


def test_makefile_tiene_target_arqueo_con_ayuda() -> None:
    """El target existe y `make help` lo puede listar."""
    # Act
    linea = linea_de_target("arqueo")

    # Assert
    assert "##" in linea
    assert "arqueo.json" in linea
    assert "ARQUEO.md" in linea


def test_arqueo_no_esta_encadenado_a_all_gold_ni_deliver() -> None:
    """Los targets del pipeline no ejecutan el Arqueo."""
    # Act / Assert
    for nombre in ("all", "gold", "deliver"):
        assert "arqueo" not in linea_de_target(nombre)


def test_help_lista_arqueo() -> None:
    """`make help` (sin make) imprime el target nuevo."""
    # Act
    resultado = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "tasks.py"), "help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    # Assert
    assert resultado.returncode == 0
    assert "arqueo" in resultado.stdout


def test_arqueo_no_importa_el_cliente_de_deepseek() -> None:
    """El paquete del Arqueo no importa ni lee la clave del modelo."""
    for ruta in FUENTES_ARQUEO:
        texto = ruta.read_text(encoding="utf-8")
        assert "langchain_deepseek" not in texto
        assert "ChatDeepSeek" not in texto
        assert 'getenv("DEEPSEEK_API_KEY"' not in texto
        assert "os.environ" not in texto


def test_arqueo_corre_sin_clave_y_escribe_los_dos_reportes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`main` funciona sin DEEPSEEK_API_KEY y escribe JSON y Markdown."""
    # Arrange
    config = make_config(tmp_path)
    write_jsonl(ruta_fragmentos(config, "base"), [fila_fragmento()])
    construir_indice(
        config,
        "base",
        configuracion=ConfiguracionEmbeddings(prefijos=True),
        embeddings=DeterministicFakeEmbedding(size=4),
    )
    salida_json = tmp_path / "arqueo.json"
    salida_md = tmp_path / "ARQUEO.md"
    monkeypatch.setattr(informe, "SALIDA_JSON", salida_json)
    monkeypatch.setattr(informe, "SALIDA_MD", salida_md)
    monkeypatch.setattr("banco_occidente_corpus.arqueo.__main__.load_config", lambda: config)
    monkeypatch.setattr(
        informe,
        "crear_embeddings",
        lambda *_args, **_kwargs: DeterministicFakeEmbedding(size=4),
    )
    monkeypatch.setattr(
        "banco_occidente_corpus.arqueo.experimentos.crear_embeddings",
        lambda *_args, **_kwargs: DeterministicFakeEmbedding(size=4),
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    # Act
    codigo = main(["--alcance", "base"])

    # Assert
    assert codigo == 0
    assert salida_json.exists()
    assert salida_md.exists()
    datos = json.loads(salida_json.read_text(encoding="utf-8"))
    assert datos["costo"]["arqueo_usd"] == 0.0
    assert len(datos["recuperacion"]) == 7
    assert datos["conteos"]["preguntas"] == 44
    assert "Arqueo escrito:" in capsys.readouterr().out


def test_main_devuelve_uno_si_falta_el_indice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Sin indice principal el mensaje pide ejecutar `make indice`."""
    # Arrange
    config = make_config(tmp_path)
    monkeypatch.setattr("banco_occidente_corpus.arqueo.__main__.load_config", lambda: config)

    # Act
    codigo = main(["--alcance", "base"])

    # Assert
    assert codigo == 1
    assert "make indice" in capsys.readouterr().err


def test_salida_json_es_estable_entre_serializaciones(tmp_path: Path) -> None:
    """Serializar dos veces el mismo diccionario produce los mismos bytes."""
    # Arrange
    datos = {"b": 2, "a": [1, 2], "c": {"z": None, "y": True}}
    destino = tmp_path / "datos.json"

    # Act
    informe.escribir_json(datos, destino)
    primero = destino.read_bytes()
    informe.escribir_json(datos, destino)

    # Assert
    assert destino.read_bytes() == primero
    assert primero.endswith(b"\n")
