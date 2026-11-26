"""Despachador del canal: identidad, autorización, consentimiento y grafo.

Es la pieza que convierte un mensaje de WhatsApp en una respuesta:

1. Calcula ``usuario_id`` con la huella HMAC del número.
2. Descarta números que no estén en las huellas autorizadas.
3. Pasa por la máquina de consentimiento de la Ley 1581.
4. Escena en vivo: ``ESCENA`` con el código de cuatro dígitos de la sesión
   activa al voluntario de la demo; desde ahí sus mensajes y las respuestas de
   Pana se publican en la lista que lee la pantalla. El comando no se reenvía
   al motor ni se publica como mensaje.
5. Si la entrevista del diagnóstico está activa, el botón o la fila avanza la
   entrevista; un texto libre repite la pregunta. Al completar, calcula el
   diagnóstico y envía la tarjeta.
6. Si hay un diagnóstico de las últimas 24 horas y el texto es un «¿Y si…?»
   («¿y si lo pago en 60 meses?»), responde con la tarjeta de antes y después.
7. Si no, intenta el motor de OpenClaw con el mensaje nuevo y la huella. Un
   fallo (timeout, error de red, ``5xx``, cuerpo inválido) cae al grafo de la
   Sucursal con ``thread_id = wa:<usuario_id>``. Cuando el grafo devuelve la
   ruta D, arranca la entrevista en lugar de la invitación.
8. Envía la respuesta con el enviador configurado (falso o Meta) y registra el
   motor que respondió (``openclaw``, ``grafo`` o ``canal``).

Durante el modo evento el alcance es el mismo: el desconocido que acepta el
consentimiento entra a la entrevista del diagnóstico y al comité, con cuota por
persona y tope global; solo cambian la puerta de entrada y los contadores.

El número y el texto nunca se registran en logs; el estado del mensaje vive en
``data/asistente/whatsapp.sqlite``. Las pruebas viven en
``test/test_canal_despachador.py`` y ``test/test_canal_entrevista.py``; las del
evento, en ``test/test_canal_evento.py``.
"""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..asistente.validacion import detectar_pii
from ..sucursal.perfil import huella_perfil
from .almacen import (
    actualizar_mensaje,
    contar_mensajes_desde,
    contar_mensajes_usuario,
    registrar_mensaje,
)
from .cola import ColaMensajes
from .configuracion import ConfiguracionCanal
from .consentimiento import MaquinaConsentimiento
from .contratos import MensajeEntrante, RespuestaCanal
from .entrevista import EntrevistaCanal
from .envio import Enviador, ErrorEnvio
from .escena_vivo import EscenaVivo, activa_entorno, es_comando
from .identidad import calcular_usuario_id

logger = logging.getLogger(__name__)

#: Aviso para números que no están en la lista de prueba.
AVISO_NO_AUTORIZADO = (
    "Este canal está en prueba y tu número no está autorizado. "
    "Pide al equipo que lo agregue a la lista de WhatsApp Business."
)

#: Respuesta fija si el grafo falla, para no dejar al usuario sin contestación.
TEXTO_ERROR = "No pude procesar tu mensaje en este momento. Inténtalo de nuevo en unos minutos."

#: Respuesta cuando la persona agotó su cuota del evento.
TEXTO_CUOTA_USUARIO = (
    "Llegaste al límite de mensajes de esta demostración. "
    "Si necesitas más, acércate al equipo de la Sucursal 1965."
)

#: Respuesta cuando se agotó el tope global del evento.
TEXTO_EVENTO_CERRADO = (
    "La demostración en vivo ya cerró. Gracias por participar de la Sucursal 1965."
)

#: Motores que se registran en la trazabilidad de cada mensaje.
MOTOR_OPENCLAW: str = "openclaw"
MOTOR_GRAFO: str = "grafo"
MOTOR_CANAL: str = "canal"

#: Firma del motor: recibe el texto nuevo y la huella, y devuelve el texto o
#: ``None`` cuando hay que usar el grafo.
Motor = Callable[[str, str], str | None]


