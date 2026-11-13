"""Valida que `data/boveda/indice.json` coincida con la colección real del almacén.

Uso:
    uv run python .opencode/skills/boveda-rag/scripts/validar_indice.py

Comprueba el tipo de almacén, la colección, el conteo de fragmentos, la métrica
coseno, la dimensión de 768, el modelo de embeddings y la bandera de prefijos.
Sale con código 1 si falta el índice o si alguna comprobación no coincide. No
crea la colección, no escribe en `data/boveda/` y no hace peticiones de red.
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
    AlmacenBloqueado,
    AlmacenVectorial,
    cerrar_almacen,
    crear_almacen_en_ruta,
)
from banco_occidente_corpus.boveda.configuracion import (
    cargar_configuracion_almacen,
    cargar_configuracion_embeddings,
)
from banco_occidente_corpus.boveda.rutas import (
    NOMBRE_METADATOS,
    TipoAlmacen,
    ruta_almacen_en,
)
from banco_occidente_corpus.config import PROJECT_ROOT

#: Dimensión que produce `nomic-embed-text-v2-moe`.
DIMENSION_ESPERADA: int = 768
#: Carpeta por defecto del índice no versionado.
CARPETA_BOVEDA: Path = PROJECT_ROOT / "data" / "boveda"
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


def abrir_almacen(ruta: Path, tipo: TipoAlmacen) -> AlmacenVectorial | None:
    """Abre la colección existente en modo lectura, sin crearla.

    Devuelve `None` si la carpeta no existe, si el motor no puede abrirla o si la
    colección `boveda` no está creada. Propaga `AlmacenBloqueado` para que el
    mensaje de la app en marcha llegue intacto.
    """
    if not ruta.exists():
        return None
    try:
        almacen = crear_almacen_en_ruta(ruta, tipo)
        if not almacen.existe():
            cerrar_almacen(almacen)
            return None
        return almacen
    except AlmacenBloqueado:
        raise
    except Exception:
        return None


def contar_coleccion(almacen: AlmacenVectorial) -> int:
    """Devuelve el número de vectores almacenados en la colección."""
    return int(almacen.contar())


def metrica_coleccion(almacen: AlmacenVectorial) -> str:
    """Devuelve la métrica de distancia declarada por la colección."""
    return almacen.metrica_almacenada()


def dimension_coleccion(almacen: AlmacenVectorial) -> int:
    """Devuelve la dimensión de los vectores almacenados, o 0 si está vacía."""
    return int(almacen.dimension_almacenada())


def revisar_indice(
    metadatos: dict[str, Any],
    *,
    conteo: int,
    metrica: str,
    dimension: int,
    modelo_config: str,
    prefijos_config: bool,
    tipo_almacen: TipoAlmacen,
    nombres_coleccion: Sequence[str],
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

    declarado = metadatos.get("almacen")
    comprobaciones.append(
        Comprobacion(
            nombre="almacen declarado",
            obtenido=str(declarado) if declarado is not None else "sin declarar",
            esperado=tipo_almacen,
            ok=declarado is None or declarado == tipo_almacen,
            detalle=(
                "un indice.json anterior a la migración se acepta como compatible"
                if declarado is None
                else "el índice declara otro motor; ejecuta `make migrar-qdrant`"
            ),
        )
    )

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

    colecciones = ", ".join(nombres_coleccion) or "ninguna"
    comprobaciones.append(
        Comprobacion(
            nombre=f"coleccion de {tipo_almacen}",
            obtenido=colecciones,
            esperado=COLECCION_POR_DEFECTO,
            ok=COLECCION_POR_DEFECTO in nombres_coleccion,
        )
    )
    comprobaciones.append(
        Comprobacion(
            nombre=f"metrica de {tipo_almacen}",
            obtenido=metrica,
            esperado=METRICA_POR_DEFECTO,
            ok=metrica == METRICA_POR_DEFECTO,
            detalle="la colección debe declarar distancia coseno",
        )
    )
    return comprobaciones


def comprobar(
    ruta_indice: Path | None = None,
    ruta_almacen: Path | None = None,
    *,
    tipo: TipoAlmacen | None = None,
    almacen: AlmacenVectorial | None = None,
) -> tuple[list[Comprobacion], dict[str, Any]]:
    """Ejecuta todas las comprobaciones sobre el índice indicado.

    Args:
        ruta_indice: ruta de `indice.json`; por defecto `data/boveda/indice.json`.
        ruta_almacen: ruta de la carpeta del almacén; por defecto la configurada.
        tipo: `qdrant` o `chroma`; si falta, se lee `[almacen].tipo`.
        almacen: almacén ya abierto (pruebas); si falta, se abre en modo lectura.

    Returns:
        Las comprobaciones y los metadatos leídos.

    Raises:
        FileNotFoundError: si falta el archivo de metadatos o la colección.
        ValueError: si el archivo de metadatos no tiene la forma esperada.
        AlmacenBloqueado: si otro proceso tiene abierta la carpeta de Qdrant.
    """
    motor: TipoAlmacen = tipo or cargar_configuracion_almacen().tipo
    indice = CARPETA_BOVEDA / NOMBRE_METADATOS if ruta_indice is None else ruta_indice
    ubicacion = ruta_almacen_en(CARPETA_BOVEDA, motor) if ruta_almacen is None else ruta_almacen
    metadatos = leer_metadatos(indice)
    abierto = almacen is None
    destino = abrir_almacen(ubicacion, motor) if abierto else almacen
    if destino is None:
        raise FileNotFoundError(
            f"No hay colección de {motor} en {ubicacion}: ejecuta `make indice` "
            "o `make indice-completo`."
        )

    try:
        ajustes = cargar_configuracion_embeddings()
        comprobaciones = revisar_indice(
            metadatos,
            conteo=contar_coleccion(destino),
            metrica=metrica_coleccion(destino),
            dimension=dimension_coleccion(destino),
            modelo_config=ajustes.modelo,
            prefijos_config=ajustes.prefijos,
            tipo_almacen=motor,
            nombres_coleccion=[destino.coleccion],
        )
    finally:
        if abierto and destino is not None:
            cerrar_almacen(destino)
    return comprobaciones, metadatos


def formatear(comprobaciones: Sequence[Comprobacion], tipo: str = "") -> str:
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
    motor = tipo or "el almacén"
    if fallos:
        lineas.append(
            f"RESULTADO: FALLA ({len(fallos)} de {len(comprobaciones)} comprobaciones). "
            "Revisa `make indice` y `config/sucursal.toml`."
        )
    else:
        lineas.append(
            f"RESULTADO: OK ({len(comprobaciones)} comprobaciones). "
            f"El índice coincide con {motor} y con la configuración."
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
        description="Valida data/boveda/indice.json contra la colección del almacén.",
    )
    parser.add_argument("--indice", type=Path, default=None, help="ruta de indice.json")
    parser.add_argument(
        "--almacen",
        type=Path,
        default=None,
        help="ruta de la carpeta del almacén (qdrant o chroma)",
    )
    parser.add_argument(
        "--tipo",
        choices=("qdrant", "chroma"),
        default=None,
        help="motor del índice; por defecto el de config/sucursal.toml",
    )
    args = parser.parse_args(argv)

    try:
        comprobaciones, _ = comprobar(
            args.indice,
            args.almacen,
            tipo=args.tipo,
        )
    except AlmacenBloqueado as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    motor = args.tipo or cargar_configuracion_almacen().tipo
    print(formatear(comprobaciones, motor))
    return 0 if all(item.ok for item in comprobaciones) else 1


if __name__ == "__main__":
    raise SystemExit(main())
