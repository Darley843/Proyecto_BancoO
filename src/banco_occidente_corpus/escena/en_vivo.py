"""Publicador local de la escena en vivo (`docs/ESCENA_EN_VIVO.md`, §4–§7).

Una sola lista `data/escena/en_vivo.jsonl`, con un turno `TurnoEscena` por
linea. La escritura solo ocurre con ``ESCENA_EN_VIVO=1`` y pasa por un bloqueo
del sistema sobre ``en_vivo.lock``, para que el MCP y la app no repitan ``seq``
ni mezclen lineas. Un turno identico al ultimo publicado del mismo personaje
(mismo ``id`` y mismo ``texto``) se descarta, para que la pantalla no repita
cuatro veces el veredicto del auditor. Las funciones nunca lanzan hacia la
herramienta: un fallo de escritura, un bloqueo ocupado o un turno invalido se
registran por codigo y la respuesta sigue. El texto de los turnos nunca se
registra en los logs.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import BinaryIO, Literal, TypedDict

from pydantic import ValidationError

from ..asistente.validacion import detectar_pii
from ..config import PROJECT_ROOT
from .contratos import TurnoEscena

#: Variable de la sesion que enciende la escritura; solo el valor exacto `1`.
VARIABLE_INTERRUPTOR: str = "ESCENA_EN_VIVO"
#: Valor que activa la escritura.
VALOR_ACTIVO: str = "1"
#: Lista local de la escena en vivo; se borra al terminar el evento.
RUTA_EN_VIVO: Path = PROJECT_ROOT / "data" / "escena" / "en_vivo.jsonl"
#: Nombre del centinela del bloqueo, hermano de la lista.
NOMBRE_BLOQUEO: str = "en_vivo.lock"
#: Tope de caracteres del texto de un turno.
MAXIMO_TEXTO: int = 4000
#: Tope de bytes de una linea completa.
MAXIMO_LINEA: int = 16 * 1024
#: Bytes que se leen del final cuando el archivo supera los 2 MB.
MAXIMO_LECTURA: int = 2 * 1024 * 1024
#: Turnos maximos que devuelve una lectura.
LIMITE_LECTURA: int = 200
#: Espera maxima por el bloqueo del sistema, en segundos.
ESPERA_BLOQUEO: float = 2.0

#: Origenes validos del sobre de la lista.
OrigenLista = Literal["herramienta", "canal"]
_ORIGENES: frozenset[str] = frozenset({"herramienta", "canal"})

_msvcrt: ModuleType | None = import_module("msvcrt") if sys.platform == "win32" else None
_fcntl: ModuleType | None = import_module("fcntl") if sys.platform != "win32" else None

_CANDADO = threading.Lock()
_CONTADOR: int = 0
logger = logging.getLogger(__name__)


class _Registro(TypedDict):
    """Un registro valido del archivo, con el turno ya validado."""

    seq: int
    ts: str
    origen: str
    turno: dict[str, object]


def publicar_turnos(
    turnos: Iterable[TurnoEscena | dict[str, object]],
    *,
    origen: OrigenLista,
    permitidos: Iterable[str] = (),
    ruta: Path | None = None,
) -> tuple[int, ...]:
    """Publica un lote de turnos en la lista local de la escena en vivo.

    Con el interruptor apagado no se crea la carpeta, no se abre la lista, no se
    toca el bloqueo y no se escribe nada. Con el interruptor encendido valida
    cada turno, descarta los invalidos y los que traen datos personales, y
    escribe los demas como una linea JSON compacta por turno.

    Args:
        turnos: turnos de la escena, ya construidos por su modulo.
        origen: quien publica, el MCP (``herramienta``) o el canal (``canal``).
        permitidos: telefonos publicos del banco que el detector de PII no debe
            marcar; las herramientas lo omiten.
        ruta: lista alternativa; solo para pruebas.

    Returns:
        Los ``seq`` escritos, en orden; vacio si el interruptor esta apagado o
        si el lote se descarta.
    """
    if os.environ.get(VARIABLE_INTERRUPTOR) != VALOR_ACTIVO:
        return ()
    if origen not in _ORIGENES:
        logger.warning("escena_en_vivo descarte origen_invalido")
        return ()
    try:
        ruta_datos = Path(ruta) if ruta is not None else RUTA_EN_VIVO
        permitidos_tupla = tuple(permitidos)
        preparados = [
            datos
            for turno in turnos
            if (datos := _preparar_turno(turno, permitidos=permitidos_tupla)) is not None
        ]
        if not preparados:
            return ()
        return _escribir_lote(preparados, origen=origen, ruta=ruta_datos)
    except OSError:
        logger.warning("escena_en_vivo descarte escritura_fallida")
        return ()
    except Exception:  # noqa: BLE001 - la publicacion nunca rompe la respuesta
        logger.warning("escena_en_vivo descarte error_publicacion")
        return ()


def leer_turnos(
    desde: int = 0,
    *,
    limite: int = LIMITE_LECTURA,
    ruta: Path | None = None,
) -> tuple[tuple[dict[str, object], ...], int]:
    """Lee los turnos nuevos de la lista, en orden ascendente de ``seq``.

    La lectura es tolerante: ignora lineas vacias, JSON invalido, ``seq`` que no
    sea entero y turnos que no validen con `TurnoEscena`. No escribe, no crea
    carpetas y no toma el bloqueo. Si el archivo no existe devuelve la lista
    vacia sin crearlo.

    Args:
        desde: devuelve solo los turnos con ``seq`` mayor que este valor.
        limite: maximo de turnos devueltos.
        ruta: lista alternativa; solo para pruebas.

    Returns:
        La tupla de registros ``{seq, ts, origen, turno}`` y el ultimo ``seq``
        entregado (o ``desde`` si no hay turnos nuevos).
    """
    inicio = int(desde)
    tope = max(0, int(limite))
    try:
        ruta_datos = Path(ruta) if ruta is not None else RUTA_EN_VIVO
        if tope == 0 or not ruta_datos.is_file():
            return (), inicio
        registros: list[_Registro] = []
        for linea in _lineas_de(ruta_datos):
            registro = _registro(linea)
            if registro is None or registro["seq"] <= inicio:
                continue
            registros.append(registro)
    except OSError:
        return (), inicio
    registros.sort(key=lambda registro: registro["seq"])
    seleccion = registros[:tope]
    ultimo = max(inicio, seleccion[-1]["seq"]) if seleccion else inicio
    return tuple(dict(registro) for registro in seleccion), ultimo


def _preparar_turno(
    turno: TurnoEscena | dict[str, object],
    *,
    permitidos: tuple[str, ...],
) -> dict[str, object] | None:
    """Valida un turno y lo deja listo para serializar, o lo descarta.

    Args:
        turno: turno de la escena o su representacion en diccionario.
        permitidos: telefonos publicos que no cuentan como PII.

    Returns:
        El turno como datos JSON, o `None` si es invalido, trae PII o supera el
        tope de texto. El motivo solo se registra por codigo.
    """
    try:
        validado = TurnoEscena.model_validate(turno)
    except ValidationError:
        logger.warning("escena_en_vivo descarte turno_invalido")
        return None
    if len(validado.texto) > MAXIMO_TEXTO:
        logger.warning("escena_en_vivo descarte texto_largo")
        return None
    if _trae_pii(validado, permitidos=permitidos):
        logger.warning("escena_en_vivo descarte pii")
        return None
    return validado.model_dump(mode="json")


def _trae_pii(turno: TurnoEscena, *, permitidos: tuple[str, ...]) -> bool:
    """Indica si el texto o el subtitulo del turno traen datos personales."""
    for texto in (turno.texto, turno.subtitulo):
        if texto and detectar_pii(texto, permitidos=permitidos) is not None:
            return True
    return False


def _escribir_lote(
    registros: list[dict[str, object]],
    *,
    origen: OrigenLista,
    ruta: Path,
) -> tuple[int, ...]:
    """Escribe el lote bajo el bloqueo del sistema y devuelve sus ``seq``.

    La seccion critica lee el ultimo ``seq`` valido, calcula los del lote,
    escribe todas las lineas, hace ``flush`` y ``fsync`` y suelta el bloqueo. Un
    lote usa ``seq`` consecutivos y un solo ``ts``. Un turno identico al ultimo
    publicado del mismo personaje se descarta antes de gastar un ``seq``.
    """
    global _CONTADOR

    ruta.parent.mkdir(parents=True, exist_ok=True)
    with _CANDADO:
        bloqueo = _tomar_bloqueo(ruta.with_name(NOMBRE_BLOQUEO))
        if bloqueo is None:
            logger.warning("escena_en_vivo descarte bloqueo_ocupado")
            return ()
        try:
            ultimo = _ultimo_seq(ruta)
            ultimos = _ultimos_por_personaje(ruta)
            ahora = datetime.now(UTC)
            base = int(ahora.timestamp() * 1000) * 1000
            ts = ahora.isoformat()
            lineas: list[str] = []
            seqs: list[int] = []
            for datos in registros:
                personaje = str(datos["personaje"])
                clave = (str(datos["id"]), str(datos["texto"]))
                if ultimos.get(personaje) == clave:
                    logger.warning("escena_en_vivo descarte turno_repetido")
                    continue
                candidato = base + (_CONTADOR % 1000)
                seq = max(ultimo + 1, candidato)
                linea = _serializar(seq, ts, origen, datos)
                if len(linea.encode("utf-8")) > MAXIMO_LINEA:
                    logger.warning("escena_en_vivo descarte linea_larga")
                    continue
                lineas.append(linea)
                seqs.append(seq)
                ultimo = seq
                ultimos[personaje] = clave
                _CONTADOR += 1
            if not lineas:
                return ()
            with ruta.open("a", encoding="utf-8", newline="\n") as archivo:
                archivo.writelines(lineas)
                archivo.flush()
                os.fsync(archivo.fileno())
            return tuple(seqs)
        finally:
            _soltar_bloqueo(bloqueo)


def _serializar(
    seq: int,
    ts: str,
    origen: OrigenLista,
    turno: dict[str, object],
) -> str:
    """Arma la linea JSON compacta de un registro, con salto ``\\n``."""
    registro = {"seq": seq, "ts": ts, "origen": origen, "turno": turno}
    return json.dumps(registro, ensure_ascii=False, separators=(",", ":")) + "\n"


def _tomar_bloqueo(ruta: Path) -> BinaryIO | None:
    """Pide el bloqueo exclusivo del sistema sobre el centinela.

    Args:
        ruta: archivo de bloqueo.

    Returns:
        El archivo abierto y bloqueado, o `None` si no se consiguio en 2 s.
    """
    archivo = ruta.open("a+b")
    try:
        if os.fstat(archivo.fileno()).st_size == 0:
            archivo.write(b"\0")
            archivo.flush()
        limite = time.monotonic() + ESPERA_BLOQUEO
        while True:
            try:
                archivo.seek(0)
                if _msvcrt is not None:
                    _msvcrt.locking(archivo.fileno(), _msvcrt.LK_NBLCK, 1)
                elif _fcntl is not None:
                    _fcntl.flock(archivo.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                return archivo
            except OSError:
                if time.monotonic() >= limite:
                    archivo.close()
                    return None
                time.sleep(0.02)
    except OSError:
        archivo.close()
        raise


def _soltar_bloqueo(archivo: BinaryIO) -> None:
    """Suelta el bloqueo del sistema y cierra el centinela."""
    try:
        archivo.seek(0)
        if _msvcrt is not None:
            _msvcrt.locking(archivo.fileno(), _msvcrt.LK_UNLCK, 1)
        elif _fcntl is not None:
            _fcntl.flock(archivo.fileno(), _fcntl.LOCK_UN)
    except OSError:  # pragma: no cover - el cierre libera el bloqueo igual
        pass
    finally:
        archivo.close()


def _lineas_de(ruta: Path) -> Iterator[str]:
    """Itera las lineas del archivo, leyendo solo los ultimos 2 MB si crecio."""
    with ruta.open("rb") as archivo:
        archivo.seek(0, os.SEEK_END)
        tamano = archivo.tell()
        inicio = max(0, tamano - MAXIMO_LECTURA)
        archivo.seek(inicio)
        datos = archivo.read()
    if inicio > 0:
        _, _, datos = datos.partition(b"\n")
    for linea in datos.decode("utf-8", errors="replace").splitlines():
        if linea.strip():
            yield linea


def _ultimo_seq(ruta: Path) -> int:
    """Devuelve el mayor ``seq`` valido del archivo, o 0 si no hay ninguno."""
    if not ruta.is_file():
        return 0
    ultimo = 0
    for linea in _lineas_de(ruta):
        registro = _registro(linea)
        if registro is not None:
            ultimo = max(ultimo, registro["seq"])
    return ultimo


def _ultimos_por_personaje(ruta: Path) -> dict[str, tuple[str, str]]:
    """Devuelve el ultimo ``(id, texto)`` publicado por cada personaje.

    Se usa para no repetir en la lista un turno identico al anterior del mismo
    personaje (el auditor publica el mismo veredicto por cada mensaje con
    cifras). El orden del archivo es el de publicacion.

    Args:
        ruta: lista de la escena; puede no existir.

    Returns:
        Un diccionario ``personaje -> (id, texto)`` con lo ultimo publicado.
    """
    if not ruta.is_file():
        return {}
    ultimos: dict[str, tuple[str, str]] = {}
    for linea in _lineas_de(ruta):
        registro = _registro(linea)
        if registro is None:
            continue
        turno = registro["turno"]
        personaje = turno.get("personaje")
        if isinstance(personaje, str):
            ultimos[personaje] = (str(turno.get("id", "")), str(turno.get("texto", "")))
    return ultimos


def _registro(linea: str) -> _Registro | None:
    """Convierte una linea en registro valido, o `None` si no lo es."""
    try:
        crudo = json.loads(linea)
        if not isinstance(crudo, dict):
            return None
        seq = crudo.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int):
            return None
        ts = crudo.get("ts")
        origen = crudo.get("origen")
        if not isinstance(ts, str) or origen not in _ORIGENES:
            return None
        turno = TurnoEscena.model_validate(crudo.get("turno"))
    except (ValueError, TypeError, ValidationError):
        return None
    return {
        "seq": seq,
        "ts": ts,
        "origen": origen,
        "turno": turno.model_dump(mode="json"),
    }
