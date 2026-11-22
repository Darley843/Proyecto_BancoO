"""Pruebas del perfil en el canal (tarea 2.6, sin red).

La revocación «olvida mis datos» borra también el perfil del store, con la
misma huella con la que se guardó, y no toca el de otra persona.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from langgraph.store.sqlite import SqliteStore

from banco_occidente_corpus.canal.almacen import registrar_caso
from banco_occidente_corpus.canal.consentimiento import MaquinaConsentimiento
from banco_occidente_corpus.canal.contratos import MensajeEntrante
from banco_occidente_corpus.sucursal.perfil import AlmacenPerfil, borrar_perfil_en, huella_perfil

USUARIO_A = "a" * 64
USUARIO_B = "b" * 64
AHORA = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def _conexion(ruta: Path) -> sqlite3.Connection:
    """Abre el store de perfil en autocommit, como en producción."""
    return sqlite3.connect(str(ruta), check_same_thread=False, isolation_level=None)


def _guardar(ruta: Path, usuario_id: str, nombre: str) -> None:
    """Guarda un perfil con la huella que usa el canal."""
    conexion = _conexion(ruta)
    try:
        AlmacenPerfil(SqliteStore(conexion)).guardar(huella_perfil(usuario_id), {"nombre": nombre})
    finally:
        conexion.close()


def _leer(ruta: Path, usuario_id: str) -> dict[str, str]:
    """Lee el perfil de una persona."""
    conexion = _conexion(ruta)
    try:
        return AlmacenPerfil(SqliteStore(conexion)).leer(huella_perfil(usuario_id))
    finally:
        conexion.close()


def _mensaje(texto: str) -> MensajeEntrante:
    """Construye un mensaje entrante válido."""
    return MensajeEntrante(
        id_mensaje="wamid.perfil",
        remitente="57000000001",
        texto=texto,
        recibido_en=AHORA,
    )


def test_revocar_borra_el_perfil(tmp_path: Path) -> None:
    """«Olvida mis datos» deja el store sin el perfil de esa persona."""
    ruta_canal = tmp_path / "whatsapp.sqlite"
    ruta_perfil = tmp_path / "perfil.sqlite"
    _guardar(ruta_perfil, USUARIO_A, "Ana")
    _guardar(ruta_perfil, USUARIO_B, "Beto")
    maquina = MaquinaConsentimiento(
        ruta_canal,
        borrar_perfil=partial(borrar_perfil_en, ruta_perfil),
    )
    maquina.aceptar(USUARIO_A, AHORA)
    registrar_caso(ruta_canal, USUARIO_A, "semaforo_rojo", semaforo="rojo", ahora=AHORA)

    respuesta = maquina.decidir(_mensaje("olvida mis datos"), USUARIO_A)

    assert respuesta is not None
    assert "borré" in respuesta.texto.lower()
    assert _leer(ruta_perfil, USUARIO_A) == {}
    assert _leer(ruta_perfil, USUARIO_B) == {"nombre": "Beto"}
    assert maquina.estado(USUARIO_A) == "sin_consentimiento"
    with sqlite3.connect(str(ruta_canal)) as conexion:
        casos = conexion.execute("SELECT COUNT(*) FROM casos WHERE usuario_id = ?", (USUARIO_A,))
    assert casos.fetchone()[0] == 0


def test_sin_callback_la_revocacion_no_falla(tmp_path: Path) -> None:
    """Una máquina sin callback sigue revocando el consentimiento."""
    ruta_canal = tmp_path / "whatsapp.sqlite"
    maquina = MaquinaConsentimiento(ruta_canal)
    maquina.aceptar(USUARIO_A, AHORA)

    maquina.revocar(USUARIO_A)

    assert maquina.estado(USUARIO_A) == "sin_consentimiento"


def test_borrar_perfil_sin_archivo_no_falla(tmp_path: Path) -> None:
    """Si el store no existe todavía, la revocación no crea un archivo vacío."""
    ruta = tmp_path / "perfil.sqlite"

    borrar_perfil_en(ruta, USUARIO_A)

    assert not ruta.exists()
