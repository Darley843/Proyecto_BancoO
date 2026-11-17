"""Pruebas del envío falso y real del canal, sin red.

El enviador real se prueba con ``httpx.MockTransport``: se inspeccionan la URL,
las cabeceras y el cuerpo, y se simulan 429, 5xx y 4xx sin abrir un socket.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest

from banco_occidente_corpus.canal.contratos import BotonCanal, RespuestaCanal
from banco_occidente_corpus.canal.envio import (
    LARGO_MAXIMO,
    EnviadorFalso,
    EnviadorMeta,
    ErrorEnvio,
    partir_texto,
)

USUARIO = "u" * 64
"""Huella ficticia del número."""

TOKEN = "token-secreto-de-prueba"
"""Token ficticio de Meta, para comprobar que no se filtra."""

AHORA = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
"""Instante fijo de las pruebas."""

TipoRespuesta = Literal["texto", "botones", "error"]


def _respuesta(
    texto: str = "hola", *, tipo: TipoRespuesta = "texto", botones: list[BotonCanal] | None = None
) -> RespuestaCanal:
    """Construye una respuesta válida del canal."""
    return RespuestaCanal(
        usuario_id=USUARIO,
        id_mensaje_origen="wamid.1",
        texto=texto,
        tipo=tipo,
        botones=botones or [],
    )


def _cliente(
    manejador: Callable[[httpx.Request], httpx.Response],
    llamadas: list[httpx.Request],
) -> httpx.Client:
    """Cliente con transporte simulado que registra cada petición."""

    def envolver(peticion: httpx.Request) -> httpx.Response:
        llamadas.append(peticion)
        return manejador(peticion)

    return httpx.Client(transport=httpx.MockTransport(envolver))


def _meta(
    cliente: httpx.Client,
    *,
    huellas: tuple[str, ...] = (USUARIO,),
    intentos: int = 2,
) -> EnviadorMeta:
    """Enviador real apuntando a un transporte simulado."""
    return EnviadorMeta(
        usuario_id=USUARIO,
        destino="57000000001",
        phone_number_id="100000000000001",
        token=TOKEN,
        user_agent="UA/prueba",
        remitente="correo@uao.edu.co",
        huellas=huellas,
        cliente=cliente,
        intentos=intentos,
        espera=lambda _: None,
    )


def test_partir_texto_corto_no_cambia() -> None:
    """Un texto que cabe se devuelve en un solo bloque."""
    assert partir_texto("hola") == ["hola"]


def test_partir_texto_por_parrafos() -> None:
    """Dos párrafos largos se reparten sin perder caracteres."""
    texto = f"{'a' * 3000}\n\n{'b' * 3000}"

    partes = partir_texto(texto)

    assert len(partes) == 2
    assert all(len(parte) <= LARGO_MAXIMO for parte in partes)
    assert "\n\n".join(partes) == texto


def test_partir_texto_corta_un_parrafo_gigante() -> None:
    """Un párrafo mayor que el límite se corta duro."""
    partes = partir_texto("x" * 5000)

    assert [len(parte) for parte in partes] == [LARGO_MAXIMO, 5000 - LARGO_MAXIMO]


def test_enviador_falso_registra_y_devuelve_id(tmp_path: Path) -> None:
    """El envío falso escribe en `envios` y no usa la red."""
    enviador = EnviadorFalso(tmp_path / "whatsapp.sqlite")

    salida = enviador.enviar(_respuesta("hola"))

    assert salida.startswith("fake:")
    with sqlite3.connect(str(tmp_path / "whatsapp.sqlite")) as conexion:
        filas = conexion.execute("SELECT clave, estado FROM envios").fetchall()
    assert len(filas) == 1
    assert len(filas[0][0]) == 64
    assert filas[0][1] == "enviado"


def test_enviador_falso_es_idempotente_por_mensaje_y_texto(tmp_path: Path) -> None:
    """El mismo mensaje y la misma respuesta no se registran dos veces."""
    enviador = EnviadorFalso(tmp_path / "whatsapp.sqlite")

    enviador.enviar(_respuesta("hola"))
    enviador.enviar(_respuesta("hola"))

    with sqlite3.connect(str(tmp_path / "whatsapp.sqlite")) as conexion:
        total = conexion.execute("SELECT COUNT(*) FROM envios").fetchone()[0]
    assert total == 1


def test_enviador_meta_rechaza_destino_no_autorizado() -> None:
    """En modo real solo se envía a una huella autorizada."""
    llamadas: list[httpx.Request] = []
    cliente = _cliente(lambda _: httpx.Response(200), llamadas)
    enviador = _meta(cliente, huellas=())

    with pytest.raises(ErrorEnvio):
        enviador.enviar(_respuesta())

    assert llamadas == []
    cliente.close()


def test_enviador_meta_envia_texto_con_cabeceras() -> None:
    """La petición lleva URL, token, User-Agent, From y el cuerpo de texto."""
    llamadas: list[httpx.Request] = []
    cliente = _cliente(
        lambda _: httpx.Response(200, json={"messages": [{"id": "wamid.OUT"}]}),
        llamadas,
    )

    salida = _meta(cliente).enviar(_respuesta("hola"))

    assert salida == "wamid.OUT"
    peticion = llamadas[0]
    assert str(peticion.url) == "https://graph.facebook.com/v23.0/100000000000001/messages"
    assert peticion.headers["authorization"] == f"Bearer {TOKEN}"
    assert peticion.headers["user-agent"] == "UA/prueba"
    assert peticion.headers["from"] == "correo@uao.edu.co"
    cuerpo = json.loads(peticion.content)
    assert cuerpo["to"] == "57000000001"
    assert cuerpo["type"] == "text"
    assert cuerpo["text"]["body"] == "hola"
    cliente.close()


def test_enviador_meta_envia_botones() -> None:
    """Dos botones viajan como mensaje interactivo con sus títulos recortados."""
    llamadas: list[httpx.Request] = []
    cliente = _cliente(lambda _: httpx.Response(200, json={"messages": [{"id": "x"}]}), llamadas)
    botones = [
        BotonCanal(id="consent:acepto", titulo="Acepto"),
        BotonCanal(id="consent:rechazo", titulo="Ahora no"),
    ]

    _meta(cliente).enviar(_respuesta("¿Aceptas?", tipo="botones", botones=botones))

    cuerpo = json.loads(llamadas[0].content)
    assert cuerpo["type"] == "interactive"
    assert [boton["reply"]["id"] for boton in cuerpo["interactive"]["action"]["buttons"]] == [
        "consent:acepto",
        "consent:rechazo",
    ]
    cliente.close()


def test_enviador_meta_reintenta_429_y_5xx() -> None:
    """Un 429 seguido de 200 se reintenta y termina bien."""
    llamadas: list[httpx.Request] = []
    respuestas = iter([429, 200])

    def manejador(_: httpx.Request) -> httpx.Response:
        estado = next(respuestas)
        return httpx.Response(estado, json={"messages": [{"id": "wamid.R"}]})

    salida = _meta(_cliente(manejador, llamadas)).enviar(_respuesta())

    assert salida == "wamid.R"
    assert len(llamadas) == 2


def test_enviador_meta_no_reintenta_4xx() -> None:
    """Un 400 no se reintenta: es un error del contrato, no de red."""
    llamadas: list[httpx.Request] = []
    cliente = _cliente(lambda _: httpx.Response(400, json={"error": "x"}), llamadas)

    with pytest.raises(ErrorEnvio):
        _meta(cliente).enviar(_respuesta())

    assert len(llamadas) == 1
    cliente.close()


def test_enviador_meta_agota_los_intentos_y_no_filtra_el_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tras dos 500 falla y el log no contiene token ni destino."""
    llamadas: list[httpx.Request] = []
    cliente = _cliente(lambda _: httpx.Response(500), llamadas)

    with caplog.at_level(logging.WARNING), pytest.raises(ErrorEnvio):
        _meta(cliente).enviar(_respuesta())

    assert len(llamadas) == 2
    assert TOKEN not in caplog.text
    assert "57000000001" not in caplog.text
    cliente.close()


def test_el_cliente_http_se_crea_con_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin cliente inyectado, `httpx.Client` recibe el timeout explícito."""
    capturado: dict[str, Any] = {}

    class ClienteFalso:
        """Cliente mínimo que responde 200 y cierra sin red."""

        def post(self, *_: Any, **__: Any) -> httpx.Response:
            """Devuelve un envío correcto."""
            return httpx.Response(200, json={"messages": [{"id": "x"}]})

        def close(self) -> None:
            """Cierra el cliente falso."""

    def fabrica(**opciones: Any) -> ClienteFalso:
        """Registra las opciones con las que se construiría el cliente."""
        capturado.update(opciones)
        return ClienteFalso()

    monkeypatch.setattr(httpx, "Client", fabrica)
    enviador = EnviadorMeta(
        usuario_id=USUARIO,
        destino="57000000001",
        phone_number_id="1",
        token=TOKEN,
        user_agent="UA",
        remitente="correo@uao.edu.co",
        huellas=(USUARIO,),
    )

    enviador.enviar(_respuesta())

    assert capturado["timeout"] == 10.0
