"""Pruebas del almacén de sesiones de la entrevista (sin red).

La tabla guarda solo la huella del usuario y los ids canónicos elegidos; se
comprueba que distingue «sin sesión» de «entrevista recién empezada», que
reemplaza las respuestas y que el contenido corrupto no rompe la lectura.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from banco_occidente_corpus.diagnostico.sesiones import (
    borrar,
    cargar,
    existe,
    guardar,
    inicializar,
)

USUARIO = "u" * 64
AHORA = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def test_sin_sesion_no_existe_y_carga_vacio(tmp_path: Path) -> None:
    """Una huella sin fila no tiene entrevista."""
    ruta = tmp_path / "diagnostico.sqlite"

    assert existe(ruta, USUARIO) is False
    assert cargar(ruta, USUARIO) == {}


def test_empezar_guarda_una_sesion_sin_respuestas(tmp_path: Path) -> None:
    """Pulsar Empezar deja la fila aunque el diccionario esté vacío."""
    ruta = tmp_path / "diagnostico.sqlite"

    guardar(ruta, USUARIO, {}, ahora=AHORA)

    assert existe(ruta, USUARIO) is True
    assert cargar(ruta, USUARIO) == {}


def test_guardar_reemplaza_y_borrar_limpia(tmp_path: Path) -> None:
    """Cada paso reemplaza las respuestas y borrar quita la fila."""
    ruta = tmp_path / "diagnostico.sqlite"
    guardar(ruta, USUARIO, {"objetivo": "objetivo.ahorro"}, ahora=AHORA)
    guardar(
        ruta,
        USUARIO,
        {"objetivo": "objetivo.ahorro", "vinculacion": "vinculacion.empleado"},
        ahora=AHORA,
    )

    assert cargar(ruta, USUARIO) == {
        "objetivo": "objetivo.ahorro",
        "vinculacion": "vinculacion.empleado",
    }
    assert borrar(ruta, USUARIO) is True
    assert existe(ruta, USUARIO) is False
    assert borrar(ruta, USUARIO) is False


def test_contenido_corrupto_se_ignora(tmp_path: Path) -> None:
    """Un JSON que no es diccionario se trata como sesión inexistente."""
    ruta = tmp_path / "diagnostico.sqlite"
    inicializar(ruta)
    with sqlite3.connect(str(ruta)) as conexion:
        conexion.execute(
            "INSERT INTO entrevistas (usuario_id, respuestas, actualizado_en) VALUES (?, ?, ?)",
            (USUARIO, "[1, 2]", AHORA.isoformat()),
        )

    assert existe(ruta, USUARIO) is True
    assert cargar(ruta, USUARIO) == {}
