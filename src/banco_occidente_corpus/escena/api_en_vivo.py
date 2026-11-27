"""Rutas de la escena en vivo: lista de solo lectura y convocatoria, en loopback.

La pantalla consulta ``GET /api/escena/en-vivo?desde=<seq>`` cada dos segundos
mientras el modo «En vivo» está abierto. La ruta no escribe, no crea carpetas,
no abre SQLite y no toca el bloqueo de la lista: si el archivo no existe o el
interruptor ``ESCENA_EN_VIVO`` está apagado, responde la lista vacía.

``POST`` y ``DELETE /api/escena/convocatoria`` abren y liberan la ranura del
voluntario en la memoria del canal. La primera huella que escriba después de la
apertura queda como voluntaria sin código; ``DELETE`` es la tecla L de la
pantalla cuando se adelantó la persona equivocada.

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

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from ..canal.escena_vivo import EscenaVivo, activa_entorno
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


class ConvocatoriaRespuesta(BaseModel):
    """Estado de la convocatoria del voluntario en la pantalla."""

    model_config = ConfigDict(extra="forbid")

    abierta: bool


class Lector(Protocol):
    """Firma de ``escena.publicador.leer_turnos``."""

    def __call__(
        self,
        desde: int,
        *,
        limite: int = LIMITE,
    ) -> tuple[tuple[Mapping[str, Any], ...], int]:
        """Devuelve los registros con ``seq > desde`` y el último ``seq``."""


def crear_router_en_vivo(
    lector: Lector | None = None,
    escena: EscenaVivo | None = None,
) -> APIRouter:
    """Crea el router de la lista en vivo para montarlo antes de los estáticos.

    Args:
        lector: lector alternativo para las pruebas; por defecto el publicador.
        escena: ranura del voluntario que comparte el canal. Sin ella, la
            convocatoria responde ``409`` y la lista sigue disponible.

    Returns:
        El router con ``GET /api/escena/en-vivo`` y la convocatoria
        ``POST``/``DELETE /api/escena/convocatoria``.
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

    @router.post("/convocatoria", response_model=ConvocatoriaRespuesta)
    def abrir_convocatoria() -> ConvocatoriaRespuesta:
        """Abre la convocatoria del voluntario desde la pantalla.

        La primera huella que escriba después de este instante, con el
        consentimiento vigente, ocupa la ranura sin código. La ruta solo vive
        en loopback: el middleware del túnel responde ``404``.

        Returns:
            ``{"abierta": true}`` cuando la convocatoria quedó abierta.

        Raises:
            HTTPException: ``409`` si el canal no tiene la ranura disponible.
        """
        if escena is None:
            raise HTTPException(status_code=409, detail="la escena en vivo no está disponible")
        escena.abrir_convocatoria()
        return ConvocatoriaRespuesta(abierta=True)

    @router.delete("/convocatoria", response_model=ConvocatoriaRespuesta)
    def liberar_convocatoria() -> ConvocatoriaRespuesta:
        """Libera al voluntario activo y cierra la convocatoria.

        La tecla L la usa cuando se adelantó la persona equivocada: deja la
        ranura libre para que la siguiente huella que escriba sea la voluntaria.

        Returns:
            ``{"abierta": false}`` cuando la ranura quedó libre.

        Raises:
            HTTPException: ``409`` si el canal no tiene la ranura disponible.
        """
        if escena is None:
            raise HTTPException(status_code=409, detail="la escena en vivo no está disponible")
        escena.liberar_convocatoria()
        return ConvocatoriaRespuesta(abierta=False)

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
