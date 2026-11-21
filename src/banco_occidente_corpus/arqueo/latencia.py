"""Latencia real de la Sucursal: `medir(flujo, cache)` y su sección del Arqueo.

Tareas 8.4 a 8.6 del cambio OpenSpec ``corresponsal-whatsapp`` (design.md,
decisión 15). Cada corrida medida se guarda en
``data/asistente/latencias.sqlite``, tabla ``latencias`` (``flujo``, ``ms``,
``cache``, ``creado``). La lee el tablero de operación
(`sucursal.operacion.resumen_latencias`) y la sección ``latencia`` del Arqueo.

La base se pasa siempre de forma explícita (``ruta``): sin ruta, `medir` mide
pero no escribe. La app la arma con la raíz de su configuración, así que las
pruebas, que usan una raíz temporal, no ensucian la latencia real de la demo. Una falla al escribir nunca corta la
respuesta a la persona: se anota en el log sin el texto del mensaje.

Solo se guardan el flujo, los milisegundos, si respondió la caché y la hora:
ni textos, ni números, ni huellas.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Generator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..sucursal.operacion import (
    MINIMO_CORRIDAS,
    RUTA_LATENCIAS,
    ZONA_HORARIA,
    LatenciaFlujo,
    resumen_latencias,
)

LOGGER = logging.getLogger(__name__)

#: Flujos que mide el proyecto (design.md, decisión 15) más la Ventanilla web.
FLUJOS: tuple[str, ...] = ("webhook", "diagnostico", "hitl", "mcp", "ventanilla")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS latencias (
    flujo TEXT NOT NULL,
    ms REAL NOT NULL,
    cache INTEGER NOT NULL DEFAULT 0,
    creado TEXT NOT NULL
);
"""

_candado = threading.Lock()


@dataclass
class Medicion:
    """Corrida en curso.

    Quien mide puede marcar `cache` al saber el resultado, o poner `guardar` en
    False para no contar una petición rechazada (por ejemplo, una pregunta vacía).
    """

    flujo: str
    cache: bool = False
    guardar: bool = True
    ms: float | None = None


def ruta_por_defecto(raiz: Path) -> Path:
    """Devuelve ``<raiz>/data/asistente/latencias.sqlite``.

    Args:
        raiz: carpeta raíz del proyecto.

    Returns:
        La ruta de la base de latencias.
    """
    return raiz / RUTA_LATENCIAS


def registrar(
    flujo: str,
    ms: float,
    *,
    cache: bool = False,
    ruta: Path | None,
    ahora: datetime | None = None,
) -> bool:
    """Guarda una corrida en la tabla ``latencias``.

    Args:
        flujo: uno de `FLUJOS`.
        ms: duración en milisegundos.
        cache: True si respondió la caché.
        ruta: base ``latencias.sqlite``; con ``None`` no se guarda nada.
        ahora: hora de la corrida; por defecto la actual en Bogotá.

    Returns:
        True si se guardó; False sin ruta o si falló la escritura.

    Raises:
        ValueError: si el flujo no es uno de `FLUJOS` o los milisegundos son
            negativos.
    """
    if flujo not in FLUJOS:
        raise ValueError(f"flujo desconocido: {flujo}")
    if ms < 0:
        raise ValueError("la latencia no puede ser negativa")
    if ruta is None:
        return False
    destino = ruta
    creado = (ahora or datetime.now(ZONA_HORARIA)).astimezone(ZONA_HORARIA)
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with _candado, closing(sqlite3.connect(destino, timeout=5)) as conexion:
            conexion.executescript(ESQUEMA)
            conexion.execute(
                "INSERT INTO latencias (flujo, ms, cache, creado) VALUES (?, ?, ?, ?)",
                (flujo, round(ms, 3), int(cache), creado.isoformat(timespec="seconds")),
            )
            conexion.commit()
    except (OSError, sqlite3.Error) as error:
        LOGGER.warning("evento=latencia_no_guardada flujo=%s error=%s", flujo, type(error).__name__)
        return False
    return True


@contextmanager
def medir(flujo: str, cache: bool = False, *, ruta: Path | None = None) -> Generator[Medicion]:
    """Mide el bloque y guarda la corrida al salir, aunque el bloque falle.

    Si el bloque marca ``corrida.guardar = False``, la duración se calcula pero
    no se guarda.

    Uso::

        with medir("ventanilla", ruta=base) as corrida:
            respuesta = servicio.preguntar(...)
            corrida.cache = respuesta["cache"]

    Args:
        flujo: uno de `FLUJOS`.
        cache: valor inicial de la marca de caché.
        ruta: base ``latencias.sqlite``; con ``None`` solo mide.

    Yields:
        La corrida en curso; al salir trae ``ms``.

    Raises:
        ValueError: si el flujo no es uno de `FLUJOS` (antes de ejecutar el bloque).
    """
    if flujo not in FLUJOS:
        raise ValueError(f"flujo desconocido: {flujo}")
    corrida = Medicion(flujo=flujo, cache=cache)
    inicio = time.perf_counter()
    try:
        yield corrida
    finally:
        corrida.ms = (time.perf_counter() - inicio) * 1000
        if corrida.guardar:
            registrar(flujo, corrida.ms, cache=corrida.cache, ruta=ruta)


