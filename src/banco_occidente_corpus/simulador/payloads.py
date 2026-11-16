"""Constructor de payloads del webhook de WhatsApp Cloud API y su firma.

Reproduce el formato que Meta envía al webhook (``object``/``entry``/``changes``/
``value``/``messages``) para tres tipos de mensaje: texto, respuesta de botón y
selección de lista. No hace peticiones de red: produce ``dict`` y ``bytes`` que las
pruebas envían al FastAPI con el cliente de pruebas.

Todo es determinista: el id del mensaje se deriva de su contenido y la marca de
tiempo es explícita, para que las pruebas puedan comparar contra fixtures.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any, Protocol

PHONE_NUMBER_ID_PRUEBA = "100000000000001"
"""Phone Number ID ficticio del número del negocio en las pruebas."""

WABA_ID_PRUEBA = "200000000000001"
"""Id ficticio de la cuenta de WhatsApp Business en las pruebas."""

NUMERO_NEGOCIO_PRUEBA = "15550000000"
"""Número visible ficticio del negocio (formato de los números de prueba de Meta)."""

PREFIJO_NUMERO_FICTICIO = "5700000"
"""Todos los números de usuario simulados empiezan así: no son móviles colombianos válidos."""

MARCA_TIEMPO_BASE = 1_794_787_200
"""2026-11-16 00:00:00 UTC; punto de partida de las conversaciones simuladas."""

TITULO_BOTON_MAX = 20
ID_BOTON_MAX = 256
TITULO_FILA_MAX = 24
DESCRIPCION_FILA_MAX = 72
TEXTO_MAX = 4096

Payload = dict[str, Any]


def numero_ficticio(indice: int) -> str:
    """Devuelve un número de usuario simulado, imposible como móvil real."""
    if not 0 <= indice < 100_000:
        raise ValueError("indice fuera de rango")
    return f"{PREFIJO_NUMERO_FICTICIO}{indice:05d}"


def id_mensaje(numero: str, marca_tiempo: int, contenido: str) -> str:
    """Genera un ``wamid`` determinista a partir del remitente, la hora y el contenido."""
    huella = hashlib.sha256(f"{numero}|{marca_tiempo}|{contenido}".encode()).hexdigest()
    return f"wamid.SIM{huella[:40]}"


def _sobre(numero: str, nombre: str, mensaje: Mapping[str, Any]) -> Payload:
    """Envuelve un mensaje en la estructura completa del webhook."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": WABA_ID_PRUEBA,
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": NUMERO_NEGOCIO_PRUEBA,
                                "phone_number_id": PHONE_NUMBER_ID_PRUEBA,
                            },
                            "contacts": [{"profile": {"name": nombre}, "wa_id": numero}],
                            "messages": [dict(mensaje)],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _base(
    numero: str, marca_tiempo: int, tipo: str, contenido: str, wamid: str | None
) -> dict[str, Any]:
    return {
        "from": numero,
        "id": wamid or id_mensaje(numero, marca_tiempo, f"{tipo}:{contenido}"),
        "timestamp": str(marca_tiempo),
        "type": tipo,
    }


def payload_texto(
    numero: str,
    texto: str,
    *,
    marca_tiempo: int = MARCA_TIEMPO_BASE,
    nombre: str = "Persona simulada",
    wamid: str | None = None,
) -> Payload:
    """Construye el payload de un mensaje de texto libre."""
    if not texto:
        raise ValueError("el texto no puede estar vacío")
    if len(texto) > TEXTO_MAX:
        raise ValueError(f"el texto supera {TEXTO_MAX} caracteres")
    mensaje = _base(numero, marca_tiempo, "text", texto, wamid)
    mensaje["text"] = {"body": texto}
    return _sobre(numero, nombre, mensaje)


