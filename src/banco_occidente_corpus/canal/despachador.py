"""Despachador del canal: identidad, autorización, consentimiento y grafo.

Es la pieza que convierte un mensaje de WhatsApp en una respuesta:

1. Calcula ``usuario_id`` con la huella HMAC del número.
2. Descarta números que no estén en las huellas autorizadas.
3. Pasa por la máquina de consentimiento de la Ley 1581.
4. Si ya hay consentimiento, entrega la pregunta al grafo de la Sucursal con
   ``thread_id = wa:<usuario_id>``.
5. Envía la respuesta con el enviador configurado (falso o Meta).

El número y el texto nunca se registran en logs; el estado del mensaje vive en
``data/asistente/whatsapp.sqlite``. Las pruebas viven en
``test/test_canal_despachador.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..sucursal.perfil import huella_perfil
from .almacen import actualizar_mensaje, registrar_mensaje
from .cola import ColaMensajes
from .configuracion import ConfiguracionCanal
from .consentimiento import MaquinaConsentimiento
from .contratos import MensajeEntrante, RespuestaCanal
from .envio import Enviador
from .identidad import calcular_usuario_id

logger = logging.getLogger(__name__)

#: Aviso para números que no están en la lista de prueba.
AVISO_NO_AUTORIZADO = (
    "Este canal está en prueba y tu número no está autorizado. "
    "Pide al equipo que lo agregue a la lista de WhatsApp Business."
)

#: Respuesta fija si el grafo falla, para no dejar al usuario sin contestación.
TEXTO_ERROR = "No pude procesar tu mensaje en este momento. Inténtalo de nuevo en unos minutos."


@dataclass
class Despachador:
    """Atiende los mensajes del canal fuera del hilo del webhook."""

    config: ConfiguracionCanal
    sal: str
    ruta_almacen: Path
    maquina: MaquinaConsentimiento
    cola: ColaMensajes
    crear_enviador: Callable[[str, str], Enviador]
    responder: Callable[[str, str, str], str]

    def recibir(self, mensaje: MensajeEntrante) -> None:
        """Registra y encola un mensaje, sin bloquear la respuesta a Meta.

        Args:
            mensaje: mensaje normalizado del webhook.
        """
        usuario_id = self._usuario_id(mensaje)
        if usuario_id is None:
            return
        if not registrar_mensaje(
            self.ruta_almacen,
            mensaje.id_mensaje,
            usuario_id,
            "recibido",
            mensaje.recibido_en,
        ):
            return
        if not self.cola.encolar(mensaje):
            actualizar_mensaje(self.ruta_almacen, mensaje.id_mensaje, "error")

    def procesar(self, mensaje: MensajeEntrante) -> None:
        """Procesa un mensaje ya encolado.

        Args:
            mensaje: mensaje normalizado del webhook.
        """
        usuario_id = self._usuario_id(mensaje)
        if usuario_id is None:
            actualizar_mensaje(self.ruta_almacen, mensaje.id_mensaje, "error")
            return

        actualizar_mensaje(self.ruta_almacen, mensaje.id_mensaje, "procesando")
        try:
            if usuario_id not in self.config.huellas:
                self._enviar_texto(mensaje, usuario_id, AVISO_NO_AUTORIZADO)
                actualizar_mensaje(
                    self.ruta_almacen, mensaje.id_mensaje, "ignorado", procesado=True
                )
                return

            respuesta = self.maquina.decidir(mensaje, usuario_id)
            if respuesta is None:
                texto = self.responder(
                    mensaje.texto,
                    f"wa:{usuario_id}",
                    huella_perfil(usuario_id),
                )
                respuesta = RespuestaCanal(
                    usuario_id=usuario_id,
                    id_mensaje_origen=mensaje.id_mensaje,
                    texto=(texto or TEXTO_ERROR)[:4096],
                )

            self.crear_enviador(usuario_id, mensaje.remitente).enviar(respuesta)
            actualizar_mensaje(self.ruta_almacen, mensaje.id_mensaje, "respondido", procesado=True)
        except Exception:
            logger.exception("fallo al procesar un mensaje del canal")
            actualizar_mensaje(self.ruta_almacen, mensaje.id_mensaje, "error", procesado=True)
            try:
                self._enviar_texto(mensaje, usuario_id, TEXTO_ERROR)
            except Exception:
                logger.warning("tampoco se pudo enviar el aviso de error")

    def _usuario_id(self, mensaje: MensajeEntrante) -> str | None:
        """Calcula la huella del remitente o ``None`` si el número no es válido."""
        try:
            return calcular_usuario_id(mensaje.remitente, self.sal, self.config.pais_por_defecto)
        except ValueError:
            logger.warning("número inválido en el canal; mensaje descartado")
            return None

    def _enviar_texto(self, mensaje: MensajeEntrante, usuario_id: str, texto: str) -> None:
        """Envía una respuesta de texto simple al remitente."""
        respuesta = RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=mensaje.id_mensaje,
            texto=texto,
        )
        self.crear_enviador(usuario_id, mensaje.remitente).enviar(respuesta)
