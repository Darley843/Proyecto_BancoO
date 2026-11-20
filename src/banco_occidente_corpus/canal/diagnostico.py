"""Entrevista del diagnóstico dentro del canal de WhatsApp.

Es el puente que faltaba entre el guion (`docs/DIAGNOSTICO.md`), el motor
(`diagnostico/motor.py`) y la tarjeta de Pana (`pana/desde_diagnostico.py`):

1. Si la persona pide un diagnóstico y no hay entrevista en curso, invita con
   dos botones («Empezar» y «Ahora no»).
2. Cada respuesta se valida contra el paso pendiente y se guarda en
   `data/asistente/diagnostico.sqlite`; la siguiente pregunta sale como botones
   (hasta tres opciones) o como lista.
3. Al cerrar la entrevista, el motor calcula y la respuesta lleva el texto y la
   tarjeta de Pana como imagen.
4. «Cancelar» borra la sesión y «asesor» deja un caso para una persona, sin
   nombre ni número.

El servicio no llama al modelo ni hace red: el cálculo es determinístico y la
tasa sale del Tablero. Las pruebas viven en `test/test_canal_diagnostico.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..diagnostico.entrevista import (
    ID_CANCELAR,
    ID_EMPEZAR,
    Pregunta,
    RespuestaInvalida,
    comando,
    pregunta_pendiente,
    registrar_respuesta,
    titulo_de,
)
from ..diagnostico.motor import ConfigDiagnostico, calcular, cargar_config, entrada_desde_respuestas
from ..diagnostico.sesiones import borrar as borrar_sesion
from ..diagnostico.sesiones import cargar as cargar_sesion
from ..diagnostico.sesiones import existe as existe_sesion
from ..diagnostico.sesiones import guardar as guardar_sesion
from ..pana.desde_diagnostico import SinTarjeta, tarjeta_y_texto
from ..sucursal.digiturno import clasificar
from ..tablero.tasas import TasaNoDisponible
from .almacen import registrar_caso
from .contratos import BotonCanal, MensajeEntrante, OpcionCanal, RespuestaCanal

#: Texto de la invitación, antes de la primera pregunta.
TEXTO_INVITACION: str = (
    "Puedo hacerte un diagnóstico financiero orientativo: con rangos de tus "
    "ingresos, gastos y cuotas actuales calculo tu capacidad de pago, la cuota "
    "estimada y un semáforo. No es una aprobación de crédito. Son siete "
    "preguntas cortas y puedes cancelar cuando quieras."
)

#: Respuesta a la orden de cancelar.
TEXTO_CANCELADO: str = "Listo, no hacemos el diagnóstico. Cuando quieras lo retomamos."

#: Respuesta cuando se pide un asesor humano.
TEXTO_ASESOR: str = (
    "Listo, dejé tu solicitud para que un asesor te contacte. No necesito más datos por este canal."
)

#: Respuesta si el motor no puede calcular (tasa ausente o datos incoherentes).
TEXTO_SIN_CALCULO: str = (
    "No pude calcular el diagnóstico con los datos de la entrevista. Puedes "
    "intentarlo otra vez o escribir «asesor» para que te contacte una persona."
)

#: Aviso que acompaña a todo resultado, como exige `docs/DIAGNOSTICO.md`.
AVISO_ORIENTATIVO: str = (
    "Es un cálculo orientativo, no una aprobación de crédito. La tasa sale del "
    "tarifario vigente del Banco."
)

#: Tipos de respuesta que este servicio puede construir.
TipoRespuesta = Literal["texto", "botones", "lista", "imagen"]


def pide_diagnostico(texto: str) -> bool:
    """Dice si el mensaje pide un diagnóstico financiero.

    Usa el Digiturno de la Sucursal para no duplicar reglas: la letra `D` es la
    ruta del diagnóstico.

    Args:
        texto: mensaje de la persona.

    Returns:
        ``True`` si el Digiturno lo clasifica en la ruta `D`.
    """
    try:
        return clasificar(texto).letra == "D"
    except ValueError:
        return False


@dataclass
class ServicioDiagnostico:
    """Atiende la entrevista del diagnóstico antes que el grafo.

    Attributes:
        ruta_sesiones: SQLite con las respuestas en curso.
        ruta_almacen: SQLite del canal, donde viven los casos de asesor.
        config: umbrales y guion de `config/diagnostico.toml`.
        raiz: carpeta de tablas Gold alternativa; por defecto la del Tablero.
        es_diagnostico: detector inyectable; por defecto usa el Digiturno.
    """

    ruta_sesiones: Path
    ruta_almacen: Path
    config: ConfigDiagnostico
    raiz: Path | None = None
    es_diagnostico: Callable[[str], bool] = pide_diagnostico

    def atender(self, mensaje: MensajeEntrante, usuario_id: str) -> RespuestaCanal | None:
        """Responde el turno si pertenece a la entrevista del diagnóstico.

        Args:
            mensaje: mensaje ya normalizado del webhook.
            usuario_id: huella HMAC del número.

        Returns:
            La respuesta del canal, o ``None`` si el mensaje no es del
            diagnóstico y debe seguir al grafo de la Sucursal.
        """
        respuestas = cargar_sesion(self.ruta_sesiones, usuario_id)
        activa = bool(respuestas) or existe_sesion(self.ruta_sesiones, usuario_id)
        orden = comando(mensaje.texto, mensaje.id_boton)

        if orden == "cancelar":
            borrar_sesion(self.ruta_sesiones, usuario_id)
            return self._respuesta(mensaje, usuario_id, TEXTO_CANCELADO, paso="cancelado")

        if orden == "asesor":
            registrar_caso(self.ruta_almacen, usuario_id, "asesor_solicitado")
            borrar_sesion(self.ruta_sesiones, usuario_id)
            return self._respuesta(mensaje, usuario_id, TEXTO_ASESOR, paso="asesor")

        if orden == "empezar":
            guardar_sesion(self.ruta_sesiones, usuario_id, respuestas)
            return self._paso(mensaje, usuario_id, respuestas)

        if not activa:
            if not self.es_diagnostico(mensaje.texto):
                return None
            return self._invitacion(mensaje, usuario_id)

        return self._avanzar(mensaje, usuario_id, respuestas)

    def _invitacion(self, mensaje: MensajeEntrante, usuario_id: str) -> RespuestaCanal:
        """Devuelve la invitación con los botones de empezar y aplazar."""
        return self._respuesta(
            mensaje,
            usuario_id,
            TEXTO_INVITACION,
            tipo="botones",
            botones=[
                BotonCanal(id=ID_EMPEZAR, titulo="Empezar"),
                BotonCanal(id=ID_CANCELAR, titulo="Ahora no"),
            ],
            paso="invitacion",
        )

    def _avanzar(
        self,
        mensaje: MensajeEntrante,
        usuario_id: str,
        respuestas: dict[str, str],
    ) -> RespuestaCanal:
        """Registra la respuesta del paso pendiente y sigue la entrevista."""
        try:
            nuevas = registrar_respuesta(
                respuestas,
                mensaje.texto,
                mensaje.id_boton,
                config=self.config,
            )
        except RespuestaInvalida as error:
            return self._paso(mensaje, usuario_id, respuestas, aviso=str(error))

        anotado = ""
        pendiente = pregunta_pendiente(respuestas, config=self.config)
        if pendiente is not None:
            elegido = nuevas.get(pendiente.clave)
            if elegido:
                anotado = f"Anotado: {titulo_de(elegido, config=self.config)}."
        return self._paso(mensaje, usuario_id, nuevas, aviso=anotado)

    def _paso(
        self,
        mensaje: MensajeEntrante,
        usuario_id: str,
        respuestas: dict[str, str],
        *,
        aviso: str = "",
    ) -> RespuestaCanal:
        """Envía la siguiente pregunta o, si ya no hay, el resultado."""
        pregunta = pregunta_pendiente(respuestas, config=self.config)
        if pregunta is None:
            return self._resultado(mensaje, usuario_id, respuestas)

        guardar_sesion(self.ruta_sesiones, usuario_id, respuestas)
        texto = f"{aviso}\n\n{pregunta.texto}".strip()
        if pregunta.tipo == "botones":
            return self._pregunta_botones(mensaje, usuario_id, pregunta, texto)
        return self._pregunta_lista(mensaje, usuario_id, pregunta, texto)

    def _pregunta_botones(
        self,
        mensaje: MensajeEntrante,
        usuario_id: str,
        pregunta: Pregunta,
        texto: str,
    ) -> RespuestaCanal:
        """Arma una pregunta de hasta tres opciones con botones."""
        return self._respuesta(
            mensaje,
            usuario_id,
            texto,
            tipo="botones",
            botones=[
                BotonCanal(id=opcion.id, titulo=opcion.titulo[:20]) for opcion in pregunta.opciones
            ],
            paso=pregunta.clave,
        )

    def _pregunta_lista(
        self,
        mensaje: MensajeEntrante,
        usuario_id: str,
        pregunta: Pregunta,
        texto: str,
    ) -> RespuestaCanal:
        """Arma una pregunta con lista de filas (más de tres opciones)."""
        return self._respuesta(
            mensaje,
            usuario_id,
            texto,
            tipo="lista",
            opciones=[
                OpcionCanal(
                    id=opcion.id,
                    titulo=opcion.titulo[:24],
                    descripcion=opcion.descripcion,
                )
                for opcion in pregunta.opciones
            ],
            paso=pregunta.clave,
        )

    def _resultado(
        self,
        mensaje: MensajeEntrante,
        usuario_id: str,
        respuestas: dict[str, str],
    ) -> RespuestaCanal:
        """Calcula el diagnóstico, borra la sesión y envía texto y tarjeta."""
        try:
            entrada = entrada_desde_respuestas(respuestas, config=self.config)
            resultado = calcular(entrada, raiz=self.raiz, config=self.config)
            png, texto = tarjeta_y_texto(resultado)
        except (SinTarjeta, TasaNoDisponible, ValueError):
            borrar_sesion(self.ruta_sesiones, usuario_id)
            return self._respuesta(mensaje, usuario_id, TEXTO_SIN_CALCULO, paso="error")

        borrar_sesion(self.ruta_sesiones, usuario_id)
        return self._respuesta(
            mensaje,
            usuario_id,
            f"{texto}\n\n{AVISO_ORIENTATIVO}",
            tipo="imagen",
            imagen=png,
            paso="resultado",
            semaforo=resultado.semaforo or "",
        )

    def _respuesta(
        self,
        mensaje: MensajeEntrante,
        usuario_id: str,
        texto: str,
        *,
        tipo: TipoRespuesta = "texto",
        botones: list[BotonCanal] | None = None,
        opciones: list[OpcionCanal] | None = None,
        imagen: bytes | None = None,
        paso: str = "",
        semaforo: str = "",
    ) -> RespuestaCanal:
        """Construye la respuesta del canal con sus metadatos de trazabilidad."""
        metadatos = {"ruta": "diagnostico", "paso": paso}
        if semaforo:
            metadatos["semaforo"] = semaforo
        return RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=mensaje.id_mensaje,
            texto=texto[:4096],
            tipo=tipo,
            botones=botones or [],
            opciones=opciones or [],
            imagen=imagen,
            metadatos=metadatos,
        )


def crear_servicio(
    ruta_sesiones: Path,
    ruta_almacen: Path,
    *,
    raiz: Path | None = None,
    config: ConfigDiagnostico | None = None,
    es_diagnostico: Callable[[str], bool] = pide_diagnostico,
) -> ServicioDiagnostico:
    """Arma el servicio con la configuración del diagnóstico ya cargada.

    Args:
        ruta_sesiones: SQLite de las entrevistas en curso.
        ruta_almacen: SQLite del canal, para los casos de asesor.
        raiz: carpeta de tablas Gold alternativa; por defecto la del Tablero.
        config: configuración ya cargada; por defecto se lee el TOML.
        es_diagnostico: detector inyectable para las pruebas.

    Returns:
        El servicio listo para el despachador.
    """
    return ServicioDiagnostico(
        ruta_sesiones=ruta_sesiones,
        ruta_almacen=ruta_almacen,
        config=config or cargar_config(),
        raiz=raiz,
        es_diagnostico=es_diagnostico,
    )
