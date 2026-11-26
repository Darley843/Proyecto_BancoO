"""Pruebas de los recursos del paso «Preguntas»: QR y diagramas.

Sin red: ``TestClient`` sobre un router montado en memoria y un directorio
temporal para el diagrama. El número del canal se inyecta con ``monkeypatch`` y
nunca se escribe en el código.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from banco_occidente_corpus.escena.recursos import (
    DIAGRAMAS,
    URL_REPOSITORIO,
    VARIABLE_NUMERO,
    crear_router_recursos,
    numero_whatsapp,
    url_whatsapp,
)

PNG = b"\x89PNG\r\n\x1a\n"


def _cliente(raiz: Path) -> TestClient:
    app = FastAPI()
    app.include_router(crear_router_recursos(raiz))
    return TestClient(app)


@pytest.fixture()
def raiz(tmp_path: Path) -> Path:
    """Raíz mínima con un diagrama válido y un archivo fuera de la lista."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "arquitectura.html").write_text("<html>arquitectura</html>", encoding="utf-8")
    (docs / "secreto.html").write_text("<html>no se sirve</html>", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("crudo", "esperado"),
    [
        ("+57 300 123 4567", "573001234567"),
        ("57-300-123-4567", "573001234567"),
        ("(57) 3001234567", "573001234567"),
        ("", None),
        ("300123", None),
        ("12345678901234567890", None),
        ("no hay número", None),
    ],
)
def test_numero_whatsapp_normaliza_y_valida(crudo: str, esperado: str | None) -> None:
    """Solo pasan números de 10 a 15 dígitos, sin importar el formato."""
    assert numero_whatsapp({VARIABLE_NUMERO: crudo}) == esperado


def test_numero_whatsapp_sin_variable_es_none() -> None:
    """Sin la variable de entorno no hay número."""
    assert numero_whatsapp({}) is None


def test_url_whatsapp() -> None:
    """El QR codifica el chat público, sin texto precargado."""
    assert url_whatsapp("573001234567") == "https://wa.me/" + "573001234567"


def test_url_repositorio_es_publica_y_sin_credenciales() -> None:
    """El repositorio del QR es público y no lleva usuario ni token."""
    assert URL_REPOSITORIO.startswith("https://github.com/")
    assert "@" not in URL_REPOSITORIO
    assert "token" not in URL_REPOSITORIO.lower()


def test_la_ruta_del_repositorio_devuelve_su_url(raiz: Path) -> None:
    """El panel pide la URL al servidor y no la escribe en el HTML."""
    respuesta = _cliente(raiz).get("/api/escena/repositorio")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"url": URL_REPOSITORIO}


def test_el_qr_del_repositorio_es_un_png(raiz: Path) -> None:
    """El QR del repositorio se dibuja en memoria y se sirve como PNG."""
    qr = _cliente(raiz).get("/api/escena/repositorio/qr.png")
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/png"
    assert qr.content.startswith(PNG)
    assert qr.headers["cache-control"] == "no-store"


def test_sin_numero_la_ruta_dice_que_no_esta_y_el_qr_es_404(
    monkeypatch: pytest.MonkeyPatch, raiz: Path
) -> None:
    """Sin número configurado no se revela nada y el QR no existe."""
    monkeypatch.delenv(VARIABLE_NUMERO, raising=False)
    cliente = _cliente(raiz)
    respuesta = cliente.get("/api/escena/whatsapp")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"disponible": False}
    assert cliente.get("/api/escena/whatsapp/qr.png").status_code == 404


def test_con_numero_el_qr_es_un_png(monkeypatch: pytest.MonkeyPatch, raiz: Path) -> None:
    """Con número configurado el QR se dibuja en memoria y no viaja en el JSON."""
    monkeypatch.setenv(VARIABLE_NUMERO, "+57 300 123 4567")
    cliente = _cliente(raiz)
    disponible = cliente.get("/api/escena/whatsapp")
    assert disponible.json() == {"disponible": True}
    assert "573001234567" not in disponible.text
    qr = cliente.get("/api/escena/whatsapp/qr.png")
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/png"
    assert qr.content.startswith(PNG)


def test_el_diagrama_de_la_lista_se_sirve(raiz: Path) -> None:
    """Un diagrama permitido responde como HTML."""
    respuesta = _cliente(raiz).get("/diagramas/arquitectura.html")
    assert respuesta.status_code == 200
    assert "arquitectura" in respuesta.text
    assert "text/html" in respuesta.headers["content-type"]


@pytest.mark.parametrize("nombre", ["secreto.html", "no-existe.html", "arquitectura.json"])
def test_un_archivo_fuera_de_la_lista_no_se_sirve(raiz: Path, nombre: str) -> None:
    """La lista cerrada evita exponer el resto de ``docs/``."""
    assert _cliente(raiz).get(f"/diagramas/{nombre}").status_code == 404


def test_la_lista_cubre_los_seis_diagramas() -> None:
    """Los seis diagramas del README están permitidos."""
    assert len(DIAGRAMAS) == 6
    assert "arquitectura.html" in DIAGRAMAS
    assert "despliegue-openclaw.html" in DIAGRAMAS
