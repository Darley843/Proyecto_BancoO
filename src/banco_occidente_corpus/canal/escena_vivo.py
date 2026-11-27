"""Escena en vivo desde el canal: activación con ``ESCENA`` y publicación.

El voluntario de la demo escribe ``ESCENA`` por WhatsApp y, desde ese momento,
sus mensajes y las respuestas de Pana se publican en la lista que lee la
pantalla (``GET /api/escena/en-vivo``). La escritura la hace
``escena/publicador.py``; aquí solo se decide **quién** publica y **qué** turno.

Reglas que implementa este módulo:

- Solo hay **un** voluntario activo, guardado en memoria con su huella HMAC, el
  destino normalizado del mensaje de ``ESCENA`` y un vencimiento deslizante. No
  va a SQLite y no sobrevive a un reinicio. El destino solo sirve para que
  ``POST /api/escena/hablar`` envíe la respuesta y la ficha por WhatsApp; nunca
  se registra en logs ni se envía al modelo.
- ``ESCENA`` seguido del código de cuatro dígitos de ``ESCENA_CODIGO`` se
  reconoce después de la autorización y del consentimiento, y antes de la
  entrevista, del escenario y del motor de OpenClaw.
- Sin código, o con otro código, el comando no activa ni publica: el mensaje
  sigue su curso privado normal.
- La **convocatoria** de la pantalla reemplaza el comando: al terminar la
  presentación, la primera huella con consentimiento que escriba después de la
  apertura queda como voluntaria sin código. Las demás siguen como invitadas y
  reciben una sola vez el aviso de que el voluntario ya está en el escenario.
  ``DELETE /api/escena/convocatoria`` libera la ranura para la tecla L.
- El interruptor ``ESCENA_EN_VIVO=1`` se consulta en cada publicación: apagarlo
  detiene la escritura sin reiniciar la app.
- Los demás invitados no se publican nunca; su conversación privada sigue igual.
- Un mensaje con datos personales no se publica: se publica la respuesta fija
  que el canal envía, porque esa no lleva el dato.
- El publicador es opcional para arrancar: si ``escena/publicador.py`` todavía
  no existe, el turno se descarta y se registra el código, sin romper el canal.

Las pruebas viven en ``test/test_canal_escena_vivo.py``.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import secrets
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from ..asistente.validacion import detectar_pii
from ..escena.contratos import OrigenTurno, PersonajeEscena, TurnoEscena
from .contratos import MensajeEntrante, RespuestaCanal

logger = logging.getLogger(__name__)

#: Palabra que activa al voluntario; se compara sin mayúsculas ni espacios.
COMANDO = "ESCENA"
#: Variable de entorno que enciende la publicación de la lista en vivo.
INTERRUPTOR = "ESCENA_EN_VIVO"
#: Variable de la sesión con el código de cuatro dígitos del voluntario.
VARIABLE_CODIGO = "ESCENA_CODIGO"
#: Frase fija cuando el interruptor está apagado.
TEXTO_APAGADA = "La escena en vivo no está activada."
#: Frase fija que confirma la activación del voluntario.
TEXTO_ACTIVADA = "Escena en vivo activada. Escribe tu primera pregunta."
#: Frase fija para la primera huella que acepta la convocatoria de la pantalla.
TEXTO_VOLUNTARIO = (
    "¡Eres nuestro voluntario! 🎬 Habla con Pana frente a la pantalla, o escríbele aquí."
)
#: Aviso para quien llega después de que la convocatoria ya tiene voluntario.
TEXTO_YA_HAY_VOLUNTARIO = (
    "El voluntario de la escena ya está en el escenario. Puedes seguir conversando "
    "conmigo por aquí: pregúntame por un crédito, las tasas o el proyecto."
)
#: Minutos que el voluntario queda activo si el TOML no dice otra cosa.
TTL_POR_DEFECTO = 180
#: Largo máximo del texto de un turno; el contrato de la lista pide 4.000.
LARGO_MAXIMO = 4000
#: Identificadores estables de los tres turnos que publica el canal.
ID_INVITADO = "canal.invitado.v1"
ID_PANA = "canal.pana.v1"
ID_ACTIVACION = "canal.pana.escena.v1"
ID_CONVOCATORIA = "canal.pana.convocatoria.v1"

#: Comando ``ESCENA`` con un código de cuatro dígitos opcional; se aplica al
#: texto normalizado (sin mayúsculas de diferencia y con un solo espacio).
_PATRON_COMANDO = re.compile(
    rf"^{re.escape(COMANDO)}(?:\s+(\d{{4}}))?$",
    re.IGNORECASE | re.ASCII,
)

#: Formas de presentarse cuyo nombre propio se enmascara antes de publicar.
_FORMAS_NOMBRE = re.compile(
    r"\b(?:me llamo|mi nombre es|soy)\s+"
    r"([A-ZÁÉÍÓÚÜÑ][\wáéíóúüñ]*(?:\s+[A-ZÁÉÍÓÚÜÑ][\wáéíóúüñ]*){0,2})"
)

#: Evita repetir el aviso de publicador ausente en cada turno.
_AVISADO_SIN_PUBLICADOR = False


class Publicador(Protocol):
    """Firma de ``escena.publicador.publicar_turnos``."""

    def __call__(
        self,
        turnos: Iterable[TurnoEscena],
        *,
        origen: str,
        permitidos: Iterable[str] = (),
    ) -> object:
        """Escribe los turnos y devuelve los ``seq`` asignados."""


def activa_entorno() -> bool:
    """Indica si la variable ``ESCENA_EN_VIVO`` está exactamente en ``1``.

    Returns:
        ``True`` solo con el valor ``1``; cualquier otro valor no publica.
    """
    return os.getenv(INTERRUPTOR, "").strip() == "1"


def es_comando(texto: str) -> bool:
    """Indica si el texto es el comando ``ESCENA``, con código o sin él.

    Args:
        texto: texto del mensaje ya normalizado por el webhook.

    Returns:
        ``True`` para ``ESCENA`` y para ``ESCENA <cuatro dígitos>``. Sirve para
        no publicar el intento aunque el código no active al voluntario.
    """
    return _PATRON_COMANDO.match(_normalizar(texto)) is not None


def codigo_del_comando(texto: str) -> str | None:
    """Devuelve el código de cuatro dígitos que acompaña al comando.

    Args:
        texto: texto del mensaje.

    Returns:
        El código tal como se escribió, o ``None`` si no lo trae.
    """
    coincidencia = _PATRON_COMANDO.match(_normalizar(texto))
    return coincidencia.group(1) if coincidencia is not None else None


def codigo_valido(texto: str) -> bool:
    """Indica si el texto trae el código de la sesión (``ESCENA_CODIGO``).

    El código se compara con el de la variable de la sesión; si la variable no
    está definida, ningún código vale y la escena no se activa.

    Args:
        texto: texto del mensaje.

    Returns:
        ``True`` solo si el comando trae el código configurado.
    """
    esperado = os.getenv(VARIABLE_CODIGO, "").strip()
    if len(esperado) != 4 or not esperado.isascii() or not esperado.isdigit():
        return False
    recibido = codigo_del_comando(texto)
    if recibido is None:
        return False
    return secrets.compare_digest(recibido, esperado)


def _normalizar(texto: str) -> str:
    """Une los espacios sobrantes del comando sin tocar el resto del texto."""
    return " ".join(texto.split())


def sin_nombres(texto: str) -> str:
    """Enmascara los nombres propios que siguen a «me llamo», «soy» o «mi nombre es».

    Solo se sustituye la forma con nombre propio en mayúscula inicial, para no
    tocar frases como «soy independiente». El publicador vuelve a comprobar la
    PII antes de escribir: esto es una ayuda, no la única barrera.

    Args:
        texto: texto del invitado o de Pana.

    Returns:
        El texto con el nombre cambiado por ``[nombre]``.
    """
    return _FORMAS_NOMBRE.sub(
        lambda match: match.group(0).replace(match.group(1), "[nombre]"), texto
    )


@dataclass(frozen=True, slots=True)
class VoluntarioActivo:
    """Huella y destino del voluntario activo, solo para el envío del canal.

    ``destino`` es el número normalizado que llegó en el mensaje de ``ESCENA``.
    Vive en memoria mientras la ranura esté vigente, no se persiste, no se
    registra en logs y nunca se envía al modelo.
    """

    huella: str = field(repr=False)
    destino: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResultadoConvocatoria:
    """Resultado de una huella que escribe con la convocatoria abierta.

    ``voluntario`` distingue a la persona que ocupa la ranura de la que llega
    después. ``texto`` es la frase que el canal debe enviar; en la activación
    ya se publicó como turno de Pana para que la pantalla abra la conversación.
    """

    voluntario: bool
    texto: str | None = None


@dataclass
class EscenaVivo:
    """Ranura del voluntario activo y publicación de sus turnos.

    Attributes:
        ttl_minutos: minutos que el voluntario queda activo; cada mensaje
            renueva el vencimiento.
        publicador: función de escritura; por defecto la de ``escena``.
        permitidos: teléfonos públicos que el detector de PII no debe marcar.
        ahora: reloj inyectable para las pruebas.
    """

    ttl_minutos: int = TTL_POR_DEFECTO
    publicador: Publicador | None = None
    permitidos: tuple[str, ...] = ()
    ahora: Callable[[], datetime] = lambda: datetime.now(UTC)
    _huella: str | None = field(default=None, init=False, repr=False)
    _destino: str | None = field(default=None, init=False, repr=False)
    _vence: datetime | None = field(default=None, init=False, repr=False)
    _apertura: datetime | None = field(default=None, init=False, repr=False)
    _abierta: bool = field(default=False, init=False, repr=False)
    _avisados: set[str] = field(default_factory=set, init=False, repr=False)
    _candado: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def decidir(self, mensaje: MensajeEntrante, usuario_id: str) -> RespuestaCanal | None:
        """Atiende el comando ``ESCENA`` si el mensaje lo es y el código cuadra.

        Args:
            mensaje: mensaje entrante ya autorizado y con consentimiento.
            usuario_id: huella HMAC del remitente.

        Returns:
            La confirmación, el aviso de que la escena está apagada, o
            ``None`` si el mensaje debe seguir su curso normal: no es el
            comando, no trae el código de la sesión, o ya hay otro voluntario
            activo que no se reemplaza.
        """
        if not es_comando(mensaje.texto):
            return None
        if not activa_entorno():
            logger.info("comando ESCENA con la escena en vivo apagada")
            return _respuesta(mensaje, usuario_id, TEXTO_APAGADA)
        if not codigo_valido(mensaje.texto):
            logger.info("comando ESCENA sin el código de la sesión")
            return None
        if not self.activar(usuario_id, destino=mensaje.remitente):
            logger.info("comando ESCENA con otro voluntario activo: se ignora")
            return None
        self._publicar_pana(ID_ACTIVACION, TEXTO_ACTIVADA)
        return _respuesta(mensaje, usuario_id, TEXTO_ACTIVADA)

    def activar(self, usuario_id: str, *, destino: str | None = None) -> bool:
        """Deja a esa huella como la única voluntaria activa.

        Si ya hay otro voluntario vigente, la ranura no se reemplaza: solo se
        cambia de voluntario reiniciando la app o esperando el vencimiento.

        Args:
            usuario_id: huella HMAC del invitado que escribió ``ESCENA``.
            destino: número normalizado del mensaje, guardado solo en memoria
                para enviar las respuestas y la ficha desde ``/hablar``. No se
                persiste, no se registra y no se envía al modelo.

        Returns:
            ``True`` si la huella quedó activa (nueva o renovada); ``False`` si
            otro voluntario seguía vigente y el comando se ignoró.
        """
        with self._candado:
            if (
                self._huella is not None
                and self._huella != usuario_id
                and self._vigente(self._huella)
            ):
                return False
            self._huella = usuario_id
            if destino is not None:
                self._destino = destino
            self._vence = self._instante() + timedelta(minutes=self.ttl_minutos)
            return True

    def abrir_convocatoria(self) -> None:
        """Abre la convocatoria y guarda el instante de apertura.

        Desde aquí, la primera huella con el consentimiento vigente que escriba
        ocupa la ranura y cierra la aceptación. La convocatoria sigue en curso
        para avisar a los demás invitados hasta que se libere con
        :meth:`liberar_convocatoria`.
        """
        with self._candado:
            self._apertura = self._instante()
            self._abierta = True
            self._avisados.clear()
            if self._huella is not None:
                # Si el voluntario anterior venció, la ranura queda libre.
                self._vigente(self._huella)

    def liberar_convocatoria(self) -> None:
        """Libera al voluntario activo y cierra la convocatoria.

        Se usa con la tecla L de la pantalla cuando la persona que se adelantó
        no es la que debe salir en el escenario. La siguiente apertura empieza
        con la ranura y los avisos limpios.
        """
        with self._candado:
            self._huella = None
            self._destino = None
            self._vence = None
            self._apertura = None
            self._abierta = False
            self._avisados.clear()

    def convocatoria_abierta(self) -> bool:
        """Indica si la convocatoria todavía acepta voluntarios.

        Returns:
            ``True`` entre la apertura y la primera activación; ``False`` si no
            hay convocatoria, si ya eligió voluntario o si se liberó.
        """
        with self._candado:
            return self._abierta and self._apertura is not None

    def convocar(
        self, usuario_id: str, *, destino: str | None = None
    ) -> ResultadoConvocatoria | None:
        """Atiende a una huella que escribe después de abrir la convocatoria.

        Sin convocatoria no hace nada y el turno sigue como hoy. Con la
        aceptación abierta y la ranura libre, la primera huella queda como
        voluntaria, con el mismo TTL y destino que ``ESCENA <código>``. Si ya
        hay voluntario, la primera vez que esa huella escribe recibe el aviso
        para seguir como invitada; las siguientes no lo repiten.

        Args:
            usuario_id: huella HMAC del remitente.
            destino: número normalizado del mensaje, guardado solo en memoria
                para que el canal envíe la respuesta y la ficha. No se
                persiste, no se registra y no se envía al modelo.

        Returns:
            ``None`` si no hay convocatoria, si la huella ya es la voluntaria
            o si el aviso ya se dio; si no, el resultado con la frase que el
            canal debe enviar.
        """
        activado = False
        with self._candado:
            if self._apertura is None:
                return None
            if self._huella is not None and not self._vigente(self._huella):
                pass  # ``_vigente`` ya dejó la ranura libre al vencer.
            if self._huella == usuario_id:
                return None
            if self._huella is None:
                if not self._abierta:
                    return None
                self._huella = usuario_id
                if destino is not None:
                    self._destino = destino
                self._vence = self._instante() + timedelta(minutes=self.ttl_minutos)
                self._abierta = False
                activado = True
            else:
                if usuario_id in self._avisados:
                    return None
                self._avisados.add(usuario_id)
        if activado:
            self._publicar_pana(ID_CONVOCATORIA, TEXTO_VOLUNTARIO)
            return ResultadoConvocatoria(voluntario=True, texto=TEXTO_VOLUNTARIO)
        return ResultadoConvocatoria(voluntario=False, texto=TEXTO_YA_HAY_VOLUNTARIO)

    def activo(self, usuario_id: str) -> bool:
        """Indica si esa huella es la voluntaria activa y no venció.

        Args:
            usuario_id: huella HMAC a comprobar.

        Returns:
            ``True`` solo para la huella activa dentro del TTL; al vencer se
            descarta la ranura.
        """
        with self._candado:
            return self._vigente(usuario_id)

    def voluntario_activo(self) -> VoluntarioActivo | None:
        """Devuelve la huella y el destino del voluntario vigente, si existe.

        El destino solo se usa para que ``/api/escena/hablar`` envíe la
        respuesta y la ficha por WhatsApp. Nunca se devuelve al navegador ni se
        escribe en un log.

        Returns:
            El voluntario activo con su destino, o ``None`` si no hay ranura
            vigente o si se activó sin destino.
        """
        with self._candado:
            if self._huella is None or not self._vigente(self._huella):
                return None
            if self._destino is None:
                return None
            return VoluntarioActivo(self._huella, self._destino)

    def renovar(self, usuario_id: str) -> bool:
        """Renueva el vencimiento si la huella sigue siendo la activa.

        Args:
            usuario_id: huella HMAC del remitente.

        Returns:
            ``True`` si renovó; ``False`` si no era la voluntaria o ya venció.
        """
        with self._candado:
            if not self._vigente(usuario_id):
                return False
            self._vence = self._instante() + timedelta(minutes=self.ttl_minutos)
            return True

    def olvidar(self) -> None:
        """Descarta al voluntario activo (borrado del evento y pruebas)."""
        with self._candado:
            self._huella = None
            self._destino = None
            self._vence = None

    def publicar_invitado(self, mensaje: MensajeEntrante, usuario_id: str) -> bool:
        """Publica el mensaje del voluntario como turno ``invitado``.

        Se llama **antes** del motor, para que la pantalla muestre el mensaje y
        después los turnos de las herramientas. Los demás invitados no publican.

        Args:
            mensaje: mensaje entrante del invitado.
            usuario_id: huella HMAC del remitente.

        Returns:
            ``True`` si se publicó; ``False`` si no era el voluntario, si el
            mensaje traía datos personales o si la escena está apagada.
        """
        if not self.renovar(usuario_id):
            return False
        texto = sin_nombres(mensaje.texto.strip())[:LARGO_MAXIMO]
        if not texto:
            return False
        if detectar_pii(texto, permitidos=self.permitidos) is not None:
            logger.info("mensaje del invitado con PII: no se publica")
            return False
        return self._publicar(_turno(ID_INVITADO, "invitado", texto))

    def publicar_pana(self, usuario_id: str, texto: str) -> bool:
        """Publica la respuesta de Pana después de que el envío salió bien.

        Args:
            usuario_id: huella HMAC del remitente.
            texto: texto exacto que se envió por WhatsApp.

        Returns:
            ``True`` si se publicó; ``False`` si no era el voluntario, si el
            texto traía PII o si la escena está apagada.
        """
        if not self.activo(usuario_id):
            return False
        return self._publicar_pana(ID_PANA, texto)

    def _publicar_pana(self, identificador: str, texto: str) -> bool:
        """Publica un turno de Pana con el saneado y el filtro de PII."""
        limpio = sin_nombres(texto.strip())[:LARGO_MAXIMO]
        if not limpio:
            return False
        if detectar_pii(limpio, permitidos=self.permitidos) is not None:
            logger.info("respuesta de Pana con PII: no se publica")
            return False
        return self._publicar(_turno(identificador, "pana", limpio))

    def _publicar(self, turno: TurnoEscena) -> bool:
        """Entrega el turno al publicador, sin propagar sus fallos."""
        if not activa_entorno():
            return False
        publicador = self.publicador
        if publicador is None:
            publicador = _publicador_por_defecto()
            if publicador is None:
                return False
        try:
            publicador((turno,), origen="canal", permitidos=self.permitidos)
        except Exception:
            logger.warning("no se pudo publicar el turno de la escena en vivo")
            return False
        return True

    def _vigente(self, usuario_id: str) -> bool:
        """Comprueba la ranura sin tomar el candado (se llama dentro de él)."""
        if self._huella is None or self._huella != usuario_id or self._vence is None:
            return False
        if self._instante() >= self._vence:
            self._huella = None
            self._destino = None
            self._vence = None
            return False
        return True

    def _instante(self) -> datetime:
        """Devuelve el instante actual en UTC, con zona aunque el reloj no la traiga."""
        valor = self.ahora()
        if valor.tzinfo is None:
            return valor.replace(tzinfo=UTC)
        return valor.astimezone(UTC)


def _respuesta(mensaje: MensajeEntrante, usuario_id: str, texto: str) -> RespuestaCanal:
    """Construye la respuesta de texto del comando."""
    return RespuestaCanal(
        usuario_id=usuario_id,
        id_mensaje_origen=mensaje.id_mensaje,
        texto=texto,
    )


def _turno(identificador: str, personaje: PersonajeEscena, texto: str) -> TurnoEscena:
    """Construye el turno del canal; ``orden`` no ordena la lista en vivo."""
    origen: OrigenTurno = "canal"
    return TurnoEscena(
        id=identificador,
        orden=0,
        personaje=personaje,
        texto=texto,
        origen=origen,
    )


def _publicador_por_defecto() -> Publicador | None:
    """Importa el publicador de la escena o devuelve ``None`` si aún no existe."""
    global _AVISADO_SIN_PUBLICADOR
    try:
        modulo = importlib.import_module("..escena.publicador", package=__package__)
    except ImportError:
        if not _AVISADO_SIN_PUBLICADOR:
            logger.warning("falta escena/publicador.py; los turnos del canal no se publican")
            _AVISADO_SIN_PUBLICADOR = True
        return None
    return cast(Publicador, modulo.publicar_turnos)
