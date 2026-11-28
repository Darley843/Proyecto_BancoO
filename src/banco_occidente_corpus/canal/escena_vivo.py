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
- El canal **conduce la entrevista del voluntario** llamando a las herramientas
  del diagnóstico directo (`diagnosticar_capacidad`, `generar_ficha_opcion` y
  `auditar_respuesta`) con `publicar=True`, sin pasar por OpenClaw: así la
  pantalla avanza rápida y no se mezcla con lo que escriben los demás invitados.
  El estado de la entrevista vive en memoria con el mismo TTL de la escena.
- Los demás invitados no se publican nunca; su conversación privada sigue igual.
- Un mensaje con datos personales no se publica: se publica la respuesta fija
  que el canal envía, porque esa no lleva el dato.
- El publicador es opcional para arrancar: si ``escena/publicador.py`` todavía
  no existe, el turno se descarta y se registra el código, sin romper el canal.

Las pruebas viven en ``test/test_canal_escena_vivo.py``.
"""

from __future__ import annotations

import base64
import importlib
import logging
import os
import re
import secrets
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any, Protocol, cast

from ..asistente.validacion import detectar_pii
from ..escena.contratos import OrigenTurno, PersonajeEscena, TurnoEscena
from ..escena.entrada import monto_de, normalizar
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

#: Estados de la entrevista que el canal conduce para el voluntario activo.
ESTADO_ENTREVISTA = "entrevista"
ESTADO_OPCIONES = "opciones"
ESTADO_CERRADA = "cerrada"

#: Frase fija si la herramienta del diagnóstico no devuelve una pregunta.
TEXTO_SIN_DIAGNOSTICO = (
    "No pude continuar el diagnóstico en este momento. Escríbeme tu pregunta y sigo contigo."
)
#: Cierre de respaldo si el auditor no deja enviar el texto de la ficha.
CIERRE_SEGURO = "Ya te envié la ficha por WhatsApp. Es orientativo: la decisión es del banco."
#: Frase fija si la ficha de la opción no se pudo generar.
TEXTO_SIN_FICHA = (
    "No pude generar la ficha en este momento. Escribe de nuevo A o B e intento otra vez."
)
#: Largo máximo de la línea de contexto que acompaña a una pregunta libre.
LARGO_CONTEXTO = 600
#: Letra de una pregunta o de las opciones A/B, sola o con «letra» u «opción».
_RE_LETRA = re.compile(r"^(?:(?:letra|opcion)\s+)?([a-h])(?:[.)])?$")

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


@dataclass(frozen=True, slots=True)
class FichaVoluntario:
    """La ficha de la opción lista para enviar como imagen al voluntario.

    Vive solo en memoria: el canal tiene el número del voluntario y no necesita
    pasar por ``data/escena/ficha_entrega.json``. ``texto`` es el equivalente
    legible de la tarjeta y ``imagen`` el PNG.
    """

    texto: str = field(repr=False)
    imagen: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class TurnoVoluntario:
    """Lo que el canal debe enviar tras un turno de la entrevista del voluntario.

    ``texto`` es la siguiente pregunta, el resumen con A y B o el cierre corto.
    ``ficha`` solo viene en el cierre: se envía como mensaje aparte.
    """

    texto: str
    ficha: FichaVoluntario | None = None


@dataclass
class _EntrevistaVoluntario:
    """Avance de la entrevista del voluntario, en memoria y con el TTL de la escena."""

    respuestas: list[str] = field(default_factory=list)
    monto: int | None = None
    pendiente: dict[str, Any] = field(default_factory=dict)
    opciones: tuple[Mapping[str, Any], ...] = ()
    estado: str = ESTADO_ENTREVISTA


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
    _entrevista: _EntrevistaVoluntario | None = field(default=None, init=False, repr=False)
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
            self._entrevista = None
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
            self._entrevista = None

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
                self._entrevista = None
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
            self._entrevista = None

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

    def iniciar_entrevista(self, usuario_id: str) -> str | None:
        """Arranca la entrevista del voluntario y devuelve su primera pregunta.

        Llama a ``diagnosticar_capacidad`` con la lista de respuestas vacía y
        ``publicar=True``. Con respuestas vacías la herramienta solo devuelve el
        paso ``faltan_datos``, así que la escena todavía no publica turnos: la
        pantalla los recibe cuando el diagnóstico avanza.

        Args:
            usuario_id: huella HMAC del voluntario activo.

        Returns:
            El ``mensaje_listo`` con la primera pregunta y sus opciones, o
            ``None`` si esa huella no es la voluntaria o la herramienta falló.
        """
        if not self.activo(usuario_id):
            return None
        estado = _EntrevistaVoluntario()
        texto = self._pedir(estado)
        with self._candado:
            if self._huella != usuario_id:
                return None
            self._entrevista = estado
        return texto

    def atender_entrevista(
        self, mensaje: MensajeEntrante, usuario_id: str
    ) -> TurnoVoluntario | None:
        """Avanza la entrevista con la letra, el monto o la opción del voluntario.

        Solo la huella activa avanza. Una letra válida de la pregunta pendiente
        (o el monto exacto, cuando esa es la pregunta) se guarda en memoria y
        se pide el paso siguiente; con el diagnóstico completo se envían las
        opciones A y B, y con A o B se genera la ficha. Cualquier otro texto no
        es una opción: se devuelve ``None`` para que el canal lo pase a OpenClaw.

        Args:
            mensaje: mensaje entrante del voluntario.
            usuario_id: huella HMAC del remitente.

        Returns:
            El texto que el canal debe enviar y, al cerrar, la ficha; o ``None``
            si el turno no es una respuesta válida de la entrevista.
        """
        if not self.activo(usuario_id):
            return None
        estado = self._entrevista
        if estado is None or estado.estado == ESTADO_CERRADA:
            return None
        if estado.estado == ESTADO_OPCIONES:
            letra = _letra_de(mensaje.texto, estado.opciones)
            if letra is None:
                return None
            return self._cerrar(estado, letra)
        if estado.pendiente.get("bloque") == "monto_exacto":
            if not self._anotar_monto(estado, mensaje.texto):
                return None
        else:
            ident = _ident_de_la_opcion(mensaje.texto, estado.opciones)
            if ident is None:
                return None
            clave = ident.split(".", 1)[0]
            estado.respuestas = [
                respuesta
                for respuesta in estado.respuestas
                if not respuesta.startswith(f"{clave}.")
            ]
            estado.respuestas.append(ident)
            if clave == "monto":
                # Si cambia el rango de monto, el monto exacto se vuelve a pedir.
                estado.monto = None
        texto = self._pedir(estado)
        return TurnoVoluntario(texto) if texto else TurnoVoluntario(TEXTO_SIN_DIAGNOSTICO)

    def contexto_entrevista(self, usuario_id: str) -> str | None:
        """Resume en una línea lo que el voluntario ya respondió.

        Se agrega delante de una pregunta libre que el canal manda a OpenClaw,
        para que Pana sepa en qué punto va la entrevista y luego el canal pueda
        retomarla. Solo incluye ids y etiquetas de la entrevista: ni el número
        ni textos libres del voluntario.

        Args:
            usuario_id: huella HMAC del remitente.

        Returns:
            La línea de contexto, o ``None`` si no hay entrevista en curso.
        """
        if not self.activo(usuario_id):
            return None
        estado = self._entrevista
        if estado is None or estado.estado == ESTADO_CERRADA or not estado.respuestas:
            return None
        etiquetas = _etiquetas()
        partes = [
            f"{etiquetas.get(respuesta, respuesta)} ({respuesta})"
            for respuesta in estado.respuestas
        ]
        linea = (
            "Contexto de la entrevista en vivo: el voluntario ya respondió "
            + ", ".join(partes)
            + ". Responde su pregunta sin repetir la entrevista: la entrevista sigue donde quedó."
        )
        return linea[:LARGO_CONTEXTO]

    def _pedir(self, estado: _EntrevistaVoluntario) -> str | None:
        """Pide a la herramienta el paso siguiente y guarda el avance.

        Args:
            estado: entrevista del voluntario que se está conduciendo.

        Returns:
            El ``mensaje_listo`` del paso, o ``None`` si la herramienta falló.
        """
        salida = _herramientas().diagnosticar_capacidad(
            list(estado.respuestas),
            monto=estado.monto,
            publicar=True,
        )
        if not salida.ok:
            logger.warning("la entrevista del voluntario no pudo continuar")
            return None
        datos = salida.datos
        if datos.get("estado") == "faltan_datos":
            estado.pendiente = dict(datos)
            estado.opciones = _opciones(datos.get("opciones"))
            estado.estado = ESTADO_ENTREVISTA
            mensaje = datos.get("mensaje_listo") or datos.get("pregunta")
            return str(mensaje).strip() if mensaje else None
        resumen = datos.get("resumen_escena")
        if isinstance(resumen, Mapping):
            estado.opciones = _opciones(resumen.get("opciones"))
            mensaje = datos.get("mensaje_listo") or resumen.get("mensaje_listo")
        else:
            estado.opciones = ()
            mensaje = datos.get("mensaje_listo")
        estado.pendiente = {}
        estado.estado = ESTADO_OPCIONES if estado.opciones else ESTADO_CERRADA
        return str(mensaje).strip() if mensaje else None

    def _cerrar(self, estado: _EntrevistaVoluntario, letra: str) -> TurnoVoluntario:
        """Genera la ficha de A o B y el cierre corto del voluntario.

        La herramienta publica el turno de la ficha en la pantalla y devuelve el
        PNG en memoria, sin dejar ``data/escena/ficha_entrega.json``: el canal
        ya tiene el número del voluntario. El cierre se audita con las cifras de
        la ficha antes de enviarlo.

        Args:
            estado: entrevista del voluntario con el diagnóstico completo.
            letra: opción elegida, ``A`` o ``B``.

        Returns:
            El cierre corto y, si se pudo, la ficha para el envío aparte.
        """
        modulo = _herramientas()
        salida = modulo.generar_ficha_opcion(
            list(estado.respuestas),
            monto=estado.monto,
            opcion=letra,
            publicar=True,
            devolver_imagen=True,
        )
        if not salida.ok:
            logger.warning("no se pudo generar la ficha del voluntario")
            return TurnoVoluntario(TEXTO_SIN_FICHA)
        datos = salida.datos
        cierre = str(datos.get("mensaje_listo") or "").strip() or CIERRE_SEGURO
        cifras = [str(valor) for valor in datos.get("cifras_permitidas") or ()]
        revision = modulo.auditar_respuesta(cierre, cifras_permitidas=cifras, publicar=True)
        if revision.ok and revision.datos.get("permite_enviar") is False:
            cierre = CIERRE_SEGURO
        estado.estado = ESTADO_CERRADA
        estado.pendiente = {}
        imagen = _imagen(datos.get("png_base64"))
        texto_ficha = str(datos.get("texto") or "").strip()
        if imagen is None or not texto_ficha:
            return TurnoVoluntario(cierre)
        return TurnoVoluntario(cierre, FichaVoluntario(texto_ficha, imagen))

    def _anotar_monto(self, estado: _EntrevistaVoluntario, texto: str) -> bool:
        """Guarda el monto exacto si cae dentro de los límites del rango pendiente.

        Args:
            estado: entrevista del voluntario con la pregunta del monto pendiente.
            texto: lo que escribió el voluntario.

        Returns:
            ``True`` si el monto se reconoció y cabe en el rango; ``False`` si
            el turno debe seguir a OpenClaw como pregunta libre.
        """
        valor = monto_de(texto)
        limites = estado.pendiente.get("limites")
        if valor is None or not isinstance(limites, Mapping):
            return False
        desde = int(limites.get("desde", 0))
        hasta = int(limites.get("hasta", 0))
        entero = int(valor)
        if not desde <= entero <= hasta:
            return False
        estado.monto = entero
        return True

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
            self._entrevista = None
            return False
        return True

    def _instante(self) -> datetime:
        """Devuelve el instante actual en UTC, con zona aunque el reloj no la traiga."""
        valor = self.ahora()
        if valor.tzinfo is None:
            return valor.replace(tzinfo=UTC)
        return valor.astimezone(UTC)


def _herramientas() -> ModuleType:
    """Importa las herramientas del diagnóstico solo cuando se necesitan.

    Returns:
        El módulo ``herramientas.lectura`` ya importado.
    """
    return importlib.import_module("..herramientas.lectura", package=__package__)


def _etiquetas() -> dict[str, str]:
    """Devuelve la etiqueta legible de cada id canónico de la entrevista.

    Returns:
        El mapa ``id → etiqueta`` de ``herramientas.esquemas``.
    """
    modulo = importlib.import_module("..herramientas.esquemas", package=__package__)
    return cast("dict[str, str]", modulo.ETIQUETAS_ENTREVISTA)


def _opciones(valor: object) -> tuple[Mapping[str, Any], ...]:
    """Normaliza la lista de opciones que devuelve la herramienta.

    Args:
        valor: lista de opciones de un paso ``faltan_datos`` o del resumen.

    Returns:
        Las opciones que son diccionarios, en su orden; vacío si no hay.
    """
    if not isinstance(valor, (list, tuple)):
        return ()
    return tuple(opcion for opcion in valor if isinstance(opcion, Mapping))


def _letra_de(texto: str, opciones: Sequence[Mapping[str, Any]]) -> str | None:
    """Reconoce la letra de una opción válida de la pregunta pendiente.

    Acepta ``"A"``, ``"b."``, ``"letra C"`` y ``"opción G"``, sin inventar
    letras que la pregunta no tenga.

    Args:
        texto: lo que escribió el voluntario.
        opciones: opciones de la pregunta pendiente.

    Returns:
        La letra en mayúscula, o ``None`` si no es una opción de esa pregunta.
    """
    coincidencia = _RE_LETRA.match(normalizar(texto))
    if coincidencia is None:
        return None
    letra = coincidencia.group(1).upper()
    validas = {str(opcion.get("letra")) for opcion in opciones}
    return letra if letra in validas else None


def _ident_de_la_opcion(texto: str, opciones: Sequence[Mapping[str, Any]]) -> str | None:
    """Devuelve el id canónico de la opción que eligió el voluntario.

    Args:
        texto: lo que escribió el voluntario.
        opciones: opciones de la pregunta pendiente.

    Returns:
        El id ``bloque.valor`` de la opción, o ``None`` si no es válida.
    """
    letra = _letra_de(texto, opciones)
    if letra is None:
        return None
    for opcion in opciones:
        if str(opcion.get("letra")) == letra:
            ident = str(opcion.get("id") or "").strip()
            return ident or None
    return None


def _imagen(png_base64: object) -> bytes | None:
    """Decodifica el PNG que la ficha devolvió en base64.

    Args:
        png_base64: contenido del campo ``png_base64`` de la herramienta.

    Returns:
        Los bytes del PNG, o ``None`` si no vino o no se pudo decodificar.
    """
    if not isinstance(png_base64, str) or not png_base64:
        return None
    try:
        return base64.b64decode(png_base64, validate=True)
    except (ValueError, TypeError):
        logger.warning("la ficha del voluntario no trajo un PNG válido")
        return None


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
