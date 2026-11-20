"""Pruebas de extracción de mensajes del webhook (sin red)."""

from __future__ import annotations

from datetime import UTC
from typing import Any

from banco_occidente_corpus.canal.entrada import extraer_mensajes


def _sobre(mensaje: dict[str, Any]) -> dict[str, Any]:
    """Envuelve un mensaje en la estructura de Meta."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "912443945191248",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [mensaje],
                        },
                    }
                ],
            }
        ],
    }


def test_extrae_texto() -> None:
    """Un mensaje de texto se normaliza con su remitente y su hora."""
    datos = _sobre(
        {
            "from": "57000000001",
            "id": "wamid.TEXTO",
            "timestamp": "1794787200",
            "type": "text",
            "text": {"body": "¿Cuál es la cuota de manejo?"},
        }
    )

    mensajes = extraer_mensajes(datos)

    assert len(mensajes) == 1
    mensaje = mensajes[0]
    assert mensaje.id_mensaje == "wamid.TEXTO"
    assert mensaje.remitente == "57000000001"
    assert mensaje.texto == "¿Cuál es la cuota de manejo?"
    assert mensaje.tipo == "texto"
    assert mensaje.recibido_en.tzinfo == UTC


def test_extrae_respuesta_de_boton() -> None:
    """El id del botón viaja en ``id_boton`` para el consentimiento."""
    datos = _sobre(
        {
            "from": "57000000001",
            "id": "wamid.BOTON",
            "timestamp": "1794787200",
            "type": "interactive",
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": "consent:acepto", "title": "Acepto"},
            },
        }
    )

    mensaje = extraer_mensajes(datos)[0]

    assert mensaje.tipo == "boton"
    assert mensaje.id_boton == "consent:acepto"
    assert mensaje.texto == "Acepto"


def test_extrae_seleccion_de_lista() -> None:
    """Una selección de lista se marca como interactiva."""
    datos = _sobre(
        {
            "from": "57000000001",
            "id": "wamid.LISTA",
            "timestamp": "1794787200",
            "type": "interactive",
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": "producto:cdt", "title": "CDT"},
            },
        }
    )

    mensaje = extraer_mensajes(datos)[0]

    assert mensaje.tipo == "interactivo"
    assert mensaje.id_boton == "producto:cdt"


def test_ignora_estados_y_tipos_no_soportados() -> None:
    """Los estados de entrega y las imágenes no llegan al despachador."""
    estados = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {"statuses": [{"id": "wamid.ESTADO", "status": "delivered"}]},
                    }
                ]
            }
        ],
    }
    imagen = _sobre(
        {
            "from": "57000000001",
            "id": "wamid.IMAGEN",
            "timestamp": "1794787200",
            "type": "image",
            "image": {"id": "media"},
        }
    )

    assert extraer_mensajes(estados) == []
    assert extraer_mensajes(imagen) == []


def test_payload_sin_entry_no_falla() -> None:
    """Un JSON vacío o raro no produce mensajes."""
    assert extraer_mensajes({}) == []
    assert extraer_mensajes({"entry": "no-es-lista"}) == []
