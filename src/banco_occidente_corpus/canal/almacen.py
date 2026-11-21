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
from typing import Literal, cast
from uuid import uuid4

from .contratos import CasoAsesor, ResultadoDiagnostico

#: Ruta por defecto de la base del canal.
RUTA_ALMACEN: Path = Path("data/asistente/whatsapp.sqlite")

#: Estados válidos de un caso de asesor, en el orden del ciclo de vida.
ESTADOS_CASO: tuple[str, ...] = ("pendiente", "contactado", "descartado", "cerrado")
#: Estados en los que el caso sigue vivo y no debe duplicarse.
ESTADOS_ABIERTOS: tuple[str, ...] = ("pendiente", "contactado")
#: Estados finales que admite `cerrar_caso`.
EstadoCierre = Literal["contactado", "descartado", "cerrado"]
#: Cualquier estado del caso, tal como lo define el contrato.
EstadoCaso = Literal["pendiente", "contactado", "descartado", "cerrado"]
#: Semáforo del caso; `pendiente` cubre la solicitud directa de asesor.
SemaforoCaso = Literal["verde", "amarillo", "rojo", "pendiente"]

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


def registrar_caso(
    ruta: Path,
    usuario_id: str,
    motivo: str,
    *,
    semaforo: str = "pendiente",
    resultado_json: str = "{}",
    ahora: datetime | None = None,
) -> str:
    """Registra un caso para un asesor humano y devuelve su id.

    El caso guarda solo la huella del usuario, el motivo, el semáforo y el
    resultado del diagnóstico si ya existe: ni nombre, ni número, ni texto
    libre.

    Args:
        ruta: archivo SQLite del canal.
        usuario_id: huella HMAC del número.
        motivo: causa del caso (`asesor_solicitado`, `semaforo_rojo`, …).
        semaforo: color del diagnóstico, o ``pendiente`` si aún no hay cálculo.
        resultado_json: resultado del diagnóstico serializado; ``{}`` si no hay.
        ahora: instante de creación; por defecto la hora UTC actual.

    Returns:
        El identificador del caso creado.
    """
    inicializar_almacen(ruta)
    id_caso = f"caso:{uuid4().hex[:12]}"
    with conectar(ruta) as conexion:
        conexion.execute(
            "INSERT INTO casos "
            "(id_caso, usuario_id, motivo, semaforo, resultado_json, estado, creado_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                id_caso,
                usuario_id,
                motivo,
                semaforo,
                resultado_json,
                "pendiente",
                (ahora or datetime.now(UTC)).isoformat(),
            ),
        )
    return id_caso


def abrir_caso(
    ruta: Path,
    usuario_id: str,
    motivo: str,
    *,
    semaforo: str = "pendiente",
    resultado_json: str = "{}",
    ahora: datetime | None = None,
) -> str:
    """Abre un caso de asesor sin duplicar el que ya esté vivo.

    La reanudación del HITL puede ejecutarse más de una vez; si la persona ya
    tiene un caso abierto con el mismo motivo, se devuelve ese id y no se
    inserta otra fila.

    Args:
        ruta: archivo SQLite del canal.
        usuario_id: huella HMAC del número.
        motivo: causa del caso (`asesor_solicitado`, `semaforo_rojo`, …).
        semaforo: color del diagnóstico, o ``pendiente`` si aún no hay cálculo.
        resultado_json: resultado serializado; ``{}`` si no hay.
        ahora: instante de creación; por defecto la hora UTC actual.

    Returns:
        El id del caso abierto, nuevo o reutilizado.
    """
    inicializar_almacen(ruta)
    with conectar(ruta) as conexion:
        fila = conexion.execute(
            "SELECT id_caso FROM casos WHERE usuario_id = ? AND motivo = ? "
            "AND estado IN ('pendiente', 'contactado') ORDER BY creado_en LIMIT 1",
            (usuario_id, motivo),
        ).fetchone()
    if fila is not None:
        return str(fila[0])
    return registrar_caso(
        ruta,
        usuario_id,
        motivo,
        semaforo=semaforo,
        resultado_json=resultado_json,
        ahora=ahora,
    )


