"""Pruebas de la entrega de la ficha al canal (`escena/ficha_entrega.py`).

La ficha viaja en un archivo corto de `data/escena/`: el MCP la deja y el canal
la toma una sola vez. Estas pruebas usan una ruta temporal y nunca tocan la
carpeta real.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from banco_occidente_corpus.escena import ficha_entrega

PNG = b"\x89PNG\r\n\x1a\nficha"


@pytest.fixture
def ruta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Apunta la entrega a una carpeta temporal y enciende la escena."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    destino = tmp_path / "escena" / "ficha_entrega.json"
    monkeypatch.setattr(ficha_entrega, "RUTA_ENTREGA", destino)
    return destino


def test_sin_escena_no_deja_nada(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Con el interruptor apagado no se crea la carpeta ni el archivo."""
    monkeypatch.delenv("ESCENA_EN_VIVO", raising=False)
    destino = tmp_path / "escena" / "ficha_entrega.json"
    monkeypatch.setattr(ficha_entrega, "RUTA_ENTREGA", destino)

    assert ficha_entrega.dejar_ficha("ficha aparte", PNG) is False
    assert not destino.parent.exists()


def test_el_canal_toma_la_ficha_una_sola_vez(ruta: Path) -> None:
    """La ficha queda disponible, se entrega con su PNG y se borra."""
    momento = datetime.now(UTC)
    assert ficha_entrega.dejar_ficha("ficha aparte", PNG, momento=momento)

    assert ficha_entrega.tomar_ficha(momento) == ("ficha aparte", PNG)
    assert not ruta.exists()
    assert ficha_entrega.tomar_ficha(momento) is None


def test_una_ficha_de_un_turno_anterior_se_descarta(ruta: Path) -> None:
    """Si la ficha quedó de un turno viejo, no se envía y se borra."""
    momento = datetime.now(UTC)
    assert ficha_entrega.dejar_ficha("ficha vieja", PNG, momento=momento)

    assert ficha_entrega.tomar_ficha(momento + timedelta(minutes=1)) is None
    assert not ruta.exists()


def test_borrar_ficha_limpia_la_pendiente(ruta: Path) -> None:
    """El cierre del evento puede borrar la ficha sin abrir el canal."""
    assert ficha_entrega.dejar_ficha("ficha aparte", PNG)

    ficha_entrega.borrar_ficha()

    assert not ruta.exists()
