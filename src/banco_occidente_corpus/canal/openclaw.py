"""Cliente del gateway local de OpenClaw para el canal de WhatsApp.

El despachador entrega cada mensaje nuevo al gateway con ``POST
/v1/chat/completions`` y el token de ``OPENCLAW_GATEWAY_TOKEN``. El cliente:

- manda solo el mensaje nuevo, con ``user = wa:<huella>``; nunca el número, el
  historial ni el perfil;
- usa ``httpx`` con ``timeout`` explícito, el User-Agent y el header ``From``
  de ``config/site.toml``, y nunca ``verify=False``;
- no reintenta: un reintento repetiría el turno;
- devuelve ``None`` ante timeout, error de red, ``5xx``, cuerpo inválido o
  contenido vacío, para que el despachador responda con el grafo.

El gateway escucha solo en loopback; la configuración rechaza cualquier otra
base. Las pruebas viven en ``test/test_canal_openclaw.py``.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import PROJECT_ROOT

logger = logging.getLogger(__name__)

#: Configuración no secreta del gateway.
RUTA_CONFIG: Path = PROJECT_ROOT / "config" / "openclaw.toml"

#: Ruta del contrato compatible con OpenAI.
RUTA_CHAT: str = "/v1/chat/completions"

#: Variables de entorno del cliente.
VARIABLE_TOKEN: str = "OPENCLAW_GATEWAY_TOKEN"
VARIABLE_ACTIVO: str = "OPENCLAW_ACTIVO"

#: Largo máximo del texto que se devuelve al canal.
LARGO_MAXIMO: int = 4096

#: Hosts aceptados: el gateway nunca sale de loopback.
HOSTS_LOOPBACK: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})

#: Valores que encienden el motor desde el entorno.
VALORES_ACTIVO: frozenset[str] = frozenset({"1", "true", "on", "si", "sí"})


@dataclass(frozen=True, slots=True)
class ConfiguracionOpenClaw:
    """Parámetros no secretos del gateway, leídos de ``config/openclaw.toml``."""

    base_url: str = "http://127.0.0.1:18789"
    modelo: str = "openclaw:pana"
    prefijo_usuario: str = "wa:"
    timeout_segundos: float = 45.0
    reintentos: int = 0
    fallback_forzado: bool = False

    def __post_init__(self) -> None:
        """Valida loopback, timeout, modelo y la ausencia de reintentos.

        Raises:
            ValueError: si la base no es loopback, el timeout no es positivo,
                hay reintentos, el modelo está vacío o falta el prefijo.
        """
        if urlparse(self.base_url).hostname not in HOSTS_LOOPBACK:
            raise ValueError("openclaw.gateway.base_url debe apuntar a loopback")
        if self.timeout_segundos <= 0:
            raise ValueError("openclaw.gateway.timeout_segundos debe ser mayor que cero")
        if self.reintentos != 0:
            raise ValueError(
                "openclaw.gateway.reintentos debe ser 0: un reintento repetiría el turno"
            )
        if not self.modelo.strip():
            raise ValueError("openclaw.gateway.modelo no puede estar vacío")
        if not self.prefijo_usuario.strip():
            raise ValueError("openclaw.gateway.prefijo_usuario no puede estar vacío")

    @property
    def url_chat(self) -> str:
        """URL completa de ``/v1/chat/completions``."""
        return f"{self.base_url.rstrip('/')}{RUTA_CHAT}"


def cargar_configuracion_openclaw(ruta: Path | None = None) -> ConfiguracionOpenClaw:
    """Lee la sección ``[gateway]`` de ``config/openclaw.toml``.

    Args:
        ruta: archivo TOML alternativo; por defecto ``config/openclaw.toml``.

    Returns:
        La configuración tipada; sin archivo devuelve los valores por defecto.

    Raises:
        ValueError: si los valores no respetan el contrato del cliente.
    """
    archivo = RUTA_CONFIG if ruta is None else ruta
    datos: dict[str, Any] = {}
    if archivo.exists():
        with archivo.open("rb") as fh:
            datos = dict(tomllib.load(fh))

    gateway: dict[str, Any] = dict(datos.get("gateway", {}))
    return ConfiguracionOpenClaw(
        base_url=str(gateway.get("base_url", "http://127.0.0.1:18789")),
        modelo=str(gateway.get("modelo", "openclaw:pana")),
        prefijo_usuario=str(gateway.get("prefijo_usuario", "wa:")),
        timeout_segundos=float(gateway.get("timeout_segundos", 45.0)),
        reintentos=int(gateway.get("reintentos", 0)),
        fallback_forzado=_booleano(gateway, "fallback_forzado", False),
    )


class ClienteOpenClaw:
    """Cliente HTTP del gateway, acotado al turno nuevo del invitado."""

    def __init__(
        self,
        config: ConfiguracionOpenClaw,
        token: str,
        user_agent: str,
        remitente: str,
        *,
        transporte: httpx.BaseTransport | None = None,
    ) -> None:
        """Guarda el contrato y crea el cliente HTTP con su timeout.

        Args:
            config: parámetros del gateway ya validados.
            token: valor de ``OPENCLAW_GATEWAY_TOKEN``; vacío deshabilita.
            user_agent: User-Agent del proyecto.
            remitente: correo del header ``From``.
            transporte: transporte alternativo para las pruebas; ``None`` usa
                el transporte real.
        """
        self.config = config
        self._token = token.strip()
        self._user_agent = user_agent
        self._remitente = remitente.strip()
        self._cliente = httpx.Client(
            timeout=httpx.Timeout(
                config.timeout_segundos,
                connect=min(3.0, config.timeout_segundos),
            ),
            transport=transporte,
            trust_env=False,
        )

    @property
    def disponible(self) -> bool:
        """Indica si hay token y el respaldo no está forzado."""
        return bool(self._token) and not self.config.fallback_forzado

    def responder(self, texto: str, usuario_id: str) -> str | None:
        """Pide un turno al gateway y devuelve su texto.

        Args:
            texto: mensaje nuevo del invitado.
            usuario_id: huella HMAC del número; viaja como ``wa:<huella>``.

        Returns:
            El texto del agente, o ``None`` si el gateway no dio una respuesta
            usable y el despachador debe usar el grafo.
        """
        if not self.disponible:
            return None
        try:
            respuesta = self._cliente.post(
                self.config.url_chat,
                json=self._cuerpo(texto, usuario_id),
                headers=self._cabeceras(),
            )
        except httpx.TimeoutException:
            logger.warning(
                "openclaw: el gateway no respondió en %.1f s; se usa el grafo",
                self.config.timeout_segundos,
            )
            return None
        except httpx.HTTPError as error:
            logger.warning("openclaw: fallo de red (%s); se usa el grafo", type(error).__name__)
            return None

        if respuesta.status_code != httpx.codes.OK:
            logger.warning(
                "openclaw: el gateway respondió %s; se usa el grafo", respuesta.status_code
            )
            return None
        return self._contenido(respuesta)

    def cerrar(self) -> None:
        """Cierra las conexiones abiertas del cliente HTTP."""
        self._cliente.close()

    def _cuerpo(self, texto: str, usuario_id: str) -> dict[str, Any]:
        """Construye el cuerpo con el modelo, el hilo y solo el mensaje nuevo."""
        return {
            "model": self.config.modelo,
            "user": f"{self.config.prefijo_usuario}{usuario_id}",
            "messages": [{"role": "user", "content": texto}],
        }

    def _cabeceras(self) -> dict[str, str]:
        """Cabeceras del turno; el token no se registra en logs."""
        return {
            "Authorization": f"Bearer {self._token}",
            "User-Agent": self._user_agent,
            "From": self._remitente,
            "Content-Type": "application/json",
        }

    def _contenido(self, respuesta: httpx.Response) -> str | None:
        """Extrae ``choices[0].message.content`` o ``None`` si no es usable."""
        try:
            datos = respuesta.json()
        except ValueError:
            logger.warning("openclaw: el cuerpo de la respuesta no es JSON")
            return None
        if not isinstance(datos, dict):
            return None
        elecciones = datos.get("choices")
        if not isinstance(elecciones, list) or not elecciones:
            return None
        primera = elecciones[0]
        if not isinstance(primera, dict):
            return None
        mensaje = primera.get("message")
        if not isinstance(mensaje, dict):
            return None
        contenido = mensaje.get("content")
        if not isinstance(contenido, str):
            return None
        texto = contenido.strip()
        if not texto:
            return None
        return texto[:LARGO_MAXIMO]


def cliente_desde_entorno(
    *,
    user_agent: str,
    remitente: str,
    ruta_config: Path | None = None,
) -> ClienteOpenClaw | None:
    """Crea el cliente si ``OPENCLAW_ACTIVO`` y el token están presentes.

    No hay valor por defecto para el token: sin él, el canal responde con el
    grafo. El token no se registra en logs.

    Args:
        user_agent: User-Agent del proyecto.
        remitente: correo del header ``From``.
        ruta_config: archivo TOML alternativo; por defecto el del proyecto.

    Returns:
        El cliente listo, o ``None`` si OpenClaw está apagado, sin token, con
        el respaldo forzado o sin contacto académico.
    """
    activo = os.getenv(VARIABLE_ACTIVO, "").strip().casefold()
    if activo not in VALORES_ACTIVO:
        return None
    token = os.getenv(VARIABLE_TOKEN, "").strip()
    if not token:
        logger.info("OpenClaw deshabilitado: falta %s", VARIABLE_TOKEN)
        return None
    config = cargar_configuracion_openclaw(ruta_config)
    if config.fallback_forzado:
        logger.info("OpenClaw deshabilitado: fallback_forzado está activo")
        return None
    if not remitente.strip():
        logger.warning("OpenClaw deshabilitado: falta site.contact para el header From")
        return None
    return ClienteOpenClaw(config, token, user_agent, remitente)


def _booleano(datos: dict[str, Any], clave: str, defecto: bool) -> bool:
    """Lee un booleano del TOML y rechaza valores de otro tipo.

    Args:
        datos: sección ``gateway`` ya cargada.
        clave: nombre del campo.
        defecto: valor si el campo no está.

    Returns:
        El booleano del archivo o el valor por defecto.

    Raises:
        ValueError: si el campo existe y no es booleano.
    """
    valor = datos.get(clave, defecto)
    if not isinstance(valor, bool):
        raise ValueError(f"openclaw.gateway.{clave} debe ser booleano")
    return valor
