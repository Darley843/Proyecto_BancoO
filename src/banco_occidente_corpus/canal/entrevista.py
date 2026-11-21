"""Entrevista guiada del diagnóstico por el canal de WhatsApp.

Convierte los ids canónicos de ``docs/DIAGNOSTICO.md`` en preguntas con botones
o listas, guarda el avance por ``usuario_id`` en ``data/asistente/whatsapp.sqlite``
y, al terminar, calcula el diagnóstico con el motor determinista y envía la
tarjeta de Pana después del texto.

Reglas del guion:

- Una sola pregunta por turno. Botones cuando hay tres opciones o menos y todas
  caben en 20 caracteres; lista de hasta diez filas en los demás casos.
- ``cuota_trasladar`` solo se pregunta en compra de cartera; monto y plazo se
  omiten en ahorro.
- El estado guarda solo el paso actual y los ids elegidos, nunca el texto libre
  ni datos personales. Vence a los ``ttl_minutos`` sin actividad y la app lo
  purga al arrancar.
- ``nuevo`` reinicia la entrevista; ``cancelar`` la deja; ``asesor`` la deja y
  ofrece revisión humana. Cualquier otro texto repite la pregunta con sus
  opciones, sin inventar un valor.

Al completar: ``entrada_desde_respuestas`` → ``calcular`` → comité (solo
amarillo o rojo con cuota) → ``tarjeta_y_texto``. El texto sale primero y la
imagen después. Si el comité falla, se responde con el diagnóstico sin comité.

«¿Y si…?»: el último resultado se guarda por huella en
``resultados_diagnostico`` durante ``VIGENCIA_RESULTADO`` (24 horas). Si la
persona escribe después «¿y si lo pago en 60 meses?», `escenario` recalcula con
el motor y responde con la tarjeta de antes y después; el original no cambia.
Sin un resultado vigente, el mensaje sigue su camino normal hacia el grafo.
La app purga al arrancar las entrevistas y los resultados vencidos, para que el
plazo del aviso no dependa de que la persona vuelva a escribir.

Las pruebas viven en ``test/test_canal_entrevista.py``.
"""

from __future__ import annotations

import json
import logging
import tomllib
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from ..config import PROJECT_ROOT
from ..diagnostico import comite, motor
from ..diagnostico.escenarios import (
    EscenarioFueraDeRango,
    comparar_resultado,
    formatear_rango,
    interpretar_pedido,
)
from ..pana.desde_diagnostico import SinTarjeta, escenario_y_texto, tarjeta_y_texto
from ..tablero.tasas import TasaNoDisponible
from .almacen import conectar, inicializar_almacen
from .contratos import (
    BotonCanal,
    EntradaDiagnostico,
    MensajeEntrante,
    OpcionLista,
    RespuestaCanal,
    ResultadoDiagnostico,
)
from .hitl import MOTIVO_ROJO, AccionHitl, HitlAsesor

logger = logging.getLogger(__name__)

#: Archivo versionado con el guion de la entrevista.
RUTA_CONFIG = PROJECT_ROOT / "config" / "diagnostico.toml"

#: Minutos por defecto que sobrevive una entrevista sin actividad.
TTL_POR_DEFECTO = 30

#: Texto del mensaje cuando la persona cancela la entrevista.
TEXTO_CANCELADO = (
    "Entendido, dejé la entrevista. Puedes escribir «quiero hacer el diagnóstico» "
    "cuando quieras retomarla."
)
#: Texto cuando la persona prefiere un asesor.
TEXTO_ASESOR = (
    "Listo, dejé tu solicitud para que un asesor te contacte. No necesito más datos por este canal."
)
#: Pregunta del HITL cuando el semáforo sale rojo.
PREGUNTA_HITL = (
    "Con estos datos el crédito aprieta tu presupuesto. ¿Quieres que un asesor "
    "revise tu caso? Puede ayudarte a ajustar el monto o el plazo."
)
#: Confirmación después de pulsar «Contactar».
TEXTO_CONTACTADO = (
    "Listo, un asesor revisará tu caso y te contactará por este canal. No necesito más datos."
)
#: Respuesta después de pulsar «Descartar».
TEXTO_DESCARTADO = "Listo, no envío tu caso a un asesor. Si cambias de idea, escribe «asesor»."
#: Recordatorio si hay un caso suspendido y el mensaje no elige.
TEXTO_RECORDAR_HITL = (
    "Tienes un caso pendiente con un asesor. Elige «Contactar» para que te "
    "contacten o «Descartar» para cerrarlo."
)
#: Respuesta a una reanudación sin hilo suspendido.
TEXTO_SIN_CASO = (
    "No tengo un caso pendiente para reanudar. Escribe «quiero hacer el "
    "diagnóstico» para empezar de nuevo o «asesor» si quieres que te contacten."
)
#: Identificador del botón que confirma el contacto con el asesor.
ID_CONTACTAR = "diagnostico.contactar"
#: Identificador del botón que descarta la asesoría.
ID_DESCARTAR = "diagnostico.descartar"
#: Texto cuando el mensaje no corresponde a ninguna opción.
TEXTO_NO_ENTENDI = "No alcancé a entender esa respuesta. Elige una de estas opciones."
#: Texto cuando el producto no tiene una tasa vigente publicada.
TEXTO_SIN_TASA = (
    "En este momento no tengo una tasa vigente para ese producto, así que no puedo "
    "calcular tu diagnóstico. Inténtalo más tarde o pregúntame por otra opción."
)
#: Tiempo durante el que se puede pedir un «¿Y si…?» sobre el último resultado.
VIGENCIA_RESULTADO = timedelta(hours=24)
#: Texto cuando el «¿Y si…?» no se puede recalcular (sin tasa vigente).
TEXTO_ESCENARIO_SIN_CALCULO = (
    "No pude recalcular ese «¿Y si…?» en este momento. Inténtalo más tarde o "
    "escribe «quiero hacer el diagnóstico» para empezar de nuevo."
)
#: Oferta de asesor que se agrega al resultado rojo sin comité.
OFERTA_ASESOR = "Puedes hablar con un asesor para revisar tu caso."

