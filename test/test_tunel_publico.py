"""Pruebas de la superficie pública del túnel de Cloudflare (sin red).

El túnel rápido publica todo el origen; la app solo deja pasar el webhook y
``/health`` cuando la petición no es local. Las pruebas usan ``TestClient``: no
abren puertos ni salen a internet.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]

#: Host que Cloudflare asigna a un túnel rápido.
TUNEL = "https://algo-nuevo.trycloudflare.com"
#: Cabecera que añade Cloudflare a toda petición que entra por el túnel.
CABECERAS_TUNEL = {"cf-ray": "8f0d1a2b3c4d5e6f-SCL"}
#: Rutas que no deben quedar públicas: pantalla, consola, API y traza.
RUTAS_PRIVADAS = (
    "/",
    "/escena.html",
    "/docs",
    "/openapi.json",
    "/api/estado",
    "/api/preguntar",
    "/api/herramientas/traza",
    "/api/operacion",
)


@pytest.fixture(scope="module")
def modulo_app() -> ModuleType:
    """Carga ``app.py`` por ruta, para no confundirlo con la carpeta ``app/``."""
    spec = importlib.util.spec_from_file_location("arranque_tunel", RAIZ / "app.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def cliente_tunel(modulo_app: ModuleType) -> TestClient:
    """Cliente que simula una petición que entra por el túnel de Cloudflare."""
    return TestClient(modulo_app.app, base_url=TUNEL, headers=CABECERAS_TUNEL)


@pytest.mark.parametrize("ruta", RUTAS_PRIVADAS)
def test_el_tunel_no_publica_la_app(cliente_tunel: TestClient, ruta: str) -> None:
    """La pantalla, la consola y la API responden 404 desde el túnel."""
    assert cliente_tunel.get(ruta).status_code == 404


def test_el_tunel_no_puede_gastar_saldo(cliente_tunel: TestClient) -> None:
    """Las rutas que llaman al modelo quedan cerradas desde el túnel."""
    for ruta in ("/api/preguntar", "/api/preguntar/stream"):
        respuesta = cliente_tunel.post(ruta, json={"pregunta": "hola"})
        assert respuesta.status_code == 404


def test_el_tunel_alcanza_el_webhook(cliente_tunel: TestClient) -> None:
    """El webhook sigue público: lo protegen su token y su firma."""
    assert cliente_tunel.get("/webhooks/whatsapp").status_code in {403, 503}
    assert cliente_tunel.post("/webhooks/whatsapp", json={}).status_code in {401, 503}


def test_el_tunel_alcanza_health(cliente_tunel: TestClient) -> None:
    """``/health`` queda público porque se usa para diagnosticar el túnel."""
    assert cliente_tunel.get("/health").status_code in {200, 503}


def test_un_host_local_falsificado_no_abre_la_app(modulo_app: ModuleType) -> None:
    """Copiar ``Host: 127.0.0.1`` no basta: las cabeceras de Cloudflare delatan el túnel."""
    cliente = TestClient(modulo_app.app, base_url=TUNEL)
    respuesta = cliente.get(
        "/api/estado",
        headers={"host": "127.0.0.1:8000", **CABECERAS_TUNEL},
    )

    assert respuesta.status_code == 404


def test_sin_cabeceras_de_cloudflare_el_host_del_tunel_cierra_la_app(
    modulo_app: ModuleType,
) -> None:
    """Un ``Host`` que no es de loopback se trata como remoto aunque falten cabeceras."""
    cliente = TestClient(modulo_app.app, base_url=TUNEL)

    assert cliente.get("/api/estado").status_code == 404


def test_la_peticion_local_conserva_toda_la_app(modulo_app: ModuleType) -> None:
    """En ``127.0.0.1`` la pantalla y la API siguen disponibles."""
    cliente = TestClient(modulo_app.app)

    assert cliente.get("/").status_code == 200
    assert cliente.get("/api/estado").status_code == 200
