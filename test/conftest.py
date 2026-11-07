"""Guardia de red de la suite: ninguna prueba abre conexiones externas.

El loopback literal sí se permite porque en Windows el ``ProactorEventLoop`` de
``asyncio`` crea su self-pipe con ``socket.socketpair()`` sobre ``127.0.0.1``;
bloquearlo rompería ``TestClient``. Cualquier otro destino falla antes de
conectarse, de modo que una prueba que llame a Ollama, a DeepSeek o al sitio del
banco no puede pasar por accidente.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest


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


@pytest.fixture(autouse=True)
def sin_red_externa(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bloquea ``connect`` y ``connect_ex`` fuera de loopback en cada prueba."""
    connect_original = socket.socket.connect
    connect_ex_original = socket.socket.connect_ex

    def connect(socket_propio: socket.socket, direccion: object) -> None:
        """Conecta solo a loopback; cualquier otro destino es un fallo de prueba."""
        if _es_loopback(direccion):
            return connect_original(socket_propio, direccion)
        raise AssertionError(f"conexion de red bloqueada: {direccion!r}")

    def connect_ex(socket_propio: socket.socket, direccion: object) -> int:
        """Variante de ``connect`` que también corta los destinos externos."""
        if _es_loopback(direccion):
            return connect_ex_original(socket_propio, direccion)
        raise AssertionError(f"conexion de red bloqueada: {direccion!r}")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
