"""Configuración del canal de WhatsApp, sin secretos.

``config/whatsapp.toml`` guarda lo que no cambia por entorno: versión de la API
de Meta, modo, país, límites y las huellas de los números autorizados. Los
secretos (token de verificación, App Secret, token de acceso y sal) se leen del
entorno en cada petición y nunca se escriben en el repositorio.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from ..config import PROJECT_ROOT
from .evento import Evento, leer_evento

#: Ruta de la configuración del canal.
RUTA_CONFIG_CANAL: Path = PROJECT_ROOT / "config" / "whatsapp.toml"

#: Modos admitidos: falso no envía nada a Meta.
Modo = Literal["falso", "real"]

#: Conjunto de modos válidos, para validar el TOML y el entorno.
MODOS_VALIDOS: frozenset[str] = frozenset({"falso", "real"})


@dataclass(frozen=True, slots=True)
class ConfiguracionCanal:
    """Parámetros no secretos del canal."""

    version_api: str = "v23.0"
    modo: Modo = "falso"
    pais_por_defecto: str = "57"
    version_aviso: str = "2026-11"
    limite_intentos_roba: int = 20
    retencion_dias: int = 30
    entrevista_ttl_minutos: int = 30
    huellas: tuple[str, ...] = ()
    evento: Evento = field(default_factory=Evento)

    def permite(self, usuario_id: str, momento: datetime | None = None) -> bool:
        """Indica si el canal atiende a esa huella ahora.

        Args:
            usuario_id: huella HMAC del número.
            momento: instante a evaluar; por defecto, ahora.

        Returns:
            ``True`` si la huella está autorizada o si el modo evento está
            vigente en ese instante.
        """
        return usuario_id in self.huellas or self.evento.vigente(momento)

    def es_evento(self, usuario_id: str, momento: datetime | None = None) -> bool:
        """Indica si la huella entra por el modo evento y no por la lista.

        Args:
            usuario_id: huella HMAC del número.
            momento: instante a evaluar; por defecto, ahora.

        Returns:
            ``True`` solo para números no autorizados durante el evento; son los
            que tienen cuota, aunque reciben el mismo alcance que la lista.
        """
        return usuario_id not in self.huellas and self.evento.vigente(momento)


def cargar_configuracion_canal(ruta: Path | None = None) -> ConfiguracionCanal:
    """Carga ``config/whatsapp.toml`` y aplica ``WHATSAPP_MODO`` si existe.

    Args:
        ruta: archivo TOML alternativo; por defecto ``config/whatsapp.toml``.

    Returns:
        La configuración tipada del canal. Si el archivo falta, devuelve los
        valores por defecto con el canal apagado (modo ``falso``) y sin huellas.

    Raises:
        ValueError: si el modo no es ``falso`` ni ``real``.
    """
    archivo = RUTA_CONFIG_CANAL if ruta is None else ruta
    datos: dict[str, Any] = {}
    if archivo.exists():
        with archivo.open("rb") as fh:
            datos = dict(tomllib.load(fh))

    canal: dict[str, Any] = dict(datos.get("canal", {}))
    autorizados: dict[str, Any] = dict(datos.get("autorizados", {}))
    evento_toml: dict[str, Any] = dict(datos.get("evento", {}))

    modo = os.getenv("WHATSAPP_MODO", "").strip().casefold() or str(canal.get("modo", "falso"))
    if modo not in MODOS_VALIDOS:
        raise ValueError("whatsapp.canal.modo debe ser 'falso' o 'real'")

    return ConfiguracionCanal(
        version_api=str(canal.get("version_api", "v23.0")),
        modo=cast(Modo, modo),
        pais_por_defecto=str(canal.get("pais_por_defecto", "57")),
        version_aviso=str(canal.get("version_aviso", "2026-11")),
        limite_intentos_roba=int(canal.get("limite_intentos_roba", 20)),
        retencion_dias=int(canal.get("retencion_dias", 30)),
        entrevista_ttl_minutos=int(canal.get("entrevista_ttl_minutos", 30)),
        huellas=tuple(str(huella) for huella in autorizados.get("huellas", [])),
        evento=leer_evento(evento_toml, activo_entorno=_booleano_entorno("WHATSAPP_EVENTO")),
    )


def leer_token_verificacion() -> str | None:
    """Devuelve ``WHATSAPP_VERIFY_TOKEN`` o ``None`` si no está definido."""
    return _variable("WHATSAPP_VERIFY_TOKEN")


def leer_app_secret() -> str | None:
    """Devuelve ``WHATSAPP_APP_SECRET`` o ``None`` si no está definido."""
    return _variable("WHATSAPP_APP_SECRET")


def _variable(nombre: str) -> str | None:
    """Lee una variable de entorno ya recortada; vacía cuenta como ausente."""
    valor = os.getenv(nombre, "").strip()
    return valor or None


def _booleano_entorno(nombre: str) -> bool | None:
    """Lee un interruptor de entorno: ``None`` si no está definido.

    Args:
        nombre: variable de entorno a leer.

    Returns:
        ``True`` o ``False`` según el valor; ``None`` si está vacía o ausente.

    Raises:
        ValueError: si el valor no se reconoce como sí o no.
    """
    valor = _variable(nombre)
    if valor is None:
        return None
    normalizado = valor.casefold()
    if normalizado in {"1", "true", "on", "si", "sí"}:
        return True
    if normalizado in {"0", "false", "off", "no"}:
        return False
    raise ValueError(f"{nombre} debe ser 1/0, true/false, on/off o si/no")
