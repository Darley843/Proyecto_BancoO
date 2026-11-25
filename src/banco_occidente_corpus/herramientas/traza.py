"""Traza local de las herramientas del agente `pana`.

Cada llamada deja una línea JSON en ``data/asistente/trazas/herramientas.jsonl``
(carpeta ignorada por Git) con el nombre, la latencia, el resultado y un resumen
no sensible de los argumentos. Los textos libres nunca se guardan: solo su
longitud. Así la traza se puede mostrar en vivo sin exponer la conversación de
un invitado.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import wraps
from inspect import BoundArguments, signature
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from .comun import error, mensaje_de_validacion
from .esquemas import SalidaHerramienta

#: Variables de entorno con las que las pruebas aíslan la traza.
VARIABLE_CARPETA: str = "CORPUS_TRAZA_DIR"
#: Nombre del archivo de traza dentro de la carpeta.
ARCHIVO_TRAZA: str = "herramientas.jsonl"
#: Campos cuyo valor es texto libre y no se registra.
CAMPOS_TEXTO: frozenset[str] = frozenset(
    {
        "consulta",
        "pregunta",
        "texto",
        "mensaje",
        "respuesta",
        "nombre",
        "empresa",
        "motivo",
        "producto",
        "campo",
    }
)
#: Largo máximo de un valor textual que sí se considera seguro.
LARGO_SEGURO: int = 32

_CANDADO = threading.Lock()


@dataclass(frozen=True, slots=True)
class RegistroTraza:
    """Una llamada registrada a una herramienta del catálogo."""

    id: str
    momento: str
    herramienta: str
    ok: bool
    codigo: str | None
    latencia_ms: float
    argumentos: dict[str, Any] = field(default_factory=dict)


def carpeta_de_traza() -> Path:
    """Devuelve la carpeta de trazas, respetando la variable de entorno.

    Returns:
        La carpeta por defecto ``data/asistente/trazas`` o la que fije
        ``CORPUS_TRAZA_DIR``.
    """
    return Path(os.environ.get(VARIABLE_CARPETA, "data/asistente/trazas"))


def ruta_de_traza() -> Path:
    """Devuelve el archivo JSONL de la traza.

    Returns:
        La ruta completa del archivo de traza.
    """
    return carpeta_de_traza() / ARCHIVO_TRAZA


def _resumen(posicion: BoundArguments) -> dict[str, Any]:
    """Resume los argumentos sin guardar textos libres ni huellas completas."""
    resumen: dict[str, Any] = {}
    for nombre, valor in posicion.arguments.items():
        if valor is None or isinstance(valor, (bool, int, float)):
            resumen[nombre] = valor
        elif nombre == "usuario_id" and isinstance(valor, str):
            resumen[nombre] = f"{valor[:12]}…"
        elif isinstance(valor, (list, tuple, set, frozenset)):
            resumen[nombre] = f"{len(valor)} elemento(s)"
        elif isinstance(valor, dict):
            resumen[nombre] = f"{len(valor)} clave(s)"
        elif nombre in CAMPOS_TEXTO or not isinstance(valor, str) or len(valor) > LARGO_SEGURO:
            resumen[nombre] = f"{len(str(valor))} caracteres"
        else:
            resumen[nombre] = str(valor)
    return resumen


def registrar(
    herramienta: str,
    argumentos: dict[str, Any],
    salida: SalidaHerramienta,
    latencia_ms: float,
) -> RegistroTraza:
    """Guarda una línea de traza y devuelve el registro con su id.

    Args:
        herramienta: nombre del catálogo.
        argumentos: resumen no sensible de los argumentos.
        salida: sobre que devolvió la herramienta.
        latencia_ms: duración de la llamada en milisegundos.

    Returns:
        El registro escrito, con su identificador para la respuesta.
    """
    registro = RegistroTraza(
        id=uuid4().hex[:12],
        momento=datetime.now(UTC).isoformat(timespec="seconds"),
        herramienta=herramienta,
        ok=salida.ok,
        codigo=salida.error.codigo if salida.error is not None else None,
        latencia_ms=round(latencia_ms, 3),
        argumentos=argumentos,
    )
    ruta = ruta_de_traza()
    with _CANDADO:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open("a", encoding="utf-8", newline="\n") as archivo:
            archivo.write(json.dumps(asdict(registro), ensure_ascii=False) + "\n")
    return registro


def ultimas(cantidad: int = 20) -> list[RegistroTraza]:
    """Lee las últimas llamadas registradas.

    Args:
        cantidad: número de registros a devolver.

    Returns:
        Los registros más recientes, del más viejo al más nuevo; vacío si no
        hay traza todavía.
    """
    if cantidad <= 0:
        return []
    ruta = ruta_de_traza()
    if not ruta.exists():
        return []
    with ruta.open(encoding="utf-8") as archivo:
        lineas = archivo.readlines()
    registros: list[RegistroTraza] = []
    for linea in lineas[-cantidad:]:
        try:
            datos = json.loads(linea)
        except json.JSONDecodeError:
            continue
        registros.append(
            RegistroTraza(
                id=str(datos.get("id", "")),
                momento=str(datos.get("momento", "")),
                herramienta=str(datos.get("herramienta", "")),
                ok=bool(datos.get("ok", False)),
                codigo=datos.get("codigo"),
                latencia_ms=float(datos.get("latencia_ms", 0.0)),
                argumentos=dict(datos.get("argumentos", {})),
            )
        )
    return registros


def con_traza(
    herramienta: str,
    funcion: Callable[..., SalidaHerramienta],
) -> Callable[..., SalidaHerramienta]:
    """Envuelve una herramienta para validar, medir y registrar cada llamada.

    Args:
        herramienta: nombre del catálogo.
        funcion: herramienta que devuelve el sobre común.

    Returns:
        Una función con la misma firma que además escribe la traza y adjunta su
        ``traza_id`` a la respuesta.
    """
    firma = signature(funcion)

    @wraps(funcion)
    def envuelta(*args: Any, **kwargs: Any) -> SalidaHerramienta:
        inicio = time.perf_counter()
        try:
            salida = funcion(*args, **kwargs)
        except ValidationError as exc:
            salida = error(herramienta, "entrada_invalida", mensaje_de_validacion(exc))
        except (ValueError, LookupError) as exc:
            salida = error(herramienta, "entrada_invalida", str(exc))
        except Exception as exc:  # noqa: BLE001 - la traza nunca rompe el turno
            salida = error(
                herramienta,
                "fallo_interno",
                f"No se pudo ejecutar {herramienta} ({type(exc).__name__}).",
            )
        latencia = (time.perf_counter() - inicio) * 1000
        try:
            argumentos = _resumen(firma.bind(*args, **kwargs))
        except TypeError:
            argumentos = {}
        try:
            registro = registrar(herramienta, argumentos, salida, latencia)
        except OSError:
            return salida
        return salida.model_copy(update={"traza_id": registro.id})

    return envuelta


def main() -> int:
    """Imprime las últimas llamadas de la traza local, sin datos personales.

    Returns:
        Código de salida de la consola.
    """
    registros = ultimas(20)
    if not registros:
        print(f"No hay traza todavía en {ruta_de_traza()}.")
        return 0
    print(f"Últimas {len(registros)} llamadas a las herramientas ({ruta_de_traza()}):")
    for registro in registros:
        estado = "ok" if registro.ok else f"error:{registro.codigo}"
        print(
            f"- {registro.momento} {registro.herramienta} {estado} "
            f"{registro.latencia_ms:.1f} ms args={registro.argumentos} id={registro.id}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
