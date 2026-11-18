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
    DatosDiagnostico,
    DatosEscenario,
    FotoEscenario,
    tarjeta_diagnostico,
    tarjeta_escenario,
    texto_diagnostico,
    texto_escenario,
)

__all__ = [
    "AVISO",
    "EXPRESIONES",
    "DatosDiagnostico",
    "DatosEscenario",
    "Expresion",
    "FotoEscenario",
    "dibujar_pana",
    "foto_de_perfil",
    "insignia",
    "tarjeta_diagnostico",
    "tarjeta_escenario",
    "texto_diagnostico",
    "texto_escenario",
]
