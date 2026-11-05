"""Carga de la configuración de la Sucursal y del plano de embeddings.

La URL del cliente de Ollama se resuelve con `base_url` explícito en
`config/sucursal.toml`; `OLLAMA_BASE_URL` y, como último respaldo, `OLLAMA_HOST`
solo cubren el caso de no declararla. El módulo no hace peticiones de red.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..config import PROJECT_ROOT

#: Ruta por defecto de la configuración de la Sucursal.
RUTA_CONFIG: Path = PROJECT_ROOT / "config" / "sucursal.toml"
#: Modelo de embeddings servido por Ollama.
MODELO_POR_DEFECTO: str = "nomic-embed-text-v2-moe"
#: URL local de Ollama (escucha en 127.0.0.1, no en 0.0.0.0).
URL_POR_DEFECTO: str = "http://127.0.0.1:11434"
#: Segundos de espera por lote de embeddings. Cubre un lote de 64 en CPU sin GPU.
TIMEOUT_POR_DEFECTO: float = 300.0
#: Fragmentos que devuelve el recuperador cuando no se indica k.
K_POR_DEFECTO: int = 5
#: Peso del componente vectorial en el híbrido.
PESO_VECTORIAL_POR_DEFECTO: float = 0.6
#: Peso del componente BM25 en el híbrido.
PESO_BM25_POR_DEFECTO: float = 0.4
#: Prefijo que nomic espera al indexar documentos.
PREFIJO_DOCUMENTO: str = "search_document: "
#: Prefijo que nomic espera al consultar.
PREFIJO_CONSULTA: str = "search_query: "
#: Hosts de bind que se traducen a la dirección local del cliente.
_HOSTS_BIND: frozenset[str] = frozenset({"0.0.0.0", "::"})
#: Variables de entorno que se aceptan como respaldo de `base_url`, en orden.
VARIABLES_URL: tuple[str, ...] = ("OLLAMA_BASE_URL", "OLLAMA_HOST")


@dataclass(frozen=True, slots=True)
class ConfiguracionEmbeddings:
    """Parámetros del plano de embeddings locales."""

    modelo: str = MODELO_POR_DEFECTO
    base_url: str = URL_POR_DEFECTO
    prefijos: bool = True
    timeout: float = TIMEOUT_POR_DEFECTO


@dataclass(frozen=True, slots=True)
class ConfiguracionRecuperacion:
    """Parámetros del recuperador híbrido de la Bóveda."""

    k: int = K_POR_DEFECTO
    peso_vectorial: float = PESO_VECTORIAL_POR_DEFECTO
    peso_bm25: float = PESO_BM25_POR_DEFECTO


def normalizar_base_url(valor: str) -> str:
    """Normaliza la URL de Ollama y traduce un host de bind a uno alcanzable.

    Args:
        valor: URL o `host:puerto` sin esquema.

    Returns:
        URL con esquema `http`/`https`, host alcanzable, puerto y sin barra final.

    Raises:
        ValueError: si el valor está vacío, el esquema no es HTTP(S) o falta el host.
    """
    texto = valor.strip()
    if not texto:
        raise ValueError("base_url de Ollama vacía: define config/sucursal.toml o OLLAMA_HOST")
    if "://" not in texto:
        texto = f"http://{texto}"

    partes = urlsplit(texto)
    if partes.scheme not in {"http", "https"}:
        raise ValueError(
            f"base_url de Ollama debe usar http o https, no {partes.scheme!r}: {valor!r}"
        )
    host = partes.hostname
    if not host:
        raise ValueError(f"base_url de Ollama sin host: {valor!r}")
    if host in _HOSTS_BIND:
        host = "127.0.0.1"
    try:
        puerto = partes.port
    except ValueError as error:
        raise ValueError(f"base_url de Ollama con puerto inválido: {valor!r}") from error

    destino = f"[{host}]" if ":" in host else host
    if puerto is not None:
        destino = f"{destino}:{puerto}"
    ruta = partes.path.rstrip("/")
    return f"{partes.scheme}://{destino}{ruta}"


def url_de_entorno() -> str | None:
    """Devuelve la primera URL declarada en el entorno, si existe."""
    for variable in VARIABLES_URL:
        valor = os.getenv(variable, "").strip()
        if valor:
            return valor
    return None


def cargar_configuracion_embeddings(ruta: Path | None = None) -> ConfiguracionEmbeddings:
    """Carga `[embeddings]` de `config/sucursal.toml` con respaldo en el entorno.

    Args:
        ruta: archivo TOML alternativo; por defecto `config/sucursal.toml`.

    Returns:
        La configuración tipada del plano de embeddings.

    Raises:
        ValueError: si una clave tiene un tipo o un valor inválido.
    """
    archivo = RUTA_CONFIG if ruta is None else ruta
    datos: dict[str, Any] = {}
    if archivo.exists():
        with archivo.open("rb") as fh:
            datos = dict(tomllib.load(fh).get("embeddings", {}))

    modelo = datos.get("modelo", MODELO_POR_DEFECTO)
    if not isinstance(modelo, str) or not modelo.strip():
        raise ValueError("embeddings.modelo debe ser un texto no vacío")

    base_url = datos.get("base_url", url_de_entorno() or URL_POR_DEFECTO)
    if not isinstance(base_url, str):
        raise ValueError("embeddings.base_url debe ser un texto")

    prefijos = datos.get("prefijos", True)
    if not isinstance(prefijos, bool):
        raise ValueError("embeddings.prefijos debe ser true o false")

    timeout = datos.get("timeout_segundos", TIMEOUT_POR_DEFECTO)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError("embeddings.timeout_segundos debe ser un número mayor que cero")

    return ConfiguracionEmbeddings(
        modelo=modelo.strip(),
        base_url=normalizar_base_url(base_url),
        prefijos=prefijos,
        timeout=float(timeout),
    )


def cargar_configuracion_recuperacion(ruta: Path | None = None) -> ConfiguracionRecuperacion:
    """Carga `[recuperacion]` de `config/sucursal.toml`.

    Args:
        ruta: archivo TOML alternativo; por defecto `config/sucursal.toml`.

    Returns:
        La configuración tipada del recuperador híbrido.

    Raises:
        ValueError: si k no es positivo, un peso es negativo o la suma es cero.
    """
    archivo = RUTA_CONFIG if ruta is None else ruta
    datos: dict[str, Any] = {}
    if archivo.exists():
        with archivo.open("rb") as fh:
            datos = dict(tomllib.load(fh).get("recuperacion", {}))

    k = datos.get("k", K_POR_DEFECTO)
    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("recuperacion.k debe ser un entero mayor que cero")

    pesos: dict[str, float] = {}
    for nombre, defecto in (
        ("peso_vectorial", PESO_VECTORIAL_POR_DEFECTO),
        ("peso_bm25", PESO_BM25_POR_DEFECTO),
    ):
        valor = datos.get(nombre, defecto)
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or valor < 0:
            raise ValueError(f"recuperacion.{nombre} debe ser un número mayor o igual a cero")
        pesos[nombre] = float(valor)

    if pesos["peso_vectorial"] + pesos["peso_bm25"] <= 0:
        raise ValueError(
            "recuperacion.peso_vectorial + recuperacion.peso_bm25 debe ser mayor que cero"
        )

    return ConfiguracionRecuperacion(
        k=k,
        peso_vectorial=pesos["peso_vectorial"],
        peso_bm25=pesos["peso_bm25"],
    )