def cerrar_caso(ruta: Path, id_caso: str, estado: EstadoCierre = "descartado") -> bool:
    """Cierra un caso vivo y devuelve si la transición se aplicó.

    Un caso ya cerrado no cambia: una segunda reanudación del mismo HITL
    devuelve ``False`` en vez de reescribir el estado.

    Args:
        ruta: archivo SQLite del canal.
        id_caso: identificador del caso.
        estado: estado final; ``contactado``, ``descartado`` o ``cerrado``.

    Returns:
        ``True`` si el caso estaba pendiente o contactado y se cerró.
    """
    if estado not in ESTADOS_CASO or estado in ESTADOS_ABIERTOS:
        raise ValueError(f"«{estado}» no es un estado de cierre")
    with conectar(ruta) as conexion:
        cursor = conexion.execute(
            "UPDATE casos SET estado = ? WHERE id_caso = ? "
            "AND estado IN ('pendiente', 'contactado')",
            (estado, id_caso),
        )
        return cursor.rowcount > 0


def listar_casos(
    ruta: Path,
    *,
    usuario_id: str | None = None,
    estado: str | None = None,
) -> tuple[CasoAsesor, ...]:
    """Lista los casos como contratos validados, sin datos personales.

    Args:
        ruta: archivo SQLite del canal.
        usuario_id: filtra por la huella del número, si se indica.
        estado: filtra por estado; si falta, devuelve todos.

    Returns:
        Los casos ordenados por fecha de creación; vacío si la base no existe.
    """
    if not ruta.exists():
        return ()
    consulta = (
        "SELECT id_caso, usuario_id, motivo, semaforo, resultado_json, estado, creado_en FROM casos"
    )
    condiciones: list[str] = []
    parametros: list[str] = []
    if usuario_id is not None:
        condiciones.append("usuario_id = ?")
        parametros.append(usuario_id)
    if estado is not None:
        condiciones.append("estado = ?")
        parametros.append(estado)
    if condiciones:
        consulta += " WHERE " + " AND ".join(condiciones)
    consulta += " ORDER BY creado_en"
    with conectar(ruta) as conexion:
        filas = conexion.execute(consulta, parametros).fetchall()
    return tuple(_caso_desde_fila(fila) for fila in filas)


def obtener_caso(ruta: Path, id_caso: str) -> CasoAsesor | None:
    """Devuelve un caso por su id, o ``None`` si no existe.

    Args:
        ruta: archivo SQLite del canal.
        id_caso: identificador del caso.

    Returns:
        El caso validado contra el contrato.
    """
    if not ruta.exists():
        return None
    with conectar(ruta) as conexion:
        fila = conexion.execute(
            "SELECT id_caso, usuario_id, motivo, semaforo, resultado_json, estado, creado_en "
            "FROM casos WHERE id_caso = ?",
            (id_caso,),
        ).fetchone()
    return None if fila is None else _caso_desde_fila(fila)


def _caso_desde_fila(fila: tuple[object, ...]) -> CasoAsesor:
    """Convierte una fila de ``casos`` en el contrato del canal."""
    id_caso, usuario_id, motivo, semaforo, resultado_json, estado, creado_en = fila
    crudo = str(resultado_json or "{}")
    return CasoAsesor(
        id_caso=str(id_caso),
        usuario_id=str(usuario_id),
        motivo=str(motivo),
        semaforo=cast(SemaforoCaso, semaforo),
        resultado=None
        if crudo.strip() in {"", "{}"}
        else ResultadoDiagnostico.model_validate_json(crudo),
        creado_en=datetime.fromisoformat(str(creado_en)),
        estado=cast(EstadoCaso, estado),
        origen="solicitud_directa" if str(motivo) == "asesor_solicitado" else "diagnostico",
    )
