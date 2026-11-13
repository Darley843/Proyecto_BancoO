"""Rutas y nombres de los almacenes vectoriales de la Bóveda.

El módulo no importa `almacen.py` ni `indice.py`: solo resuelve carpetas. Así el
almacén puede conocer su ubicación sin crear un ciclo de importaciones.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ..config import Config

#: Nombre del archivo de metadatos del índice.
NOMBRE_METADATOS: str = "indice.json"
#: Carpeta del índice persistente de Qdrant (almacén por defecto).
NOMBRE_QDRANT: str = "qdrant"
#: Carpeta del índice persistente de Chroma (opción de compatibilidad).
NOMBRE_CHROMA: str = "chroma"
#: Tipos de almacén admitidos por la Bóveda.
TipoAlmacen = Literal["qdrant", "chroma"]

#: Carpeta de cada tipo de almacén dentro de `data/boveda/`.
CARPETAS: dict[str, str] = {
    "qdrant": NOMBRE_QDRANT,
    "chroma": NOMBRE_CHROMA,
}


def carpeta_boveda(config: Config) -> Path:
    """Devuelve `data/boveda` para el proyecto configurado."""
    return config.paths.root / "data" / "boveda"


def ruta_metadatos(config: Config) -> Path:
    """Devuelve la ruta de `data/boveda/indice.json`."""
    return carpeta_boveda(config) / NOMBRE_METADATOS


def ruta_almacen(config: Config, tipo: TipoAlmacen | None = None) -> Path:
    """Devuelve la carpeta del almacén pedido, por defecto el configurado.

    Args:
        config: configuración con las rutas del corpus.
        tipo: `qdrant` o `chroma`; si falta, se lee `[almacen].tipo`.

    Returns:
        La carpeta persistente del almacén.
    """
    if tipo is None:
        from .configuracion import cargar_configuracion_almacen

        tipo = cargar_configuracion_almacen().tipo
    return ruta_almacen_en(carpeta_boveda(config), tipo)


def ruta_almacen_en(carpeta: Path, tipo: TipoAlmacen) -> Path:
    """Devuelve la carpeta del almacén `tipo` dentro de una carpeta de índice."""
    return carpeta / CARPETAS[tipo]
