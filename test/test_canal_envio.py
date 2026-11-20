"""Pruebas del envío falso y real del canal, sin red.

El enviador real se prueba con ``httpx.MockTransport``: se inspeccionan la URL,
las cabeceras y el cuerpo, y se simulan 429, 5xx y 4xx sin abrir un socket.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest

from banco_occidente_corpus.canal.contratos import BotonCanal, OpcionCanal, RespuestaCanal
from banco_occidente_corpus.canal.envio import (
    LARGO_MAXIMO,
    EnviadorFalso,
    EnviadorMeta,
    ErrorEnvio,
    partir_texto,
)

USUARIO = "u" * 64
"""Huella ficticia del número."""

TOKEN = "token-de-prueba"
"""Token ficticio de Meta, para comprobar que no se filtra."""

AHORA = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
"""Instante fijo de las pruebas."""

TipoRespuesta = Literal["texto", "botones", "lista", "error", "imagen"]

PNG = b"\x89PNG\r\n\x1a\n" + b"tarjeta-de-pana"
"""Bytes ficticios de una tarjeta; el enviador no decodifica el PNG."""


def _respuesta(
    texto: str = "hola",
    *,
    tipo: TipoRespuesta = "texto",
    botones: list[BotonCanal] | None = None,
    opciones: list[OpcionCanal] | None = None,
    imagen: bytes | None = None,
) -> RespuestaCanal:
    """Construye una respuesta válida del canal."""
    return RespuestaCanal(
        usuario_id=USUARIO,
        id_mensaje_origen="wamid.1",
        texto=texto,
        tipo=tipo,
        botones=botones or [],
        opciones=opciones or [],
        imagen=imagen,
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


def test_enviador_meta_envia_lista_con_filas() -> None:
    """Las opciones de la entrevista viajan como lista interactiva."""
    llamadas: list[httpx.Request] = []
    cliente = _cliente(lambda _: httpx.Response(200, json={"messages": [{"id": "x"}]}), llamadas)
    opciones = [
        OpcionCanal(id="objetivo.vivienda", titulo="Vivienda", descripcion="Crédito hipotecario"),
        OpcionCanal(id="objetivo.ahorro", titulo="Solo ahorrar"),
    ]

    _meta(cliente).enviar(_respuesta("¿Qué quieres revisar?", tipo="lista", opciones=opciones))

    cuerpo = json.loads(llamadas[0].content)
    interactivo = cuerpo["interactive"]
    assert cuerpo["type"] == "interactive"
    assert interactivo["type"] == "list"
    assert interactivo["action"]["button"] == "Elige una opción"
    filas = interactivo["action"]["sections"][0]["rows"]
    assert [fila["id"] for fila in filas] == ["objetivo.vivienda", "objetivo.ahorro"]
    assert filas[0]["description"] == "Crédito hipotecario"
    assert "description" not in filas[1]
    cliente.close()


def test_enviador_meta_recorta_titulos_de_la_lista() -> None:
    """El envío aplica los topes de Meta aunque el contrato los valide antes."""
    llamadas: list[httpx.Request] = []
    cliente = _cliente(lambda _: httpx.Response(200, json={"messages": [{"id": "x"}]}), llamadas)
    opcion = OpcionCanal(id="fila", titulo="x" * 24, descripcion="y" * 72)

    _meta(cliente).enviar(_respuesta("Elige", tipo="lista", opciones=[opcion]))

    fila = json.loads(llamadas[0].content)["interactive"]["action"]["sections"][0]["rows"][0]
    assert len(fila["title"]) == 24
    assert len(fila["description"]) == 72
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


def test_enviador_falso_registra_texto_y_despues_imagen(tmp_path: Path) -> None:
    """El falso deja constancia del orden: primero el texto, luego la tarjeta."""
    enviador = EnviadorFalso(tmp_path / "whatsapp.sqlite")

    enviador.enviar(_respuesta("Tu diagnóstico", tipo="imagen", imagen=PNG))

    assert [tipo for tipo, _ in enviador.registro] == ["texto", "imagen"]
    assert enviador.registro[0][1] == "Tu diagnóstico"
    assert enviador.registro[1][1] == hashlib.sha256(PNG).hexdigest()


def test_enviador_meta_sube_la_imagen_y_la_envia_despues_del_texto() -> None:
    """La tarjeta viaja como media y después como mensaje de imagen."""
    llamadas: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "media-1"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.OUT"}]})

    cliente = _cliente(manejador, llamadas)

    salida = _meta(cliente).enviar(_respuesta("Tu diagnóstico", tipo="imagen", imagen=PNG))

    assert salida == "wamid.OUT"
    assert [peticion.url.path for peticion in llamadas] == [
        "/v23.0/100000000000001/messages",
        "/v23.0/100000000000001/media",
        "/v23.0/100000000000001/messages",
    ]
    primera = json.loads(llamadas[0].content)
    assert primera["type"] == "text"

    subida = llamadas[1]
    assert subida.headers["authorization"] == f"Bearer {TOKEN}"
    assert subida.headers["user-agent"] == "UA/prueba"
    assert subida.headers["from"] == "correo@uao.edu.co"
    assert subida.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="pana.png"' in subida.content
    assert b"Content-Type: image/png" in subida.content
    assert b'name="messaging_product"' in subida.content

    imagen = json.loads(llamadas[2].content)
    assert imagen["type"] == "image"
    assert imagen["image"] == {"id": "media-1"}
    cliente.close()


@pytest.mark.parametrize("falla", ["subida", "envio"])
def test_falla_de_la_imagen_no_corta_la_respuesta(falla: str) -> None:
    """Si la tarjeta no sale, el envío termina bien con el id del texto."""
    llamadas: list[httpx.Request] = []
    mensajes = {"n": 0}

    def manejador(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path.endswith("/media"):
            if falla == "subida":
                return httpx.Response(500, json={"error": "x"})
            return httpx.Response(200, json={"id": "media-1"})
        mensajes["n"] += 1
        if falla == "envio" and mensajes["n"] == 2:
            return httpx.Response(400, json={"error": "x"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.TEXTO"}]})

    salida = _meta(_cliente(manejador, llamadas)).enviar(
        _respuesta("Tu diagnóstico", tipo="imagen", imagen=PNG)
    )

    assert salida == "wamid.TEXTO"
    assert len(llamadas) == 3


def test_falla_de_la_imagen_no_filtra_el_token_ni_el_destino(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """El aviso de la tarjeta fallida no expone credenciales ni el número."""
    llamadas: list[httpx.Request] = []

    def manejador(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path.endswith("/media"):
            return httpx.Response(400, json={"error": "x"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.TEXTO"}]})

    with caplog.at_level(logging.WARNING):
        _meta(_cliente(manejador, llamadas)).enviar(
            _respuesta("Tu diagnóstico", tipo="imagen", imagen=PNG)
        )

    assert "no se pudo enviar la tarjeta" in caplog.text
    assert TOKEN not in caplog.text
    assert "57000000001" not in caplog.text
