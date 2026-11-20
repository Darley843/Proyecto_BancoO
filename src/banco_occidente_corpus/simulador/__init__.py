"""Simulador de payloads del webhook de WhatsApp y personas sintéticas (sin red)."""

from banco_occidente_corpus.simulador.payloads import (
    encabezados_firmados,
    enviar_a_webhook,
    firmar,
    numero_ficticio,
    payload_boton,
    payload_lista,
    payload_texto,
    serializar,
)
from banco_occidente_corpus.simulador.personas import Persona, cargar_personas, conversacion

__all__ = [
    "Persona",
    "cargar_personas",
    "conversacion",
    "encabezados_firmados",
    "enviar_a_webhook",
    "firmar",
    "numero_ficticio",
    "payload_boton",
    "payload_lista",
    "payload_texto",
    "serializar",
]
