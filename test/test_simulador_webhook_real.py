"""Prueba de punta a punta: el simulador contra el webhook real del canal, sin red.

Las conversaciones de las personas sintéticas se firman con el simulador y se
envían a ``/webhooks/whatsapp`` del router real de ``canal.webhook`` (y una vez
por la app completa de ``app.py``). Comprueba que el formato y la firma del
simulador son los que el webhook acepta, y que una firma inválida o un cuerpo
alterado se rechazan en la puerta. El App Secret es ficticio y se inyecta con
``monkeypatch``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from banco_occidente_corpus.canal.webhook import EVENTO_RECIBIDO, router
from banco_occidente_corpus.simulador.payloads import (
    encabezados_firmados,
    enviar_a_webhook,
    serializar,
)
from banco_occidente_corpus.simulador.personas import Persona, cargar_personas, conversacion

RAIZ = Path(__file__).resolve().parents[1]
"""Raíz del repositorio."""

PERSONAS = RAIZ / "data" / "evaluacion" / "personas_sinteticas.json"
"""Guiones de las personas sintéticas."""

FIXTURES = RAIZ / "test" / "fixtures" / "whatsapp"
"""Payloads de ejemplo del simulador (texto, botón y lista)."""

SECRETO = "s3creto-de-prueba"
"""App Secret ficticio de la prueba."""

RUTA = "/webhooks/whatsapp"
"""Ruta real del webhook."""


def _personas() -> tuple[Persona, ...]:
    """Carga las personas sintéticas del JSON del proyecto."""
    return cargar_personas(PERSONAS)


@pytest.fixture()
def cliente(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Cliente sobre un FastAPI que monta el router real del webhook, con secreto ficticio."""
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRETO)
    aplicacion = FastAPI()
    aplicacion.include_router(router)
    return TestClient(aplicacion)


@pytest.mark.parametrize("persona", _personas(), ids=lambda persona: persona.id)
def test_conversacion_firmada_se_acepta_completa(cliente: TestClient, persona: Persona) -> None:
    """Cada mensaje de la persona, firmado por el simulador, recibe el acuse de Meta."""
    payloads = conversacion(persona)

    respuestas = [enviar_a_webhook(cliente, payload, SECRETO, ruta=RUTA) for payload in payloads]

    assert payloads
    assert [respuesta.status_code for respuesta in respuestas] == [200] * len(payloads)
    assert all(respuesta.json() == EVENTO_RECIBIDO for respuesta in respuestas)


@pytest.mark.parametrize("persona", _personas(), ids=lambda persona: persona.id)
def test_conversacion_con_firma_invalida_se_rechaza(cliente: TestClient, persona: Persona) -> None:
    """Con otro secreto, ningún mensaje de la persona pasa la puerta."""
    payloads = conversacion(persona)

    respuestas = [
        enviar_a_webhook(cliente, payload, SECRETO, ruta=RUTA, firma_valida=False)
        for payload in payloads
    ]

    assert [respuesta.status_code for respuesta in respuestas] == [401] * len(payloads)


@pytest.mark.parametrize("nombre", ["texto", "boton", "lista"])
def test_fixtures_del_simulador_se_aceptan(cliente: TestClient, nombre: str) -> None:
    """Los payloads de ejemplo de texto, botón y lista son eventos válidos para el webhook."""
    payload = json.loads((FIXTURES / f"{nombre}.json").read_text(encoding="utf-8"))

    respuesta = enviar_a_webhook(cliente, payload, SECRETO, ruta=RUTA)

    assert respuesta.status_code == 200
    assert respuesta.json() == EVENTO_RECIBIDO


def test_cuerpo_alterado_despues_de_firmar_se_rechaza(cliente: TestClient) -> None:
    """Firmar los bytes del simulador y mandar otros (un espacio de más) falla con 401."""
    persona = _personas()[0]
    cuerpo = serializar(conversacion(persona)[0])
    encabezados = encabezados_firmados(cuerpo, SECRETO)
    alterado = cuerpo.replace(b"}", b" }", 1)

    respuesta = cliente.post(RUTA, content=alterado, headers=encabezados)

    assert alterado != cuerpo
    assert respuesta.status_code == 401


def test_sin_app_secret_el_canal_no_esta_disponible(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin ``WHATSAPP_APP_SECRET`` el webhook responde 503 aunque el simulador firme bien."""
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    aplicacion = FastAPI()
    aplicacion.include_router(router)
    payload = conversacion(_personas()[0])[0]

    respuesta = enviar_a_webhook(TestClient(aplicacion), payload, SECRETO, ruta=RUTA)

    assert respuesta.status_code == 503


def test_la_app_completa_acepta_al_simulador(monkeypatch: pytest.MonkeyPatch) -> None:
    """La app real de ``app.py`` acepta un mensaje firmado y rechaza el mismo con mala firma."""
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRETO)
    spec = importlib.util.spec_from_file_location("arranque_simulador", RAIZ / "app.py")
    assert spec is not None and spec.loader is not None
    modulo: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    cliente = TestClient(modulo.app)
    payload = conversacion(_personas()[0])[0]

    valida = enviar_a_webhook(cliente, payload, SECRETO, ruta=RUTA)
    invalida = enviar_a_webhook(cliente, payload, SECRETO, ruta=RUTA, firma_valida=False)

    assert valida.status_code == 200
    assert valida.json() == EVENTO_RECIBIDO
    assert invalida.status_code == 401
