"""Sesiones de la entrevista del diagnóstico en SQLite.

Guarda la huella del usuario y las respuestas canónicas de la entrevista
(`objetivo.libre_inversion`, `ingresos.DE_5M_A_8M`, …), nada más: ni nombre, ni
número, ni texto libre. La base vive en `data/asistente/diagnostico.sqlite`, que
`.gitignore` excluye; se regenera borrándola.

La sesión no guarda el paso actual: se deduce de las respuestas con
`entrevista.pregunta_pendiente`. Así un reinicio del proceso no repite preguntas
ni inventa estado.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

#: Ruta por defecto de las sesiones de la entrevista.
RUTA_SESIONES: Path = Path("data/asistente/diagnostico.sqlite")

#: Esquema de la tabla de sesiones.
ESQUEMA: str = """
CREATE TABLE IF NOT EXISTS entrevistas (
    usuario_id TEXT PRIMARY KEY,
    respuestas TEXT NOT NULL,
    actualizado_en TEXT NOT NULL
);
"""


def conectar(ruta: Path = RUTA_SESIONES) -> sqlite3.Connection:
    """Abre la base de sesiones y crea la carpeta si falta.

    Args:
        ruta: archivo SQLite; por defecto `data/asistente/diagnostico.sqlite`.

    Returns:
        Conexión abierta, lista para usar con ``with``.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(ruta), check_same_thread=False)


def inicializar(ruta: Path = RUTA_SESIONES) -> None:
    """Crea la tabla de sesiones si no existe.

    Es idempotente: dos llamadas dejan el mismo esquema y conservan los datos.

    Args:
        ruta: archivo SQLite de las sesiones.
    """
    with conectar(ruta) as conexion:
        conexion.executescript(ESQUEMA)


def cargar(ruta: Path, usuario_id: str) -> dict[str, str]:
    """Devuelve las respuestas guardadas de una persona.

    Args:
        ruta: archivo SQLite de las sesiones.
        usuario_id: huella HMAC del número, nunca el número.

    Returns:
        Las respuestas por bloque; vacío si no hay entrevista en curso o si el
        contenido guardado no tiene la forma esperada.
    """
    inicializar(ruta)
    with conectar(ruta) as conexion:
        fila = conexion.execute(
            "SELECT respuestas FROM entrevistas WHERE usuario_id = ?",
            (usuario_id,),
        ).fetchone()
    if fila is None:
        return {}
    try:
        datos = json.loads(str(fila[0]))
    except ValueError:
        return {}
    if not isinstance(datos, dict):
        return {}
    return {str(clave): str(valor) for clave, valor in datos.items()}


def existe(ruta: Path, usuario_id: str) -> bool:
    """Dice si hay una entrevista iniciada, aunque no tenga respuestas.

    Sirve para distinguir «no hay sesión» de «la persona pulsó Empezar y todavía
    no eligió el objetivo»: las dos guardan un diccionario vacío.

    Args:
        ruta: archivo SQLite de las sesiones.
        usuario_id: huella HMAC del número.

    Returns:
        ``True`` si la persona tiene una entrevista en curso.
    """
    inicializar(ruta)
    with conectar(ruta) as conexion:
        fila = conexion.execute(
            "SELECT 1 FROM entrevistas WHERE usuario_id = ?",
            (usuario_id,),
        ).fetchone()
    return fila is not None


def guardar(
    ruta: Path,
    usuario_id: str,
    respuestas: Mapping[str, str],
    *,
    ahora: datetime | None = None,
) -> None:
    """Guarda o reemplaza las respuestas de una entrevista en curso.

    Args:
        ruta: archivo SQLite de las sesiones.
        usuario_id: huella HMAC del número.
        respuestas: bloque → id canónico elegido.
        ahora: instante de la actualización; por defecto la hora UTC actual.
    """
    inicializar(ruta)
    instante = (ahora or datetime.now(UTC)).isoformat()
    with conectar(ruta) as conexion:
        conexion.execute(
            "INSERT INTO entrevistas (usuario_id, respuestas, actualizado_en) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(usuario_id) DO UPDATE SET respuestas = excluded.respuestas, "
            "actualizado_en = excluded.actualizado_en",
            (usuario_id, json.dumps(dict(respuestas), ensure_ascii=False), instante),
        )


def borrar(ruta: Path, usuario_id: str) -> bool:
    """Borra la entrevista de una persona.

    Args:
        ruta: archivo SQLite de las sesiones.
        usuario_id: huella HMAC del número.

    Returns:
        ``True`` si había una sesión y se borró.
    """
    inicializar(ruta)
    with conectar(ruta) as conexion:
        cursor = conexion.execute(
            "DELETE FROM entrevistas WHERE usuario_id = ?",
            (usuario_id,),
        )
        return cursor.rowcount > 0
