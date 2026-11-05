"""Construcción del Tablero: une tarifario y tablas, escribe el CSV y cruza preguntas."""

from __future__ import annotations

import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Config
from ..texto import normalizar
from ..utils import read_jsonl
from .tablas_web import extraer_tablas_web
from .tarifas import extraer_tarifario
from .tipos import Fila, escribir_filas, ruta_tablero

#: URL del tarifario que alimenta al Tablero.
URL_TARIFAS = "https://www.bancodeoccidente.com.co/documents/d/guest/tarifas-persona-1"
#: Archivo Gold preferido del tarifario 2025.
ARCHIVO_TARIFAS = "ver-tarifas-2025-2025-a46157.md"
#: Preguntas de la fase 2.
RUTA_PREGUNTAS = "config/evaluacion/preguntas_fase2.toml"


@dataclass(frozen=True, slots=True)
class Falla:
    """Pregunta de tabla que no encontró fila o valor."""

    identificador: str
    pregunta: str
    motivo: str


@dataclass(frozen=True, slots=True)
class ResumenTablero:
    """Resultado de construir el Tablero."""

    ruta: Path
    total: int
    por_origen: dict[str, int]
    preguntas: int
    fallas: tuple[Falla, ...]


def construir_filas(config: Config) -> list[Fila]:
    """Extrae el tarifario y las tablas web sin hacer red."""
    filas: list[Fila] = []
    ruta, fuente = _ruta_tarifario(config)
    texto = ruta.read_text(encoding="utf-8", errors="replace")
    filas.extend(extraer_tarifario(texto, _relativa(config, ruta), fuente))
    filas.extend(extraer_tablas_web(config))
    return filas


def escribir_tablero(config: Config) -> ResumenTablero:
    """Construye las filas, escribe el CSV y verifica las ocho preguntas."""
    filas = construir_filas(config)
    ruta = ruta_tablero(config)
    total = escribir_filas(ruta, filas)
    preguntas = cargar_preguntas_tabla(config)
    fallas = tuple(verificar_preguntas(filas, preguntas))
    return ResumenTablero(
        ruta=ruta,
        total=total,
        por_origen=dict(sorted(Counter(fila.origen for fila in filas).items())),
        preguntas=len(preguntas),
        fallas=fallas,
    )


def cargar_preguntas_tabla(config: Config) -> list[dict[str, Any]]:
    """Carga las preguntas de tipo `tabla` del set de fase 2."""
    ruta = config.paths.root / RUTA_PREGUNTAS
    if not ruta.exists():
        return []
    with ruta.open("rb") as fh:
        datos = tomllib.load(fh)
    return [pregunta for pregunta in datos.get("pregunta", []) if pregunta.get("tipo") == "tabla"]


def verificar_preguntas(filas: list[Fila], preguntas: list[dict[str, Any]]) -> list[Falla]:
    """Devuelve las preguntas de tabla que el Tablero no puede responder."""
    fallas: list[Falla] = []
    for pregunta in preguntas:
        fuentes = set(pregunta.get("fuentes_esperadas", []))
        candidatas = [fila for fila in filas if fila.fuente in fuentes]
        if not candidatas:
            fallas.append(_falla(pregunta, "sin fila con la fuente esperada"))
            continue
        if not any(_contiene_terminos(fila, pregunta.get("terminos", [])) for fila in candidatas):
            fallas.append(_falla(pregunta, "sin el valor esperado en las filas de esa fuente"))
    return fallas


def formatear_resumen(resumen: ResumenTablero) -> str:
    """Devuelve el texto legible del Tablero construido."""
    origenes = ", ".join(f"{origen}={total}" for origen, total in resumen.por_origen.items())
    lineas = [
        f"Tablero escrito: {resumen.total} filas en {resumen.ruta}",
        f"Por origen: {origenes or 'sin filas'}",
        f"Preguntas de tabla verificadas: {resumen.preguntas - len(resumen.fallas)}"
        f"/{resumen.preguntas}",
    ]
    for falla in resumen.fallas:
        lineas.append(f"  - {falla.identificador}: {falla.motivo} ({falla.pregunta})")
    return "\n".join(lineas)


def _contiene_terminos(fila: Fila, terminos: list[list[str]]) -> bool:
    """Comprueba que cada grupo de términos tenga una alternativa en la fila."""
    texto = normalizar(
        " ".join(
            [
                fila.concepto,
                fila.valor,
                fila.moneda,
                fila.periodicidad,
                fila.recargos,
                fila.vigente_desde,
            ]
        )
    )
    return all(any(normalizar(alternativa) in texto for alternativa in grupo) for grupo in terminos)


def _falla(pregunta: dict[str, Any], motivo: str) -> Falla:
    """Construye una falla con el identificador y el texto de la pregunta."""
    identificador = str(pregunta.get("id") or pregunta.get("numero") or "?")
    texto = str(pregunta.get("pregunta", "")).strip()
    return Falla(identificador=identificador, pregunta=texto, motivo=motivo)


def _ruta_tarifario(config: Config) -> tuple[Path, str]:
    """Localiza el Markdown del tarifario y su URL pública."""
    candidatas: list[tuple[Path, str]] = []
    for fila in read_jsonl(config.paths.documents_index):
        archivo = str(fila.get("archivo", "")).strip()
        fuente = str(fila.get("fuente", "")).strip()
        if not archivo:
            continue
        ruta = config.paths.root / archivo
        if ruta.name.endswith(ARCHIVO_TARIFAS) or fuente == URL_TARIFAS:
            candidatas.append((ruta, fuente))
    if not candidatas:
        raise FileNotFoundError(
            "No está el tarifario en data/gold/documents: ejecuta `make docs` antes de `make tablero`."
        )
    preferida = next(
        (par for par in candidatas if par[0].name.endswith(ARCHIVO_TARIFAS)), candidatas[0]
    )
    return preferida


def _relativa(config: Config, ruta: Path) -> str:
    """Devuelve la ruta relativa al repositorio, con separador `/`."""
    try:
        return ruta.relative_to(config.paths.root).as_posix()
    except ValueError:
        return ruta.as_posix()
