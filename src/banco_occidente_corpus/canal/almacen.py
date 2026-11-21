"""Almacén SQLite del canal de WhatsApp.

Cinco tablas: ``mensajes`` para la deduplicación por id, ``consentimientos``
para la Ley 1581, ``envios`` para que un reintento no duplique la respuesta,
``casos`` para los asesores humanos y ``entrevistas`` para el paso actual y los
ids elegidos en la entrevista del diagnóstico.

El esquema no tiene columnas para el número, el nombre ni el texto del mensaje:
el perfil vive fuera del repositorio y el número solo existe en memoria. La
entrevista guarda únicamente ids canónicos y el nombre del paso, nunca el texto
libre. La base tampoco se versiona: se crea al usarla y se regenera borrándola.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

#: Ruta por defecto de la base del canal.
RUTA_ALMACEN: Path = Path("data/asistente/whatsapp.sqlite")

#: Esquema de las cinco tablas del canal.
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

CREATE TABLE IF NOT EXISTS entrevistas (
    usuario_id TEXT PRIMARY KEY,
    paso TEXT NOT NULL,
    respuestas_json TEXT NOT NULL,
    actualizado_en TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resultados_diagnostico (
    usuario_id TEXT PRIMARY KEY,
    resultado_json TEXT NOT NULL,
    guardado_en TEXT NOT NULL
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
    """Crea las tablas del canal si no existen.

    Es idempotente: llamarla dos veces deja el mismo esquema y conserva los
    datos ya escritos.

    Args:
        ruta: archivo SQLite; por defecto ``data/asistente/whatsapp.sqlite``.
    """
    with conectar(ruta) as conexion:
        conexion.executescript(ESQUEMA)


def registrar_mensaje(
    ruta: Path,
    id_mensaje: str,
    usuario_id: str,
    estado: str,
    recibido_en: datetime,
) -> bool:
    """Registra un mensaje entrante si su id no estaba visto.

    Args:
        ruta: archivo SQLite del canal.
        id_mensaje: id de Meta; es la clave de deduplicación.
        usuario_id: huella del número, nunca el número.
        estado: estado inicial del mensaje.
        recibido_en: instante del mensaje.

    Returns:
        ``True`` si el mensaje es nuevo; ``False`` si Meta lo reenvió.
    """
    with conectar(ruta) as conexion:
        cursor = conexion.execute(
            "INSERT OR IGNORE INTO mensajes "
            "(id_mensaje, usuario_id, estado, recibido_en) VALUES (?, ?, ?, ?)",
            (id_mensaje, usuario_id, estado, recibido_en.isoformat()),
        )
        return cursor.rowcount > 0


def actualizar_mensaje(
    ruta: Path,
    id_mensaje: str,
    estado: str,
    *,
    procesado: bool = False,
) -> None:
    """Cambia el estado de un mensaje ya registrado.

    Args:
        ruta: archivo SQLite del canal.
        id_mensaje: id de Meta.
        estado: ``procesando``, ``respondido``, ``error`` o ``ignorado``.
        procesado: si se marca la hora de procesamiento.
    """
    procesado_en = datetime.now(UTC).isoformat() if procesado else None
    with conectar(ruta) as conexion:
        conexion.execute(
            "UPDATE mensajes SET estado = ?, procesado_en = COALESCE(?, procesado_en) "
            "WHERE id_mensaje = ?",
            (estado, procesado_en, id_mensaje),
        )


def marcar_procesando_como_error(ruta: Path) -> int:
    """Marca como ``error`` los mensajes que quedaron a medias al apagar.

    Args:
        ruta: archivo SQLite del canal.

    Returns:
        Cuántos mensajes se corrigieron.
    """
    with conectar(ruta) as conexion:
        cursor = conexion.execute(
            "UPDATE mensajes SET estado = 'error' WHERE estado = 'procesando'"
        )
        return cursor.rowcount


def contar_mensajes(ruta: Path) -> dict[str, int]:
    """Cuenta los mensajes por estado, útil para el tablero de operación.

    Args:
        ruta: archivo SQLite del canal.

    Returns:
        Diccionario ``estado -> total``; vacío si la base no existe.
    """
    if not ruta.exists():
        return {}
    with conectar(ruta) as conexion:
        filas = conexion.execute("SELECT estado, COUNT(*) FROM mensajes GROUP BY estado").fetchall()
    return {str(estado): int(total) for estado, total in filas}