def _instante(momento: datetime | None = None) -> datetime:
    """Normaliza un instante a UTC para comparar con la configuración.

    Args:
        momento: instante a normalizar; por defecto, ahora.

    Returns:
        El instante en UTC; una fecha sin zona se asume UTC.
    """
    instante = momento or datetime.now(UTC)
    if instante.tzinfo is None:
        return instante.replace(tzinfo=UTC)
    return instante.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class RespuestaGrafo:
    """Respuesta del grafo con la ruta que tomó.

    ``avisos`` es la lista que devuelve el grafo; el despachador usa
    ``diagnostico`` para arrancar la entrevista en lugar de enviar la
    invitación de la ruta D. Un doble de prueba puede devolver solo el texto:
    se toma como una respuesta sin ruta especial.
    """

    texto: str
    avisos: tuple[str, ...] = ()

    @property
    def es_diagnostico(self) -> bool:
        """Indica si el grafo tomó la ruta D del diagnóstico."""
        return "diagnostico" in self.avisos


def _respuesta_del_grafo(resultado: RespuestaGrafo | str) -> RespuestaGrafo:
    """Normaliza lo que devuelve el grafo a ``RespuestaGrafo``.

    Args:
        resultado: respuesta del grafo o un texto suelto de un doble.

    Returns:
        La respuesta con sus avisos; un texto suelto no tiene ruta especial.
    """
    if isinstance(resultado, RespuestaGrafo):
        return resultado
    return RespuestaGrafo(texto=str(resultado or ""))


