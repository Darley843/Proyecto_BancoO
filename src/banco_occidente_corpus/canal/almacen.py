"""Almacén SQLite del canal de WhatsApp.

Cuatro tablas: ``mensajes`` para la deduplicación por id, ``consentimientos``
para la Ley 1581, ``envios`` para que un reintento no duplique la respuesta y
``casos`` para los asesores humanos.

El esquema no tiene columnas para el número, el nombre ni el texto del mensaje:
el perfil vive fuera del repositorio y el número solo existe en memoria. La base
tampoco se versiona: se crea al usarla y se regenera borrándola.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

#: Ruta por defecto de la base del canal.
RUTA_ALMACEN: Path = Path("data/asistente/whatsapp.sqlite")

#: Esquema de las cuatro tablas del canal.
ESQUEMA: str = """
CREATE TABLE IF NOT EXISTS mensajes (
    id_mensaje TEXT PRIMARY KEY,
    usuario_id TEXT NOT NULL,
    estado TEXT NOT NULL,
    recibido_en TEXT NOT NULL,
    procesado_en TEXT
);

CREATE TABLE IF NOT EXISTS consentimientos (
    usuario_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    aceptado_en TEXT NOT NULL,
    revocado_en TEXT
);

CREATE TABLE IF NOT EXISTS envios (
    clave TEXT PRIMARY KEY,
    id_mensaje TEXT NOT NULL,
    usuario_id TEXT NOT NULL,
    estado TEXT NOT NULL,
    creado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS casos (
    id_caso TEXT PRIMARY KEY,
    usuario_id TEXT NOT NULL,
    motivo TEXT NOT NULL,
    semaforo TEXT NOT NULL,
    resultado_json TEXT NOT NULL,
    estado TEXT NOT NULL,
    creado_en TEXT NOT NULL
);
"""


def conectar(ruta: Path = RUTA_ALMACEN) -> sqlite3.Connection:
    """Abre una conexión con la base del canal y crea la carpeta si falta.

    Args:
        ruta: archivo SQLite; por defecto ``data/asistente/whatsapp.sqlite``.

    Returns:
        Conexión abierta, lista para usar con ``with`` o cerrar a mano.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(ruta), check_same_thread=False)


def inicializar_almacen(ruta: Path = RUTA_ALMACEN) -> None:
    """Crea las cuatro tablas del canal si no existen.

    Es idempotente: llamarla dos veces deja el mismo esquema y conserva los
    datos ya escritos.

    Args:
        ruta: archivo SQLite; por defecto ``data/asistente/whatsapp.sqlite``.
    """
    with conectar(ruta) as conexion:
        conexion.executescript(ESQUEMA)
