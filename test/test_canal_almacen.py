"""Pruebas del almacén SQLite del canal.

Fijan el esquema del diseño: cinco tablas, sin columnas para el número, el
nombre ni el texto, y una inicialización idempotente que no borra datos.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from banco_occidente_corpus.canal.almacen import inicializar_almacen

TABLAS = {"mensajes", "consentimientos", "envios", "casos", "entrevistas", "resultados_diagnostico"}
"""Las seis tablas que debe crear la inicialización."""

COLUMNAS_PROHIBIDAS = {"numero", "remitente", "nombre", "texto", "telefono"}
"""Ninguna tabla puede guardar datos personales ni el cuerpo del mensaje."""


def _tablas(ruta: Path) -> set[str]:
    """Devuelve los nombres de las tablas de usuario de la base."""
    with sqlite3.connect(str(ruta)) as conexion:
        filas = conexion.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {fila[0] for fila in filas}


def _columnas(ruta: Path, tabla: str) -> list[str]:
    """Devuelve las columnas de una tabla en orden de definición."""
    with sqlite3.connect(str(ruta)) as conexion:
        filas = conexion.execute(f"PRAGMA table_info({tabla})").fetchall()
    return [fila[1] for fila in filas]


def test_crea_las_cinco_tablas(tmp_path: Path) -> None:
    """La inicialización deja mensajes, consentimientos, envíos, casos y entrevistas."""
    ruta = tmp_path / "whatsapp.sqlite"

    inicializar_almacen(ruta)

    assert _tablas(ruta) == TABLAS


def test_es_idempotente(tmp_path: Path) -> None:
    """Dos inicializaciones dejan el mismo esquema y no fallan."""
    ruta = tmp_path / "whatsapp.sqlite"

    inicializar_almacen(ruta)
    antes = {tabla: _columnas(ruta, tabla) for tabla in TABLAS}
    inicializar_almacen(ruta)

    assert _tablas(ruta) == TABLAS
    assert {tabla: _columnas(ruta, tabla) for tabla in TABLAS} == antes


def test_conserva_los_datos_al_reinicializar(tmp_path: Path) -> None:
    """Reinicializar no borra un mensaje ya registrado."""
    ruta = tmp_path / "whatsapp.sqlite"
    inicializar_almacen(ruta)

    with sqlite3.connect(str(ruta)) as conexion:
        conexion.execute(
            "INSERT INTO mensajes (id_mensaje, usuario_id, estado, recibido_en) "
            "VALUES (?, ?, ?, ?)",
            ("wamid.SIM1", "u" * 32, "recibido", "2026-11-16T12:00:00+00:00"),
        )

    inicializar_almacen(ruta)

    with sqlite3.connect(str(ruta)) as conexion:
        total = conexion.execute("SELECT COUNT(*) FROM mensajes").fetchone()[0]

    assert total == 1


def test_ninguna_tabla_guarda_numero_nombre_ni_texto(tmp_path: Path) -> None:
    """El esquema no tiene columnas de PII ni del cuerpo del mensaje."""
    ruta = tmp_path / "whatsapp.sqlite"
    inicializar_almacen(ruta)

    for tabla in TABLAS:
        columnas = {columna.casefold() for columna in _columnas(ruta, tabla)}
        assert columnas.isdisjoint(COLUMNAS_PROHIBIDAS), tabla


def test_mensajes_tiene_las_columnas_del_diseno(tmp_path: Path) -> None:
    """La tabla de deduplicación conserva id, usuario, estado, fechas y motor."""
    ruta = tmp_path / "whatsapp.sqlite"
    inicializar_almacen(ruta)

    assert _columnas(ruta, "mensajes") == [
        "id_mensaje",
        "usuario_id",
        "estado",
        "recibido_en",
        "procesado_en",
        "motor",
    ]


def test_migra_una_base_anterior_sin_motor(tmp_path: Path) -> None:
    """Una base creada antes del motor recibe la columna sin perder datos."""
    ruta = tmp_path / "whatsapp.sqlite"
    with sqlite3.connect(str(ruta)) as conexion:
        conexion.execute(
            "CREATE TABLE mensajes ("
            "id_mensaje TEXT PRIMARY KEY, usuario_id TEXT NOT NULL, "
            "estado TEXT NOT NULL, recibido_en TEXT NOT NULL, procesado_en TEXT)"
        )
        conexion.execute(
            "INSERT INTO mensajes (id_mensaje, usuario_id, estado, recibido_en) "
            "VALUES (?, ?, ?, ?)",
            ("wamid.VIEJO", "u" * 32, "respondido", "2026-11-16T12:00:00+00:00"),
        )

    inicializar_almacen(ruta)

    assert "motor" in _columnas(ruta, "mensajes")
    with sqlite3.connect(str(ruta)) as conexion:
        total = conexion.execute("SELECT COUNT(*) FROM mensajes").fetchone()[0]
    assert total == 1


def test_crea_la_carpeta_padre(tmp_path: Path) -> None:
    """La base se crea aunque la carpeta intermedia no exista."""
    ruta = tmp_path / "asistente" / "whatsapp.sqlite"

    inicializar_almacen(ruta)

    assert ruta.exists()
    assert _tablas(ruta) == TABLAS