#: Frases que reinician la entrevista.
TEXTOS_NUEVO = frozenset({"nuevo", "reiniciar", "empezar de nuevo", "volver a empezar"})
#: Frases que cancelan la entrevista.
TEXTOS_CANCELAR = frozenset({"cancelar", "salir", "dejalo", "dejar"})
#: Frases con las que se pide un asesor.
TEXTOS_ASESOR = frozenset(
    {"asesor", "prefiero un asesor", "hablar con un asesor", "quiero un asesor"}
)
#: Frases con las que se confirma el contacto con el asesor.
TEXTOS_CONTACTAR = frozenset({"contactar", "contacten", "que me contacten"})
#: Frases con las que se descarta la asesoría.
TEXTOS_DESCARTAR = frozenset({"descartar", "no gracias"})

#: Pregunta del primer paso.
PREGUNTA_OBJETIVO = "¿Qué te gustaría revisar?"
#: Pregunta de la vinculación.
PREGUNTA_VINCULACION = "¿Cómo recibes tus ingresos?"
#: Instrucción breve que acompaña a la primera pregunta.
INTRO_DIAGNOSTICO = (
    "Vamos con tu diagnóstico financiero orientativo: no es una aprobación de crédito."
)


@dataclass(frozen=True, slots=True)
class OpcionEntrevista:
    """Una opción de la entrevista con su id canónico.

    ``titulo`` es el texto visible. En las listas no puede pasar de 24
    caracteres y en los botones de 20; ``descripcion`` solo la usan las filas
    de lista.
    """

    id: str
    titulo: str
    descripcion: str | None = None


@dataclass(frozen=True, slots=True)
class Paso:
    """Una pregunta de la entrevista con sus opciones."""

    clave: str
    pregunta: str
    opciones: tuple[OpcionEntrevista, ...]


@dataclass(frozen=True, slots=True)
class BloqueEntrevista:
    """Un bloque de rangos de ``config/diagnostico.toml``."""

    clave: str
    pregunta: str
    opciones: tuple[OpcionEntrevista, ...]
    aplica_a: frozenset[str]


@dataclass(frozen=True, slots=True)
class EstadoEntrevista:
    """El paso actual y los ids elegidos por un usuario."""

    paso: str
    respuestas: Mapping[str, str]
    actualizado_en: datetime


@dataclass(frozen=True, slots=True)
class Avance:
    """Resultado de procesar un turno de la entrevista.

    O hay otra pregunta (``respuesta``) o la entrevista terminó y ``respuestas``
    trae los ids elegidos. Nunca vienen las dos cosas a la vez.
    """

    respuesta: RespuestaCanal | None = None
    respuestas: Mapping[str, str] | None = None


#: Objetivos del diagnóstico, en el orden del guion.
OBJETIVOS: tuple[OpcionEntrevista, ...] = (
    OpcionEntrevista("objetivo.libre_inversion", "Libre inversión", "Préstamo de libre inversión"),
    OpcionEntrevista(
        "objetivo.compra_cartera",
        "Compra de cartera",
        "Pasar mis deudas a una mejor tasa",
    ),
    OpcionEntrevista("objetivo.vehiculo_nuevo", "Vehículo nuevo", "Comprar vehículo nuevo"),
    OpcionEntrevista("objetivo.vehiculo_usado", "Vehículo usado", "Comprar vehículo usado"),
    OpcionEntrevista("objetivo.vivienda", "Vivienda", "Comprar vivienda"),
    OpcionEntrevista("objetivo.libranza", "Libranza", "Crédito por libranza"),
    OpcionEntrevista("objetivo.ahorro", "Solo ahorrar", "Solo quiero ahorrar"),
)

