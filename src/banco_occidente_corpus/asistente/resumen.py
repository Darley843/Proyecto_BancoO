"""Resumen ejecutivo del corpus, con fuentes verificadas contra el contexto."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from .contexto_prompt import ContextoPrompt
from .metricas import diagnostico_respuesta_vacia, extraer_metricas
from .prompts import Prompt
from .validacion import (
    LIMITE_RESUMEN,
    cifras_duras,
    cifras_inventadas,
    contar_palabras,
    detectar_fuga_prompt,
    detectar_pii,
    extraer_urls_texto,
    limitar_resumen,
    limpiar_respuesta,
    separar_fuentes,
    texto_de_contenido,
    url_en_contexto,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


@dataclass(frozen=True, slots=True)
class RespuestaResumen:
    """Resumen validado y sus fuentes."""

    texto: str
    fuentes: tuple[str, ...]
    avisos: tuple[str, ...] = ()
    metricas: dict[str, Any] = field(default_factory=dict)

    @property
    def palabras(self) -> int:
        """Numero de palabras del resumen final."""
        return contar_palabras(self.texto)


class ResumenInvalido(RuntimeError):
    """El resumen no cumple el contrato tras el reintento."""

    def __init__(self, errores: list[str]) -> None:
        self.errores = errores
        super().__init__("; ".join(errores) or "Resumen invalido")


def construir_mensajes_resumen(
    prompt: Prompt,
    contexto: ContextoPrompt,
    tema: str = "",
) -> list[BaseMessage]:
    """Arma el mensaje de sistema con el contexto y el humano con la tarea."""
    sistema = f"<contexto>\n{contexto.texto}\n</contexto>\n\n{prompt.sistema}"
    recordatorio = prompt.recordatorio or (
        "Resume solo con el contexto y cierra con Fuentes: y URLs exactas."
    )
    humano = f"<reglas_clave>\n{recordatorio}\n</reglas_clave>\n\n"
    if tema.strip():
        humano += f"Enfoca el resumen en: {tema.strip()}\n\n"
    humano += "Redacta ahora el resumen ejecutivo."
    return [SystemMessage(content=sistema), HumanMessage(content=humano)]


def validar_resumen(
    texto: str,
    contexto: ContextoPrompt,
) -> tuple[list[str], tuple[str, ...]]:
    """Comprueba fuentes, cifras, PII y fuga del prompt en el resumen."""
    errores: list[str] = []
    cuerpo, bloque_fuentes = separar_fuentes(texto)
    if not cuerpo:
        errores.append("el resumen esta vacio")

    fuentes = extraer_urls_texto(bloque_fuentes)
    if not fuentes:
        errores.append("falta el bloque 'Fuentes:' con URLs")
    for url in fuentes:
        if not url_en_contexto(url, contexto.urls):
            errores.append(f"fuente fuera del contexto: {url}")

    permitidos = contexto.canal.telefonos if contexto.canal else ()
    if cifras_inventadas(cuerpo, cifras_contexto=cifras_duras(contexto.texto)):
        errores.append("cifras no presentes en el contexto")
    if detectar_fuga_prompt(cuerpo):
        errores.append("la respuesta revela instrucciones internas")
    if detectar_pii(texto, permitidos=permitidos):
        errores.append("datos personales en el resumen")

    return errores, fuentes


def generar_resumen(
    modelo: BaseChatModel,
    prompt: Prompt,
    contexto: ContextoPrompt,
    tema: str = "",
) -> RespuestaResumen:
    """Genera el resumen y lo reintenta una vez si no cumple el contrato.

    Si el modelo devuelve contenido vacio (por ejemplo, porque el razonamiento
    agoto ``max_tokens``), el error informa ``finish_reason`` y los tokens de
    razonamiento en lugar de un mensaje generico.
    """
    mensajes = construir_mensajes_resumen(prompt, contexto, tema)
    errores: list[str] = []

    for _ in range(2):
        respuesta = modelo.invoke(mensajes)
        metricas = extraer_metricas(respuesta)
        texto = limpiar_respuesta(texto_de_contenido(respuesta.content))

        if not texto:
            errores = [diagnostico_respuesta_vacia(metricas)]
        else:
            errores, fuentes = validar_resumen(texto, contexto)
            if not errores:
                texto, recortado = limitar_resumen(texto, LIMITE_RESUMEN)
                avisos = ("recortado",) if recortado else ()
                return RespuestaResumen(
                    texto=texto,
                    fuentes=fuentes,
                    avisos=avisos,
                    metricas=metricas,
                )

        mensajes = [
            *mensajes,
            HumanMessage(
                content=(
                    "El resumen anterior no cumple: "
                    + "; ".join(errores)
                    + ". Corrige y cierra con 'Fuentes:' y URLs exactas del contexto."
                )
            ),
        ]

    raise ResumenInvalido(errores)
