"""Webhook de WhatsApp Cloud API: verificación, firma y entrega a la cola.

Dos rutas bajo ``/webhooks/whatsapp``:

- ``GET`` responde el reto de Meta solo si ``hub.mode`` es ``subscribe`` y el
  token coincide; si la variable de entorno falta, el canal queda deshabilitado
  con 503 y sin valor por defecto.
- ``POST`` lee el **cuerpo crudo**, valida ``X-Hub-Signature-256`` en tiempo
  constante, extrae los mensajes soportados y los entrega a ``recibir`` (el
  despachador, que registra y encola) antes de responder 200. Sin ``recibir``
  solo valida la firma, como en la primera versión del canal.
"""

from __future__ import annotations

import hmac
import json
import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from .configuracion import leer_app_secret, leer_token_verificacion
from .contratos import MensajeEntrante
from .entrada import extraer_mensajes
from .firma import firma_valida

logger = logging.getLogger(__name__)

#: Respuesta mínima que Meta espera después de aceptar un evento.
EVENTO_RECIBIDO: dict[str, str] = {"status": "EVENT_RECEIVED"}


def crear_router_canal(
    recibir: Callable[[MensajeEntrante], None] | None = None,
) -> APIRouter:
    """Crea el router del canal con la entrega de mensajes inyectada.

    Args:
        recibir: función que registra y encola cada mensaje; si falta, el
            webhook solo valida la firma y responde 200.

    Returns:
        Router de FastAPI con ``GET`` y ``POST`` bajo ``/webhooks/whatsapp``.
    """
    router = APIRouter(tags=["canal"])

    @router.get("/webhooks/whatsapp")
    async def verificar_webhook(request: Request) -> Response:
        """Contesta la verificación ``GET`` que hace Meta al registrar el callback.

        Args:
            request: petición con ``hub.mode``, ``hub.verify_token`` y
                ``hub.challenge`` en la cadena de consulta.

        Returns:
            200 con el reto en texto plano, 403 si el modo o el token no
            coinciden, 400 si falta el reto y 503 sin token configurado.
        """
        esperado = leer_token_verificacion()
        if esperado is None:
            return JSONResponse({"detail": "canal sin token de verificación"}, status_code=503)

        modo = request.query_params.get("hub.mode")
        recibido = request.query_params.get("hub.verify_token")
        reto = request.query_params.get("hub.challenge")

        if modo != "subscribe" or not hmac.compare_digest(recibido or "", esperado):
            return JSONResponse({"detail": "verificación rechazada"}, status_code=403)
        if not reto:
            return JSONResponse({"detail": "falta hub.challenge"}, status_code=400)

        return PlainTextResponse(reto, status_code=200)

    @router.post("/webhooks/whatsapp")
    async def recibir_webhook(request: Request) -> Response:
        """Acepta un evento firmado y entrega sus mensajes.

        Args:
            request: petición con el cuerpo crudo y ``X-Hub-Signature-256``.

        Returns:
            200 si la firma es válida, 401 si falta o no coincide, 400 si el
            JSON no se puede leer y 503 sin App Secret configurado.
        """
        secreto = leer_app_secret()
        if secreto is None:
            return JSONResponse({"detail": "canal sin App Secret"}, status_code=503)

        cuerpo = await request.body()
        cabecera = request.headers.get("X-Hub-Signature-256")
        if not firma_valida(cuerpo, cabecera, secreto):
            return JSONResponse({"detail": "firma inválida"}, status_code=401)

        try:
            datos: Any = json.loads(cuerpo)
        except json.JSONDecodeError:
            return JSONResponse({"detail": "cuerpo inválido"}, status_code=400)
        if not isinstance(datos, dict):
            return JSONResponse({"detail": "cuerpo inválido"}, status_code=400)

        if recibir is not None:
            for mensaje in extraer_mensajes(datos):
                try:
                    recibir(mensaje)
                except Exception:
                    logger.exception("fallo al encolar un mensaje del canal")

        return JSONResponse(EVENTO_RECIBIDO, status_code=200)

    return router


#: Router por defecto: solo verifica y valida la firma.
router = crear_router_canal()
