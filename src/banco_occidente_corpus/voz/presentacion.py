"""Presentación fija de Pana, igual en WhatsApp y en la app web.

Es la respuesta a «preséntate» o «¿quién eres?». Es fija a propósito: no pasa
por el modelo, así que dice siempre lo mismo, no gasta y no tiene datos de la
persona. Por eso el despachador la atiende antes del consentimiento: no
procesa datos personales.
"""

from __future__ import annotations

import re
import unicodedata

#: Lo que dice Pana al presentarse (texto y nota de voz).
TEXTO_PRESENTACION = (
    "¡Hola! Soy Pana, el asistente del Banco de Occidente para jóvenes que van a "
    "pedir su primer crédito. Te ayudo en tres cosas. Primero, respondo tus "
    "preguntas sobre productos y tasas con la información que el banco publica. "
    "Segundo, te hago un diagnóstico financiero: te pregunto por rangos tus "
    "ingresos, gastos y cuotas, y te muestro con un semáforo si la cuota te cabe. "
    "Tercero, puedes preguntarme «¿y si lo pago en más meses?» y te comparo los "
    "dos escenarios. Antes de empezar te pido permiso para tratar tus datos, y "
    "con «olvida mis datos» los borro. Soy una orientación, no una aprobación del "
    "crédito: la decisión final la toma el banco. ¿Empezamos?"
)

#: Mensajes cortos que piden la presentación, ya sin tildes ni signos.
_PEDIDO = re.compile(
    r"^(?:hola\s+)?(?:pana\s*)?(?:presentate|quien eres|que eres|quien es pana|que es pana)"
    r"(?:\s+pana)?(?:\s+al\s+publico)?$"
)

#: Más largo que esto ya no es un pedido de presentación sino una pregunta.
LARGO_MAXIMO_PEDIDO = 60


def _normalizar(texto: str) -> str:
    """Quita tildes, signos y espacios de más, y pasa a minúsculas."""
    sin_tildes = "".join(
        letra
        for letra in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(letra) != "Mn"
    )
    solo_letras = re.sub(r"[^a-z0-9ñ ]+", " ", sin_tildes)
    return " ".join(solo_letras.split())


def es_pedido_de_presentacion(texto: str | None) -> bool:
    """Indica si el mensaje pide que Pana se presente.

    Args:
        texto: texto del mensaje; ``None`` si fue un botón o un adjunto.

    Returns:
        True para «preséntate», «¿quién eres?», «Pana, preséntate al público»
        y variantes cortas; False para cualquier otra pregunta.
    """
    if not texto or len(texto) > LARGO_MAXIMO_PEDIDO:
        return False
    return bool(_PEDIDO.match(_normalizar(texto)))
