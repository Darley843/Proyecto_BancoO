"""Pruebas del ciclo de vida del caso de asesor (tarea 4.3).

El caso nace ``pendiente``, no se duplica si se abre dos veces con el mismo
motivo, se cierra una sola vez y solo guarda lo que permite el contrato: ni
nombre, ni n├║mero, ni texto libre.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from banco_occidente_corpus.canal.almacen import (
    abrir_caso,
    cerrar_caso,
    conectar,
    inicializar_almacen,
    listar_casos,
    obtener_caso,
    registrar_caso,
)

USUARIO = "u" * 64
AHORA = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
COLUMNAS_PROHIBIDAS = {"numero", "remitente", "nombre", "texto", "telefono"}


def _ruta(tmp_path: Path) -> Path:
    """Devuelve la base del canal en la carpeta temporal."""
    return tmp_path / "whatsapp.sqlite"


def test_registrar_caso_nace_pendiente(tmp_path: Path) -> None:
    """El estado inicial es el que espera el tablero de operaci├│n."""
    ruta = _ruta(tmp_path)

    registrar_caso(ruta, USUARIO, "asesor_solicitado", ahora=AHORA)

    with sqlite3.connect(str(ruta)) as conexion:
        estados = conexion.execute("SELECT estado FROM casos").fetchall()
    assert estados == [("pendiente",)]


def test_abrir_caso_no_duplica_el_vivo(tmp_path: Path) -> None:
    """Dos aperturas con el mismo motivo devuelven el mismo caso."""
    ruta = _ruta(tmp_path)

    primero = abrir_caso(ruta, USUARIO, "semaforo_rojo", semaforo="rojo", ahora=AHORA)
    segundo = abrir_caso(ruta, USUARIO, "semaforo_rojo", semaforo="rojo", ahora=AHORA)

    assert primero == segundo
    assert len(listar_casos(ruta)) == 1


def test_abrir_caso_tras_cerrarlo_crea_uno_nuevo(tmp_path: Path) -> None:
    """Un caso descartado no bloquea una solicitud posterior."""
    ruta = _ruta(tmp_path)
    primero = abrir_caso(ruta, USUARIO, "semaforo_rojo", ahora=AHORA)
    assert cerrar_caso(ruta, primero, "descartado") is True

    segundo = abrir_caso(ruta, USUARIO, "semaforo_rojo", ahora=AHORA)

    assert segundo != primero
    assert [caso.estado for caso in listar_casos(ruta)] == ["descartado", "pendiente"]


def test_cerrar_caso_solo_una_vez(tmp_path: Path) -> None:
    """La segunda reanudaci├│n no cambia el estado ni cuenta como cierre."""
    ruta = _ruta(tmp_path)
    id_caso = abrir_caso(ruta, USUARIO, "semaforo_rojo", ahora=AHORA)

    assert cerrar_caso(ruta, id_caso, "descartado") is True
    assert cerrar_caso(ruta, id_caso, "descartado") is False
    assert obtener_caso(ruta, id_caso).estado == "descartado"  # type: ignore[union-attr]


def test_cerrar_caso_rechaza_un_estado_abierto(tmp_path: Path) -> None:
    """Cerrar con ``pendiente`` no es una transici├│n v├ílida."""
    ruta = _ruta(tmp_path)
    id_caso = abrir_caso(ruta, USUARIO, "semaforo_rojo", ahora=AHORA)

    with pytest.raises(ValueError):
        cerrar_caso(ruta, id_caso, "pendiente")  # type: ignore[arg-type]


def test_listar_casos_valida_el_contrato(tmp_path: Path) -> None:
    """Los casos se devuelven como `CasoAsesor`, con el origen deducido."""
    ruta = _ruta(tmp_path)
    directo = abrir_caso(ruta, USUARIO, "asesor_solicitado", ahora=AHORA)
    rojo = abrir_caso(ruta, USUARIO, "semaforo_rojo", semaforo="rojo", ahora=AHORA)

    casos = listar_casos(ruta)

    assert {caso.id_caso for caso in casos} == {directo, rojo}
    por_motivo = {caso.motivo: caso for caso in casos}
    assert por_motivo["asesor_solicitado"].origen == "solicitud_directa"
    assert por_motivo["asesor_solicitado"].resultado is None
    assert por_motivo["semaforo_rojo"].origen == "diagnostico"
    assert por_motivo["semaforo_rojo"].semaforo == "rojo"
    assert por_motivo["semaforo_rojo"].estado == "pendiente"


def test_el_esquema_no_admite_pii(tmp_path: Path) -> None:
    """La tabla ``casos`` no tiene columnas para datos personales."""
    ruta = _ruta(tmp_path)
    inicializar_almacen(ruta)

    with conectar(ruta) as conexion:
        columnas = {
            str(fila[1]).casefold()
            for fila in conexion.execute("PRAGMA table_info(casos)").fetchall()
        }
    assert columnas.isdisjoint(COLUMNAS_PROHIBIDAS)
