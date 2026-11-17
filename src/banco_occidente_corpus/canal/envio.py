"""Envío de respuestas del canal: Meta real y falso local.

Dos implementaciones detrás del ``Protocol`` :class:`Enviador`:

- :class:`EnviadorFalso` no sale a la red: registra el envío en
  ``data/asistente/whatsapp.sqlite`` y devuelve ``fake:<uuid>``. Es el modo por
  defecto de la suite y de la demo.
- :class:`EnviadorMeta` habla con ``graph.facebook.com`` con ``timeout``
  explícito, User-Agent, header ``From`` y reintentos solo en 429/5xx. Exige que
  el destino esté entre las huellas autorizadas.

Los textos largos se parten por párrafos en bloques de 4.096 caracteres; los
botones van en un mensaje interactivo y el título se recorta a 20. El token y el
número nunca se registran en los logs. Las pruebas viven en
``test/test_canal_envio.py``.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import httpx

from .almacen import conectar, inicializar_almacen
from .contratos import BotonCanal, RespuestaCanal

#: Largo máximo de un mensaje de WhatsApp.
LARGO_MAXIMO: int = 4096

#: Intentos totales contra Meta (el primero más un reintento).
INTENTOS: int = 2

#: Base de la API de Meta.
URL_META: str = "https://graph.facebook.com"

#: Tiempo de espera entre reintentos, en segundos.
ESPERA_SEGUNDOS: float = 0.5

logger = logging.getLogger(__name__)


class ErrorEnvio(RuntimeError):
    """Falla definitiva del envío: no se insiste más."""


class Enviador(Protocol):
    """Contrato de envío de respuestas del canal."""

    def enviar(self, respuesta: RespuestaCanal) -> str:
        """Envía la respuesta y devuelve el id de salida."""
        ...


def partir_texto(texto: str, limite: int = LARGO_MAXIMO) -> list[str]:
    """Parte un texto en bloques de ``limite`` caracteres por párrafo.

    Args:
        texto: texto completo de la respuesta.
        limite: largo máximo de cada bloque.

    Returns:
        Bloques en orden; un párrafo más largo que el límite se corta duro.
    """
    if len(texto) <= limite:
        return [texto]

    partes: list[str] = []
    actual = ""
    for parrafo in texto.split("\n\n"):
        bloque = f"\n\n{parrafo}" if actual else parrafo
        if len(actual) + len(bloque) <= limite:
            actual += bloque
            continue
        if actual:
            partes.append(actual)
            actual = ""
        while len(parrafo) > limite:
            partes.append(parrafo[:limite])
            parrafo = parrafo[limite:]
        actual = parrafo
    if actual or not partes:
        partes.append(actual)
    return partes


@dataclass
class EnviadorFalso:
    """Enviador local que registra el envío y no toca la red."""

    ruta: Path

    def __post_init__(self) -> None:
        """Crea la carpeta y las tablas del almacén si faltan."""
        inicializar_almacen(self.ruta)

    def enviar(self, respuesta: RespuestaCanal) -> str:
        """Registra el envío y devuelve un id ficticio.

        Args:
            respuesta: respuesta ya validada del canal.

        Returns:
            Un identificador ``fake:<uuid>``.
        """
        digesto = hashlib.sha256(respuesta.texto.encode("utf-8")).hexdigest()
        clave = hashlib.sha256(f"{respuesta.id_mensaje_origen}|{digesto}".encode()).hexdigest()
        with conectar(self.ruta) as conexion:
            conexion.execute(
                "INSERT OR IGNORE INTO envios "
                "(clave, id_mensaje, usuario_id, estado, creado_en) VALUES (?, ?, ?, ?, ?)",
                (
                    clave,
                    respuesta.id_mensaje_origen,
                    respuesta.usuario_id,
                    "enviado",
                    datetime.now(UTC).isoformat(),
                ),
            )
        return f"fake:{uuid4()}"


@dataclass
class EnviadorMeta:
    """Enviador real contra la API de WhatsApp Cloud."""

    usuario_id: str
    destino: str
    phone_number_id: str
    token: str
    user_agent: str
    remitente: str
    huellas: tuple[str, ...] = ()
    version_api: str = "v23.0"
    timeout: float = 10.0
    intentos: int = INTENTOS
    cliente: httpx.Client | None = None
    espera: Callable[[float], None] = field(default=time.sleep)

    def enviar(self, respuesta: RespuestaCanal) -> str:
        """Envía la respuesta y devuelve el id que asigna Meta.

        Args:
            respuesta: respuesta ya validada del canal.

        Returns:
            El ``messages[0].id`` de la respuesta de Meta, o cadena vacía si no
            viene.

        Raises:
            ErrorEnvio: si el destino no está autorizado, si Meta responde 4xx
                o si se agotan los reintentos de 429/5xx.
        """
        if self.usuario_id not in self.huellas:
            raise ErrorEnvio("destino no autorizado para el modo real")

        propio = self.cliente is None
        cliente = self.cliente or httpx.Client(timeout=self.timeout)
        try:
            salida = ""
            partes = partir_texto(respuesta.texto)
            for indice, parte in enumerate(partes):
                ultima = indice == len(partes) - 1
                botones = respuesta.botones if ultima and respuesta.tipo == "botones" else []
                salida = self._enviar_parte(cliente, parte, botones)
            return salida
        finally:
            if propio:
                cliente.close()

    def _cuerpo(self, texto: str, botones: list[BotonCanal]) -> dict[str, Any]:
        """Arma el JSON de un mensaje de texto o interactivo."""
        cuerpo: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.destino,
        }
        if botones:
            cuerpo["type"] = "interactive"
            cuerpo["interactive"] = {
                "type": "button",
                "body": {"text": texto},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": boton.id, "title": boton.titulo[:20]},
                        }
                        for boton in botones
                    ]
                },
            }
        else:
            cuerpo["type"] = "text"
            cuerpo["text"] = {"body": texto}
        return cuerpo

    def _enviar_parte(self, cliente: httpx.Client, texto: str, botones: list[BotonCanal]) -> str:
        """Envía una parte con reintentos acotados y sin filtrar secretos."""
        url = f"{URL_META}/{self.version_api}/{self.phone_number_id}/messages"
        cabeceras = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": self.user_agent,
            "From": self.remitente,
        }
        cuerpo = self._cuerpo(texto, botones)

        for intento in range(1, self.intentos + 1):
            try:
                respuesta = cliente.post(url, json=cuerpo, headers=cabeceras, timeout=self.timeout)
            except httpx.HTTPError as error:
                raise ErrorEnvio("fallo de red al enviar a Meta") from error

            if respuesta.status_code < 400:
                return _id_salida(respuesta)
            reintentable = respuesta.status_code == 429 or respuesta.status_code >= 500
            if reintentable and intento < self.intentos:
                self.espera(ESPERA_SEGUNDOS * intento)
                continue
            logger.warning("Meta respondió %s al enviar un mensaje", respuesta.status_code)
            raise ErrorEnvio(f"Meta respondió {respuesta.status_code}")

        raise ErrorEnvio("Meta no respondió")


def _id_salida(respuesta: httpx.Response) -> str:
    """Extrae el id del mensaje enviado del JSON de Meta."""
    try:
        datos = respuesta.json()
    except ValueError:
        return ""
    mensajes = datos.get("messages") if isinstance(datos, dict) else None
    if isinstance(mensajes, list) and mensajes and isinstance(mensajes[0], dict):
        return str(mensajes[0].get("id", ""))
    return ""
