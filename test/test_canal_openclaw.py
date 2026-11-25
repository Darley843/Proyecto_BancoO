"""Pruebas del cliente del gateway de OpenClaw (sin red).

El transporte HTTP se sustituye por ``httpx.MockTransport``: se comprueba el
contrato del cuerpo y las cabeceras, que no viaja el número ni el historial, y
que timeout, error de red, ``5xx`` y cuerpos inválidos se clasifican como fallo
para que el despachador use el grafo.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from banco_occidente_corpus.canal.openclaw import (
    VARIABLE_ACTIVO,
    VARIABLE_TOKEN,
    ClienteOpenClaw,
    ConfiguracionOpenClaw,
    cargar_configuracion_openclaw,
    cliente_desde_entorno,
)

HUELLA = "a" * 64
"""Huella HMAC ficticia: 64 hexadecimales, sin número en claro."""

TOKEN = "token-de-prueba"
UA = "TAAML-bot/1.0 (uso academico)"
REMITENTE = "qa@example.edu"


def _cliente(
    handler: object,
    *,
    token: str = TOKEN,
    config: ConfiguracionOpenClaw | None = None,
) -> ClienteOpenClaw:
    """Construye el cliente con un transporte falso y un token de prueba."""
    return ClienteOpenClaw(
        config or ConfiguracionOpenClaw(),
        token=token,
        user_agent=UA,
        remitente=REMITENTE,
        transporte=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


def _respuesta(texto: str) -> httpx.Response:
    """Devuelve una respuesta compatible con OpenAI."""
    return httpx.Response(200, json={"choices": [{"message": {"content": texto}}]})


def test_envia_solo_el_mensaje_nuevo_y_la_huella() -> None:
    """El cuerpo lleva el modelo, el hilo y un único mensaje: sin historial."""
    visto: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Guarda el cuerpo y las cabeceras del turno."""
        visto["cuerpo"] = json.loads(request.content)
        visto["cabeceras"] = dict(request.headers)
        return _respuesta("  respuesta del agente  ")

    cliente = _cliente(handler)

    assert cliente.responder("¿cuál es la cuota?", HUELLA) == "respuesta del agente"
    assert visto["cuerpo"] == {
        "model": "openclaw:pana",
        "user": f"wa:{HUELLA}",
        "messages": [{"role": "user", "content": "¿cuál es la cuota?"}],
    }
    assert len(visto["cuerpo"]["messages"]) == 1  # type: ignore[index]
    assert visto["cabeceras"]["authorization"] == f"Bearer {TOKEN}"  # type: ignore[index]
    assert visto["cabeceras"]["user-agent"] == UA  # type: ignore[index]
    assert visto["cabeceras"]["from"] == REMITENTE  # type: ignore[index]


def test_el_numero_no_aparece_en_la_peticion() -> None:
    """La huella es lo único que identifica al invitado; no viaja el número."""
    enviado: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        """Guarda el cuerpo y las cabeceras completas como texto."""
        enviado["cuerpo"] = request.content.decode("utf-8")
        enviado["cabeceras"] = repr(request.headers)
        return _respuesta("ok")

    _cliente(handler).responder("hola", HUELLA)

    assert "57000000001" not in enviado["cuerpo"]
    assert "57000000001" not in enviado["cabeceras"]
    assert HUELLA in enviado["cuerpo"]


def test_timeout_se_clasifica_como_fallo() -> None:
    """Un gateway colgado devuelve ``None`` para que responda el grafo."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Simula que el gateway agotó el tiempo."""
        raise httpx.ReadTimeout("agotado", request=request)

    assert _cliente(handler).responder("hola", HUELLA) is None


def test_error_de_red_se_clasifica_como_fallo() -> None:
    """Un fallo de conexión no propaga la excepción al despachador."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Simula que el gateway no está escuchando."""
        raise httpx.ConnectError("sin conexión", request=request)

    assert _cliente(handler).responder("hola", HUELLA) is None


@pytest.mark.parametrize(
    ("estado", "cuerpo"),
    [
        (500, {"choices": []}),
        (503, {"error": "no disponible"}),
        (401, {"error": "token inválido"}),
        (200, None),
        (200, {}),
        (200, {"choices": []}),
        (200, {"choices": [{"message": {"content": ""}}]}),
        (200, {"choices": [{"message": {"content": None}}]}),
        (200, {"choices": [{"message": "texto"}]}),
    ],
)
def test_respuestas_no_usables_se_clasifican_como_fallo(
    estado: int, cuerpo: dict[str, object] | None
) -> None:
    """Un estado distinto de 200 o un contenido vacío no se envía al invitado."""

    def handler(_request: httpx.Request) -> httpx.Response:
        """Devuelve el estado y el cuerpo del caso."""
        if cuerpo is None:
            return httpx.Response(estado, content=b"no-json")
        return httpx.Response(estado, json=cuerpo)

    assert _cliente(handler).responder("hola", HUELLA) is None


