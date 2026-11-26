"""Ruta de la lista en vivo de la escena: solo lectura y solo loopback.

La pantalla consulta ``GET /api/escena/en-vivo?desde=<seq>`` cada dos segundos
mientras el modo «En vivo» está abierto. La ruta no escribe, no crea carpetas,
no abre SQLite y no toca el bloqueo de la lista: si el archivo no existe o el
interruptor ``ESCENA_EN_VIVO`` está apagado, responde la lista vacía.

La lectura la hace ``escena/publicador.py``; aquí se valida el contrato, se
ignoran los registros corruptos y se limita la respuesta a 200 turnos. El
``Cache-Control: no-store`` evita que el navegador muestre una escena vieja.

La app ya escucha solo en ``127.0.0.1`` y la guarda del túnel responde ``404``
para esta ruta cuando la petición viene de Cloudflare. Las pruebas viven en
``test/test_escena_en_vivo_api.py``.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Mapping
from typing import Any, Literal, Protocol, cast

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from ..canal.escena_vivo import activa_entorno
from .contratos import TurnoEscena

logger = logging.getLogger(__name__)

#: Turnos máximos por respuesta; la pantalla vuelve a pedir con el nuevo `ultimo`.
LIMITE = 200

#: Evita repetir el aviso de publicador ausente en cada sondeo.
_AVISADO_SIN_PUBLICADOR = False


class TurnoEnVivo(BaseModel):
    """Un registro de la lista: el sobre y el turno de la escena."""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(ge=0)
    ts: str = Field(min_length=1)
    origen: Literal["herramienta", "canal"]
    turno: TurnoEscena


class EnVivoRespuesta(BaseModel):
    """Turnos nuevos desde ``desde`` y el cursor para el siguiente sondeo."""

    model_config = ConfigDict(extra="forbid")

    turnos: tuple[TurnoEnVivo, ...]
    ultimo: int = Field(ge=0)


class Lector(Protocol):
    """Firma de ``escena.publicador.leer_turnos``."""

    def __call__(
        self,
        desde: int,
        *,
        limite: int = LIMITE,
    ) -> tuple[tuple[Mapping[str, Any], ...], int]:
        """Devuelve los registros con ``seq > desde`` y el último ``seq``."""


def crear_router_en_vivo(lector: Lector | None = None) -> APIRouter:
    """Crea el router de la lista en vivo para montarlo antes de los estáticos.

    Args:
        lector: lector alternativo para las pruebas; por defecto el publicador.

    Returns:
        El router con ``GET /api/escena/en-vivo``.
    """
    leer = lector if lector is not None else _leer_por_defecto
    router = APIRouter(prefix="/api/escena", tags=["escena"])

    @router.get("/en-vivo", response_model=EnVivoRespuesta)
    def en_vivo(response: Response, desde: int = Query(default=0, ge=0)) -> EnVivoRespuesta:
        """Devuelve los turnos nuevos, en orden, sin escribir nada.

        Args:
            response: respuesta de FastAPI, para fijar el ``no-store``.
            desde: último ``seq`` que ya tiene la pantalla; por defecto 0.

        Returns:
            Los turnos con ``seq > desde`` (máximo 200) y el nuevo cursor.
        """
        response.headers["Cache-Control"] = "no-store"
        registros, ultimo = leer(desde, limite=LIMITE)
        turnos: list[TurnoEnVivo] = []
        for registro in registros:
            try:
                turnos.append(TurnoEnVivo.model_validate(registro))
            except ValueError:
                logger.info("registro inválido en la lista en vivo: se ignora")
        turnos.sort(key=lambda turno: turno.seq)
        maximo = turnos[-1].seq if turnos else desde
        return EnVivoRespuesta(turnos=tuple(turnos), ultimo=max(desde, ultimo, maximo))

    return router


def _leer_por_defecto(
    desde: int,
    *,
    limite: int = LIMITE,
) -> tuple[tuple[Mapping[str, Any], ...], int]:
    """Lee la lista con el publicador; vacía si está apagada o si aún no existe."""
    global _AVISADO_SIN_PUBLICADOR
    if not activa_entorno():
        return (), desde
    try:
        modulo = importlib.import_module(".publicador", package=__package__)
    except ImportError:
        if not _AVISADO_SIN_PUBLICADOR:
            logger.warning("falta escena/publicador.py; la lista en vivo queda vacía")
            _AVISADO_SIN_PUBLICADOR = True
        return (), desde
    leer_turnos = cast(Lector, modulo.leer_turnos)
    try:
        return leer_turnos(desde, limite=limite)
    except Exception:
        logger.warning("no se pudo leer la lista en vivo")
        return (), desde
