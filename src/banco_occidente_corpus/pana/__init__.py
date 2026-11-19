"""Pana: el personaje del corresponsal y sus tarjetas con imagen.

Pana es el asistente de un proyecto académico de la UAO, no del Banco de
Occidente. Las tarjetas **acompañan** al texto de la respuesta, nunca lo
reemplazan: el texto lleva los mismos datos, para accesibilidad, para el
Arqueo y por si la imagen no llega. Las imágenes se generan en memoria, no
llevan nombre ni número de la persona y no se guardan en disco.
"""

from __future__ import annotations

from .personaje import EXPRESIONES, Expresion, dibujar_pana, foto_de_perfil, insignia
from .tarjetas import (
    AVISO,
    DatosAhorro,
    DatosDiagnostico,
    DatosEscenario,
    DatosNoAplica,
    FotoEscenario,
    TasaCaptacion,
    tarjeta_ahorro,
    tarjeta_diagnostico,
    tarjeta_escenario,
    tarjeta_no_aplica,
    texto_ahorro,
    texto_diagnostico,
    texto_escenario,
    texto_no_aplica,
)

__all__ = [
    "AVISO",
    "EXPRESIONES",
    "DatosAhorro",
    "DatosDiagnostico",
    "DatosEscenario",
    "DatosNoAplica",
    "Expresion",
    "FotoEscenario",
    "TasaCaptacion",
    "dibujar_pana",
    "foto_de_perfil",
    "insignia",
    "tarjeta_ahorro",
    "tarjeta_diagnostico",
    "tarjeta_escenario",
    "tarjeta_no_aplica",
    "texto_ahorro",
    "texto_diagnostico",
    "texto_escenario",
    "texto_no_aplica",
]
