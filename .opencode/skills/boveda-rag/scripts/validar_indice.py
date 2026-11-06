"""Valida que `data/boveda/indice.json` coincida con la colección real de Chroma.

Uso:
    uv run python .opencode/skills/boveda-rag/scripts/validar_indice.py

Comprueba el conteo de fragmentos, la métrica coseno, la dimensión de 768, el
modelo de embeddings y la bandera de prefijos. Sale con código 1 si falta el
índice o si alguna comprobación no coincide. No escribe en `data/boveda/` ni
hace peticiones de red.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from banco_occidente_corpus.boveda.almacen import (
    COLECCION_POR_DEFECTO,
    METRICA_POR_DEFECTO,
)
from banco_occidente_corpus.boveda.configuracion import (
    cargar_configuracion_embeddings,
)
from banco_occidente_corpus.config import PROJECT_ROOT

#: Dimensión que produce `nomic-embed-text-v2-moe`.
DIMENSION_ESPERADA: int = 768
#: Carpeta por defecto del índice no versionado.
CARPETA_BOVEDA: Path = PROJECT_ROOT / "data" / "boveda"
#: Nombre del archivo de metadatos del índice.
NOMBRE_METADATOS: str = "indice.json"
#: Nombre de la carpeta persistente de Chroma.
NOMBRE_ALMACEN: str = "chroma"
#: Alcances admitidos por `boveda/indice.py`.
ALCANCES: frozenset[str] = frozenset({"base", "completo"})


@dataclass(frozen=True, slots=True)
class Comprobacion:
    """Resultado de comparar un valor del índice con el valor esperado."""

    nombre: str
    obtenido: str
    esperado: str
    ok: bool
    detalle: str = ""


def leer_metadatos(ruta: Path) -> dict[str, Any]:
    """Lee `indice.json` y comprueba que sea un objeto JSON.

    Raises:
        FileNotFoundError: si el archivo no existe.
        ValueError: si el contenido no es un objeto JSON.
    """
    if not ruta.exists():
        raise FileNotFoundError(
            f"No hay metadatos en {ruta}: ejecuta `make indice` o `make indice-completo`."
        )
    datos: Any = json.loads(ruta.read_text(encoding="utf-8"))
    if not isinstance(datos, dict):
        raise ValueError(f"{ruta} no contiene un objeto JSON")
    return datos


def abrir_coleccion(ruta: Path) -> Any | None:
    """Abre la colección existente de Chroma en modo lectura.

    Devuelve `None` si la carpeta no existe, si Chroma no puede abrirla o si la
    colección `boveda` no está creada. No crea una colección vacía.
    """
    if not ruta.exists():
        return None
    try:
        import chromadb

        cliente = chromadb.PersistentClient(path=str(ruta))
        return cliente.get_collection(
            name=COLECCION_POR_DEFECTO,
            embedding_function=None,
        )
    except Exception:
        return None


def contar_coleccion(coleccion: Any) -> int:
    """Devuelve el número de vectores almacenados en la colección."""
    return int(coleccion.count())


def metrica_coleccion(coleccion: Any) -> str:
    """Devuelve la métrica declarada por la colección (`hnsw:space`)."""
    metadatos = getattr(coleccion, "metadata", None) or {}
    return str(metadatos.get("hnsw:space", ""))


def dimension_coleccion(coleccion: Any) -> int:
    """Devuelve la dimensión del primer vector almacenado, o 0 si está vacía."""
    resultado = coleccion.get(limit=1, include=["embeddings"])
    vectores = resultado.get("embeddings")
    if vectores is None or len(vectores) == 0:
        return 0
    return len(vectores[0])


def revisar_indice(
    metadatos: dict[str, Any],
    *,
    conteo: int,
    metrica: str,
    dimension: int,
    modelo_config: str,
    prefijos_config: bool,
) -> list[Comprobacion]:
    """Compara los metadatos del índice con la colección y la configuración."""
    esperados = {"modelo", "prefijos", "alcance", "fragmentos", "dimension"}
    faltantes = sorted(esperados - set(metadatos))
    comprobaciones: list[Comprobacion] = [
        Comprobacion(
            nombre="campos de indice.json",
            obtenido=", ".join(sorted(metadatos)),
            esperado=", ".join(sorted(esperados)),
            ok=not faltantes,
            detalle=f"faltan: {', '.join(faltantes)}" if faltantes else "",
        )
    ]

    alcance = str(metadatos.get("alcance", ""))
    comprobaciones.append(
        Comprobacion(
            nombre="alcance",
            obtenido=alcance,
            esperado="base o completo",
            ok=alcance in ALCANCES,
        )
    )

    fragmentos = metadatos.get("fragmentos")
    comprobaciones.append(
        Comprobacion(
            nombre="fragmentos",
            obtenido=str(fragmentos),
            esperado=str(conteo),
            ok=isinstance(fragmentos, int) and fragmentos == conteo,
            detalle="vuelve a ejecutar `make indice` si no coinciden",
        )
    )

    dimension_json = metadatos.get("dimension")
    comprobaciones.append(
        Comprobacion(
            nombre="dimension del json",
            obtenido=str(dimension_json),
            esperado=str(DIMENSION_ESPERADA),
            ok=isinstance(dimension_json, int) and dimension_json == DIMENSION_ESPERADA,
        )
    )
    comprobaciones.append(
        Comprobacion(
            nombre="dimension real",
            obtenido=str(dimension),
            esperado=str(DIMENSION_ESPERADA),
            ok=dimension == DIMENSION_ESPERADA,
            detalle="el vector almacenado no mide 768",
        )
    )

    modelo = str(metadatos.get("modelo", ""))
    comprobaciones.append(
        Comprobacion(
            nombre="modelo",
            obtenido=modelo,
            esperado=modelo_config,
            ok=modelo == modelo_config,
            detalle="cambió el modelo; reindexa con `make indice`",
        )
    )

    prefijos = metadatos.get("prefijos")
    comprobaciones.append(
        Comprobacion(
            nombre="prefijos",
            obtenido=str(prefijos),
            esperado=str(prefijos_config),
            ok=isinstance(prefijos, bool) and prefijos == prefijos_config,
            detalle="cambió [embeddings].prefijos; reindexa con `make indice`",
        )
    )

    comprobaciones.append(
        Comprobacion(
            nombre="metrica de Chroma",
            obtenido=metrica,
            esperado=METRICA_POR_DEFECTO,
            ok=metrica == METRICA_POR_DEFECTO,
            detalle="la colección debe declarar hnsw:space=cosine",
        )
    )
    return comprobaciones


def comprobar(
    ruta_indice: Path | None = None,
    ruta_almacen: Path | None = None,
) -> tuple[list[Comprobacion], dict[str, Any]]:
    """Ejecuta todas las comprobaciones sobre el índice indicado.

    Args:
        ruta_indice: ruta de `indice.json`; por defecto `data/boveda/indice.json`.
        ruta_almacen: ruta de Chroma; por defecto `data/boveda/chroma`.

    Returns:
        Las comprobaciones y los metadatos leídos.

    Raises:
        FileNotFoundError: si falta el archivo de metadatos o la colección.
        ValueError: si el archivo de metadatos no tiene la forma esperada.
    """
    indice = CARPETA_BOVEDA / NOMBRE_METADATOS if ruta_indice is None else ruta_indice
    almacen = CARPETA_BOVEDA / NOMBRE_ALMACEN if ruta_almacen is None else ruta_almacen
    metadatos = leer_metadatos(indice)
    coleccion = abrir_coleccion(almacen)
    if coleccion is None:
        raise FileNotFoundError(
            f"No hay colección en {almacen}: ejecuta `make indice` o `make indice-completo`."
        )

    ajustes = cargar_configuracion_embeddings()
    comprobaciones = revisar_indice(
        metadatos,
        conteo=contar_coleccion(coleccion),
        metrica=metrica_coleccion(coleccion),
        dimension=dimension_coleccion(coleccion),
        modelo_config=ajustes.modelo,
        prefijos_config=ajustes.prefijos,
    )
    return comprobaciones, metadatos


def formatear(comprobaciones: Sequence[Comprobacion]) -> str:
    """Devuelve el texto legible de las comprobaciones."""
    lineas = ["Comprobación del índice de la Bóveda:", ""]
    for item in comprobaciones:
        estado = "OK   " if item.ok else "FALLA"
        linea = f"  {estado}  {item.nombre}: obtenido={item.obtenido} esperado={item.esperado}"
        if item.detalle and not item.ok:
            linea = f"{linea}  ({item.detalle})"
        lineas.append(linea)
    fallos = [item for item in comprobaciones if not item.ok]
    lineas.append("")
    if fallos:
        lineas.append(
            f"RESULTADO: FALLA ({len(fallos)} de {len(comprobaciones)} comprobaciones). "
            "Revisa `make indice` y `config/sucursal.toml`."
        )
    else:
        lineas.append(
            f"RESULTADO: OK ({len(comprobaciones)} comprobaciones). "
            "El índice coincide con Chroma y con la configuración."
        )
    return "\n".join(lineas)


def _configurar_salida() -> None:
    """Fuerza UTF-8 en la salida para que las tildes se vean en Windows."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta la validación y devuelve el código de salida."""
    _configurar_salida()
    parser = argparse.ArgumentParser(
        prog="validar_indice.py",
        description="Valida data/boveda/indice.json contra la colección de Chroma.",
    )
    parser.add_argument("--indice", type=Path, default=None, help="ruta de indice.json")
    parser.add_argument("--almacen", type=Path, default=None, help="ruta de la carpeta Chroma")
    args = parser.parse_args(argv)

    try:
        comprobaciones, _ = comprobar(args.indice, args.almacen)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(formatear(comprobaciones))
    return 0 if all(item.ok for item in comprobaciones) else 1


if __name__ == "__main__":
    raise SystemExit(main())
