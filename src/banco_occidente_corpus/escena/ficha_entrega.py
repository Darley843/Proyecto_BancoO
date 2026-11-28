"""Entrega de la ficha de la opción al WhatsApp del voluntario.

El servidor MCP calcula la ficha y su PNG, pero no conoce el número del
voluntario: quien lo tiene es el canal. Por eso la herramienta deja la ficha en
un archivo breve de ``data/escena/`` y el despachador, al terminar el turno del
voluntario, la toma una sola vez y la envía como mensaje aparte. El archivo no
lleva datos personales, no se versiona y se borra al consumirlo o al cerrar el
evento.

Las funciones nunca lanzan hacia la herramienta: un fallo de escritura o un
archivo corrupto solo dejan un aviso y el turno sigue igual.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..asistente.validacion import detectar_pii
from ..config import PROJECT_ROOT

#: Ruta de la ficha pendiente; las pruebas la cambian por una temporal.
RUTA_ENTREGA: Path = PROJECT_ROOT / "data" / "escena" / "ficha_entrega.json"
#: Interruptor de la escena en vivo; sin él no se deja nada.
VARIABLE_INTERRUPTOR: str = "ESCENA_EN_VIVO"
#: Tolerancia para aceptar una ficha escrita al empezar el turno del canal.
TOLERANCIA: timedelta = timedelta(seconds=5)

_CANDADO = threading.Lock()
logger = logging.getLogger(__name__)


def _activa() -> bool:
    """Indica si la escena en vivo está encendida en este proceso.

    Returns:
        ``True`` solo con ``ESCENA_EN_VIVO=1``.
    """
    return os.environ.get(VARIABLE_INTERRUPTOR, "").strip() == "1"


def _instante(momento: datetime | None) -> datetime:
    """Normaliza un instante a UTC.

    Args:
        momento: instante; por defecto, ahora.

    Returns:
        El instante en UTC.
    """
    valor = momento or datetime.now(UTC)
    if valor.tzinfo is None:
        return valor.replace(tzinfo=UTC)
    return valor.astimezone(UTC)


def dejar_ficha(texto: str, imagen: bytes, momento: datetime | None = None) -> bool:
    """Deja la ficha pendiente para que el canal la envíe como mensaje aparte.

    Args:
        texto: texto equivalente de la ficha, sin datos personales.
        imagen: PNG de la tarjeta, generado en memoria.
        momento: instante de la ficha; por defecto, ahora.

    Returns:
        ``True`` si quedó escrita; ``False`` si la escena está apagada, la
        ficha está vacía, trae datos personales o no se pudo escribir.
    """
    if not _activa() or not texto.strip() or not imagen:
        return False
    if detectar_pii(texto) is not None:
        logger.warning("ficha descartada por datos personales")
        return False
    datos = {
        "momento": _instante(momento).isoformat(),
        "texto": texto.strip(),
        "png_base64": base64.b64encode(imagen).decode("ascii"),
    }
    try:
        with _CANDADO:
            RUTA_ENTREGA.parent.mkdir(parents=True, exist_ok=True)
            temporal = RUTA_ENTREGA.with_name(f"{RUTA_ENTREGA.name}.tmp")
            temporal.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
            temporal.replace(RUTA_ENTREGA)
    except OSError:
        logger.warning("no se pudo dejar la ficha para el canal")
        return False
    return True


def tomar_ficha(desde: datetime) -> tuple[str, bytes] | None:
    """Toma la ficha pendiente de este turno y la borra.

    Args:
        desde: instante en que empezó el turno del canal; una ficha anterior a
            ese instante con la tolerancia se descarta.

    Returns:
        El texto y el PNG, o ``None`` si no hay ficha o es de un turno anterior.
    """
    with _CANDADO:
        try:
            datos = json.loads(RUTA_ENTREGA.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        with contextlib.suppress(OSError):
            RUTA_ENTREGA.unlink()
    if not isinstance(datos, dict):
        return None
    try:
        momento = datetime.fromisoformat(str(datos["momento"]))
        if momento.tzinfo is None:
            momento = momento.replace(tzinfo=UTC)
        texto = str(datos["texto"]).strip()
        imagen = base64.b64decode(str(datos["png_base64"]), validate=True)
    except (KeyError, ValueError, TypeError):
        return None
    if not texto or not imagen or momento < _instante(desde) - TOLERANCIA:
        return None
    return texto, imagen


def borrar_ficha() -> None:
    """Borra la ficha pendiente, si existe (cierre del evento y pruebas)."""
    with _CANDADO:
        try:
            RUTA_ENTREGA.unlink(missing_ok=True)
        except OSError:
            logger.warning("no se pudo borrar la ficha pendiente")


__all__ = ["RUTA_ENTREGA", "borrar_ficha", "dejar_ficha", "tomar_ficha"]
