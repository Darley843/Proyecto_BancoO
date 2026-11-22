"""Endpoints de las voces de la escena para la app web.

- ``GET /api/pana/presentacion``: el texto fijo con que Pana se presenta y si
  hay voz de Piper para Pana en este computador.
- ``GET /api/voz/personajes``: por personaje, si tiene voz de Piper lista, qué
  motor usa (``piper`` o ``navegador``) y qué voz del navegador prefiere.
- ``POST /api/voz``: convierte el texto de un personaje en audio OGG/Opus con
  su voz. Responde 503 si no hay modelo; la web entonces usa la voz del
  navegador para ese personaje. Con ``motor = "navegador"`` también responde:
  es el respaldo cuando esa voz del navegador no está.

El texto se convierte en el computador con Piper: no sale a ningún servicio.
Las pruebas viven en ``test/test_voz.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from .presentacion import TEXTO_PRESENTACION
from .sintesis import PERSONAJES, VOZ_POR_DEFECTO, VozEscena, VozNoDisponible, VozPersonaje

#: Largo máximo del texto que acepta ``POST /api/voz``.
LARGO_MAXIMO_API = 900

#: Personajes válidos en el cuerpo de ``POST /api/voz``.
Personaje = Literal["pana", "don_gota", "joven", "agente_joven", "agente_banco", "auditor"]


class PresentacionRespuesta(BaseModel):
    """Texto de la presentación y si hay voz de Piper disponible."""

    texto: str
    voz: bool


class VozNavegador(BaseModel):
    """Voz del navegador de un personaje (motor principal o respaldo)."""

    voz: str
    tono: float
    velocidad: float


class EstadoPersonaje(BaseModel):
    """Cómo habla un personaje en este computador."""

    motor: Literal["piper", "navegador"]
    piper: bool
    navegador: VozNavegador


class PersonajesRespuesta(BaseModel):
    """Cómo habla cada personaje de la escena."""

    personajes: dict[str, EstadoPersonaje]


class PedidoVoz(BaseModel):
    """Texto que dirá un personaje de la escena."""

    texto: str = Field(min_length=1, max_length=LARGO_MAXIMO_API)
    personaje: Personaje = "pana"


def _estado(voz: VozPersonaje, piper: bool) -> EstadoPersonaje:
    """Arma el estado público de un personaje (sin rutas ni datos internos)."""
    return EstadoPersonaje(
        motor="navegador" if voz.motor == "navegador" else "piper",
        piper=piper,
        navegador=VozNavegador(
            voz=voz.navegador, tono=voz.tono_navegador, velocidad=voz.velocidad_navegador
        ),
    )


def crear_router_voz(
    voz: VozEscena | None,
    disponibles: Mapping[str, bool] | None = None,
    personajes: Mapping[str, VozPersonaje] | None = None,
) -> APIRouter:
    """Crea el router de las voces de la escena.

    Args:
        voz: las voces configuradas, o ``None`` si están apagadas.
        disponibles: ``{personaje: True/False}`` según el modelo descargado; si
            falta, se asume que todos tienen voz cuando ``voz`` existe.
        personajes: la voz configurada de cada personaje; si falta, se toman
            las de ``voz`` o la voz por defecto.

    Returns:
        El router con ``/api/pana/presentacion``, ``/api/voz/personajes`` y
        ``/api/voz``.
    """
    router = APIRouter(prefix="/api", tags=["voz"])
    configuradas = personajes or (voz.personajes if voz is not None else {})
    estado = {
        nombre: _estado(
            configuradas.get(nombre, VOZ_POR_DEFECTO),
            voz is not None and (disponibles is None or bool(disponibles.get(nombre))),
        )
        for nombre in PERSONAJES
    }

    @router.get("/pana/presentacion", response_model=PresentacionRespuesta)
    def presentacion() -> PresentacionRespuesta:
        """Devuelve la presentación fija de Pana."""
        return PresentacionRespuesta(texto=TEXTO_PRESENTACION, voz=estado["pana"].piper)

    @router.get("/voz/personajes", response_model=PersonajesRespuesta)
    def personajes() -> PersonajesRespuesta:
        """Dice cómo habla cada personaje (motor, Piper listo, voz del navegador)."""
        return PersonajesRespuesta(personajes=dict(estado))

    @router.post("/voz", response_model=None)
    def hablar(pedido: PedidoVoz) -> Response:
        """Devuelve el audio OGG/Opus del texto, o 503 si no hay voz."""
        if voz is None:
            return _sin_voz("Las voces están apagadas en config/voz.toml.")
        try:
            audio = voz.audio(pedido.texto, pedido.personaje)
        except VozNoDisponible as error:
            return _sin_voz(str(error))
        return Response(content=audio, media_type="audio/ogg")

    return router


def _sin_voz(mensaje: str) -> JSONResponse:
    """Responde 503 con el formato de error de la API."""
    return JSONResponse(
        status_code=503,
        content={"error": {"codigo": "sin_voz", "mensaje": mensaje}},
    )