def test_un_solo_intento_ante_un_5xx() -> None:
    """El cliente no reintenta: un reintento repetiría el turno."""
    llamadas: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        """Cuenta las peticiones y falla siempre."""
        llamadas.append(1)
        return httpx.Response(500)

    assert _cliente(handler).responder("hola", HUELLA) is None
    assert len(llamadas) == 1


def test_sin_token_no_hay_peticion() -> None:
    """Sin token el motor queda deshabilitado y no se abre la conexión."""
    llamadas: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        """No debería ejecutarse."""
        llamadas.append(1)
        return _respuesta("ok")

    cliente = _cliente(handler, token="")

    assert cliente.disponible is False
    assert cliente.responder("hola", HUELLA) is None
    assert llamadas == []


def test_fallback_forzado_no_hace_peticion() -> None:
    """``fallback_forzado`` devuelve el canal al grafo sin tocar la red."""
    llamadas: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        """No debería ejecutarse."""
        llamadas.append(1)
        return _respuesta("ok")

    cliente = _cliente(handler, config=ConfiguracionOpenClaw(fallback_forzado=True))

    assert cliente.disponible is False
    assert cliente.responder("hola", HUELLA) is None
    assert llamadas == []


def test_configuracion_rechaza_base_fuera_de_loopback() -> None:
    """El token nunca se envía a un host público."""
    with pytest.raises(ValueError, match="loopback"):
        ConfiguracionOpenClaw(base_url="http://example.com:18789")


def test_configuracion_rechaza_reintentos() -> None:
    """El contrato prohíbe reintentos."""
    with pytest.raises(ValueError, match="reintentos"):
        ConfiguracionOpenClaw(reintentos=1)


def test_configuracion_rechaza_timeout_no_positivo() -> None:
    """Un timeout de cero no se acepta."""
    with pytest.raises(ValueError, match="timeout"):
        ConfiguracionOpenClaw(timeout_segundos=0)


def test_carga_la_seccion_gateway(tmp_path: Path) -> None:
    """El cargador lee los valores del TOML y calcula la URL del contrato."""
    archivo = tmp_path / "openclaw.toml"
    archivo.write_text(
        "[gateway]\n"
        'base_url = "http://127.0.0.1:19000/"\n'
        'modelo = "openclaw:otro"\n'
        'prefijo_usuario = "wa:"\n'
        "timeout_segundos = 5.5\n"
        "reintentos = 0\n"
        "fallback_forzado = false\n",
        encoding="utf-8",
    )

    config = cargar_configuracion_openclaw(archivo)

    assert config.base_url == "http://127.0.0.1:19000/"
    assert config.modelo == "openclaw:otro"
    assert config.timeout_segundos == 5.5
    assert config.url_chat == "http://127.0.0.1:19000/v1/chat/completions"


def test_configuracion_por_defecto_sin_archivo(tmp_path: Path) -> None:
    """Sin archivo se usan los valores del contrato."""
    config = cargar_configuracion_openclaw(tmp_path / "no-existe.toml")

    assert config.url_chat == "http://127.0.0.1:18789/v1/chat/completions"
    assert config.timeout_segundos == 45.0
    assert config.reintentos == 0


def test_cliente_desde_entorno_apagado(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sin ``OPENCLAW_ACTIVO`` el cliente no se crea aunque haya token."""
    monkeypatch.setenv(VARIABLE_TOKEN, TOKEN)
    monkeypatch.delenv(VARIABLE_ACTIVO, raising=False)

    assert (
        cliente_desde_entorno(
            user_agent=UA, remitente=REMITENTE, ruta_config=tmp_path / "openclaw.toml"
        )
        is None
    )


def test_cliente_desde_entorno_sin_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Con el motor activo pero sin token, no hay valor por defecto."""
    monkeypatch.setenv(VARIABLE_ACTIVO, "1")
    monkeypatch.delenv(VARIABLE_TOKEN, raising=False)

    assert (
        cliente_desde_entorno(
            user_agent=UA, remitente=REMITENTE, ruta_config=tmp_path / "openclaw.toml"
        )
        is None
    )


def test_cliente_desde_entorno_sin_contacto(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sin ``site.contact`` no se puede enviar el header ``From``."""
    monkeypatch.setenv(VARIABLE_ACTIVO, "1")
    monkeypatch.setenv(VARIABLE_TOKEN, TOKEN)

    assert (
        cliente_desde_entorno(user_agent=UA, remitente="", ruta_config=tmp_path / "openclaw.toml")
        is None
    )


def test_cliente_desde_entorno_activo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Con interruptor, token y contacto, el cliente queda disponible."""
    monkeypatch.setenv(VARIABLE_ACTIVO, "1")
    monkeypatch.setenv(VARIABLE_TOKEN, TOKEN)

    cliente = cliente_desde_entorno(
        user_agent=UA, remitente=REMITENTE, ruta_config=tmp_path / "openclaw.toml"
    )

    assert cliente is not None
    assert cliente.disponible is True
    cliente.cerrar()
