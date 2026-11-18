"""Pruebas del cargador de ``config/whatsapp.toml`` (sin red).

Usan archivos temporales: el cargador no depende de que el TOML versionado
exista ni de que la rama traiga la configuración del canal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from banco_occidente_corpus.canal.configuracion import cargar_configuracion_canal


def test_cargar_configuracion_desde_un_toml(tmp_path: Path) -> None:
    """El cargador tipa el TOML y conserva las huellas."""
    ruta = tmp_path / "whatsapp.toml"
    ruta.write_text(
        "[canal]\n"
        'version_api = "v23.0"\n'
        'modo = "falso"\n'
        'pais_por_defecto = "57"\n'
        "limite_intentos_roba = 20\n"
        "retencion_dias = 30\n"
        "[autorizados]\n"
        'huellas = ["a", "b"]\n',
        encoding="utf-8",
    )

    configuracion = cargar_configuracion_canal(ruta)

    assert configuracion.modo == "falso"
    assert configuracion.version_api == "v23.0"
    assert configuracion.pais_por_defecto == "57"
    assert configuracion.huellas == ("a", "b")


def test_sin_archivo_devuelve_el_canal_apagado(tmp_path: Path) -> None:
    """Sin TOML no hay huellas ni modo real: el canal queda en falso."""
    configuracion = cargar_configuracion_canal(tmp_path / "no-existe.toml")

    assert configuracion.modo == "falso"
    assert configuracion.huellas == ()


def test_modo_por_entorno_sobrescribe_el_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``WHATSAPP_MODO`` manda sobre ``canal.modo``."""
    monkeypatch.setenv("WHATSAPP_MODO", "real")
    ruta = tmp_path / "whatsapp.toml"
    ruta.write_text('[canal]\nmodo = "falso"\n', encoding="utf-8")

    assert cargar_configuracion_canal(ruta).modo == "real"


def test_modo_invalido_falla(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un modo fuera de falso/real no se acepta en silencio."""
    monkeypatch.setenv("WHATSAPP_MODO", "produccion")
    ruta = tmp_path / "whatsapp.toml"
    ruta.write_text("[canal]\n", encoding="utf-8")

    with pytest.raises(ValueError):
        cargar_configuracion_canal(ruta)
