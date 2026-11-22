"""Consentimiento de la Ley 1581 antes de invocar el grafo.

La primera interacción de un número autorizado recibe el aviso y dos botones:
«Acepto» y «Ahora no». Sin aceptación el despachador no invoca el grafo ni crea
perfil; el estado queda en ``consentimientos`` y la versión del aviso se guarda
para poder auditar qué texto se aceptó.

«Olvida mis datos» revoca la autorización y borra los datos del diagnóstico:
los casos, el avance de la entrevista, el último resultado guardado para el
«¿Y si…?», el hilo suspendido del HITL y el perfil del store. La fila del
consentimiento **no se borra**: queda con ``revocado_en`` como prueba de la
autorización (Decreto 1377 de 2013, art. 8); solo guarda la huella, la versión
del aviso y las fechas. El id de deduplicación se conserva porque no contiene
datos personales.

El plazo máximo del aviso (``retencion_dias``, 30 por defecto) sigue siendo
cierto: la entrevista se purga a los ``entrevista_ttl_minutos`` sin actividad y
el último resultado a las 24 horas, ambos por debajo de ese máximo.

El aviso cumple el deber de informar (Ley 1581 de 2012, art. 12): responsable,
datos que se tratan, finalidad, a quién se comparten (el asesor del equipo y el
proveedor de IA, DeepSeek, que procesa fuera de Colombia: transferencia
internacional del art. 26), conservación, derechos del titular y cómo
ejercerlos.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from .almacen import conectar, inicializar_almacen
from .contratos import BotonCanal, MensajeEntrante, RespuestaCanal
from .hitl import limpiar_hilo

#: El usuario todavía no aceptó el aviso.
ESTADO_SIN_CONSENTIMIENTO = "sin_consentimiento"

#: El usuario aceptó la versión vigente del aviso.
ESTADO_ACEPTADO = "aceptado"

EstadoConsentimiento = Literal["sin_consentimiento", "aceptado"]

#: Lo que el usuario respondió al aviso.
Decision = Literal["acepto", "rechazo", "silencio"]

#: Versión por defecto del aviso; `config/whatsapp.toml` puede cambiarla.
VERSION_POR_DEFECTO = "2026-11"

#: Días que se conservan los casos si `config/whatsapp.toml` no dice otra cosa.
RETENCION_POR_DEFECTO = 30

#: Límite de caracteres del cuerpo de un mensaje interactivo de WhatsApp.
LARGO_MAXIMO_AVISO = 1024


def texto_aviso(retencion_dias: int = RETENCION_POR_DEFECTO) -> str:
    """Arma el aviso de privacidad con el plazo de conservación configurado.

    Args:
        retencion_dias: días que se conservan los datos del diagnóstico.

    Returns:
        El aviso completo que exige la Ley 1581 de 2012 (art. 12).
    """
    return (
        "Proyecto académico de la Universidad Autónoma de Occidente; no es un canal "
        "oficial del Banco de Occidente. Responsable: equipo Sucursal 1965 (UAO). "
        "Para orientarte trataremos tu nombre (opcional), tu rol, los rangos de "
        "ingresos, gastos y deudas que elijas y el resultado del diagnóstico; si lo "
        "pides, lo verá un asesor del equipo. Algunas respuestas las redacta un "
        "proveedor externo de inteligencia artificial (DeepSeek), con servidores fuera "
        "de Colombia: le enviamos solo el texto necesario para responder, nunca tu "
        "número. No guardamos tu número, solo una "
        f"huella cifrada, y conservamos los datos máximo {retencion_dias} días. "
        "Puedes conocer, actualizar, rectificar o suprimir tus datos escribiendo "
        "aquí, y revocar esta autorización con «olvida mis datos». "
        "¿Autorizas el tratamiento de tus datos (Ley 1581 de 2012)?"
    )


#: Texto del aviso con la conservación por defecto.
AVISO = texto_aviso()

#: Identificadores de los botones del aviso.
ID_ACEPTO = "consent:acepto"
ID_RECHAZO = "consent:rechazo"

#: Palabras que cuentan como aceptación o rechazo por texto libre.
#:
#: Solo cuentan las que nombran el acto de autorizar. Un «sí» suelto puede estar
#: respondiendo a cualquier otra pregunta y no sirve como autorización previa,
#: expresa e informada (Ley 1581 de 2012, art. 9); los botones del aviso siguen
#: siendo la vía principal.
TEXTOS_ACEPTO = frozenset({"acepto", "si acepto", "autorizo", "si autorizo"})
TEXTOS_RECHAZO = frozenset({"no acepto", "ahora no", "no autorizo", "no"})
TEXTOS_REVOCACION = frozenset({"olvida mis datos", "borra mis datos", "elimina mis datos"})


def _normalizar(texto: str) -> str:
    """Pasa a minúsculas, quita tildes y signos y colapsa espacios."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in descompuesto if not unicodedata.combining(c))
    limpio = "".join(c if c.isalnum() or c.isspace() else " " for c in sin_tildes.casefold())
    return " ".join(limpio.split())