def con_latencia[**P, R](
    flujo: str, funcion: Callable[P, R], *, ruta: Path | None
) -> Callable[P, R]:
    """Envuelve una función para medir cada llamada como `flujo`.

    Args:
        flujo: uno de `FLUJOS`.
        funcion: función que se mide, por ejemplo `Despachador.procesar`.
        ruta: base ``latencias.sqlite``; con ``None`` solo mide.

    Returns:
        Una función con la misma firma que mide y delega.
    """

    def medida(*args: P.args, **kwargs: P.kwargs) -> R:
        """Llama a la función original dentro de `medir`."""
        with medir(flujo, ruta=ruta):
            return funcion(*args, **kwargs)

    medida.__doc__ = funcion.__doc__
    medida.__name__ = getattr(funcion, "__name__", "medida")
    return medida


def _flujo_json(latencia: LatenciaFlujo) -> dict[str, Any]:
    """Convierte los percentiles de un flujo al formato de ``arqueo.json``."""
    return {
        "p50_ms": round(latencia.p50_ms, 1),
        "p95_ms": round(latencia.p95_ms, 1),
        "n": latencia.n,
        "suficiente": latencia.suficiente,
    }


def seccion_latencia(ruta: Path) -> dict[str, Any]:
    """Arma la sección ``latencia`` de ``arqueo.json`` a partir de la base.

    Las corridas de caché van aparte para no mezclar tiempos que no pasan por
    el modelo. Un flujo con menos de `MINIMO_CORRIDAS` corridas queda con
    ``suficiente: false`` y el reporte no presenta su percentil como resultado.

    Args:
        ruta: base ``latencias.sqlite``; si no existe, la sección queda vacía.

    Returns:
        ``{"minimo_corridas", "sin_cache", "con_cache"}``.
    """
    normales, con_cache = resumen_latencias(ruta)
    return {
        "minimo_corridas": MINIMO_CORRIDAS,
        "sin_cache": {flujo: _flujo_json(valor) for flujo, valor in normales.items()},
        "con_cache": {flujo: _flujo_json(valor) for flujo, valor in con_cache.items()},
    }


def _fila_markdown(flujo: str, datos: Mapping[str, Any]) -> str:
    """Una fila de la tabla de latencia; sin muestra suficiente no da percentiles."""
    if datos.get("suficiente"):
        return f"| {flujo} | {datos['n']} | {datos['p50_ms']:.1f} | {datos['p95_ms']:.1f} |"
    return f"| {flujo} | {datos['n']} | no concluyente | no concluyente |"


def markdown_latencia(seccion: Mapping[str, Any] | None) -> list[str]:
    """Escribe la sección «Latencia» de ``docs/ARQUEO.md``.

    Args:
        seccion: el bloque ``latencia`` de ``arqueo.json``.

    Returns:
        Las líneas de la sección, listas para unir con saltos de línea.
    """
    lineas = ["## Latencia", ""]
    datos = seccion or {}
    minimo = int(datos.get("minimo_corridas", MINIMO_CORRIDAS))
    sin_cache: Mapping[str, Any] = datos.get("sin_cache") or {}
    con_cache: Mapping[str, Any] = datos.get("con_cache") or {}
    if not sin_cache and not con_cache:
        lineas += [
            "Todavía no hay corridas medidas en `data/asistente/latencias.sqlite`. "
            "Se llenan al usar la app (`make app`) con el canal y la Ventanilla.",
            "",
        ]
        return lineas
    lineas += [
        f"Percentil nearest-rank en milisegundos. Con menos de {minimo} corridas el "
        "flujo se marca como no concluyente y no se informa su percentil.",
        "",
    ]
    for titulo, tabla in (("Sin caché", sin_cache), ("Con caché", con_cache)):
        if not tabla:
            continue
        lineas += [f"### {titulo}", "", "| Flujo | n | p50 (ms) | p95 (ms) |", "|---|---|---|---|"]
        lineas += [_fila_markdown(flujo, tabla[flujo]) for flujo in sorted(tabla)]
        lineas.append("")
    return lineas
