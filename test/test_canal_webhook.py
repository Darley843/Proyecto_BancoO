"""Pruebas del webhook de WhatsApp: verificación GET y firma POST, sin red.

Usan ``TestClient`` sobre un FastAPI mínimo y sobre la app real del proyecto.
Las variables de entorno se inyectan con ``monkeypatch``; nunca hay valores por
defecto para los secretos.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from banco_occidente_corpus.canal.firma import calcular_firma
from banco_occidente_corpus.canal.webhook import router

RAIZ = Path(__file__).resolve().parents[1]
"""Raíz del repositorio, para cargar ``app.py`` por ruta."""

TOKEN = "token-de-verificacion"
"""Token ficticio de la verificación GET."""

SECRETO = "s3creto-de-prueba"
"""App Secret ficticio de la prueba."""


@pytest.fixture()
def cliente() -> TestClient:
    """Cliente sobre un FastAPI que solo monta el webhook."""
    aplicacion = FastAPI()
    aplicacion.include_router(router)
    return TestClient(aplicacion)


def _cuerpo(mensaje_id: str = "wamid.SIM1") -> bytes:
    """Payload mínimo de Meta con un mensaje de texto."""
    datos = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "200000000000001",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "57000000001",
                                    "id": mensaje_id,
                                    "timestamp": "1794787200",
                                    "type": "text",
                                    "text": {"body": "hola"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
    return json.dumps(datos).encode("utf-8")


def _cabecera(cuerpo: bytes, secreto: str = SECRETO) -> dict[str, str]:
    """Cabecera de firma válida para un cuerpo."""
    return {"X-Hub-Signature-256": calcular_firma(cuerpo, secreto)}


def test_get_devuelve_el_reto_en_texto_plano(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con modo y token correctos, Meta recibe el reto exacto."""
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", TOKEN)

    respuesta = cliente.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": TOKEN,
            "hub.challenge": "1234567890",
        },
    )

    assert respuesta.status_code == 200
    assert respuesta.text == "1234567890"
    assert respuesta.headers["content-type"].startswith("text/plain")


def test_get_con_token_incorrecto_responde_403(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un token distinto no revela el esperado y se rechaza."""
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", TOKEN)

    respuesta = cliente.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "otro",
            "hub.challenge": "1234567890",
        },
    )

    assert respuesta.status_code == 403
    assert TOKEN not in respuesta.text


def test_get_sin_modo_subscribe_responde_403(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meta solo verifica con ``hub.mode=subscribe``."""
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", TOKEN)

    respuesta = cliente.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "otro", "hub.verify_token": TOKEN, "hub.challenge": "1"},
    )

    assert respuesta.status_code == 403


def test_get_sin_token_en_el_entorno_responde_503(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin variable de entorno el canal queda deshabilitado, sin valor por defecto."""
    monkeypatch.delenv("WHATSAPP_VERIFY_TOKEN", raising=False)

    respuesta = cliente.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"},
    )

    assert respuesta.status_code == 503


def test_get_sin_challenge_responde_400(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si Meta no manda el reto, no hay nada que devolver."""
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", TOKEN)

    respuesta = cliente.get(
        "/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": TOKEN},
    )

    assert respuesta.status_code == 400


def test_post_con_firma_valida_responde_200(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un evento firmado se acepta con el acuse de Meta."""
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRETO)
    cuerpo = _cuerpo()

    respuesta = cliente.post("/webhooks/whatsapp", content=cuerpo, headers=_cabecera(cuerpo))

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "EVENT_RECEIVED"}


def test_post_con_firma_invalida_responde_401(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una firma de otro secreto no pasa."""
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRETO)
    cuerpo = _cuerpo()

    respuesta = cliente.post(
        "/webhooks/whatsapp",
        content=cuerpo,
        headers=_cabecera(cuerpo, "otro-secreto"),
    )

    assert respuesta.status_code == 401


def test_post_sin_cabecera_responde_401(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin ``X-Hub-Signature-256`` no se procesa nada."""
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRETO)

    respuesta = cliente.post("/webhooks/whatsapp", content=_cuerpo())

    assert respuesta.status_code == 401


def test_post_con_cuerpo_alterado_responde_401(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Firmar un cuerpo y enviar otro debe fallar en la puerta."""
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRETO)
    original = _cuerpo("wamid.UNO")
    alterado = _cuerpo("wamid.DOS")

    respuesta = cliente.post("/webhooks/whatsapp", content=alterado, headers=_cabecera(original))

    assert respuesta.status_code == 401


def test_post_sin_app_secret_responde_503(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin App Secret el canal no puede validar y se declara no disponible."""
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    cuerpo = _cuerpo()

    respuesta = cliente.post("/webhooks/whatsapp", content=cuerpo, headers=_cabecera(cuerpo))

    assert respuesta.status_code == 503


def test_post_con_json_invalido_responde_400(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una firma válida no convierte basura en un evento."""
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRETO)
    cuerpo = b"{no-es-json"

    respuesta = cliente.post("/webhooks/whatsapp", content=cuerpo, headers=_cabecera(cuerpo))

    assert respuesta.status_code == 400


def test_la_app_monta_el_webhook() -> None:
    """La app real de la sucursal incluye las dos rutas del canal."""
    spec = importlib.util.spec_from_file_location("arranque_canal", RAIZ / "app.py")
    assert spec is not None and spec.loader is not None
    modulo: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    ruta = modulo.app.openapi()["paths"]["/webhooks/whatsapp"]

    assert "get" in ruta
    assert "post" in ruta
