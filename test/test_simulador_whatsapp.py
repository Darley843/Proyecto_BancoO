"""Pruebas del simulador de payloads de WhatsApp y de las personas sintéticas (sin red)."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import pytest

from banco_occidente_corpus.simulador.payloads import (
    MARCA_TIEMPO_BASE,
    NUMERO_NEGOCIO_PRUEBA,
    PREFIJO_NUMERO_FICTICIO,
    enviar_a_webhook,
    firmar,
    id_mensaje,
    numero_ficticio,
    payload_boton,
    payload_lista,
    payload_texto,
    serializar,
)
from banco_occidente_corpus.simulador.personas import (
    SemaforoEsperado,
    cargar_personas,
    conversacion,
)

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = RAIZ / "test" / "fixtures" / "whatsapp"
PERSONAS = RAIZ / "data" / "evaluacion" / "personas_sinteticas.json"
SECRETO = "secreto-de-prueba-no-real"


def _mensaje(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["entry"][0]["changes"][0]["value"]["messages"][0]


# --- Estructura de los payloads ---


def test_payload_texto_tiene_la_estructura_de_meta() -> None:
    payload = payload_texto(numero_ficticio(1), "hola")
    assert payload["object"] == "whatsapp_business_account"
    cambio = payload["entry"][0]["changes"][0]
    assert cambio["field"] == "messages"
    assert cambio["value"]["messaging_product"] == "whatsapp"
    mensaje = _mensaje(payload)
    assert mensaje["type"] == "text"
    assert mensaje["text"] == {"body": "hola"}
    assert mensaje["timestamp"] == str(MARCA_TIEMPO_BASE)
    assert mensaje["id"].startswith("wamid.")


def test_payload_boton_es_button_reply() -> None:
    mensaje = _mensaje(
        payload_boton(
            numero_ficticio(1), "consentimiento.acepto", "Acepto", contexto_wamid="wamid.X"
        )
    )
    assert mensaje["type"] == "interactive"
    assert mensaje["interactive"] == {
        "type": "button_reply",
        "button_reply": {"id": "consentimiento.acepto", "title": "Acepto"},
    }
    assert mensaje["context"] == {"from": NUMERO_NEGOCIO_PRUEBA, "id": "wamid.X"}


def test_payload_lista_es_list_reply_y_omite_descripcion_si_no_hay() -> None:
    mensaje = _mensaje(payload_lista(numero_ficticio(1), "plazo.36", "36 meses"))
    assert mensaje["interactive"] == {
        "type": "list_reply",
        "list_reply": {"id": "plazo.36", "title": "36 meses"},
    }
    assert "context" not in mensaje


@pytest.mark.parametrize(
    "construir",
    [
        lambda: payload_boton(numero_ficticio(1), "x", "T" * 21),
        lambda: payload_boton(numero_ficticio(1), "x" * 257, "ok"),
        lambda: payload_lista(numero_ficticio(1), "x", "T" * 25),
        lambda: payload_lista(numero_ficticio(1), "x", "ok", "D" * 73),
        lambda: payload_texto(numero_ficticio(1), ""),
        lambda: payload_texto(numero_ficticio(1), "a" * 4097),
    ],
)
def test_limites_de_meta_se_validan(construir: Any) -> None:
    with pytest.raises(ValueError):
        construir()


def test_id_de_mensaje_es_determinista_y_distingue_contenido() -> None:
    assert id_mensaje("1", 10, "a") == id_mensaje("1", 10, "a")
    assert id_mensaje("1", 10, "a") != id_mensaje("1", 10, "b")
    assert id_mensaje("1", 10, "a") != id_mensaje("1", 11, "a")


def test_numeros_ficticios_no_son_moviles_colombianos() -> None:
    numero = numero_ficticio(42)
    assert numero.startswith(PREFIJO_NUMERO_FICTICIO)
    assert not numero.startswith("573")


@pytest.mark.parametrize(
    ("nombre", "construir"),
    [
        (
            "texto.json",
            lambda ctx: payload_texto(numero_ficticio(1), "Hola, quiero hacer el diagnóstico"),
        ),
        (
            "boton.json",
            lambda ctx: payload_boton(
                numero_ficticio(1), "consentimiento.acepto", "Acepto", contexto_wamid=ctx
            ),
        ),
        (
            "lista.json",
            lambda ctx: payload_lista(
                numero_ficticio(1),
                "ingresos.DE_3M_A_5M",
                "$3 M a $5 M",
                "Ingreso mensual",
                contexto_wamid=ctx,
            ),
        ),
    ],
)
def test_fixtures_coinciden_con_el_constructor(nombre: str, construir: Any) -> None:
    contexto = id_mensaje(NUMERO_NEGOCIO_PRUEBA, MARCA_TIEMPO_BASE, "pregunta")
    esperado = json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))
    assert construir(contexto) == esperado


# --- Firma X-Hub-Signature-256 ---


def test_firma_es_hmac_sha256_del_cuerpo_crudo() -> None:
    cuerpo = serializar(payload_texto(numero_ficticio(1), "hola"))
    esperada = "sha256=" + hmac.new(SECRETO.encode(), cuerpo, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(firmar(cuerpo, SECRETO), esperada)


def test_cambiar_un_byte_cambia_la_firma() -> None:
    cuerpo = serializar(payload_texto(numero_ficticio(1), "hola"))
    alterado = cuerpo.replace(b"hola", b"hol4")
    assert firmar(cuerpo, SECRETO) != firmar(alterado, SECRETO)


def test_serializar_conserva_tildes_en_utf8() -> None:
    cuerpo = serializar(payload_texto(numero_ficticio(1), "¿Qué tasa?"))
    assert "¿Qué tasa?".encode() in cuerpo


def test_firmar_rechaza_secreto_vacio() -> None:
    with pytest.raises(ValueError):
        firmar(b"{}", "")


class _ClienteFalso:
    """Registra lo que se enviaría al webhook, sin red."""

    def __init__(self) -> None:
        self.llamadas: list[tuple[str, bytes, dict[str, str]]] = []

    def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> int:
        self.llamadas.append((url, content, headers))
        return 200


def test_enviar_a_webhook_firma_el_cuerpo_exacto() -> None:
    cliente = _ClienteFalso()
    enviar_a_webhook(cliente, payload_texto(numero_ficticio(1), "hola"), SECRETO)
    url, cuerpo, encabezados = cliente.llamadas[0]
    assert url == "/webhook/whatsapp"
    assert encabezados["Content-Type"] == "application/json"
    assert encabezados["X-Hub-Signature-256"] == firmar(cuerpo, SECRETO)


def test_enviar_a_webhook_puede_mandar_firma_invalida() -> None:
    cliente = _ClienteFalso()
    enviar_a_webhook(
        cliente, payload_texto(numero_ficticio(1), "hola"), SECRETO, firma_valida=False
    )
    _, cuerpo, encabezados = cliente.llamadas[0]
    assert encabezados["X-Hub-Signature-256"] != firmar(cuerpo, SECRETO)


# --- Personas sintéticas ---


def test_hay_cinco_personas_con_los_perfiles_de_la_guia() -> None:
    ids = {p.id for p in cargar_personas(PERSONAS)}
    assert ids == {
        "empleada_verde",
        "independiente_rojo",
        "pensionado_amarillo",
        "joven_sin_historial",
        "intento_inyeccion",
    }


def test_las_personas_cubren_los_tres_colores_y_la_inyeccion() -> None:
    personas = cargar_personas(PERSONAS)
    colores = {p.esperado.semaforo for p in personas}
    assert {SemaforoEsperado.VERDE, SemaforoEsperado.AMARILLO, SemaforoEsperado.ROJO} <= colores
    assert any(p.esperado.bloquea_inyeccion for p in personas)
    assert all(
        p.esperado.deriva_asesor == (p.esperado.semaforo is SemaforoEsperado.ROJO) for p in personas
    )


@pytest.mark.parametrize("persona", cargar_personas(PERSONAS), ids=lambda p: p.id)
def test_conversacion_completa_y_ordenada(persona: Any) -> None:
    payloads = conversacion(persona)
    mensajes = [_mensaje(p) for p in payloads]
    assert len(mensajes) == len(persona.turnos)
    marcas = [int(m["timestamp"]) for m in mensajes]
    assert marcas == sorted(marcas) and len(set(marcas)) == len(marcas)
    assert len({m["id"] for m in mensajes}) == len(mensajes)
    assert {m["from"] for m in mensajes} == {persona.numero}
    ids_interactivos = [
        m["interactive"][m["interactive"]["type"]]["id"]
        for m in mensajes
        if m["type"] == "interactive"
    ]
    assert "consentimiento.acepto" in ids_interactivos
    assert ids_interactivos[-1] == "confirmacion.confirmar"
    # La entrevista pide las cinco listas del guion antes de confirmar.
    for prefijo in ("objetivo.", "ingresos.", "gastos.", "cuotas.", "vinculacion.", "plazo."):
        assert any(i.startswith(prefijo) for i in ids_interactivos), prefijo


def test_persona_de_inyeccion_envia_los_ataques_antes_de_la_entrevista() -> None:
    persona = next(p for p in cargar_personas(PERSONAS) if p.id == "intento_inyeccion")
    textos = [t.valor for t in persona.turnos if t.tipo == "texto"]
    assert any("prompt" in t.lower() for t in textos)
    assert any("ignora" in t.lower() for t in textos)
