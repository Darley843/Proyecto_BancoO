"""Descarga de los modelos de voz de Piper (``make voz-modelo``).

Baja ``<modelo>.onnx`` y ``<modelo>.onnx.json`` del repositorio público de voces
de Piper en Hugging Face (``rhasspy/piper-voices``), una sola vez por modelo.

No es scraping del sitio del banco, así que no pasa por ``net.py`` ni aplica
``robots.txt`` ni la pausa de 1,5 s (igual que la API de Meta en
``canal/envio.py``). Sí cumple el resto de la regla HTTP del proyecto:
``httpx`` con ``timeout`` explícito, el User-Agent de ``config/site.toml``, el
header ``From`` y nunca ``verify=False``. Usa la misma ruta que el descargador
oficial de Piper (`REVISION_VOCES`).

El archivo se escribe primero como ``.parcial`` y se renombra al terminar: una
descarga cortada no deja un modelo dañado que parezca listo.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

import httpx

LOGGER = logging.getLogger(__name__)

#: Repositorio público de voces de Piper.
BASE_VOCES = "https://huggingface.co/rhasspy/piper-voices/resolve"
#: Revisión del repositorio; es la que usa ``piper.download_voices`` 1.x.
REVISION_VOCES = "main"
#: Segundos sin recibir datos antes de abandonar (por lectura, no total).
TIMEOUT_SEGUNDOS = 30.0
#: Tamaño de cada bloque escrito a disco.
BLOQUE = 1024 * 1024
#: Forma de un nombre de voz: ``es_MX-ald-medium``.
_NOMBRE = re.compile(
    r"^(?P<idioma>[a-z]{2,3})_(?P<pais>[A-Z]{2})-(?P<voz>[a-z0-9_]+)"
    r"-(?P<calidad>x_low|low|medium|high)$"
)


class ErrorDescarga(RuntimeError):
    """No se pudo bajar un modelo de voz."""


def urls_del_modelo(modelo: str) -> tuple[str, str]:
    """Arma las URL del ``.onnx`` y del ``.onnx.json`` de una voz.

    Args:
        modelo: nombre de la voz, por ejemplo ``es_MX-ald-medium``.

    Returns:
        (url del modelo, url de su configuración).

    Raises:
        ValueError: si el nombre no tiene la forma ``idioma_PAIS-voz-calidad``.
    """
    partes = _NOMBRE.match(modelo)
    if partes is None:
        raise ValueError(f"nombre de voz inválido: {modelo}")
    ruta = (
        f"{BASE_VOCES}/{REVISION_VOCES}/{partes['idioma']}/"
        f"{partes['idioma']}_{partes['pais']}/{partes['voz']}/{partes['calidad']}/{modelo}"
    )
    return f"{ruta}.onnx", f"{ruta}.onnx.json"


def _bajar(cliente: httpx.Client, url: str, destino: Path) -> None:
    """Baja una URL a un archivo, pasando por ``.parcial``."""
    parcial = destino.with_name(destino.name + ".parcial")
    try:
        with cliente.stream("GET", url, follow_redirects=True) as respuesta:
            if respuesta.status_code != 200:
                raise ErrorDescarga(f"{destino.name}: HTTP {respuesta.status_code}")
            with parcial.open("wb") as archivo:
                for bloque in respuesta.iter_bytes(BLOQUE):
                    archivo.write(bloque)
    except httpx.HTTPError as error:
        parcial.unlink(missing_ok=True)
        raise ErrorDescarga(f"{destino.name}: {type(error).__name__}") from error
    except ErrorDescarga:
        parcial.unlink(missing_ok=True)
        raise
    parcial.replace(destino)


def descargar_modelos(
    modelos: tuple[str, ...] | list[str],
    carpeta: Path,
    *,
    user_agent: str,
    remitente: str,
    crear_cliente: Callable[..., httpx.Client] = httpx.Client,
) -> list[str]:
    """Baja los modelos que falten en ``carpeta``.

    Args:
        modelos: nombres de voz de Piper.
        carpeta: dónde quedan ``<modelo>.onnx`` y ``<modelo>.onnx.json``.
        user_agent: User-Agent del proyecto (``config/site.toml``).
        remitente: header ``From`` del proyecto (``site.contact``).
        crear_cliente: fábrica del cliente HTTP (las pruebas pasan uno falso).

    Returns:
        Los modelos que se bajaron en esta llamada (los ya presentes no).

    Raises:
        ValueError: si falta ``remitente`` o un nombre no es válido.
        ErrorDescarga: si un archivo no se pudo bajar.
    """
    if not remitente.strip():
        raise ValueError("falta site.contact: el proyecto no hace peticiones sin el header From")
    carpeta.mkdir(parents=True, exist_ok=True)
    bajados: list[str] = []
    encabezados = {"User-Agent": user_agent, "From": remitente.strip()}
    with crear_cliente(timeout=TIMEOUT_SEGUNDOS, headers=encabezados) as cliente:
        for modelo in modelos:
            url_modelo, url_config = urls_del_modelo(modelo)
            onnx = carpeta / f"{modelo}.onnx"
            config = carpeta / f"{modelo}.onnx.json"
            if onnx.exists() and config.exists():
                continue
            LOGGER.info("evento=voz_descarga modelo=%s", modelo)
            _bajar(cliente, url_config, config)
            _bajar(cliente, url_modelo, onnx)
            bajados.append(modelo)
    return bajados
