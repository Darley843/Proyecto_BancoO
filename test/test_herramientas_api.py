"""Pruebas de la traza pública de herramientas que lee la pantalla de la escena."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from banco_occidente_corpus.herramientas import traza
from banco_occidente_corpus.herramientas.api import CANTIDAD_MAXIMA, crear_router_herramientas
from banco_occidente_corpus.herramientas.comun import error
from banco_occidente_corpus.herramientas.esquemas import SalidaHerramienta


@pytest.fixture
def carpeta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Aísla la traza en una carpeta temporal."""
    monkeypatch.setenv(traza.VARIABLE_CARPETA, str(tmp_path))
    return tmp_path


@pytest.fixture
def cliente() -> TestClient:
    """Cliente de una app que solo monta el router de herramientas."""
    app = FastAPI()
    app.include_router(crear_router_herramientas())
    return TestClient(app)


def _ok(herramienta: str) -> SalidaHerramienta:
    """Sobre de una llamada que salió bien, sin datos."""
    return SalidaHerramienta(herramienta=herramienta, ok=True, datos={})


def test_sin_traza_devuelve_lista_vacia(carpeta: Path, cliente: TestClient) -> None:
    """Antes de la primera llamada la pantalla recibe una lista vacía, no un 404."""
    respuesta = cliente.get("/api/herramientas/traza")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"llamadas": []}


def test_devuelve_la_mas_nueva_primero(carpeta: Path, cliente: TestClient) -> None:
    """La pantalla pinta de arriba abajo: la última llamada va primero."""
    traza.registrar("consultar_tasa", {}, _ok("consultar_tasa"), 12.5)
    traza.registrar("simular_cuota", {}, _ok("simular_cuota"), 3.0)
    traza.registrar(
        "buscar_en_documentos",
        {},
        error("buscar_en_documentos", "fallo_interno", "sin Ollama"),
        40.0,
    )

    llamadas = cliente.get("/api/herramientas/traza").json()["llamadas"]
    assert [llamada["herramienta"] for llamada in llamadas] == [
        "buscar_en_documentos",
        "simular_cuota",
        "consultar_tasa",
    ]
    assert llamadas[0]["ok"] is False
    assert llamadas[0]["codigo"] == "fallo_interno"
    assert llamadas[2]["ok"] is True
    assert llamadas[2]["codigo"] is None
    assert llamadas[2]["latencia_ms"] == 12.5


def test_no_expone_argumentos_ni_huella(carpeta: Path, cliente: TestClient) -> None:
    """El resumen de argumentos (prefijo de huella, largos) no sale a la pantalla."""
    traza.registrar(
        "registrar_consentimiento",
        {"usuario_id": "wa:abcdef0123…", "texto": "18 caracteres"},
        _ok("registrar_consentimiento"),
        1.0,
    )

    cuerpo = cliente.get("/api/herramientas/traza").text
    assert "argumentos" not in cuerpo
    assert "wa:abcdef" not in cuerpo
    assert "caracteres" not in cuerpo


def test_respeta_la_cantidad_pedida(carpeta: Path, cliente: TestClient) -> None:
    """`n` limita cuántas llamadas vuelven, empezando por las más nuevas."""
    for indice in range(5):
        traza.registrar(f"h{indice}", {}, _ok(f"h{indice}"), 1.0)

    llamadas = cliente.get("/api/herramientas/traza", params={"n": 2}).json()["llamadas"]
    assert [llamada["herramienta"] for llamada in llamadas] == ["h4", "h3"]


@pytest.mark.parametrize("n", [0, CANTIDAD_MAXIMA + 1])
def test_rechaza_cantidades_fuera_de_rango(carpeta: Path, cliente: TestClient, n: int) -> None:
    """Una cantidad fuera de 1..50 es un 422, no una lectura sin límite."""
    assert cliente.get("/api/herramientas/traza", params={"n": n}).status_code == 422


def test_la_app_monta_la_ruta() -> None:
    """`app.py` incluye el router, para que la pantalla no reciba un 404."""
    texto = Path("app.py").read_text(encoding="utf-8")
    assert "crear_router_herramientas()" in texto


ESCENA = Path(__file__).resolve().parents[1] / "app" / "web" / "escena"


def test_la_pantalla_conoce_las_veinte_herramientas_y_sus_duenas() -> None:
    """herramientas.js nombra las 20 del catálogo con la misma dueña, ni una más."""
    from banco_occidente_corpus.herramientas.catalogo import CATALOGO

    codigo = (ESCENA / "herramientas.js").read_text(encoding="utf-8")
    en_pantalla = dict(
        re.findall(r'^\s+([a-z_]+): \{ texto: "[^"]+", duena: "(\w+)" \}', codigo, re.M)
    )
    assert en_pantalla == {herramienta.nombre: herramienta.duena for herramienta in CATALOGO}


def test_la_pantalla_tiene_los_ids_del_panel() -> None:
    """Cada porId("...") de herramientas.js existe en escena.html."""
    html = (ESCENA.parent / "escena.html").read_text(encoding="utf-8")
    codigo = (ESCENA / "herramientas.js").read_text(encoding="utf-8")
    ids = set(re.findall(r'porId\("([a-z-]+)"\)', codigo))
    assert {"escena-herramientas", "escena-herramientas-lista"} <= ids
    for identificador in ids:
        assert f'id="{identificador}"' in html, identificador


def test_la_pantalla_no_pinta_html_ni_argumentos() -> None:
    """Sin innerHTML y sin leer argumentos: solo nombre, resultado y latencia."""
    codigo = (ESCENA / "herramientas.js").read_text(encoding="utf-8")
    assert "innerHTML" not in codigo
    assert ".argumentos" not in codigo
    assert "/api/herramientas/traza" in codigo
