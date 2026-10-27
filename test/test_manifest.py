"""Pruebas de los metadatos del contexto (sin red y sin ejecutar git).

La fecha se obtiene con ``git log``; aqui ``subprocess.run`` se simula siempre,
de modo que la suite nunca invoca git de verdad.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from banco_occidente_corpus.asistente import manifest as manifest_mod
from banco_occidente_corpus.asistente.manifest import (
    RUTA_MANIFEST_RELATIVA,
    ManifestAusente,
    cargar_metadatos,
    fecha_version_contexto,
)

FECHA_COMMIT = "2026-10-26T13:09:07-05:00"

MANIFEST = """{
  "version": 1,
  "max_tokens": 175000,
  "tokens": 167057,
  "tokens_metodo": "stable_tokens (chars/4, sin red)",
  "paginas": {"leidas": 243, "incluidas": 193, "excluidas": 50}
}
"""


def _manifest(tmp_path: Path) -> Path:
    """Escribe un manifest minimo con los campos que lee la app."""
    ruta = tmp_path / "manifest.json"
    ruta.write_text(MANIFEST, encoding="utf-8", newline="\n")
    return ruta


def _proceso(stdout: str = FECHA_COMMIT, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    """Resultado simulado de ``git log``."""
    return subprocess.CompletedProcess(
        args=["git", "log"],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


def _simular(monkeypatch: pytest.MonkeyPatch, funcion: Any) -> list[dict[str, Any]]:
    """Sustituye ``subprocess.run`` y devuelve la lista de llamadas recibidas."""
    llamadas: list[dict[str, Any]] = []

    def falso(*args: Any, **kwargs: Any) -> Any:
        llamadas.append({"args": args, "kwargs": kwargs})
        return funcion()

    monkeypatch.setattr(manifest_mod.subprocess, "run", falso)
    return llamadas


# ---------------------------------------------------------------- metadatos


def test_cargar_metadatos_lee_tokens_tope_y_paginas(tmp_path: Path) -> None:
    """El manifest aporta los tokens del contexto y las paginas incluidas."""
    ruta = _manifest(tmp_path)

    metadatos = cargar_metadatos(ruta)

    assert metadatos.tokens == 167_057
    assert metadatos.max_tokens == 175_000
    assert metadatos.paginas_incluidas == 193
    assert metadatos.tokens_metodo.startswith("stable_tokens")


def test_cargar_metadatos_sin_manifest_sugiere_make_contexto(tmp_path: Path) -> None:
    """Sin manifest, el error explica como generarlo."""
    with pytest.raises(ManifestAusente, match="make contexto"):
        cargar_metadatos(tmp_path / "no-existe.json")


# ---------------------------------------------------------------- fecha git


def test_fecha_version_contexto_devuelve_la_fecha_del_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Con git disponible devuelve la fecha ISO del ultimo commit."""
    llamadas = _simular(monkeypatch, lambda: _proceso(f"{FECHA_COMMIT}\n"))

    fecha = fecha_version_contexto(ruta=tmp_path / "manifest.json", cwd=tmp_path)

    assert fecha == FECHA_COMMIT
    assert len(llamadas) == 1


def test_fecha_version_contexto_invoca_git_sin_shell_y_con_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """La llamada usa lista de argumentos, timeout y el cwd indicado."""
    llamadas = _simular(monkeypatch, lambda: _proceso())

    fecha = fecha_version_contexto(ruta=tmp_path / "manifest.json", cwd=tmp_path, timeout=3.0)

    assert fecha == FECHA_COMMIT
    args = llamadas[0]["args"]
    kwargs = llamadas[0]["kwargs"]
    assert args[0] == ["git", "log", "-1", "--format=%cI", "--", RUTA_MANIFEST_RELATIVA]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["timeout"] == 3.0
    assert kwargs.get("shell", False) is False
    assert kwargs["capture_output"] is True


def test_fecha_version_contexto_sin_git_devuelve_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si git no esta instalado, la app muestra 'no disponible' sin caerse."""

    def falla() -> Any:
        raise FileNotFoundError("git")

    _simular(monkeypatch, falla)

    assert fecha_version_contexto() is None


def test_fecha_version_contexto_con_timeout_devuelve_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un git colgado no bloquea la app."""

    def agota() -> Any:
        raise subprocess.TimeoutExpired(cmd="git log", timeout=5.0)

    _simular(monkeypatch, agota)

    assert fecha_version_contexto() is None


def test_fecha_version_contexto_sin_versionar_devuelve_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un archivo sin commits (o un repo ausente) no produce fecha."""
    _simular(monkeypatch, lambda: _proceso(stdout="", returncode=128))

    assert fecha_version_contexto() is None


def test_fecha_version_contexto_con_salida_vacia_devuelve_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin stdout no hay fecha que mostrar."""
    _simular(monkeypatch, lambda: _proceso(stdout="  \n"))

    assert fecha_version_contexto() is None
