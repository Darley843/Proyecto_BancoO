"""Pruebas de la configuración del canal y del diagnóstico.

La configuración no guarda secretos: los tokens viven en el entorno. Estas
pruebas fijan eso y comprueban que las huellas autorizadas son hexadecimales y
que el catálogo de productos y los umbrales están completos.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from banco_occidente_corpus.config import PROJECT_ROOT

RUTA_WHATSAPP = PROJECT_ROOT / "config" / "whatsapp.toml"
"""Configuración del canal, versionada y sin secretos."""

RUTA_DIAGNOSTICO = PROJECT_ROOT / "config" / "diagnostico.toml"
"""Umbrales del semáforo y catálogo de productos del diagnóstico."""

PATRON_HUELLA = re.compile(r"^[0-9a-f]{64}$")
"""Huella HMAC-SHA256 en hexadecimal minúscula."""

PATRON_TELEFONO = re.compile(r"\d{10,}")
"""Secuencia de diez o más dígitos: un número en claro, no una versión."""

CLAVES_PROHIBIDAS = ("token", "secret", "clave", "salt")
"""Fragmentos que delatan un secreto guardado en la configuración."""


def _cargar(ruta: Path) -> dict[str, Any]:
    """Carga un TOML del proyecto como diccionario."""
    with ruta.open("rb") as archivo:
        return dict(tomllib.load(archivo))


def _claves(datos: dict[str, Any]) -> list[str]:
    """Recorre el TOML y devuelve todas las claves, sin repetir."""
    encontradas: list[str] = []
    for clave, valor in datos.items():
        encontradas.append(clave)
        if isinstance(valor, dict):
            encontradas.extend(_claves(dict(valor)))
    return encontradas


def test_whatsapp_no_guarda_secretos_ni_numeros_en_claro() -> None:
    """El TOML del canal no lleva tokens, sal ni teléfonos en claro."""
    datos = _cargar(RUTA_WHATSAPP)
    sin_huellas = {clave: valor for clave, valor in datos.items() if clave != "autorizados"}

    sospechosas = [
        clave for clave in _claves(datos) if any(p in clave.casefold() for p in CLAVES_PROHIBIDAS)
    ]

    assert sospechosas == []
    assert PATRON_TELEFONO.search(json.dumps(sin_huellas, ensure_ascii=False)) is None


def test_hay_cinco_huellas_hexadecimales() -> None:
    """Los cinco números autorizados se guardan como huellas, no como números."""
    huellas = _cargar(RUTA_WHATSAPP)["autorizados"]["huellas"]

    assert len(huellas) == 5
    assert all(PATRON_HUELLA.match(huella) for huella in huellas)
    assert len(set(huellas)) == 5


def test_modo_del_canal_es_falso_o_real() -> None:
    """El canal arranca en modo falso salvo que se pida el real."""
    assert _cargar(RUTA_WHATSAPP)["canal"]["modo"] in {"falso", "real"}


def test_umbrales_del_semaforo_estan_ordenados() -> None:
    """Verde queda por debajo de amarillo y ambos dentro de 0 y 1."""
    umbrales = _cargar(RUTA_DIAGNOSTICO)["umbrales"]

    assert 0 < umbrales["verde_hasta"] < umbrales["amarillo_hasta"] < 1


def test_catalogo_de_productos_tiene_los_diez_del_diseno() -> None:
    """El catálogo cubre los diez productos del tarifario."""
    productos = _cargar(RUTA_DIAGNOSTICO)["productos"]

    assert set(productos) == {
        "libre_inversion",
        "compra_cartera",
        "credito_rotativo",
        "libranza",
        "vehiculo_nuevo",
        "vehiculo_usado",
        "vivienda",
        "tarjeta_credito",
        "ahorro",
        "cdt",
    }
    assert all(isinstance(nombre, str) and nombre for nombre in productos.values())
