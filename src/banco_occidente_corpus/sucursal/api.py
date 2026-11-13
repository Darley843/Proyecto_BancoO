"""API local de la Sucursal: estado, Tablero, Bóveda, pipeline, Arqueo y Vestíbulo.

Los endpoints de datos solo leen artefactos ya construidos (`tablero.csv`,
`indice.json`, `mapa.json`, `arqueo.json`, `config/vestibulo.toml`).
`POST /api/preguntar` delega en `sucursal.preguntar`, que construye el grafo y sus
dependencias la primera vez que se pregunta y no al importar este módulo.
`POST /api/preguntar/stream` atiende el mismo turno con el mismo servicio, pero
envía el avance de cada nodo como eventos del servidor (SSE, `sucursal.transmision`).
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse
from ollama import ResponseError
from pydantic import BaseModel, Field

from ..boveda.mapa import ServicioMapa
from ..config import Config
from ..panel import pipeline_summary
from ..tablero.consultas import buscar_filas
from ..tablero.tipos import Fila, leer_filas, ruta_tablero
from .ajustes import ConfiguracionSucursal, tope_efectivo
from .costo import CacheRespuestas, GastoDiario
from .preguntar import (
    ErrorSucursal,
    PiezasGrafo,
    ServicioPreguntas,
    construir_piezas,
    leer_indice,
)
from .transmision import MensajeTurno, TransmisionTurno, con_avance

#: Largo máximo de la pregunta que se ubica en el mapa.
LARGO_PREGUNTA_MAPA = 500
#: Ruta del reporte del Arqueo.
RUTA_ARQUEO = "data/evaluacion/arqueo.json"
#: Ruta de los hitos del Vestíbulo.
RUTA_VESTIBULO = "config/vestibulo.toml"
#: Encabezados del streaming: sin caché y sin búfer en proxies intermedios.
ENCABEZADOS_SSE: dict[str, str] = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class EstadoRespuesta(BaseModel):
    """Estado operativo de la Sucursal."""

    modo_demo: bool
    gasto_hoy_usd: float
    tope_usd: float
    indice_listo: bool
    fragmentos_indexados: int
    modelo_embeddings: str


class FilaTablero(BaseModel):
    """Una fila del Tablero con su trazabilidad."""

    concepto: str
    categoria: str
    valor: str
    moneda: str
    recargos: str
    periodicidad: str
    vigente_desde: str
    origen: str
    pagina: str
    fuente: str


class TableroRespuesta(BaseModel):
    """Filas del Tablero que cumplen el filtro."""

    filas: list[FilaTablero] = Field(default_factory=list)
    total: int = 0


class PuntoMapa(BaseModel):
    """Punto del mapa PCA de la Bóveda."""

    x: float
    y: float
    seccion: str = ""
    titulo: str = ""


class PreguntaMapa(BaseModel):
    """Coordenada de la pregunta proyectada."""

    x: float
    y: float


class MapaRespuesta(BaseModel):
    """Mapa del corpus; `disponible` explica si el índice ya se generó."""

    puntos: list[PuntoMapa] = Field(default_factory=list)
    pregunta: PreguntaMapa | None = None
    top: list[dict[str, Any]] = Field(default_factory=list)
    disponible: bool = False
    error: str | None = None


class EtapaRespuesta(BaseModel):
    """Etapa del pipeline con sus métricas."""

    key: str
    title: str
    hint: str
    metrics: list[dict[str, str]] = Field(default_factory=list)
    note: str = ""
    warning: str = ""


class IndexacionRespuesta(BaseModel):
    """Estado de la indexación de la Bóveda."""

    indice_listo: bool
    fragmentos_indexados: int = 0
    modelo_embeddings: str = ""
    alcance: str = ""


class PipelineRespuesta(BaseModel):
    """Resumen del pipeline y de la indexación."""

    etapas: list[EtapaRespuesta] = Field(default_factory=list)
    fuentes: list[str] = Field(default_factory=list)
    repeticiones: dict[str, Any] | None = None
    indexacion: IndexacionRespuesta


class ArqueoRespuesta(BaseModel):
    """Contenido del reporte del Arqueo, si existe."""

    disponible: bool
    datos: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class HitoRespuesta(BaseModel):
    """Un hito del Vestíbulo."""

    anio: int
    texto: str
    url: str


class VestibuloRespuesta(BaseModel):
    """Línea de tiempo del banco."""

    hitos: list[HitoRespuesta] = Field(default_factory=list)


class FuenteRespuesta(BaseModel):
    """Fuente numerada de una respuesta, con el número que usa la cita `[n]`."""

    n: int
    titulo: str = ""
    url: str
    seccion: str = ""
    tipo: str = ""
    similitud: float | None = None


class PreguntarRequest(BaseModel):
    """Pregunta que envía la Ventanilla junto con su hilo de conversación."""

    pregunta: str = ""
    thread_id: str = ""


class PreguntarRespuesta(BaseModel):
    """Turno atendido: ticket, ruta, respuesta, fuentes y costo.

    Las letras siguen siendo `B`, `T` y `X`; la ruta distingue además la
    cortesía (`cortesia`, sin búsqueda) y la pregunta mixta (`mixta`, Tablero y
    Bóveda en un solo turno).
    """

    turno: Literal["B", "T", "X"]
    turno_numero: int
    ruta: Literal["boveda", "tablero", "rechazo", "cortesia", "mixta"]
    motivo: str
    uso_modelo: bool
    reformulada: str | None = None
    respuesta: str
    fuentes: list[FuenteRespuesta] = Field(default_factory=list)
    tokens_entrada: int = 0
    tokens_salida: int = 0
    tokens_cache: int = 0
    costo_usd: float = 0.0
    tiempo_s: float = 0.0
    cache: bool = False


def crear_router(
    config: Config,
    ajustes: ConfiguracionSucursal,
    gasto: GastoDiario,
    *,
    cache: CacheRespuestas | None = None,
    piezas: Callable[[], PiezasGrafo] | None = None,
    mapa_boveda: ServicioMapa | None = None,
) -> APIRouter:
    """Crea el router `/api` con las dependencias inyectadas.

    Args:
        config: configuración con las rutas del corpus.
        ajustes: tope, TTL de caché y modo demo.
        gasto: acumulado diario del gasto del modelo.
        cache: caché alternativa para las pruebas; por defecto `data/asistente/`.
        piezas: fábrica alternativa del grafo para las pruebas; por defecto se
            construye de forma perezosa en la primera pregunta.
        mapa_boveda: servicio alternativo del mapa para las pruebas; por defecto
            lee `data/boveda/mapa.json` y usa Ollama y el recuperador real.

    Returns:
        El router con los ocho endpoints de la Sucursal.
    """
    router = APIRouter(prefix="/api")
    fabrica = piezas or _fabrica_piezas(config, ajustes)
    servicio = ServicioPreguntas(
        config, ajustes, gasto, cache=cache, piezas=lambda: con_avance(fabrica())
    )
    servicio_mapa = mapa_boveda or ServicioMapa(config)

    @router.get("/estado", response_model=EstadoRespuesta)
    def estado() -> EstadoRespuesta:
        """Devuelve el estado operativo y el gasto del día."""
        indice = leer_indice(config)
        costo, _, _ = gasto.hoy()
        return EstadoRespuesta(
            modo_demo=ajustes.demo,
            gasto_hoy_usd=round(costo, 6),
            tope_usd=tope_efectivo(ajustes),
            indice_listo=indice is not None,
            fragmentos_indexados=int(indice.get("fragmentos", 0)) if indice else 0,
            modelo_embeddings=str(indice.get("modelo", "")) if indice else "",
        )

    @router.get("/tablero", response_model=TableroRespuesta)
    def tablero(q: str = "") -> TableroRespuesta:
        """Devuelve las filas del CSV del Tablero, filtradas por `q`."""
        filas = leer_filas(ruta_tablero(config))
        filtradas = buscar_filas(filas, q) if q.strip() else filas
        return TableroRespuesta(
            filas=[FilaTablero(**fila.como_dict()) for fila in filtradas],
            total=len(filtradas),
        )

    @router.get("/boveda/mapa", response_model=MapaRespuesta)
    def mapa(
        pregunta: str | None = Query(default=None, max_length=LARGO_PREGUNTA_MAPA),
    ) -> MapaRespuesta:
        """Devuelve el mapa de la Bóveda y, si hay pregunta, su posición y el top.

        Sin pregunta, `pregunta` es null y `top` está vacío. Si el índice falta,
        responde un estado explicable. Si Ollama no responde al ubicar la
        pregunta, devuelve igual los puntos y explica el problema en `error`.
        """
        datos = servicio_mapa.mapa()
        if datos is None:
            return MapaRespuesta(
                disponible=False,
                error="El mapa aún no está generado: ejecuta `make indice`.",
            )
        puntos = [PuntoMapa(**punto) for punto in datos.get("puntos", [])]
        texto = (pregunta or "").strip()
        if not texto:
            return MapaRespuesta(puntos=puntos, disponible=True)
        try:
            ubicada = servicio_mapa.ubicar(datos, texto)
            top = servicio_mapa.top(texto)
        except (ValueError, RuntimeError, OSError, httpx.HTTPError, ResponseError) as error:
            return MapaRespuesta(
                puntos=puntos,
                disponible=True,
                error=f"No se pudo ubicar la pregunta: {error}",
            )
        return MapaRespuesta(
            puntos=puntos,
            pregunta=PreguntaMapa(**ubicada),
            top=top,
            disponible=True,
        )

    @router.get("/pipeline", response_model=PipelineRespuesta)
    def pipeline() -> PipelineRespuesta:
        """Devuelve las etapas del pipeline y el estado de indexación."""
        resumen = pipeline_summary(config)
        repeticiones = asdict(resumen.repetitions) if resumen.repetitions else None
        return PipelineRespuesta(
            etapas=[
                EtapaRespuesta(
                    key=etapa.key,
                    title=etapa.title,
                    hint=etapa.hint,
                    metrics=[asdict(metrica) for metrica in etapa.metrics],
                    note=etapa.note,
                    warning=etapa.warning,
                )
                for etapa in resumen.stages
            ],
            fuentes=list(resumen.sources),
            repeticiones=repeticiones,
            indexacion=_indexacion(config),
        )

    @router.get("/arqueo", response_model=ArqueoRespuesta)
    def arqueo() -> ArqueoRespuesta:
        """Devuelve `arqueo.json` o `disponible: false` si no existe."""
        datos = _leer_json(config.paths.root / RUTA_ARQUEO)
        if datos is None:
            return ArqueoRespuesta(
                disponible=False,
                error="El Arqueo aún no está generado: ejecuta `make arqueo`.",
            )
        return ArqueoRespuesta(disponible=True, datos=datos)

    @router.get("/vestibulo", response_model=VestibuloRespuesta)
    def vestibulo() -> VestibuloRespuesta:
        """Devuelve los hitos de `config/vestibulo.toml`."""
        ruta = config.paths.root / RUTA_VESTIBULO
        if not ruta.exists():
            return VestibuloRespuesta()
        with ruta.open("rb") as fh:
            datos = tomllib.load(fh)
        return VestibuloRespuesta(hitos=[HitoRespuesta(**hito) for hito in datos.get("hito", [])])

    @router.post("/preguntar", response_model=PreguntarRespuesta)
    def preguntar(
        datos: PreguntarRequest | None = None,
    ) -> PreguntarRespuesta | JSONResponse:
        """Atiende una pregunta con el grafo y devuelve el turno completo.

        Args:
            datos: pregunta y `thread_id`; si falta el cuerpo se responde 422 con
                el mismo formato de error que el resto de los rechazos.

        Returns:
            La respuesta del contrato o `{"error": {"codigo", "mensaje"}}`.
        """
        peticion = datos or PreguntarRequest()
        try:
            respuesta = servicio.preguntar(peticion.pregunta, peticion.thread_id)
        except ErrorSucursal as error:
            return _error(error)
        return PreguntarRespuesta.model_validate(respuesta)

    @router.post("/preguntar/stream", response_model=None)
    def preguntar_stream(
        datos: PreguntarRequest | None = None,
    ) -> StreamingResponse | JSONResponse:
        """Atiende la pregunta y transmite el avance del grafo por SSE.

        Envía un evento `etapa` cuando cada nodo empieza y termina, y cierra
        con `final` (el mismo cuerpo de `POST /api/preguntar`) o con `error`.
        Los rechazos previos al grafo (pregunta vacía, sin hilo, sin índice,
        sin clave o tope) responden con su estado HTTP y el JSON de siempre,
        para que la Ventanilla los maneje igual que hoy.

        Args:
            datos: pregunta y `thread_id`, igual que en `POST /api/preguntar`.

        Returns:
            Un `text/event-stream` o `{"error": {"codigo", "mensaje"}}`.
        """
        peticion = datos or PreguntarRequest()

        def atender() -> dict[str, Any]:
            """Atiende el turno y valida el cuerpo con el contrato de la API."""
            respuesta = servicio.preguntar(peticion.pregunta, peticion.thread_id)
            return PreguntarRespuesta.model_validate(respuesta).model_dump(mode="json")

        transmision = TransmisionTurno(atender).iniciar()
        primero = transmision.siguiente()
        if primero is not None and primero.tipo == "error":
            return _error_de_mensaje(primero)
        return StreamingResponse(
            transmision.eventos_sse(primero),
            media_type="text/event-stream",
            headers=ENCABEZADOS_SSE,
        )

    return router


def _fabrica_piezas(config: Config, ajustes: ConfiguracionSucursal) -> Callable[[], PiezasGrafo]:
    """Devuelve la fábrica real del grafo, la misma que usa `ServicioPreguntas`."""

    def construir() -> PiezasGrafo:
        """Construye el grafo y sus dependencias con la configuración real."""
        return construir_piezas(config, ajustes)

    return construir


def _error_de_mensaje(mensaje: MensajeTurno) -> JSONResponse:
    """Devuelve el error del streaming con su estado HTTP y el JSON del contrato."""
    return JSONResponse(status_code=mensaje.estado_http, content=mensaje.datos)


def _error(error: ErrorSucursal) -> JSONResponse:
    """Devuelve `{"error": {"codigo", "mensaje"}}` con el estado HTTP del error."""
    return JSONResponse(
        status_code=error.estado_http,
        content={"error": {"codigo": error.codigo, "mensaje": error.mensaje}},
    )


def _leer_json(ruta: Path) -> dict[str, Any] | None:
    """Lee un JSON si existe y es un objeto; si no, devuelve None."""
    if not ruta.exists():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return datos if isinstance(datos, dict) else None


def _indexacion(config: Config) -> IndexacionRespuesta:
    """Lee el estado de indexación de `indice.json`."""
    indice = leer_indice(config)
    if indice is None:
        return IndexacionRespuesta(indice_listo=False)
    return IndexacionRespuesta(
        indice_listo=True,
        fragmentos_indexados=int(indice.get("fragmentos", 0)),
        modelo_embeddings=str(indice.get("modelo", "")),
        alcance=str(indice.get("alcance", "")),
    )


# Reexportado para que las pruebas puedan construir filas sin importar el módulo.
__all__ = ["Fila", "crear_router"]
