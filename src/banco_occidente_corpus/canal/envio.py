"""Envío de respuestas del canal: Meta real y falso local.

Dos implementaciones detrás del ``Protocol`` :class:`Enviador`:

- :class:`EnviadorFalso` no sale a la red: registra el envío en
  ``data/asistente/whatsapp.sqlite`` y devuelve ``fake:<uuid>``. Es el modo por
  defecto de la suite y de la demo.
- :class:`EnviadorMeta` habla con ``graph.facebook.com`` con ``timeout``
  explícito, User-Agent, header ``From`` y reintentos solo en 429/5xx. Exige que
  el destino esté entre las huellas autorizadas.

Los textos largos se parten por párrafos en bloques de 4.096 caracteres; los
botones van en un mensaje interactivo (título recortado a 20) y las listas en
otro, con hasta diez filas. La tarjeta de Pana se sube como media y se envía
como imagen después del texto: si la imagen falla, el texto ya salió y la
respuesta no se corta. El token, el número y los bytes de la imagen nunca se
registran en los logs. Las pruebas viven en ``test/test_canal_envio.py``.
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
from .contratos import BotonCanal, OpcionCanal, RespuestaCanal

#: Largo máximo de un mensaje de WhatsApp.
LARGO_MAXIMO: int = 4096

#: Etiqueta del botón que abre la lista interactiva (Meta corta en 20).
TITULO_LISTA: str = "Elige una opción"

#: Título de la única sección de la lista (Meta corta en 24).
TITULO_SECCION: str = "Opciones"

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
    """Enviador local que registra el envío y no toca la red.

    ``registro`` guarda, en orden, lo que se habría enviado: ``("texto", texto)``
    y, si la respuesta trae tarjeta, ``("imagen", sha256 del PNG)``. Sirve para
    comprobar que el texto sale antes que la imagen.
    """

    ruta: Path
    registro: list[tuple[str, str]] = field(default_factory=list)

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
        material = respuesta.texto.encode("utf-8")
        if respuesta.imagen is not None:
            material += b"|" + hashlib.sha256(respuesta.imagen).hexdigest().encode("ascii")
        digesto = hashlib.sha256(material).hexdigest()
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
        self.registro.append(("texto", respuesta.texto))
        if respuesta.tipo == "imagen" and respuesta.imagen is not None:
            self.registro.append(("imagen", hashlib.sha256(respuesta.imagen).hexdigest()))
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
            viene. Si la respuesta trae tarjeta y la imagen falla, devuelve el
            id del texto: la persona ya recibió la respuesta.

        Raises:
            ErrorEnvio: si el destino no está autorizado, si Meta responde 4xx
                al texto o si se agotan los reintentos de 429/5xx.
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
                opciones = respuesta.opciones if ultima and respuesta.tipo == "lista" else []
                salida = self._enviar_parte(cliente, parte, botones, opciones)
            if respuesta.tipo == "imagen" and respuesta.imagen is not None:
                try:
                    media_id = self._subir_imagen(cliente, respuesta.imagen)
                    self._enviar_imagen(cliente, media_id)
                except ErrorEnvio:
                    logger.warning("no se pudo enviar la tarjeta; el texto ya salió")
            return salida
        finally:
            if propio:
                cliente.close()

    def _cuerpo(
        self,
        texto: str,
        botones: list[BotonCanal],
        opciones: list[OpcionCanal],
    ) -> dict[str, Any]:
        """Arma el JSON de un mensaje de texto, de botones o de lista."""
        cuerpo: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.destino,
        }
        if opciones:
            cuerpo["type"] = "interactive"
            cuerpo["interactive"] = {
                "type": "list",
                "body": {"text": texto},
                "action": {
                    "button": TITULO_LISTA,
                    "sections": [
                        {
                            "title": TITULO_SECCION,
                            "rows": [_fila(opcion) for opcion in opciones],
                        }
                    ],
                },
            }
        elif botones:
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

    def _publicar(
        self,
        cliente: httpx.Client,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> httpx.Response:
        """Hace una petición a Meta con reintentos acotados y sin secretos.

        Args:
            cliente: cliente HTTP ya construido con ``timeout``.
            url: destino en ``graph.facebook.com``.
            json: cuerpo JSON del mensaje, si aplica.
            data: campos del formulario multipart, si aplica.
            files: archivo del formulario multipart, si aplica.

        Returns:
            La respuesta con estado menor que 400.

        Raises:
            ErrorEnvio: si hay un fallo de red, si Meta responde 4xx o si se
                agotan los reintentos de 429/5xx.
        """
        cabeceras = {
            "Authorization": f"Bearer {self.token}",
            "User-Agent": self.user_agent,
            "From": self.remitente,
        }

        for intento in range(1, self.intentos + 1):
            try:
                respuesta = cliente.post(
                    url,
                    json=json,
                    data=data,
                    files=files,
                    headers=cabeceras,
                    timeout=self.timeout,
                )
            except httpx.HTTPError as error:
                raise ErrorEnvio("fallo de red al enviar a Meta") from error

            if respuesta.status_code < 400:
                return respuesta
            reintentable = respuesta.status_code == 429 or respuesta.status_code >= 500
            if reintentable and intento < self.intentos:
                self.espera(ESPERA_SEGUNDOS * intento)
                continue
            logger.warning("Meta respondió %s al enviar un mensaje", respuesta.status_code)
            raise ErrorEnvio(f"Meta respondió {respuesta.status_code}")

        raise ErrorEnvio("Meta no respondió")

    def _enviar_parte(
        self,
        cliente: httpx.Client,
        texto: str,
        botones: list[BotonCanal],
        opciones: list[OpcionCanal],
    ) -> str:
        """Envía una parte con reintentos acotados y sin filtrar secretos."""
        url = f"{URL_META}/{self.version_api}/{self.phone_number_id}/messages"
        respuesta = self._publicar(cliente, url, json=self._cuerpo(texto, botones, opciones))
        return _id_salida(respuesta)

    def _subir_imagen(self, cliente: httpx.Client, png: bytes) -> str:
        """Sube el PNG a Meta y devuelve su ``media_id``.

        Args:
            cliente: cliente HTTP de la petición.
            png: bytes de la tarjeta, generados en memoria.

        Returns:
            El identificador de media que asigna Meta.

        Raises:
            ErrorEnvio: si Meta no responde con un id válido.
        """
        url = f"{URL_META}/{self.version_api}/{self.phone_number_id}/media"
        respuesta = self._publicar(
            cliente,
            url,
            data={"messaging_product": "whatsapp", "type": "image/png"},
            files={"file": ("pana.png", png, "image/png")},
        )
        try:
            datos = respuesta.json()
        except ValueError as error:
            raise ErrorEnvio("Meta no devolvió el id de la imagen") from error
        media_id = datos.get("id") if isinstance(datos, dict) else None
        if not isinstance(media_id, str) or not media_id:
            raise ErrorEnvio("Meta no devolvió el id de la imagen")
        return media_id

    def _enviar_imagen(self, cliente: httpx.Client, media_id: str) -> str:
        """Envía la tarjeta como mensaje de imagen, sin repetir el texto.

        Args:
            cliente: cliente HTTP de la petición.
            media_id: identificador devuelto por la subida.

        Returns:
            El id del mensaje de imagen, o cadena vacía si Meta no lo envía.
        """
        url = f"{URL_META}/{self.version_api}/{self.phone_number_id}/messages"
        cuerpo = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self.destino,
            "type": "image",
            "image": {"id": media_id},
        }
        return _id_salida(self._publicar(cliente, url, json=cuerpo))


def _fila(opcion: OpcionCanal) -> dict[str, str]:
    """Convierte una opción en la fila que espera la lista de Meta.

    Args:
        opcion: fila del contrato del canal.

    Returns:
        El JSON de la fila, con los topes de Meta aplicados (24 y 72).
    """
    fila = {"id": opcion.id, "title": opcion.titulo[:24]}
    if opcion.descripcion:
        fila["description"] = opcion.descripcion[:72]
    return fila


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
