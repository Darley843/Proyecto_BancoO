"""API local de la Sucursal: estado, Tablero, Bóveda, pipeline, Arqueo y Vestíbulo.

La API solo lee artefactos ya construidos (`tablero.csv`, `indice.json`,
`mapa.json`, `arqueo.json`, `config/vestibulo.toml`). No llama al modelo ni hace
red: el endpoint de preguntas llega en el PR 10b.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import Config
from ..panel import pipeline_summary
from ..tablero.consultas import buscar_filas
from ..tablero.tipos import Fila, leer_filas, ruta_tablero
from .ajustes import ConfiguracionSucursal, tope_efectivo
from .costo import GastoDiario

#: Ruta del índice de la Bóveda dentro de `data/boveda/`.
RUTA_INDICE = "data/boveda/indice.json"
#: Ruta del mapa PCA.
RUTA_MAPA = "data/boveda/mapa.json"
#: Ruta del reporte del Arqueo.
RUTA_ARQUEO = "data/evaluacion/arqueo.json"
#: Ruta de los hitos del Vestíbulo.
RUTA_VESTIBULO = "config/vestibulo.toml"


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


def crear_router(
    config: Config,
    ajustes: ConfiguracionSucursal,
    gasto: GastoDiario,
) -> APIRouter:
    """Crea el router `/api` con las dependencias inyectadas."""
    router = APIRouter(prefix="/api")

    @router.get("/estado", response_model=EstadoRespuesta)
    def estado() -> EstadoRespuesta:
        """Devuelve el estado operativo y el gasto del día."""
        indice = _leer_json(config.paths.root / RUTA_INDICE)
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
    def mapa(pregunta: str | None = None) -> MapaRespuesta:
        """Devuelve el mapa de la Bóveda o un estado explicable si falta."""
        datos = _leer_json(config.paths.root / RUTA_MAPA)
        if datos is None:
            return MapaRespuesta(
                disponible=False,
                error="El mapa aún no está generado: ejecuta `make indice`.",
            )
        return MapaRespuesta(
            puntos=[PuntoMapa(**punto) for punto in datos.get("puntos", [])],
            pregunta=_pregunta_mapa(datos.get("pregunta")),
            top=list(datos.get("top", [])),
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

    return router


def _leer_json(ruta: Path) -> dict[str, Any] | None:
    """Lee un JSON si existe y es un objeto; si no, devuelve None."""
    if not ruta.exists():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return datos if isinstance(datos, dict) else None


def _pregunta_mapa(datos: Any) -> PreguntaMapa | None:
    """Convierte la pregunta proyectada del mapa, si existe."""
    if not isinstance(datos, dict):
        return None
    try:
        return PreguntaMapa(x=float(datos["x"]), y=float(datos["y"]))
    except (KeyError, TypeError, ValueError):
        return None


def _indexacion(config: Config) -> IndexacionRespuesta:
    """Lee el estado de indexación de `indice.json`."""
    indice = _leer_json(config.paths.root / RUTA_INDICE)
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