def payload_boton(
    numero: str,
    id_boton: str,
    titulo: str,
    *,
    marca_tiempo: int = MARCA_TIEMPO_BASE,
    nombre: str = "Persona simulada",
    contexto_wamid: str | None = None,
    wamid: str | None = None,
) -> Payload:
    """Construye el payload de la respuesta a un botón interactivo (``button_reply``)."""
    if not 0 < len(id_boton) <= ID_BOTON_MAX:
        raise ValueError(f"el id del botón debe tener entre 1 y {ID_BOTON_MAX} caracteres")
    if not 0 < len(titulo) <= TITULO_BOTON_MAX:
        raise ValueError(f"el título del botón debe tener entre 1 y {TITULO_BOTON_MAX} caracteres")
    mensaje = _base(numero, marca_tiempo, "interactive", id_boton, wamid)
    if contexto_wamid:
        mensaje["context"] = {"from": NUMERO_NEGOCIO_PRUEBA, "id": contexto_wamid}
    mensaje["interactive"] = {
        "type": "button_reply",
        "button_reply": {"id": id_boton, "title": titulo},
    }
    return _sobre(numero, nombre, mensaje)


def payload_lista(
    numero: str,
    id_fila: str,
    titulo: str,
    descripcion: str | None = None,
    *,
    marca_tiempo: int = MARCA_TIEMPO_BASE,
    nombre: str = "Persona simulada",
    contexto_wamid: str | None = None,
    wamid: str | None = None,
) -> Payload:
    """Construye el payload de la selección de una fila de lista (``list_reply``)."""
    if not 0 < len(id_fila) <= ID_BOTON_MAX:
        raise ValueError(f"el id de la fila debe tener entre 1 y {ID_BOTON_MAX} caracteres")
    if not 0 < len(titulo) <= TITULO_FILA_MAX:
        raise ValueError(f"el título de la fila debe tener entre 1 y {TITULO_FILA_MAX} caracteres")
    if descripcion is not None and len(descripcion) > DESCRIPCION_FILA_MAX:
        raise ValueError(f"la descripción supera {DESCRIPCION_FILA_MAX} caracteres")
    mensaje = _base(numero, marca_tiempo, "interactive", id_fila, wamid)
    if contexto_wamid:
        mensaje["context"] = {"from": NUMERO_NEGOCIO_PRUEBA, "id": contexto_wamid}
    respuesta: dict[str, str] = {"id": id_fila, "title": titulo}
    if descripcion is not None:
        respuesta["description"] = descripcion
    mensaje["interactive"] = {"type": "list_reply", "list_reply": respuesta}
    return _sobre(numero, nombre, mensaje)


def serializar(payload: Payload) -> bytes:
    """Serializa el payload como lo haría Meta: JSON compacto en UTF-8.

    La firma se calcula sobre estos bytes exactos; volver a serializar el ``dict``
    con otro formato cambia la firma.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def firmar(cuerpo: bytes, app_secret: str) -> str:
    """Devuelve el valor de ``X-Hub-Signature-256``: ``sha256=`` + HMAC-SHA256 en hexadecimal."""
    if not app_secret:
        raise ValueError("app_secret vacío")
    return "sha256=" + hmac.new(app_secret.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()


def encabezados_firmados(cuerpo: bytes, app_secret: str) -> dict[str, str]:
    """Encabezados HTTP con los que Meta entrega el webhook."""
    return {"Content-Type": "application/json", "X-Hub-Signature-256": firmar(cuerpo, app_secret)}


class ClienteHTTP(Protocol):
    """Lo mínimo que se necesita del ``TestClient`` de FastAPI (o de ``httpx.Client``)."""

    def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> Any:
        """Envía un POST con cuerpo crudo."""
        ...


def enviar_a_webhook(
    cliente: ClienteHTTP,
    payload: Payload,
    app_secret: str,
    *,
    ruta: str = "/webhook/whatsapp",
    firma_valida: bool = True,
) -> Any:
    """Serializa, firma y envía un payload al webhook. Devuelve la respuesta del cliente.

    Con ``firma_valida=False`` firma con un secreto distinto para probar el rechazo.
    """
    cuerpo = serializar(payload)
    secreto = app_secret if firma_valida else app_secret + "-invalido"
    return cliente.post(ruta, content=cuerpo, headers=encabezados_firmados(cuerpo, secreto))
