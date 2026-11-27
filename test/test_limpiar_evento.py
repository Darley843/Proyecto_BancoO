"""Contrato de `scripts/limpiar_evento.ps1`: fuerza la parada y compacta las bases."""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "scripts" / "limpiar_evento.ps1"


def _texto() -> str:
    """Lee el script sin depender del BOM ni del fin de línea de Windows."""
    return SCRIPT.read_text(encoding="utf-8-sig", errors="replace")


def test_modo_prueba_muestra_la_compactacion() -> None:
    """El resumen de prueba enseña que se compactan la base del agente y la de estado."""
    texto = _texto()
    assert "Invoke-CompactacionBases -Compactar $false" in texto
    assert "openclaw-agent.sqlite" in texto
    assert "state/openclaw.sqlite" in texto
    assert "PRAGMA wal_checkpoint(TRUNCATE)" in texto
    assert "VACUUM" in texto
    assert "Bases que se compactarian" in texto


def test_confirmar_detiene_el_gateway_con_force() -> None:
    """OpenClaw 2026.11.6 exige --force y solo se usa dentro de -Confirmar."""
    texto = _texto()
    assert "'daemon', 'stop', '--force'" in texto
    assert "Invoke-OpenClaw -Argumentos @('daemon', 'stop')" not in texto


def test_el_gateway_se_vuelve_a_levantar_en_el_finally() -> None:
    """La parada forzada nunca deja el gateway apagado si algo falla."""
    texto = _texto()
    assert "finally {" in texto
    assert "Invoke-OpenClaw -Argumentos @('daemon', 'start')" in texto


def test_memory_forget_y_reset_no_reciben_force() -> None:
    """Solo daemon stop pide --force; el olvido y el reset no lo aceptan."""
    texto = _texto()
    assert "'memory', 'forget', '--force'" not in texto
    assert "'memory', 'reset', '--force'" not in texto