@dataclass
class Despachador:
    """Atiende los mensajes del canal fuera del hilo del webhook."""

    config: ConfiguracionCanal
    sal: str
    ruta_almacen: Path
    maquina: MaquinaConsentimiento
    cola: ColaMensajes
    crear_enviador: Callable[[str, str], Enviador]
    responder: Callable[[str, str, str], RespuestaGrafo | str]
    motor: Motor | None = None
    entrevista: EntrevistaCanal | None = None
    escena: EscenaVivo | None = None
    _candado_proceso: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

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

    def procesar(
        self, mensaje: MensajeEntrante, momento: datetime | None = None
    ) -> RespuestaCanal | None:
        """Procesa un mensaje ya encolado, serializado con ``/hablar``.

        Args:
            mensaje: mensaje normalizado del webhook.
            momento: instante de referencia para la ventana del evento y las
                cuotas; por defecto, ahora. Las pruebas lo fijan.

        Returns:
            La respuesta que se envió, o ``None`` si el turno se descartó o el
            envío falló. ``/api/escena/hablar`` usa este valor para mostrar en
            la pantalla lo mismo que recibió el voluntario.
        """
        with self._candado_proceso:
            return self._procesar(mensaje, momento)

    def _procesar(
        self, mensaje: MensajeEntrante, momento: datetime | None = None
    ) -> RespuestaCanal | None:
        """Cuerpo de `procesar`, ya dentro del candado del canal."""
        usuario_id = self._usuario_id(mensaje)
        if usuario_id is None:
            actualizar_mensaje(self.ruta_almacen, mensaje.id_mensaje, "error")
            return None

        actualizar_mensaje(self.ruta_almacen, mensaje.id_mensaje, "procesando")
        ahora = _instante(momento)
        comando_escena = False
        intento_escena = False
        try:
            if not self.config.permite(usuario_id, ahora):
                self._avisar_no_autorizado(mensaje, usuario_id)
                actualizar_mensaje(
                    self.ruta_almacen,
                    mensaje.id_mensaje,
                    "ignorado",
                    procesado=True,
                    motor=MOTOR_CANAL,
                )
                return None

            cierre = self._motivo_cierre(usuario_id, ahora)
            if cierre is not None:
                respuesta_cierre = self._enviar_texto(mensaje, usuario_id, cierre)
                actualizar_mensaje(
                    self.ruta_almacen,
                    mensaje.id_mensaje,
                    "ignorado",
                    procesado=True,
                    motor=MOTOR_CANAL,
                )
                return respuesta_cierre

            # El evento no recorta el alcance: quien vino por la ventana recorre
            # el mismo diagnóstico que un número de la lista, con el
            # consentimiento primero y las cuotas ya verificadas arriba.
            respuesta = self.maquina.decidir(mensaje, usuario_id)
            if respuesta is None and self.escena is not None:
                intento_escena = es_comando(mensaje.texto)
                respuesta = self.escena.decidir(mensaje, usuario_id)
                if respuesta is not None:
                    comando_escena = True
                    if self.entrevista is not None:
                        # ESCENA cancela la entrevista a medias: el siguiente
                        # mensaje ya es de la escena y no una respuesta suelta.
                        self.entrevista.descartar(usuario_id)
                elif not intento_escena:
                    # El mensaje del voluntario se publica antes del motor: la
                    # pantalla lo muestra primero y después los turnos de las
                    # herramientas. Los demás invitados no publican. Un
                    # ``ESCENA`` sin el código de la sesión tampoco publica.
                    self.escena.publicar_invitado(mensaje, usuario_id)
            if respuesta is None and self.entrevista is not None:
                respuesta = self.entrevista.reanudar(mensaje, usuario_id)
            if respuesta is None:
                respuesta = self._turno_entrevista(mensaje, usuario_id)
            if respuesta is None and self.entrevista is not None:
                respuesta = self.entrevista.escenario(mensaje, usuario_id)
            motor_usado: str | None = None
            if respuesta is None:
                texto_motor = self._texto_del_motor(mensaje.texto, usuario_id)
                if texto_motor is not None:
                    resultado = RespuestaGrafo(texto=texto_motor)
                    motor_usado = MOTOR_OPENCLAW
                else:
                    resultado = _respuesta_del_grafo(
                        self.responder(
                            mensaje.texto,
                            f"wa:{usuario_id}",
                            huella_perfil(usuario_id),
                        )
                    )
                    motor_usado = MOTOR_GRAFO
                if resultado.es_diagnostico and self.entrevista is not None:
                    respuesta = self.entrevista.iniciar(usuario_id, mensaje.id_mensaje)
                else:
                    respuesta = RespuestaCanal(
                        usuario_id=usuario_id,
                        id_mensaje_origen=mensaje.id_mensaje,
                        texto=(resultado.texto or TEXTO_ERROR)[:4096],
                    )

            self.crear_enviador(usuario_id, mensaje.remitente).enviar(respuesta)
            if self.escena is not None and not comando_escena and not intento_escena:
                # Solo publica si el envío salió bien: la pantalla no muestra
                # una respuesta que el invitado no recibió. La confirmación de
                # ESCENA ya se publicó con su propio identificador, y un
                # comando con código equivocado no publica nada.
                self.escena.publicar_pana(usuario_id, respuesta.texto)
            actualizar_mensaje(
                self.ruta_almacen,
                mensaje.id_mensaje,
                "respondido",
                procesado=True,
                motor=motor_usado or MOTOR_CANAL,
            )
            return respuesta
        except Exception:
            logger.exception("fallo al procesar un mensaje del canal")
            actualizar_mensaje(self.ruta_almacen, mensaje.id_mensaje, "error", procesado=True)
            try:
                self._enviar_texto(mensaje, usuario_id, TEXTO_ERROR)
            except Exception:
                logger.warning("tampoco se pudo enviar el aviso de error")
            return None

    def _avisar_no_autorizado(self, mensaje: MensajeEntrante, usuario_id: str) -> None:
        """Intenta avisar al número no autorizado sin romper el turno.

        En modo real el enviador bloquea cualquier destino que no esté en la
        lista ni dentro de la ventana del evento, así que el aviso no sale: es
        el comportamiento esperado de ``docs/DESPLIEGUE_WHATSAPP.md`` §7.1. El
        mensaje queda ``ignorado`` y no ``error``, y el registro no lleva
        traza de excepción porque no hubo falla del canal.

        Args:
            mensaje: mensaje del número no autorizado.
            usuario_id: huella HMAC del número.
        """
        try:
            self._enviar_texto(mensaje, usuario_id, AVISO_NO_AUTORIZADO)
        except ErrorEnvio as error:
            logger.info("aviso no enviado al número no autorizado: %s", error)

    def _texto_del_motor(self, texto: str, usuario_id: str) -> str | None:
        """Devuelve el texto del motor OpenClaw o ``None`` para usar el grafo.

        No se reenvían los comandos que empiezan por ``/``: el gateway tiene
        sus propios comandos y el invitado no debe dispararlos. Un texto con
        PII tampoco sale al gateway; el grafo aplica la política completa. Un
        fallo del motor no se propaga: el turno cae al grafo y el invitado
        recibe una sola respuesta.

        Args:
            texto: mensaje nuevo del invitado.
            usuario_id: huella HMAC del número.

        Returns:
            El texto del agente, o ``None`` si el turno sigue en el grafo.
        """
        if self.motor is None:
            return None
        limpio = texto.strip()
        if not limpio or limpio.startswith("/"):
            return None
        if detectar_pii(limpio) is not None:
            return None
        try:
            respuesta = self.motor(limpio, usuario_id)
        except Exception as error:
            logger.warning("el motor OpenClaw falló (%s); se usa el grafo", type(error).__name__)
            return None
        if not isinstance(respuesta, str):
            return None
        recortado = respuesta.strip()
        return recortado[:4096] or None

    def _motivo_cierre(self, usuario_id: str, ahora: datetime) -> str | None:
        """Devuelve el texto que explica por qué no se atiende, o ``None``.

        Solo aplica a los números que entran por el modo evento: la lista de
        ``[autorizados]`` no tiene cuota. El tope global cuenta todos los
        mensajes desde que empezó el evento; el tope por persona cuenta la última
        hora y el total.

        Args:
            usuario_id: huella del número.
            ahora: instante del mensaje que se está procesando.

        Returns:
            El aviso de cuota, el aviso de cierre, o ``None`` si puede seguir.
        """
        if not self.config.es_evento(usuario_id, ahora):
            return None
        evento = self.config.evento
        inicio = evento.inicio(ahora)
        if contar_mensajes_desde(self.ruta_almacen, inicio) > evento.max_total:
            return TEXTO_EVENTO_CERRADO
        if contar_mensajes_usuario(self.ruta_almacen, usuario_id, ahora - timedelta(hours=1)) > (
            evento.max_por_hora
        ):
            return TEXTO_CUOTA_USUARIO
        if contar_mensajes_usuario(self.ruta_almacen, usuario_id, inicio) > (
            evento.max_por_usuario
        ):
            return TEXTO_CUOTA_USUARIO
        return None

    def _turno_entrevista(self, mensaje: MensajeEntrante, usuario_id: str) -> RespuestaCanal | None:
        """Resuelve el turno si hay una entrevista del diagnóstico activa.

        Args:
            mensaje: mensaje entrante ya validado.
            usuario_id: huella del número.

        Returns:
            La siguiente pregunta, el diagnóstico completo o un texto de
            cancelación; ``None`` si no hay entrevista activa y el turno debe
            seguir hacia el grafo.
        """
        if self.entrevista is None or not self.entrevista.activa(usuario_id):
            return None
        avance = self.entrevista.avanzar(mensaje, usuario_id)
        if avance.respuestas is not None:
            return self.entrevista.completar(usuario_id, mensaje.id_mensaje, avance.respuestas)
        return avance.respuesta

    def hablar(self, texto: str, momento: datetime | None = None) -> RespuestaCanal | None:
        """Procesa el texto dictado por el voluntario activo como un mensaje más.

        Reutiliza la misma puerta que el webhook (autorización, consentimiento,
        PII, entrevista y motor) y envía la respuesta por WhatsApp al destino
        que la ranura guardó en memoria. La ficha también sale por ese envío si
        el turno la produce.

        Args:
            texto: lo que el navegador transcribió en la entrada por voz.
            momento: instante de referencia para las pruebas.

        Returns:
            La respuesta enviada, o ``None`` si no hay voluntario activo con
            destino o si el turno se descartó.
        """
        if self.escena is None or not activa_entorno():
            return None
        activo = self.escena.voluntario_activo()
        if activo is None:
            return None
        limpio = texto.strip()
        if not limpio:
            return None
        mensaje = MensajeEntrante(
            id_mensaje=f"escena-voz-{secrets.token_hex(8)}",
            remitente=activo.destino,
            texto=limpio[:4096],
            recibido_en=_instante(momento),
        )
        return self.procesar(mensaje, momento)

    def _usuario_id(self, mensaje: MensajeEntrante) -> str | None:
        """Calcula la huella del remitente o ``None`` si el número no es válido."""
        try:
            return calcular_usuario_id(mensaje.remitente, self.sal, self.config.pais_por_defecto)
        except ValueError:
            logger.warning("número inválido en el canal; mensaje descartado")
            return None

    def _enviar_texto(
        self, mensaje: MensajeEntrante, usuario_id: str, texto: str
    ) -> RespuestaCanal:
        """Envía una respuesta de texto simple al remitente y la devuelve."""
        respuesta = RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=mensaje.id_mensaje,
            texto=texto,
        )
        self.crear_enviador(usuario_id, mensaje.remitente).enviar(respuesta)
        return respuesta
