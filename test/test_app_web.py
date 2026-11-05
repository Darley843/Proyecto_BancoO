"""Pruebas del arranque de la app web (tarea 15.3), sin red y sin navegador.

Usan ``TestClient`` de FastAPI: no abren ningún puerto.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def modulo_app() -> ModuleType:
    """Carga ``app.py`` por ruta, para no confundirlo con la carpeta ``app/``."""
    spec = importlib.util.spec_from_file_location("arranque_sucursal", RAIZ / "app.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def cliente(modulo_app: ModuleType) -> TestClient:
    """Cliente de prueba sobre la app real de la sucursal."""
    return TestClient(modulo_app.app)


def test_escucha_solo_en_localhost(modulo_app: ModuleType) -> None:
    """La escucha configurada es ``127.0.0.1:8000``, nunca un host público."""
    assert modulo_app.HOST == "127.0.0.1"
    assert modulo_app.PUERTO == 8000


def test_raiz_sirve_el_html_de_la_sucursal(cliente: TestClient) -> None:
    """``/`` devuelve ``index.html`` con la navegación de la sucursal."""
    respuesta = cliente.get("/")
    assert respuesta.status_code == 200
    assert "text/html" in respuesta.headers["content-type"]
    assert "Sucursal 1965" in respuesta.text


@pytest.mark.parametrize(
    "ruta",
    [
        "/estilos.css",
        "/app.js",
        "/comun.js",
        "/vistas/boveda.js",
        "/vistas/ventanilla.js",
        "/datos-ejemplo/estado.json",
        "/datos-ejemplo/preguntar.json",
    ],
)
def test_sirve_los_archivos_de_la_app(cliente: TestClient, ruta: str) -> None:
    """Los estáticos de ``app/web/`` se sirven con su ruta relativa."""
    assert cliente.get(ruta).status_code == 200


def test_la_api_responde_estado(cliente: TestClient) -> None:
    """Con el PR 10 la API existe y ``/api/estado`` trae los seis campos."""
    respuesta = cliente.get("/api/estado")

    assert respuesta.status_code == 200
    assert "indice_listo" in respuesta.json()


def test_crear_app_acepta_otra_carpeta(modulo_app: ModuleType, tmp_path: Path) -> None:
    """``crear_app`` sirve la carpeta que se le indique."""
    (tmp_path / "index.html").write_text("<p>prueba</p>", encoding="utf-8")
    respuesta = TestClient(modulo_app.crear_app(tmp_path)).get("/")
    assert respuesta.text == "<p>prueba</p>"
