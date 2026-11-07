"""Guardia de red de la suite: ninguna prueba abre conexiones externas.

El loopback literal sí se permite porque en Windows el ``ProactorEventLoop`` de
``asyncio`` crea su self-pipe con ``socket.socketpair()`` sobre ``127.0.0.1``;
bloquearlo rompería ``TestClient``. La excepción es el puerto de Ollama
(``11434``): es un loopback, pero apunta a un servicio real y una prueba que lo
llamara por accidente pasaría en cualquier equipo con Ollama encendido.
Cualquier otro destino falla antes de conectarse, de modo que una prueba que
llame a Ollama, a DeepSeek o al sitio del banco no puede pasar por accidente.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

#: Puertos locales de servicios reales que ninguna prueba debe usar (Ollama).
PUERTOS_PROHIBIDOS: frozenset[int] = frozenset({11434})


def _es_loopback(direccion: object) -> bool:
    """Indica si una dirección de socket es un literal de loopback IPv4 o IPv6."""
    if not isinstance(direccion, tuple) or not direccion:
        return False
    host = str(direccion[0])
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _permitida(direccion: object) -> bool:
    """Permite loopback salvo en los puertos de servicios reales (Ollama)."""
    if not isinstance(direccion, tuple) or not _es_loopback(direccion):
        return False
    return direccion[1] not in PUERTOS_PROHIBIDOS


def _error_de_red(direccion: object) -> AssertionError:
    """Arma el fallo de la guardia con la alternativa sin red para embeddings."""
    return AssertionError(
        f"conexion de red bloqueada: {direccion!r}; "
        "las pruebas no llaman a servicios reales: usa DeterministicFakeEmbedding"
    )


@pytest.fixture(autouse=True)
def sin_red_externa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bloquea ``connect`` y ``connect_ex`` fuera de loopback y en el puerto de Ollama."""
    connect_original = socket.socket.connect
    connect_ex_original = socket.socket.connect_ex

    def connect(socket_propio: socket.socket, direccion: object) -> None:
        """Conecta solo a loopback permitido; cualquier otro destino es un fallo."""
        if _permitida(direccion):
            return connect_original(socket_propio, direccion)
        raise _error_de_red(direccion)

    def connect_ex(socket_propio: socket.socket, direccion: object) -> int:
        """Variante de ``connect`` que también corta los destinos no permitidos."""
        if _permitida(direccion):
            return connect_ex_original(socket_propio, direccion)
        raise _error_de_red(direccion)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
