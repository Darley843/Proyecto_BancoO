"""Configuración de la Sucursal: tope de gasto, caché y modo demo."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT

#: Ruta de la configuración de la fase 2.
RUTA_CONFIG_SUCURSAL: Path = PROJECT_ROOT / "config" / "sucursal.toml"
#: Tope diario por defecto, en USD.
TOPE_POR_DEFECTO: float = 0.20
#: TTL por defecto de la caché de respuestas, en segundos.
TTL_POR_DEFECTO: int = 3600


@dataclass(frozen=True, slots=True)
class ConfiguracionSucursal:
    """Parámetros de operación de la Sucursal."""

    tope_diario_usd: float = TOPE_POR_DEFECTO
    cache_ttl_segundos: int = TTL_POR_DEFECTO
    demo: bool = False


def cargar_configuracion_sucursal(ruta: Path | None = None) -> ConfiguracionSucursal:
    """Carga `[sucursal]` y lee `SUCURSAL_DEMO` del entorno.

    Args:
        ruta: archivo TOML alternativo; por defecto `config/sucursal.toml`.

    Returns:
        La configuración tipada de la Sucursal.

    Raises:
        ValueError: si el tope o el TTL no son válidos.
    """
    archivo = RUTA_CONFIG_SUCURSAL if ruta is None else ruta
    datos: dict[str, Any] = {}
    if archivo.exists():
        with archivo.open("rb") as fh:
            datos = dict(tomllib.load(fh).get("sucursal", {}))

    tope = datos.get("tope_diario_usd", TOPE_POR_DEFECTO)
    if isinstance(tope, bool) or not isinstance(tope, (int, float)) or tope <= 0:
        raise ValueError("sucursal.tope_diario_usd debe ser un número mayor que cero")

    ttl = datos.get("cache_ttl_segundos", TTL_POR_DEFECTO)
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 0:
        raise ValueError("sucursal.cache_ttl_segundos debe ser un entero mayor o igual a cero")

    return ConfiguracionSucursal(
        tope_diario_usd=float(tope),
        cache_ttl_segundos=ttl,
        demo=modo_demo(),
    )


def modo_demo() -> bool:
    """Indica si `SUCURSAL_DEMO` activa el modo sin modelo."""
    return os.getenv("SUCURSAL_DEMO", "").strip().casefold() in {"1", "true", "si", "sí"}


def tope_efectivo(configuracion: ConfiguracionSucursal) -> float:
    """Devuelve el tope del día, con `SUCURSAL_TOPE_USD` como sobrescritura."""
    crudo = os.getenv("SUCURSAL_TOPE_USD", "").strip()
    if not crudo:
        return configuracion.tope_diario_usd
    try:
        valor = float(crudo.replace(",", "."))
    except ValueError as error:
        raise ValueError("SUCURSAL_TOPE_USD debe ser un número") from error
    if valor <= 0:
        raise ValueError("SUCURSAL_TOPE_USD debe ser mayor que cero")
    return valor
