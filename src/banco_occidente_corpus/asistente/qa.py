"""Q&A del asistente: contexto completo, temperatura 0 y validacion posterior.

El contexto va entre ``<contexto>`` y ``</contexto>`` al inicio del mensaje de
sistema; las reglas clave se repiten despues del contexto y la pregunta va entre
``<pregunta>`` y ``</pregunta>``. La respuesta se valida antes de mostrarla.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from .contexto_prompt import ContextoPrompt
from .metricas import extraer_metricas
from .prompts import Prompt
from .validacion import (
    FRASE_SIN_DATOS,
    LIMITE_QA,
    cifras_inventadas,
    contar_palabras,
    detectar_fuga_prompt,
    detectar_pii,
    limitar_palabras,
    limpiar_respuesta,
    mensaje_pii,
    respuesta_sin_datos,
    sanear_pregunta,
    texto_de_contenido,
    validar_fuente,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


@dataclass(frozen=True, slots=True)
class RespuestaQA:
    """Respuesta validada del Q&A."""

    texto: str
    fuente: str
    sin_datos: bool
    avisos: tuple[str, ...] = ()
    metricas: dict[str, Any] = field(default_factory=dict)

    @property
    def palabras(self) -> int:
        """Numero de palabras de la respuesta final."""
        return contar_palabras(self.texto)


def construir_mensajes(
    prompt: Prompt,
    contexto: ContextoPrompt,
    pregunta: str,
) -> list[BaseMessage]:
    """Arma sistema (contexto + reglas) y humano (recordatorio + pregunta)."""
    sistema = f"<contexto>\n{contexto.texto}\n</contexto>\n\n{prompt.sistema}"
    recordatorio = prompt.recordatorio or "Responde solo con el contexto y cita la fuente."
    humano = (
        f"<reglas_clave>\n{recordatorio}\n</reglas_clave>\n\n<pregunta>\n{pregunta}\n</pregunta>"
    )
    return [SystemMessage(content=sistema), HumanMessage(content=humano)]


def _fallback(
    contexto: ContextoPrompt,
    aviso: str,
    metricas: dict[str, Any] | None = None,
) -> RespuestaQA:
    """Respuesta segura cuando el modelo no cumple el contrato."""
    canal = contexto.canal
    return RespuestaQA(
        texto=respuesta_sin_datos(canal),
        fuente=canal.url if canal else "",
        sin_datos=True,
        avisos=(aviso,),
        metricas=metricas or {},
    )


def responder(
    modelo: BaseChatModel,
    prompt: Prompt,
    contexto: ContextoPrompt,
    pregunta: str,
) -> RespuestaQA:
    """Responde una pregunta con el contexto y valida fuente, cifras y PII."""
    pregunta_limpia = sanear_pregunta(pregunta)
    permitidos = contexto.canal.telefonos if contexto.canal else ()
    deteccion = detectar_pii(pregunta_limpia, permitidos=permitidos)
    if deteccion:
        return RespuestaQA(
            texto=mensaje_pii(deteccion.categoria, contexto.canal),
            fuente=contexto.canal.url if contexto.canal else "",
            sin_datos=False,
            avisos=("pii_bloqueada",),
        )

    respuesta = modelo.invoke(construir_mensajes(prompt, contexto, pregunta_limpia))
    metricas = extraer_metricas(respuesta)
    texto = limpiar_respuesta(texto_de_contenido(respuesta.content))

    if not texto or FRASE_SIN_DATOS in texto:
        return _fallback(contexto, "sin_datos", metricas)

    fuente = validar_fuente(texto, contexto.urls)
    if not fuente:
        return _fallback(contexto, "fuente_invalida", metricas)

    if cifras_inventadas(texto, contexto.texto):
        return _fallback(contexto, "cifra_inventada", metricas)

    if detectar_fuga_prompt(texto):
        return _fallback(contexto, "fuga_prompt", metricas)

    if detectar_pii(texto, permitidos=permitidos):
        return _fallback(contexto, "pii_en_respuesta", metricas)

    texto, recortado = limitar_palabras(texto, LIMITE_QA)
    avisos: list[str] = []
    if recortado:
        avisos.append("recortado")

    if fuente and validar_fuente(texto, contexto.urls) is None:
        texto, _ = limitar_palabras(f"{texto}\nFuente: {fuente}", LIMITE_QA)

    return RespuestaQA(
        texto=texto,
        fuente=validar_fuente(texto, contexto.urls) or fuente,
        sin_datos=False,
        avisos=tuple(avisos),
        metricas=metricas,
    )
