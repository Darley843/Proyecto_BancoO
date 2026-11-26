"""API local de la escena gota a gota: opciones, voluntario, entrada y escena.

La API es sin estado: no crea SQLite, no guarda perfiles y no confía en cifras
del cliente. Las respuestas se recalculan desde `PerfilEscena` y `config/`, y los
JSON de respaldo se leen de `data/escena/` (ignorado por Git). Todas las rutas
cuelgan de `/api/escena` y el router se monta antes de los estáticos.

Las pruebas viven en ``test/test_escena_api.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..config import PROJECT_ROOT
from ..tablero.tasas import TasaNoDisponible
from .contratos import (
    Escena,
    NegociacionEscena,
    PerfilEscena,
    RespuestaEscena,
    SeleccionVoluntario,
    TurnoEscena,
)
from .entrada import (
    Interpretacion,
    Letra,
    Pregunta,
    PreguntaEscena,
    interpretar,
    preguntas_escena,
)
from .perfiles import OpcionEscena, PerfilSeguro, cargar_perfiles, perfil_seguro
from .respondedor import Respondedor, respondedor_compartido, tema_del_turno
from .servicio import (
    ModoEscena,
    construir_escena,
    construir_negociacion,
    construir_perfil,
)
from .voluntario import seleccionar_voluntario

#: Carpeta de los JSON que genera `make escena-proyectada`.
RUTA_SALIDA = PROJECT_ROOT / "data" / "escena"
#: Largo máximo del texto que se interpreta.
LARGO_MAXIMO_TEXTO = 300


class _ModeloApi(BaseModel):
    """Base de los cuerpos de la API: rechaza campos desconocidos."""

    model_config = ConfigDict(extra="forbid")


class PreguntaPeticion(_ModeloApi):
    """Pregunta del público. La audiencia no viaja: la fija el servidor."""

    pregunta: str = Field(min_length=1, max_length=LARGO_MAXIMO_TEXTO)


class PreguntaRespuestaPana(BaseModel):
    """Respuesta de Pana a una pregunta del público."""

    tema: str
    turno: TurnoEscena


class OpcionRespuesta(BaseModel):
    """Una tarjeta A–F con su rango y su valor de cálculo."""

    letra: str
    id: str
    texto: str
    valor: Decimal
    desde: Decimal | None
    hasta: Decimal | None


class PreguntaRespuesta(BaseModel):
    """Una de las cuatro preguntas con sus tarjetas."""

    clave: Pregunta
    pregunta: str
    opciones: tuple[OpcionRespuesta, ...]


class OpcionesRespuesta(BaseModel):
    """Las cuatro preguntas de la escena."""

    preguntas: tuple[PreguntaRespuesta, ...]


class PerfilRespuesta(BaseModel):
    """Perfil seguro con el color que esperaba y el que obtuvo."""

    id: str
    personaje: str
    proposito: str
    esperado: str
    obtenido: str | None
    valido: bool
    respuestas: tuple[RespuestaEscena, ...]


class PerfilesRespuesta(BaseModel):
    """Perfiles seguros versionados, válidos o no."""

    perfiles: tuple[PerfilRespuesta, ...]


class VoluntarioPeticion(_ModeloApi):
    """Rangos del salón y, si se elige a mano, la fila y la silla."""

    filas: int | None = Field(default=None, ge=1, le=100)
    sillas: int | None = Field(default=None, ge=1, le=100)
    semilla: int | None = None
    fila: int | None = Field(default=None, ge=1, le=100)
    silla: int | None = Field(default=None, ge=1, le=100)


class InterpretarPeticion(_ModeloApi):
    """Texto reconocido o escrito y la pregunta que se responde."""

    texto: str = Field(min_length=1, max_length=LARGO_MAXIMO_TEXTO)
    pregunta: Pregunta
    monto: Decimal | None = None


class InterpretarRespuesta(BaseModel):
    """Respuesta interpretada, si hubo ajuste de monto y qué explicar."""

    respuesta: RespuestaEscena | None
    ajustado: bool = False
    mensaje: str | None = None
    seguro: bool = False


class RespuestaEntrada(_ModeloApi):
    """Letra y monto declarado de una respuesta; el servidor resuelve el valor."""

    pregunta: Pregunta
    letra: Letra | None = None
    monto: Decimal | None = None


class EscenaPeticion(_ModeloApi):
    """Petición de la fase 1: perfil seguro o las cuatro respuestas."""

    perfil_id: str | None = None
    respuestas: tuple[RespuestaEntrada, ...] | None = None
    monto: Decimal | None = None
    seleccion: SeleccionVoluntario | None = None
    confirmado: bool = True


class NegociacionPeticion(_ModeloApi):
    """Petición de la fase 2: un perfil ya validado o un perfil seguro."""

    perfil: PerfilEscena | None = None
    perfil_id: str | None = None
    seleccion: SeleccionVoluntario | None = None


class DisponibleRespuesta(BaseModel):
    """Datos ausentes o no disponibles, sin romper la pantalla."""

    disponible: bool
    detalle: str


class ServicioEscena(Protocol):
    """Operaciones que la API necesita del servicio de la escena."""

    def opciones(self) -> Sequence[PreguntaEscena]:
        """Devuelve las cuatro preguntas con sus tarjetas."""

    def perfiles(self) -> Sequence[PerfilSeguro]:
        """Devuelve los perfiles seguros con su validación."""

    def voluntario(self, peticion: VoluntarioPeticion) -> SeleccionVoluntario:
        """Elige fila y silla."""

    def interpretar(self, peticion: InterpretarPeticion) -> Interpretacion:
        """Interpreta el texto del voluntario."""

    def escena(self, peticion: EscenaPeticion) -> Escena:
        """Arma la fase 1."""

    def negociacion(self, peticion: NegociacionPeticion) -> NegociacionEscena:
        """Arma la fase 2."""

    def proyectado(self, modo: str) -> Escena | None:
        """Lee la escena de respaldo, o devuelve `None` si no existe."""


class ServicioEscenaReal:
    """Implementación del servicio sobre los módulos de la escena."""

    def __init__(self, raiz: Path | None = None, salida: Path | None = None) -> None:
        """Guarda la raíz del repositorio y la carpeta de respaldo."""
        self.raiz = raiz
        self.salida = salida if salida is not None else RUTA_SALIDA

    def opciones(self) -> Sequence[PreguntaEscena]:
        """Lee las preguntas y tarjetas del TOML del diagnóstico."""
        return preguntas_escena()

    def perfiles(self) -> Sequence[PerfilSeguro]:
        """Lee y valida los perfiles seguros contra el motor."""
        return cargar_perfiles(raiz=self.raiz)

    def voluntario(self, peticion: VoluntarioPeticion) -> SeleccionVoluntario:
        """Elige fila y silla con los rangos pedidos o los del TOML."""
        return seleccionar_voluntario(
            filas=peticion.filas,
            sillas=peticion.sillas,
            semilla=peticion.semilla,
            fila=peticion.fila,
            silla=peticion.silla,
        )

    def interpretar(self, peticion: InterpretarPeticion) -> Interpretacion:
        """Interpreta el texto con el parser determinista."""
        return interpretar(peticion.texto, peticion.pregunta, monto=peticion.monto)

    def _perfil(
        self, peticion: EscenaPeticion | NegociacionPeticion
    ) -> tuple[PerfilEscena, ModoEscena]:
        """Resuelve el perfil de la petición y el modo de la escena."""
        if peticion.perfil_id:
            return perfil_seguro(peticion.perfil_id, raiz=self.raiz), "seguro"
        if isinstance(peticion, NegociacionPeticion) and peticion.perfil is not None:
            return peticion.perfil, "vivo"
        if isinstance(peticion, EscenaPeticion) and peticion.respuestas:
            if not peticion.confirmado:
                raise HTTPException(status_code=409, detail="el perfil no está confirmado")
            respuestas: list[RespuestaEscena] = []
            for entrada in peticion.respuestas:
                texto = f"letra {entrada.letra}" if entrada.letra else ""
                resultado = interpretar(
                    texto,
                    entrada.pregunta,
                    monto=entrada.monto,
                )
                if resultado.respuesta is None:
                    raise HTTPException(
                        status_code=422,
                        detail=resultado.mensaje or "respuesta inválida",
                    )
                respuestas.append(resultado.respuesta)
            return construir_perfil(respuestas, monto_declarado=peticion.monto), "vivo"
        raise HTTPException(status_code=422, detail="falta el perfil o las respuestas")

    def escena(self, peticion: EscenaPeticion) -> Escena:
        """Arma la fase 1 desde el perfil o las respuestas."""
        perfil, modo = self._perfil(peticion)
        return construir_escena(
            perfil,
            seleccion=peticion.seleccion,
            modo=modo,
            raiz=self.raiz,
        )

    def negociacion(self, peticion: NegociacionPeticion) -> NegociacionEscena:
        """Arma la fase 2 y el veredicto sobre la escena completa."""
        perfil, _ = self._perfil(peticion)
        return construir_negociacion(
            perfil,
            seleccion=peticion.seleccion,
            raiz=self.raiz,
        )

    def proyectado(self, modo: str) -> Escena | None:
        """Lee `proyectado.json` o `nucleo.json` y lo valida."""
        nombre = "nucleo.json" if modo == "nucleo" else "proyectado.json"
        ruta = self.salida / nombre
        if not ruta.is_file():
            return None
        return Escena.model_validate_json(ruta.read_text(encoding="utf-8"))


def _opcion(opcion: OpcionEscena) -> OpcionRespuesta:
    """Convierte una opción del parser en el modelo de la API."""
    return OpcionRespuesta(
        letra=opcion.letra,
        id=opcion.opcion_id,
        texto=opcion.texto,
        valor=opcion.valor,
        desde=opcion.desde,
        hasta=opcion.hasta,
    )


def _pregunta(pregunta: PreguntaEscena) -> PreguntaRespuesta:
    """Convierte una pregunta del parser en el modelo de la API."""
    return PreguntaRespuesta(
        clave=pregunta.clave,
        pregunta=pregunta.pregunta,
        opciones=tuple(_opcion(opcion) for opcion in pregunta.opciones),
    )


def _perfil(perfil: PerfilSeguro) -> PerfilRespuesta:
    """Convierte un perfil seguro en el modelo de la API."""
    return PerfilRespuesta(
        id=perfil.id,
        personaje=perfil.perfil.personaje,
        proposito=perfil.perfil.proposito,
        esperado=perfil.esperado,
        obtenido=perfil.obtenido,
        valido=perfil.valido,
        respuestas=perfil.perfil.respuestas,
    )


def _error_tasa() -> JSONResponse:
    """Respuesta cuando el Tablero no publica la tasa del producto."""
    return JSONResponse(
        status_code=503,
        content={
            "disponible": False,
            "detalle": "el Tablero no publica la tasa de libre inversión",
        },
    )


def crear_router_escena(
    servicio: ServicioEscena | None = None,
    respondedor: Respondedor | None = None,
) -> APIRouter:
    """Crea el router de la escena para montarlo antes de los estáticos.

    Args:
        servicio: servicio alternativo para las pruebas; por defecto el real.
        respondedor: respondedor de preguntas para las pruebas; por defecto el
            real, que se construye en la primera pregunta.

    Returns:
        El router con todas las rutas bajo `/api/escena`.
    """
    actual = servicio if servicio is not None else ServicioEscenaReal()
    router = APIRouter(prefix="/api/escena", tags=["escena"])

    @router.get("/opciones", response_model=OpcionesRespuesta)
    def opciones() -> OpcionesRespuesta:
        """Devuelve las cuatro preguntas con sus tarjetas A–F."""
        return OpcionesRespuesta(preguntas=tuple(_pregunta(p) for p in actual.opciones()))

    @router.get("/perfiles", response_model=PerfilesRespuesta)
    def perfiles() -> PerfilesRespuesta:
        """Devuelve los perfiles seguros con su validación."""
        return PerfilesRespuesta(perfiles=tuple(_perfil(p) for p in actual.perfiles()))

    @router.post("/voluntario", response_model=SeleccionVoluntario)
    def voluntario(peticion: VoluntarioPeticion) -> SeleccionVoluntario:
        """Elige una fila y una silla; la selección no se guarda."""
        try:
            return actual.voluntario(peticion)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/interpretar", response_model=InterpretarRespuesta)
    def interpretar_texto(peticion: InterpretarPeticion) -> InterpretarRespuesta:
        """Interpreta una letra o un monto; no guarda el texto."""
        resultado = actual.interpretar(peticion)
        if resultado.respuesta is None and not resultado.seguro:
            raise HTTPException(
                status_code=422,
                detail=resultado.mensaje or "respuesta inválida",
            )
        return InterpretarRespuesta(
            respuesta=resultado.respuesta,
            ajustado=resultado.ajustado,
            mensaje=resultado.mensaje,
            seguro=resultado.seguro,
        )

    @router.post("", response_model=Escena)
    def escena(peticion: EscenaPeticion) -> Escena | JSONResponse:
        """Arma la fase 1: perfil, diagnóstico, Don Gota y comparación."""
        try:
            return actual.escena(peticion)
        except TasaNoDisponible:
            return _error_tasa()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/negociacion", response_model=NegociacionEscena)
    def negociacion(peticion: NegociacionPeticion) -> NegociacionEscena | JSONResponse:
        """Arma la fase 2: negociación, veredicto del auditor y cierre."""
        try:
            return actual.negociacion(peticion)
        except TasaNoDisponible:
            return _error_tasa()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/pregunta", response_model=PreguntaRespuestaPana)
    def pregunta(peticion: PreguntaPeticion) -> PreguntaRespuestaPana:
        """Responde una pregunta del público con un turno de Pana.

        La pregunta no se guarda. La audiencia es siempre `publico`, así que la
        regla de datos personales no se puede saltar desde el cliente.
        """
        responder = respondedor if respondedor is not None else respondedor_compartido()
        try:
            turno = responder(peticion.pregunta)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="pregunta vacía") from exc
        return PreguntaRespuestaPana(tema=tema_del_turno(turno), turno=turno)

    @router.get("/proyectado", response_model=None)
    def proyectado(
        modo: str = Query(default="completo", pattern="^(completo|nucleo)$"),
    ) -> Escena | JSONResponse:
        """Devuelve la escena de respaldo precalculada, si existe."""
        escena_guardada = actual.proyectado(modo)
        if escena_guardada is None:
            return JSONResponse(
                status_code=404,
                content={
                    "disponible": False,
                    "detalle": "falta data/escena/: ejecuta make escena-proyectada",
                },
            )
        return escena_guardada

    return router