#: Formas de vinculación, en el orden del guion.
VINCULACIONES: tuple[OpcionEntrevista, ...] = (
    OpcionEntrevista("vinculacion.empleado", "Empleado"),
    OpcionEntrevista("vinculacion.independiente", "Independiente"),
    OpcionEntrevista("vinculacion.pensionado", "Pensionado"),
)


def _normalizar(texto: str) -> str:
    """Pasa a minúsculas, quita tildes y signos y colapsa espacios.

    Args:
        texto: mensaje libre de la persona.

    Returns:
        El texto normalizado para comparar con los comandos.
    """
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    limpio = "".join(c if c.isalnum() or c.isspace() else " " for c in sin_tildes.casefold())
    return " ".join(limpio.split())


def cargar_bloques(ruta: Path | None = None) -> dict[str, BloqueEntrevista]:
    """Lee las preguntas y opciones de los rangos de la entrevista.

    Args:
        ruta: archivo TOML alternativo; por defecto
            ``config/diagnostico.toml``.

    Returns:
        Los bloques indexados por su clave, en el orden del archivo.

    Raises:
        FileNotFoundError: si el archivo no existe.
        KeyError: si un rango no declara su clave o una opción su id o texto.
    """
    archivo = Path(ruta) if ruta is not None else RUTA_CONFIG
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    bloques: dict[str, BloqueEntrevista] = {}
    for rango in datos.get("rango", []):
        clave = str(rango["clave"])
        opciones = tuple(
            OpcionEntrevista(id=str(opcion["id"]), titulo=str(opcion["texto"]))
            for opcion in rango.get("opcion", [])
        )
        bloques[clave] = BloqueEntrevista(
            clave=clave,
            pregunta=str(rango["pregunta"]),
            opciones=opciones,
            aplica_a=frozenset(str(producto) for producto in rango.get("aplica_a", [])),
        )
    return bloques


def _producto(respuestas: Mapping[str, str]) -> str | None:
    """Extrae el producto del id elegido en el paso del objetivo.

    Args:
        respuestas: ids canónicos ya guardados, indexados por paso.

    Returns:
        El producto (``libre_inversion``, ``ahorro``, …) o ``None`` si todavía
        no se respondió el objetivo.
    """
    ident = respuestas.get("objetivo", "")
    return ident.split(".", 1)[1] if "." in ident else None


def _sin_aviso(recomendacion: str, aviso: str) -> str:
    """Quita el aviso del final de la recomendación del comité.

    La tarjeta ya lleva su propio aviso; repetirlo en el mismo mensaje solo
    agrega ruido. Solo se recorta la aparición exacta al final.

    Args:
        recomendacion: texto sintetizado por el comité.
        aviso: aviso orientativo del resultado.

    Returns:
        La recomendación sin el aviso final.
    """
    if aviso and recomendacion.endswith(aviso):
        return recomendacion[: -len(aviso)].strip()
    return recomendacion.strip()


def _componer_texto(
    texto_tarjeta: str,
    resultado: ResultadoDiagnostico,
    deliberacion: comite.DeliberacionComite | None,
) -> str:
    """Inserta la recomendación del comité antes del aviso de la tarjeta.

    Args:
        texto_tarjeta: texto equivalente de la tarjeta de Pana.
        resultado: diagnóstico del motor.
        deliberacion: opinión del comité, o ``None`` si no se convocó.

    Returns:
        El texto que recibe la persona. Si excede los 4.096 caracteres, se
        devuelve el texto de la tarjeta, que siempre es más corto.
    """
    partes: list[str] = []
    if deliberacion is not None:
        partes.append(_sin_aviso(deliberacion.recomendacion, resultado.aviso))
    if resultado.semaforo == "rojo" and (deliberacion is None or not deliberacion.ofrece_asesor):
        partes.append(OFERTA_ASESOR)
    extra = "\n\n".join(parte for parte in partes if parte)
    if not extra:
        return texto_tarjeta

    corte = texto_tarjeta.rfind("\n\n_")
    if corte == -1:
        final = f"{texto_tarjeta}\n\n{extra}"
    else:
        final = f"{texto_tarjeta[:corte]}\n\n{extra}{texto_tarjeta[corte:]}"
    return final if len(final) <= 4096 else texto_tarjeta


def _texto_sin_tarjeta(resultado: ResultadoDiagnostico) -> str:
    """Escribe un texto de respaldo cuando la tarjeta no se puede generar.

    Args:
        resultado: diagnóstico del motor.

    Returns:
        Un resumen con el semáforo, la cuota, las recomendaciones y el aviso.
    """
    lineas: list[str] = []
    if resultado.semaforo is not None:
        lineas.append(f"Semáforo del diagnóstico: {resultado.semaforo}.")
    if resultado.cuota_mensual is not None:
        lineas.append(f"Cuota estimada: {formatear_rango(resultado.cuota_mensual)}.")
    lineas.extend(resultado.recomendaciones)
    lineas.append(resultado.aviso)
    return "\n".join(linea for linea in lineas if linea)


