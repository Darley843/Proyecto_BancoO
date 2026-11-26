"""Recursos de la pantalla (tecla G): QR del repositorio, WhatsApp y diagramas.

El QR del repositorio se dibuja en memoria con ``segno`` a partir de una URL
pública versionada. El número del canal no vive en el repositorio: se lee de la
variable de entorno ``PANA_WHATSAPP_NUMERO`` y solo se usa para dibujar su QR.
Sin la variable, la ruta dice que no está disponible y el navegador oculta el
bloque; el número nunca se escribe en un log, en un archivo versionado ni en la
respuesta JSON.

Los diagramas se sirven desde una lista cerrada de archivos de ``docs/``; el
router no expone el resto del repositorio. El túnel público solo deja pasar
``/webhooks/whatsapp`` y ``/health`` (``app.py``), así que estas rutas quedan
locales.

Las pruebas viven en ``test/test_escena_recursos.py``.
"""

from __future__ import annotations

import io
import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

import segno
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..config import PROJECT_ROOT

#: Repositorio público del proyecto. El QR y el botón abren esta dirección.
URL_REPOSITORIO = "https://github.com/Darley843/Proyecto_BancoO"
#: Variable de entorno con el número del canal, en formato internacional.
VARIABLE_NUMERO = "PANA_WHATSAPP_NUMERO"
#: Dígitos mínimos y máximos de un número en E.164 sin el signo ``+``.
LARGO_MINIMO = 10
LARGO_MAXIMO = 15
#: Diagramas generados con Archify que la app puede servir.
DIAGRAMAS: frozenset[str] = frozenset(
    {
        "arquitectura.html",
        "datos.html",
        "canal.html",
        "diagnostico.html",
        "agente-openclaw.html",
        "despliegue-openclaw.html",
    }
)


class WhatsappRespuesta(BaseModel):
    """Indica si el bloque de WhatsApp tiene número configurado."""

    disponible: bool = Field(description="Hay un número válido en el entorno.")


class RepositorioRespuesta(BaseModel):
    """URL pública del repositorio, para el botón del panel de recursos."""

    url: str = Field(description="Repositorio público del proyecto.")


def numero_whatsapp(entorno: Mapping[str, str] | None = None) -> str | None:
    """Lee y normaliza el número del canal desde el entorno.

    Args:
        entorno: variables de entorno alternativas para las pruebas; por
            defecto las del proceso.

    Returns:
        Los dígitos del número (sin ``+``, espacios ni guiones), o ``None`` si
        falta o no tiene entre 10 y 15 dígitos.
    """
    fuente = os.environ if entorno is None else entorno
    crudo = str(fuente.get(VARIABLE_NUMERO, ""))
    digitos = "".join(caracter for caracter in crudo if caracter in "0123456789")
    if not LARGO_MINIMO <= len(digitos) <= LARGO_MAXIMO:
        return None
    return digitos


def url_whatsapp(numero: str) -> str:
    """Arma el enlace ``wa.me`` que codifica el QR.

    Args:
        numero: número ya normalizado a dígitos.

    Returns:
        La URL pública del chat, sin parámetros ni texto precargado.
    """
    return f"https://wa.me/{numero}"


@lru_cache(maxsize=8)
def _qr_png(contenido: str) -> bytes:
    """Dibuja el QR una vez por contenido y lo guarda en memoria."""
    salida = io.BytesIO()
    segno.make(contenido, error="m").save(salida, kind="png", scale=6, border=2)
    return salida.getvalue()


def crear_router_recursos(raiz: Path | None = None) -> APIRouter:
    """Crea el router de los QR (repositorio y WhatsApp) y los diagramas.

    Args:
        raiz: raíz alternativa del repositorio para las pruebas; por defecto la
            del proyecto.

    Returns:
        El router con el QR del repositorio, el de WhatsApp y los diagramas.
    """
    carpeta = (Path(raiz) if raiz is not None else PROJECT_ROOT) / "docs"
    router = APIRouter(tags=["escena"])

    @router.get("/api/escena/repositorio", response_model=RepositorioRespuesta)
    def repositorio() -> RepositorioRespuesta:
        """Devuelve la URL pública del repositorio para el botón del panel."""
        return RepositorioRespuesta(url=URL_REPOSITORIO)

    @router.get("/api/escena/repositorio/qr.png")
    def repositorio_qr() -> Response:
        """Devuelve el QR del repositorio, dibujado en memoria."""
        return Response(
            content=_qr_png(URL_REPOSITORIO),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/escena/whatsapp", response_model=WhatsappRespuesta)
    def whatsapp() -> WhatsappRespuesta:
        """Dice si hay número de WhatsApp configurado, sin revelarlo."""
        return WhatsappRespuesta(disponible=numero_whatsapp() is not None)

    @router.get("/api/escena/whatsapp/qr.png")
    def whatsapp_qr() -> Response:
        """Devuelve el QR del canal o ``404`` si no hay número configurado."""
        numero = numero_whatsapp()
        if numero is None:
            raise HTTPException(status_code=404, detail="WhatsApp no configurado")
        return Response(
            content=_qr_png(url_whatsapp(numero)),
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/diagramas/{nombre}")
    def diagrama(nombre: str) -> FileResponse:
        """Sirve uno de los diagramas de Archify de la lista cerrada."""
        if nombre not in DIAGRAMAS:
            raise HTTPException(status_code=404, detail="diagrama no encontrado")
        ruta = carpeta / nombre
        if not ruta.is_file():
            raise HTTPException(status_code=404, detail="diagrama no encontrado")
        return FileResponse(ruta, media_type="text/html")

    return router
