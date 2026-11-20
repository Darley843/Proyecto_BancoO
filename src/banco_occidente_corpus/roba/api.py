"""API de la terminal de Roba la Bóveda (tarea 7.8).

Cuatro rutas bajo ``/api/roba`` (design.md, decisión 14):

- ``GET /api/roba?sesion=…``: límite, marcador e historial de la sesión.
- ``POST /api/roba/intento`` con ``{sesion, texto}``: clasifica, consulta al
  asistente en modo demo, decide si la defensa resistió y lo anota.
- ``POST /api/roba/reiniciar`` con ``{sesion}``: borra los intentos de la sesión.
- ``GET /api/roba/exportar?sesion=…``: resumen para el Arqueo, sin datos
  personales.

El intento se trata siempre como texto: no se ejecuta, no abre archivos y no
cambia la configuración. Un intento con un dato personal no llega al asistente:
lo rechaza la puerta de PII, queda como defensa resistida y su texto no se
guarda (solo una marca fija). La clasificación previa se hace antes de llamar
al asistente, con los datos públicos del banco. Si el asistente
falla, la ruta responde 503 con el error del contrato, deja registrado el fallo
en el log (sin el texto) y el intento no gasta un turno de la sesión. Nada de
esto envía mensajes por WhatsApp.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..canal.configuracion import cargar_configuracion_canal
from .clasificador import (
    clasificar_intento,
    contiene_pii,
    evaluar_exito,
    puntos_de,
    refinar_categoria,
    sanear,
)
from .marcador import LimiteAlcanzado, MarcadorRoba

#: Logger de la terminal; nunca recibe el texto del intento ni la respuesta.
LOGGER = logging.getLogger(__name__)

#: Intentos por sesión si ``config/whatsapp.toml`` no trae un límite válido.
LIMITE_POR_DEFECTO = 20
#: Largo máximo de un intento, igual que ``LARGO_MAXIMO`` de ``roba.js``.
LARGO_MAXIMO = 500
#: Sesión válida: la que crea la vista (``web-`` y ocho hexadecimales) u otra corta.
PATRON_SESION = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
#: Lo que se guarda en lugar de un intento que traía un dato personal.
TEXTO_CON_PII = "[intento con datos personales: el texto no se guarda]"
#: Respuesta fija de la puerta de PII: el intento no llega al asistente.
RESPUESTA_PII = (
    "Por seguridad no proceso datos personales como documentos, teléfonos, correos o "
    "números de tarjeta. Escribe tu pregunta sin esos datos."
)


@dataclass(frozen=True, slots=True)
class RespuestaAsistente:
    """Lo que devuelve el asistente a un intento, en modo demo."""

    respuesta: str
    turno: str
    motivo: str = ""
    permitidos: tuple[str, ...] = ()
    marcadores_prompt: tuple[str, ...] = ()


class AsistenteNoDisponible(Exception):
    """El asistente no pudo responder; lleva un código y un mensaje para la vista."""

    def __init__(self, codigo: str, mensaje: str, estado_http: int = 503) -> None:
        """Guarda el código, el mensaje y el estado HTTP del error."""
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.estado_http = estado_http


class Respondedor(Protocol):
    """Quien contesta los intentos: la Sucursal en modo demo o un doble de prueba."""

    def permitidos(self) -> tuple[str, ...]:
        """Devuelve los datos públicos del banco que no cuentan como personales."""
        ...

    def responder(self, texto: str, hilo: str) -> RespuestaAsistente:
        """Responde el intento en el hilo dado."""
        ...


class IntentoRequest(BaseModel):
    """Cuerpo de ``POST /api/roba/intento``."""

    sesion: str = ""
    texto: str = ""


class SesionRequest(BaseModel):
    """Cuerpo de ``POST /api/roba/reiniciar``."""

    sesion: str = ""


def limite_configurado() -> int:
    """Lee ``canal.limite_intentos_roba`` de ``config/whatsapp.toml``.

    Returns:
        El límite de intentos por sesión, o ``LIMITE_POR_DEFECTO`` si falta o
        no es un entero positivo.
    """
    try:
        limite = cargar_configuracion_canal().limite_intentos_roba
    except (OSError, ValueError):
        return LIMITE_POR_DEFECTO
    return limite if limite > 0 else LIMITE_POR_DEFECTO


def _error(estado_http: int, codigo: str, mensaje: str) -> JSONResponse:
    """Devuelve ``{"error": {"codigo", "mensaje"}}`` como el resto de la API."""
    return JSONResponse(
        status_code=estado_http, content={"error": {"codigo": codigo, "mensaje": mensaje}}
    )


def _sesion_invalida(sesion: str) -> JSONResponse | None:
    """Devuelve el 422 si la sesión no tiene el formato esperado."""
    if PATRON_SESION.fullmatch(sesion):
        return None
    return _error(422, "sesion_invalida", "Falta la sesión del juego o no tiene un formato válido.")


def _permitidos(respondedor: Respondedor) -> tuple[str, ...]:
    """Pide los datos públicos del banco; si el asistente aún no puede darlos, ninguno."""
    try:
        return tuple(respondedor.permitidos())
    except Exception as error:
        LOGGER.warning("evento=roba_sin_permitidos codigo=%s", type(error).__name__)
        return ()


def crear_router_roba(marcador: MarcadorRoba, respondedor: Respondedor) -> APIRouter:
    """Crea el router ``/roba`` con el marcador y el asistente inyectados.

    Se monta dentro del router ``/api`` de la Sucursal, así que las rutas
    quedan en ``/api/roba``.

    Args:
        marcador: marcador persistente con el límite de intentos.
        respondedor: asistente que contesta los intentos.

    Returns:
        El router con las cuatro rutas de la terminal.
    """
    router = APIRouter(prefix="/roba", tags=["roba"])

    @router.get("", response_model=None)
    def estado(sesion: str = Query(default="")) -> dict[str, Any] | JSONResponse:
        """Devuelve el límite, el marcador y el historial saneado de la sesión."""
        invalida = _sesion_invalida(sesion)
        if invalida is not None:
            return invalida
        return marcador.estado(sesion)

    @router.post("/intento", response_model=None)
    def intento(datos: IntentoRequest | None = None) -> dict[str, Any] | JSONResponse:
        """Clasifica el intento, consulta al asistente y anota el resultado."""
        peticion = datos or IntentoRequest()
        invalida = _sesion_invalida(peticion.sesion)
        if invalida is not None:
            return invalida
        texto = peticion.texto.strip()
        if not texto:
            return _error(422, "intento_vacio", "Escribe un intento antes de enviarlo.")
        if len(texto) > LARGO_MAXIMO:
            return _error(422, "intento_largo", f"El intento supera {LARGO_MAXIMO} caracteres.")
        if marcador.contar(peticion.sesion) >= marcador.limite:
            return _error(
                409,
                "limite_alcanzado",
                f"Usaste los {marcador.limite} intentos de esta sesión: reinicia el marcador.",
            )

        permitidos = _permitidos(respondedor)
        previa = clasificar_intento(texto, permitidos)
        con_pii = contiene_pii(texto, permitidos)
        if con_pii:
            resultado = RespuestaAsistente(respuesta=RESPUESTA_PII, turno="X", motivo="pii")
        else:
            try:
                resultado = respondedor.responder(texto, f"roba:{peticion.sesion}")
            except AsistenteNoDisponible as error:
                LOGGER.warning("evento=roba_fallo_controlado codigo=%s", error.codigo)
                return _error(error.estado_http, error.codigo, error.mensaje)
            except Exception as error:
                LOGGER.warning("evento=roba_fallo_controlado codigo=%s", type(error).__name__)
                return _error(
                    503,
                    "asistente_fallo",
                    "El asistente falló con este intento; el marcador sigue disponible.",
                )

        publicos = (*permitidos, *resultado.permitidos)
        categoria = refinar_categoria(previa, resultado.turno, resultado.motivo)
        exito = evaluar_exito(
            categoria,
            resultado.respuesta,
            resultado.turno,
            permitidos=publicos,
            marcadores_prompt=resultado.marcadores_prompt,
        )
        try:
            guardado = marcador.registrar(
                peticion.sesion,
                categoria=categoria,
                texto=TEXTO_CON_PII if con_pii else sanear(texto, publicos),
                respuesta=sanear(resultado.respuesta, publicos),
                exito=exito,
                puntos=puntos_de(categoria, exito),
                con_pii=con_pii,
            )
        except LimiteAlcanzado:
            return _error(
                409,
                "limite_alcanzado",
                f"Usaste los {marcador.limite} intentos de esta sesión: reinicia el marcador.",
            )
        totales = marcador.totales(peticion.sesion)
        return {
            "n": guardado.n,
            "categoria": guardado.categoria,
            "exito": guardado.exito,
            "puntos": guardado.puntos,
            "defensa": guardado.defensa,
            "respuesta": guardado.respuesta,
            "marcador": {
                "intentos": totales["intentos"],
                "exitos": totales["exitos"],
                "puntos": totales["puntos"],
            },
        }

    @router.post("/reiniciar", response_model=None)
    def reiniciar(datos: SesionRequest | None = None) -> dict[str, Any] | JSONResponse:
        """Borra los intentos de la sesión y devuelve el marcador en cero."""
        peticion = datos or SesionRequest()
        invalida = _sesion_invalida(peticion.sesion)
        if invalida is not None:
            return invalida
        borrados = marcador.reiniciar(peticion.sesion)
        return {"sesion": peticion.sesion, "borrados": borrados, **marcador.estado(peticion.sesion)}

    @router.get("/exportar", response_model=None)
    def exportar(sesion: str = Query(default="")) -> dict[str, Any] | JSONResponse:
        """Devuelve el resumen de la sesión para el Arqueo, sin datos personales."""
        invalida = _sesion_invalida(sesion)
        if invalida is not None:
            return invalida
        return marcador.exportar(sesion)

    return router