def _botones_hitl() -> list[BotonCanal]:
    """Botones de decisión del HITL, en el orden de `docs/DIAGNOSTICO.md`."""
    return [
        BotonCanal(id=ID_CONTACTAR, titulo="Contactar"),
        BotonCanal(id=ID_DESCARTAR, titulo="Descartar"),
    ]


@dataclass
class EntrevistaCanal:
    """Máquina de estados de la entrevista del diagnóstico.

    El avance vive en la tabla ``entrevistas`` del almacén del canal y vence a
    los ``ttl_minutos``. El modelo del comité y la fecha de la tasa se pueden
    inyectar para las pruebas; en producción se usan el modelo del comité y la
    fecha de hoy.
    """

    ruta: Path
    ttl_minutos: int = TTL_POR_DEFECTO
    modelo: BaseChatModel | None = None
    hoy: datetime | None = None
    raiz: Path | None = None
    reloj: Callable[[], datetime] = field(default_factory=lambda: lambda: datetime.now(UTC))
    _config: motor.ConfigDiagnostico | None = field(default=None, init=False, repr=False)
    _bloques: dict[str, BloqueEntrevista] | None = field(default=None, init=False, repr=False)
    _hitl: HitlAsesor = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Crea la tabla de entrevistas y prepara las cachés del catálogo."""
        inicializar_almacen(self.ruta)
        self._config = None
        self._bloques = None
        self._hitl = HitlAsesor(self.ruta)

    def _ajustes(self) -> motor.ConfigDiagnostico:
        """Carga y memoriza los umbrales y valores del motor."""
        if self._config is None:
            self._config = motor.cargar_config()
        return self._config

    def _catalogo(self) -> dict[str, BloqueEntrevista]:
        """Carga y memoriza las preguntas y opciones de la entrevista."""
        if self._bloques is None:
            self._bloques = cargar_bloques()
        return self._bloques

    def activa(self, usuario_id: str) -> bool:
        """Indica si el usuario tiene una entrevista vigente.

        Args:
            usuario_id: huella del número.

        Returns:
            ``True`` si hay un paso pendiente y no venció.
        """
        return self.leer(usuario_id) is not None

    def leer(self, usuario_id: str) -> EstadoEntrevista | None:
        """Recupera el avance del usuario y descarta el que venció.

        Args:
            usuario_id: huella del número.

        Returns:
            El paso y las respuestas, o ``None`` si no hay entrevista vigente.
        """
        with conectar(self.ruta) as conexion:
            fila = conexion.execute(
                "SELECT paso, respuestas_json, actualizado_en FROM entrevistas "
                "WHERE usuario_id = ?",
                (usuario_id,),
            ).fetchone()
        if fila is None:
            return None
        actualizado_en = datetime.fromisoformat(str(fila[2]))
        if actualizado_en.tzinfo is None:
            actualizado_en = actualizado_en.replace(tzinfo=UTC)
        if self.reloj() - actualizado_en >= timedelta(minutes=self.ttl_minutos):
            self.descartar(usuario_id)
            return None
        try:
            crudas = json.loads(str(fila[1]))
            respuestas = {str(clave): str(valor) for clave, valor in dict(crudas).items()}
        except (TypeError, ValueError):
            self.descartar(usuario_id)
            return None
        return EstadoEntrevista(
            paso=str(fila[0]),
            respuestas=respuestas,
            actualizado_en=actualizado_en,
        )

    def descartar(self, usuario_id: str) -> None:
        """Borra el avance del usuario sin tocar el resto del almacén.

        Args:
            usuario_id: huella del número.
        """
        with conectar(self.ruta) as conexion:
            conexion.execute("DELETE FROM entrevistas WHERE usuario_id = ?", (usuario_id,))

    def iniciar(self, usuario_id: str, id_mensaje: str) -> RespuestaCanal:
        """Arranca la entrevista y devuelve la primera pregunta.

        Args:
            usuario_id: huella del número.
            id_mensaje: id del mensaje que originó la respuesta.

        Returns:
            La pregunta del objetivo con sus opciones.
        """
        return self.reiniciar(usuario_id, id_mensaje)

    def reiniciar(self, usuario_id: str, id_mensaje: str) -> RespuestaCanal:
        """Borra el avance y vuelve a la primera pregunta.

        Args:
            usuario_id: huella del número.
            id_mensaje: id del mensaje que originó la respuesta.

        Returns:
            La pregunta del objetivo con sus opciones.
        """
        self._guardar(usuario_id, "objetivo", {})
        return self._pregunta(
            usuario_id,
            id_mensaje,
            self._pasos(None)[0],
            nota=INTRO_DIAGNOSTICO,
        )

    def avanzar(self, mensaje: MensajeEntrante, usuario_id: str) -> Avance:
        """Procesa un turno de una entrevista activa.

        Un botón o una fila con un id válido avanza al paso siguiente. Un texto
        libre repite la pregunta con sus opciones; ``nuevo`` reinicia,
        ``cancelar`` abandona y ``asesor`` abandona con una oferta de revisión.

        Args:
            mensaje: mensaje entrante del webhook.
            usuario_id: huella del número.

        Returns:
            La siguiente pregunta, o las respuestas cuando la entrevista
            terminó. Si no hay entrevista vigente, ``Avance`` vacío.
        """
        estado = self.leer(usuario_id)
        if estado is None:
            return Avance()

        if not mensaje.id_boton:
            comando = _normalizar(mensaje.texto)
            if comando in TEXTOS_NUEVO:
                return Avance(respuesta=self.reiniciar(usuario_id, mensaje.id_mensaje))
            if comando in TEXTOS_CANCELAR:
                self.descartar(usuario_id)
                return Avance(
                    respuesta=self._texto(usuario_id, mensaje.id_mensaje, TEXTO_CANCELADO)
                )
            if comando in TEXTOS_ASESOR:
                self.descartar(usuario_id)
                self._hitl.contactar_directo(usuario_id)
                return Avance(respuesta=self._texto(usuario_id, mensaje.id_mensaje, TEXTO_ASESOR))

        pasos = self._pasos(_producto(estado.respuestas))
        paso = next((candidato for candidato in pasos if candidato.clave == estado.paso), None)
        if paso is None:
            return Avance(respuesta=self.reiniciar(usuario_id, mensaje.id_mensaje))

        if mensaje.id_boton not in {opcion.id for opcion in paso.opciones}:
            return Avance(
                respuesta=self._pregunta(
                    usuario_id, mensaje.id_mensaje, paso, nota=TEXTO_NO_ENTENDI
                )
            )

        respuestas = dict(estado.respuestas)
        respuestas[paso.clave] = str(mensaje.id_boton)
        posicion = pasos.index(paso)
        siguiente = pasos[posicion + 1] if posicion + 1 < len(pasos) else None
        if siguiente is None:
            self.descartar(usuario_id)
            return Avance(respuestas=respuestas)

        self._guardar(usuario_id, siguiente.clave, respuestas)
        return Avance(respuesta=self._pregunta(usuario_id, mensaje.id_mensaje, siguiente))

    def completar(
        self,
        usuario_id: str,
        id_mensaje: str,
        respuestas: Mapping[str, str],
    ) -> RespuestaCanal:
        """Calcula el diagnóstico y arma la respuesta con su tarjeta.

        Convoca al comité solo en amarillo o rojo con cuota. Si el comité falla,
        responde con el diagnóstico sin comité. En rojo ofrece hablar con un
        asesor.

        Args:
            usuario_id: huella del número.
            id_mensaje: id del mensaje que originó la respuesta.
            respuestas: ids canónicos elegidos en la entrevista.

        Returns:
            La respuesta con el texto y, si se pudo generar, el PNG de Pana.
        """
        entrada = motor.entrada_desde_respuestas(respuestas, config=self._ajustes())
        try:
            resultado = motor.calcular(
                entrada,
                hoy=self.hoy.date() if self.hoy is not None else None,
                raiz=self.raiz,
                config=self._ajustes(),
            )
        except TasaNoDisponible:
            return self._texto(usuario_id, id_mensaje, TEXTO_SIN_TASA)
        self._guardar_resultado(usuario_id, resultado)
        deliberacion = self._deliberar(entrada, resultado)
        if resultado.semaforo == "rojo":
            return self._suspender_hitl(usuario_id, id_mensaje, resultado, deliberacion)
        try:
            png, texto_tarjeta = tarjeta_y_texto(resultado)
        except SinTarjeta:
            return self._texto(
                usuario_id,
                id_mensaje,
                _componer_texto(_texto_sin_tarjeta(resultado), resultado, deliberacion),
            )
        return RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=id_mensaje,
            texto=_componer_texto(texto_tarjeta, resultado, deliberacion),
            tipo="imagen",
            imagen=png,
        )

    def reanudar(self, mensaje: MensajeEntrante, usuario_id: str) -> RespuestaCanal | None:
        """Resuelve el turno si el hilo está suspendido en el HITL.

        El botón o el texto eligen entre contactar y descartar; cualquier otro
        mensaje repite los botones. «Cancelar» cierra el caso pendiente sin
        escalarlo.

        Args:
            mensaje: mensaje entrante del webhook.
            usuario_id: huella del número.

        Returns:
            La respuesta del HITL, o ``None`` si no hay un caso suspendido y el
            turno debe seguir su camino normal.
        """
        if not self._hitl.suspendido(usuario_id):
            comando = _normalizar(mensaje.texto) if not mensaje.id_boton else ""
            pide_hitl = (
                mensaje.id_boton in {ID_CONTACTAR, ID_DESCARTAR}
                or comando in TEXTOS_CONTACTAR
                or comando in TEXTOS_DESCARTAR
            )
            if pide_hitl:
                return self._texto(usuario_id, mensaje.id_mensaje, TEXTO_SIN_CASO)
            return None
        comando = _normalizar(mensaje.texto) if not mensaje.id_boton else ""
        if mensaje.id_boton == ID_CONTACTAR or comando in TEXTOS_CONTACTAR:
            return self._cerrar_hitl(mensaje, usuario_id, "contactar")
        if mensaje.id_boton == ID_DESCARTAR or comando in TEXTOS_DESCARTAR:
            return self._cerrar_hitl(mensaje, usuario_id, "descartar")
        if comando in TEXTOS_CANCELAR:
            self._hitl.limpiar(usuario_id)
            self.descartar(usuario_id)
            return self._texto(usuario_id, mensaje.id_mensaje, TEXTO_CANCELADO)
        return RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=mensaje.id_mensaje,
            texto=TEXTO_RECORDAR_HITL,
            tipo="botones",
            botones=_botones_hitl(),
        )

    def _suspender_hitl(
        self,
        usuario_id: str,
        id_mensaje: str,
        resultado: ResultadoDiagnostico,
        deliberacion: comite.DeliberacionComite | None,
    ) -> RespuestaCanal:
        """Suspende el turno en rojo y ofrece hablar con un asesor."""
        self._hitl.suspender(usuario_id, motivo=MOTIVO_ROJO, semaforo=resultado.semaforo or "rojo")
        try:
            _, texto_tarjeta = tarjeta_y_texto(resultado)
            detalle = _componer_texto(texto_tarjeta, resultado, deliberacion)
        except SinTarjeta:
            detalle = _componer_texto(_texto_sin_tarjeta(resultado), resultado, deliberacion)
        return RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=id_mensaje,
            texto=f"{detalle}\n\n{PREGUNTA_HITL}",
            tipo="botones",
            botones=_botones_hitl(),
        )

    def _cerrar_hitl(
        self,
        mensaje: MensajeEntrante,
        usuario_id: str,
        accion: AccionHitl,
    ) -> RespuestaCanal:
        """Reanuda el HITL, abre o descarta el caso y envía la tarjeta."""
        decision = self._hitl.reanudar(usuario_id, accion)
        if decision is None:
            return self._texto(usuario_id, mensaje.id_mensaje, TEXTO_SIN_CASO)
        cabecera = TEXTO_CONTACTADO if accion == "contactar" else TEXTO_DESCARTADO
        resultado = self.ultimo_resultado(usuario_id)
        if resultado is None:
            return self._texto(usuario_id, mensaje.id_mensaje, cabecera)
        try:
            png, texto = tarjeta_y_texto(resultado)
        except SinTarjeta:
            return self._texto(
                usuario_id,
                mensaje.id_mensaje,
                f"{cabecera}\n\n{_texto_sin_tarjeta(resultado)}",
            )
        return RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=mensaje.id_mensaje,
            texto=f"{cabecera}\n\n{texto}",
            tipo="imagen",
            imagen=png,
        )

    def escenario(self, mensaje: MensajeEntrante, usuario_id: str) -> RespuestaCanal | None:
        """Responde un «¿Y si…?» sobre el último diagnóstico de la persona.

        Args:
            mensaje: mensaje de texto, por ejemplo «¿y si lo pago en 60 meses?».
            usuario_id: huella del número.

        Returns:
            La tarjeta de antes y después con su texto, la explicación del
            límite si el cambio no cabe, o ``None`` si el mensaje no es un
            «¿Y si…?» o no hay un diagnóstico vigente (sigue hacia el grafo).
        """
        if mensaje.id_boton:
            return None
        cambio = interpretar_pedido(mensaje.texto)
        if cambio is None:
            return None
        original = self.ultimo_resultado(usuario_id)
        if original is None:
            return None
        try:
            _, comparacion = comparar_resultado(
                original,
                cambio,
                origen=f"wa:{usuario_id}",
                calcular=lambda entrada: motor.calcular(
                    entrada,
                    hoy=self.hoy.date() if self.hoy is not None else None,
                    raiz=self.raiz,
                    config=self._ajustes(),
                ),
            )
            png, texto = escenario_y_texto(comparacion, original.entrada.plazo_meses or 0)
        except EscenarioFueraDeRango as error:
            return self._texto(usuario_id, mensaje.id_mensaje, error.mensaje)
        except (TasaNoDisponible, ValueError):
            logger.warning("evento=escenario_sin_calculo")
            return self._texto(usuario_id, mensaje.id_mensaje, TEXTO_ESCENARIO_SIN_CALCULO)
        return RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=mensaje.id_mensaje,
            texto=texto,
            tipo="imagen",
            imagen=png,
        )

    def ultimo_resultado(self, usuario_id: str) -> ResultadoDiagnostico | None:
        """Devuelve el último diagnóstico vigente; si venció, lo borra.

        Args:
            usuario_id: huella del número.

        Returns:
            El resultado guardado, o ``None`` si no hay uno de las últimas 24 horas.
        """
        with conectar(self.ruta) as conexion:
            fila = conexion.execute(
                "SELECT resultado_json, guardado_en FROM resultados_diagnostico "
                "WHERE usuario_id = ?",
                (usuario_id,),
            ).fetchone()
        if fila is None:
            return None
        try:
            guardado = datetime.fromisoformat(str(fila[1]))
            if guardado.tzinfo is None:
                guardado = guardado.replace(tzinfo=UTC)
            vigente = self.reloj() - guardado < VIGENCIA_RESULTADO
            resultado = ResultadoDiagnostico.model_validate_json(str(fila[0])) if vigente else None
        except ValueError:
            resultado = None
        if resultado is None:
            self.olvidar_resultado(usuario_id)
        return resultado

    def olvidar_resultado(self, usuario_id: str) -> None:
        """Borra el último diagnóstico guardado de la persona.

        Args:
            usuario_id: huella del número.
        """
        with conectar(self.ruta) as conexion:
            conexion.execute(
                "DELETE FROM resultados_diagnostico WHERE usuario_id = ?", (usuario_id,)
            )

    def purgar_vencidos(self, momento: datetime | None = None) -> int:
        """Borra las entrevistas y los resultados que ya vencieron.

        La app la llama al arrancar, sobre la misma instancia que usa el
        despachador. Sin esta purga, una entrevista abandonada o un resultado
        que nadie vuelve a consultar quedarían en la base más allá de los plazos
        que promete el aviso: ``ttl_minutos`` sin actividad para la entrevista y
        24 horas para el resultado.

        Args:
            momento: instante de referencia; por defecto ahora en UTC.

        Returns:
            Cuántas filas se borraron entre las dos tablas.
        """
        ahora = momento or datetime.now(UTC)
        limite_entrevistas = (ahora - timedelta(minutes=self.ttl_minutos)).isoformat()
        limite_resultados = (ahora - VIGENCIA_RESULTADO).isoformat()
        with conectar(self.ruta) as conexion:
            entrevistas = conexion.execute(
                "DELETE FROM entrevistas WHERE actualizado_en < ?",
                (limite_entrevistas,),
            ).rowcount
            resultados = conexion.execute(
                "DELETE FROM resultados_diagnostico WHERE guardado_en < ?",
                (limite_resultados,),
            ).rowcount
        return entrevistas + resultados

    def _guardar_resultado(self, usuario_id: str, resultado: ResultadoDiagnostico) -> None:
        """Guarda el resultado para un «¿Y si…?» posterior; no lleva el número.

        Args:
            usuario_id: huella del número.
            resultado: diagnóstico recién calculado.
        """
        with conectar(self.ruta) as conexion:
            conexion.execute(
                "INSERT INTO resultados_diagnostico (usuario_id, resultado_json, guardado_en) "
                "VALUES (?, ?, ?) ON CONFLICT(usuario_id) DO UPDATE SET "
                "resultado_json = excluded.resultado_json, guardado_en = excluded.guardado_en",
                (usuario_id, resultado.model_dump_json(), self.reloj().isoformat()),
            )

    def _deliberar(
        self,
        entrada: EntradaDiagnostico,
        resultado: ResultadoDiagnostico,
    ) -> comite.DeliberacionComite | None:
        """Convoca al comité y, si falla, sigue sin él.

        Args:
            entrada: entrada del diagnóstico ya validada.
            resultado: resultado del motor.

        Returns:
            La deliberación, o ``None`` en verde, sin cuota o si el comité falla.
        """
        if resultado.semaforo not in {"amarillo", "rojo"} or resultado.cuota_mensual is None:
            return None
        try:
            deliberacion = comite.deliberar(
                entrada,
                resultado,
                modelo=self.modelo,
                hoy=self.hoy.date() if self.hoy is not None else None,
                raiz=self.raiz,
            )
        except Exception:
            logger.exception("el comité no pudo deliberar; se responde con el diagnóstico")
            return None
        if deliberacion is None:
            return None
        if all(postura.postura == "abstencion" for postura in deliberacion.posturas):
            # Sin ninguna postura no hay recomendación que mostrar: se responde
            # con el diagnóstico, igual que si el comité hubiera fallado.
            return None
        return deliberacion

    def _pasos(self, producto: str | None) -> list[Paso]:
        """Arma la secuencia de preguntas para el producto elegido.

        Args:
            producto: clave del producto, o ``None`` si falta el objetivo.

        Returns:
            Los pasos en el orden del guion. En ahorro se omiten monto y plazo;
            ``cuota_trasladar`` solo aparece en compra de cartera.
        """
        pasos = [
            Paso("objetivo", PREGUNTA_OBJETIVO, OBJETIVOS),
            Paso("vinculacion", PREGUNTA_VINCULACION, VINCULACIONES),
        ]
        pasos.extend(self._paso_rango(clave) for clave in ("ingresos", "gastos", "cuotas"))
        if producto is None:
            return pasos
        if producto == "compra_cartera":
            pasos.append(self._paso_rango("cuota_trasladar"))
        if producto != "ahorro":
            pasos.append(self._paso_monto(producto))
            pasos.append(self._paso_plazo(producto))
        return pasos

    def _paso_rango(self, clave: str) -> Paso:
        """Convierte un bloque del TOML en un paso de la entrevista.

        Args:
            clave: clave del bloque (``ingresos``, ``cuotas``, …).

        Returns:
            El paso con su pregunta y sus opciones.

        Raises:
            KeyError: si el bloque no existe en el TOML.
        """
        bloque = self._catalogo()[clave]
        return Paso(bloque.clave, bloque.pregunta, bloque.opciones)

    def _paso_monto(self, producto: str) -> Paso:
        """Elige el bloque de monto que aplica al producto.

        Args:
            producto: clave del producto.

        Returns:
            El paso del monto con las opciones del producto.

        Raises:
            ValueError: si no hay bloque de monto para el producto.
        """
        for clave, bloque in self._catalogo().items():
            if (clave == "monto" or clave.startswith("monto_")) and producto in bloque.aplica_a:
                return Paso("monto", bloque.pregunta, bloque.opciones)
        raise ValueError(f"«{producto}» no tiene opciones de monto")

    def _paso_plazo(self, producto: str) -> Paso:
        """Elige el bloque de plazo que aplica al producto.

        Args:
            producto: clave del producto.

        Returns:
            El paso del plazo con las opciones del producto.

        Raises:
            ValueError: si no hay bloque de plazo para el producto.
        """
        for clave, bloque in self._catalogo().items():
            if (clave == "plazo" or clave.startswith("plazo_")) and producto in bloque.aplica_a:
                return Paso("plazo", bloque.pregunta, bloque.opciones)
        raise ValueError(f"«{producto}» no tiene opciones de plazo")

    def _guardar(self, usuario_id: str, paso: str, respuestas: Mapping[str, str]) -> None:
        """Guarda el paso actual y los ids elegidos, sin texto libre.

        Args:
            usuario_id: huella del número.
            paso: clave de la pregunta que se está haciendo.
            respuestas: ids canónicos ya elegidos.
        """
        with conectar(self.ruta) as conexion:
            conexion.execute(
                "INSERT INTO entrevistas "
                "(usuario_id, paso, respuestas_json, actualizado_en) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(usuario_id) DO UPDATE SET "
                "paso = excluded.paso, "
                "respuestas_json = excluded.respuestas_json, "
                "actualizado_en = excluded.actualizado_en",
                (
                    usuario_id,
                    paso,
                    json.dumps(dict(respuestas), ensure_ascii=False, sort_keys=True),
                    self.reloj().isoformat(),
                ),
            )

    def _pregunta(
        self,
        usuario_id: str,
        id_mensaje: str,
        paso: Paso,
        *,
        nota: str = "",
    ) -> RespuestaCanal:
        """Arma la respuesta de una pregunta con botones o lista.

        Usa botones si hay tres opciones o menos y todos los títulos caben en
        20 caracteres; en los demás casos usa una lista de hasta diez filas.

        Args:
            usuario_id: huella del número.
            id_mensaje: id del mensaje que originó la respuesta.
            paso: pregunta que se está haciendo.
            nota: línea que se agrega antes de la pregunta, por ejemplo cuando
                la respuesta anterior no correspondía.

        Returns:
            La respuesta con el texto y las opciones.
        """
        texto = f"{nota}\n\n{paso.pregunta}" if nota else paso.pregunta
        if len(paso.opciones) <= 3 and all(len(opcion.titulo) <= 20 for opcion in paso.opciones):
            return RespuestaCanal(
                usuario_id=usuario_id,
                id_mensaje_origen=id_mensaje,
                texto=texto,
                tipo="botones",
                botones=[
                    BotonCanal(id=opcion.id, titulo=opcion.titulo) for opcion in paso.opciones
                ],
            )
        return RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=id_mensaje,
            texto=texto,
            tipo="lista",
            opciones=[
                OpcionLista(
                    id=opcion.id,
                    titulo=opcion.titulo[:24],
                    descripcion=opcion.descripcion,
                )
                for opcion in paso.opciones
            ],
        )

    @staticmethod
    def _texto(usuario_id: str, id_mensaje: str, texto: str) -> RespuestaCanal:
        """Construye una respuesta de texto simple.

        Args:
            usuario_id: huella del número.
            id_mensaje: id del mensaje que originó la respuesta.
            texto: cuerpo de la respuesta.

        Returns:
            La respuesta de tipo texto.
        """
        return RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=id_mensaje,
            texto=texto,
        )