def interpretar(mensaje: MensajeEntrante) -> Decision:
    """Clasifica la respuesta al aviso como acepto, rechazo o silencio.

    Args:
        mensaje: mensaje normalizado del webhook.

    Returns:
        La decisión; cualquier texto distinto de los reconocidos es ``silencio``.
    """
    if mensaje.id_boton == ID_ACEPTO:
        return "acepto"
    if mensaje.id_boton == ID_RECHAZO:
        return "rechazo"

    texto = _normalizar(mensaje.texto)
    if texto in TEXTOS_ACEPTO:
        return "acepto"
    if texto in TEXTOS_RECHAZO:
        return "rechazo"
    return "silencio"


def es_revocacion(mensaje: MensajeEntrante) -> bool:
    """Indica si el mensaje pide borrar los datos del usuario."""
    return _normalizar(mensaje.texto) in TEXTOS_REVOCACION


@dataclass
class MaquinaConsentimiento:
    """Estado de consentimiento de los usuarios del canal.

    Attributes:
        ruta: base `whatsapp.sqlite` del canal.
        version: versión vigente del aviso de la Ley 1581.
        retencion_dias: plazo de conservación de los casos del asesor.
        borrar_perfil: callback que borra el perfil de la persona; si falta, la
            revocación solo limpia las tablas del canal.
    """

    ruta: Path
    version: str = VERSION_POR_DEFECTO
    retencion_dias: int = RETENCION_POR_DEFECTO
    borrar_perfil: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        """Crea el almacén y sus tablas si no existen."""
        inicializar_almacen(self.ruta)

    def estado(self, usuario_id: str) -> EstadoConsentimiento:
        """Devuelve si el usuario aceptó el aviso vigente.

        Args:
            usuario_id: huella del número, nunca el número.

        Returns:
            ``aceptado`` si hay fila sin revocar; ``sin_consentimiento`` si no.
        """
        with conectar(self.ruta) as conexion:
            fila = conexion.execute(
                "SELECT revocado_en, version FROM consentimientos WHERE usuario_id = ?",
                (usuario_id,),
            ).fetchone()
        if fila is None or fila[0] or fila[1] != self.version:
            return ESTADO_SIN_CONSENTIMIENTO
        return ESTADO_ACEPTADO

    def aceptar(self, usuario_id: str, momento: datetime | None = None) -> None:
        """Registra la aceptación con la versión vigente del aviso.

        Args:
            usuario_id: huella del número.
            momento: instante de la aceptación; por defecto ahora en UTC.
        """
        instante = (momento or datetime.now(UTC)).isoformat()
        with conectar(self.ruta) as conexion:
            conexion.execute(
                "INSERT INTO consentimientos (usuario_id, version, aceptado_en, revocado_en) "
                "VALUES (?, ?, ?, NULL) "
                "ON CONFLICT(usuario_id) DO UPDATE SET "
                "version = excluded.version, aceptado_en = excluded.aceptado_en, revocado_en = NULL",
                (usuario_id, self.version, instante),
            )

    def revocar(self, usuario_id: str, momento: datetime | None = None) -> None:
        """Revoca la autorización y borra los datos del diagnóstico.

        Borra los casos, el avance de la entrevista, el último resultado del
        «¿Y si…?», el hilo suspendido del HITL y el perfil del store. La fila del
        consentimiento se conserva con ``revocado_en`` como prueba de la
        autorización (Decreto 1377 de 2013, art. 8). No contiene datos
        personales: solo la huella, la versión del aviso y las fechas.

        Args:
            usuario_id: huella del número.
            momento: instante de la revocación; por defecto ahora en UTC.
        """
        instante = (momento or datetime.now(UTC)).isoformat()
        with conectar(self.ruta) as conexion:
            conexion.execute(
                "UPDATE consentimientos SET revocado_en = ? "
                "WHERE usuario_id = ? AND revocado_en IS NULL",
                (instante, usuario_id),
            )
            conexion.execute("DELETE FROM casos WHERE usuario_id = ?", (usuario_id,))
            conexion.execute("DELETE FROM entrevistas WHERE usuario_id = ?", (usuario_id,))
            conexion.execute(
                "DELETE FROM resultados_diagnostico WHERE usuario_id = ?", (usuario_id,)
            )
        limpiar_hilo(self.ruta, usuario_id)
        if self.borrar_perfil is not None:
            self.borrar_perfil(usuario_id)

    def purgar_casos_vencidos(self, momento: datetime | None = None) -> int:
        """Borra los casos más viejos que el plazo de conservación del aviso.

        El despachador la llama al arrancar; así el aviso no promete un plazo
        que el código no cumple. Los consentimientos no se purgan: son la
        prueba de la autorización.

        Args:
            momento: instante de referencia; por defecto ahora en UTC.

        Returns:
            Cuántos casos se borraron.
        """
        limite = ((momento or datetime.now(UTC)) - timedelta(days=self.retencion_dias)).isoformat()
        with conectar(self.ruta) as conexion:
            cursor = conexion.execute("DELETE FROM casos WHERE creado_en < ?", (limite,))
            return cursor.rowcount

    def aviso(self, usuario_id: str, id_mensaje: str) -> RespuestaCanal:
        """Construye el aviso con los botones «Acepto» y «Ahora no».

        Args:
            usuario_id: huella del número.
            id_mensaje: id del mensaje que originó la respuesta.

        Returns:
            Respuesta con dos botones.
        """
        return RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=id_mensaje,
            texto=texto_aviso(self.retencion_dias),
            tipo="botones",
            botones=[
                BotonCanal(id=ID_ACEPTO, titulo="Acepto"),
                BotonCanal(id=ID_RECHAZO, titulo="Ahora no"),
            ],
        )

    def decidir(self, mensaje: MensajeEntrante, usuario_id: str) -> RespuestaCanal | None:
        """Resuelve el turno de consentimiento antes de llamar al grafo.

        Args:
            mensaje: mensaje entrante ya validado.
            usuario_id: huella del número que envió el mensaje.

        Returns:
            La respuesta del canal, o ``None`` si hay consentimiento vigente y
            el despachador debe seguir con el grafo.
        """
        if es_revocacion(mensaje):
            self.revocar(usuario_id)
            return self._respuesta(
                usuario_id,
                mensaje.id_mensaje,
                "Listo, revoqué tu autorización y borré los datos de tu diagnóstico. "
                "Si quieres volver a empezar, escribe «hola».",
            )

        if self.estado(usuario_id) == ESTADO_ACEPTADO:
            return None

        decision = interpretar(mensaje)
        if decision == "acepto":
            self.aceptar(usuario_id)
            return self._respuesta(
                usuario_id,
                mensaje.id_mensaje,
                "Gracias. Ya puedes preguntarme por tasas, tarifas o tu diagnóstico.",
            )
        if decision == "rechazo":
            return self._respuesta(
                usuario_id,
                mensaje.id_mensaje,
                "Entendido, no guardaré tus datos. Si cambias de opinión, escribe «hola».",
            )
        return self.aviso(usuario_id, mensaje.id_mensaje)

    @staticmethod
    def _respuesta(usuario_id: str, id_mensaje: str, texto: str) -> RespuestaCanal:
        """Construye una respuesta de texto simple."""
        return RespuestaCanal(
            usuario_id=usuario_id,
            id_mensaje_origen=id_mensaje,
            texto=texto,
        )
