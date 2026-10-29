"""Pruebas de la capa Bronze (fetch.py), robots.txt y el cliente HTTP (sin red).

Issue #30: fetch.py no tenia pruebas propias y los documentos se aceptaban sin
consultar robots.txt. Todos los clientes aqui son dobles en memoria.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterable
from pathlib import Path

import httpx
import pytest

from banco_occidente_corpus import cli, documents, fetch
from banco_occidente_corpus.config import (
    Config,
    CrawlConfig,
    DiscoveryConfig,
    Paths,
    SiteConfig,
)
from banco_occidente_corpus.discover import discover, is_document_target
from banco_occidente_corpus.net import BlockedError, HttpClient, Response, RobotsGuard

BASE = "https://www.bancodeoccidente.com.co"
ROBOTS = "User-agent: *\nDisallow: /portaltransaccional/\nDisallow: /privado/\n"


def _config(tmp_path: Path) -> Config:
    """Configuracion aislada en ``tmp_path`` con contacto y exclusiones reales."""
    return Config(
        site=SiteConfig(
            base_url=BASE,
            allowed_hosts=["www.bancodeoccidente.com.co"],
            sitemap_url=f"{BASE}/sitemap.xml",
            user_agent="TAAML-bot/1.0",
            contact="grupo@uao.edu.co",
        ),
        crawl=CrawlConfig(),
        discovery=DiscoveryConfig(
            document_extensions=[".pdf"],
            exclude_patterns=["/login", "/documents/", "/formulario-autorizacion"],
        ),
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
        ),
    )


def _ok(url: str, text: str = "", content_type: str = "text/html; charset=utf-8") -> Response:
    """Respuesta 200 sin red."""
    return Response(
        url=url,
        status=200,
        text=text,
        content=text.encode(),
        content_type=content_type,
        elapsed=0.01,
    )


def _error(url: str, status: int) -> Response:
    """Respuesta de error HTTP sin red."""
    return Response(
        url=url,
        status=status,
        text="",
        content_type="text/html",
        elapsed=0.01,
        error=f"HTTP {status}",
    )


class ClienteFalso:
    """Doble de ``HttpClient``: responde desde un diccionario y anota las URLs pedidas."""

    def __init__(self, respuestas: dict[str, Response | Exception]) -> None:
        """Guarda las respuestas por URL; lo que no este responde 404."""
        self.respuestas = respuestas
        self.pedidas: list[str] = []
        self.cerrado = False
        self.delay = 1.5

    def get(self, url: str, *, accept: str | None = None) -> Response:
        """Devuelve la respuesta registrada o lanza la excepcion registrada."""
        self.pedidas.append(url)
        respuesta = self.respuestas.get(url, _error(url, 404))
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    def get_optional(self, url: str) -> Response | None:
        """Igual que ``get`` pero devuelve None ante ``BlockedError``."""
        try:
            return self.get(url)
        except BlockedError:
            return None

    def close(self) -> None:
        """Anota el cierre: las pruebas comprueban quien es el dueno del cliente."""
        self.cerrado = True

    def __enter__(self) -> ClienteFalso:
        """Soporta ``with``."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Soporta ``with``."""


def _usar_cliente(monkeypatch: pytest.MonkeyPatch, modulo: object, cliente: ClienteFalso) -> None:
    """Sustituye ``HttpClient`` en ``modulo`` por el doble."""
    monkeypatch.setattr(modulo, "HttpClient", lambda *args, **kwargs: cliente)


def _capturas(config: Config) -> list[dict]:
    """Lee ``capture.jsonl``."""
    texto = config.paths.capture_file.read_text(encoding="utf-8")
    return [json.loads(linea) for linea in texto.splitlines() if linea.strip()]


# ---------------------------------------------------------------- save_bronze


def test_save_bronze_guarda_html_y_registro(tmp_path: Path) -> None:
    """El HTML se guarda tal cual y el registro apunta al archivo."""
    config = _config(tmp_path)
    registro = fetch.save_bronze(
        config, f"{BASE}/cuentas", "<html>hola</html>", content_type="text/html; charset=utf-8"
    )
    archivo = config.paths.root / registro["archivo"]
    assert archivo.read_text(encoding="utf-8") == "<html>hola</html>"
    assert registro["status"] == 200
    assert registro["content_type"] == "text/html"
    assert registro["bytes"] == len(b"<html>hola</html>")


def test_save_bronze_rechaza_contenido_que_no_es_html(tmp_path: Path) -> None:
    """Bronze HTML no guarda PDF ni JSON."""
    with pytest.raises(ValueError, match="no es HTML"):
        fetch.save_bronze(
            _config(tmp_path), f"{BASE}/x.pdf", "%PDF", content_type="application/pdf"
        )


@pytest.mark.parametrize(
    ("content_type", "esperado"),
    [
        ("text/html", True),
        ("text/html; charset=utf-8", True),
        ("application/xhtml+xml", True),
        ("", True),
        ("application/pdf", False),
        ("application/json", False),
    ],
)
def test_is_html(content_type: str, esperado: bool) -> None:
    """Solo HTML (o sin Content-Type) entra a Bronze."""
    assert fetch.is_html(content_type) is esperado


# ---------------------------------------------------------------- fetch_all


def test_fetch_all_guarda_omite_y_registra_errores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una corrida con exito, 404 y contenido no HTML deja todo en capture.jsonl."""
    config = _config(tmp_path)
    cliente = ClienteFalso(
        {
            f"{BASE}/a": _ok(f"{BASE}/a", "<html>A</html>"),
            f"{BASE}/json": _ok(f"{BASE}/json", "{}", "application/json"),
        }
    )
    _usar_cliente(monkeypatch, fetch, cliente)

    stats = fetch.fetch_all(config, [f"{BASE}/a", f"{BASE}/no-existe", f"{BASE}/json"])

    assert (stats.ok, stats.failed, stats.cached) == (1, 2, 0)
    errores = {c["url"]: c["error"] for c in _capturas(config)}
    assert errores[f"{BASE}/a"] is None
    assert errores[f"{BASE}/no-existe"] == "HTTP 404"
    assert errores[f"{BASE}/json"].startswith("no es HTML")
    assert len(list(config.paths.raw_html.glob("*.html"))) == 1


def test_fetch_all_es_reanudable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Lo ya capturado no se vuelve a pedir."""
    config = _config(tmp_path)
    cliente = ClienteFalso({f"{BASE}/a": _ok(f"{BASE}/a", "<html>A</html>")})
    _usar_cliente(monkeypatch, fetch, cliente)

    fetch.fetch_all(config, [f"{BASE}/a"])
    stats = fetch.fetch_all(config, [f"{BASE}/a"])

    assert stats.cached == 1
    assert cliente.pedidas == [f"{BASE}/a"]
    assert fetch.pending_urls(config, [f"{BASE}/a", f"{BASE}/b"]) == [f"{BASE}/b"]


def test_fetch_all_se_detiene_ante_un_bloqueo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el sitio bloquea una URL, no se insiste con las demas."""
    config = _config(tmp_path)
    cliente = ClienteFalso({f"{BASE}/a": BlockedError("HTTP 403")})
    _usar_cliente(monkeypatch, fetch, cliente)

    stats = fetch.fetch_all(config, [f"{BASE}/a", f"{BASE}/b"])

    assert stats.failed == 1
    assert cliente.pedidas == [f"{BASE}/a"]


def test_fetch_all_no_cierra_un_cliente_inyectado(tmp_path: Path) -> None:
    """La app comparte un unico cliente con robots.txt: fetch_all no lo cierra."""
    # Arrange
    config = _config(tmp_path)
    cliente = ClienteFalso({f"{BASE}/a": _ok(f"{BASE}/a", "<html>A</html>")})

    # Act
    stats = fetch.fetch_all(config, [f"{BASE}/a"], client=cliente)  # type: ignore[arg-type]

    # Assert
    assert stats.ok == 1
    assert cliente.pedidas == [f"{BASE}/a"]
    assert cliente.cerrado is False


def test_fetch_all_cierra_el_cliente_que_crea(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El cliente propio (creado aqui) si se cierra al terminar la captura."""
    # Arrange
    config = _config(tmp_path)
    cliente = ClienteFalso({f"{BASE}/a": _ok(f"{BASE}/a", "<html>A</html>")})
    _usar_cliente(monkeypatch, fetch, cliente)

    # Act
    fetch.fetch_all(config, [f"{BASE}/a"])

    # Assert
    assert cliente.cerrado is True


def test_iter_bronze_devuelve_solo_capturas_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La lectura de Bronze trae el HTML de las capturas exitosas."""
    config = _config(tmp_path)
    _usar_cliente(monkeypatch, fetch, ClienteFalso({f"{BASE}/a": _ok(f"{BASE}/a", "<p>A</p>")}))
    fetch.fetch_all(config, [f"{BASE}/a", f"{BASE}/b"])

    filas = fetch.load_bronze(config)

    assert [f["url"] for f in filas] == [f"{BASE}/a"]
    assert filas[0]["html"] == "<p>A</p>"


# ---------------------------------------------------------------- robots.txt


def test_robots_guard_lee_cada_host_una_vez() -> None:
    """robots.txt se descarga una vez por host y se respeta su Disallow."""
    cliente = ClienteFalso({f"{BASE}/robots.txt": _ok(f"{BASE}/robots.txt", ROBOTS)})
    guard = RobotsGuard(cliente, "TAAML-bot/1.0")  # type: ignore[arg-type]

    assert guard.allowed(f"{BASE}/cuentas")
    assert not guard.allowed(f"{BASE}/privado/informe.pdf")
    assert cliente.pedidas.count(f"{BASE}/robots.txt") == 1


def test_robots_guard_sin_robots_permite() -> None:
    """Un robots.txt ausente (404) equivale a no tener restricciones."""
    guard = RobotsGuard(ClienteFalso({}), "TAAML-bot/1.0")  # type: ignore[arg-type]
    assert guard.allowed(f"{BASE}/lo-que-sea")


def test_is_document_target_aplica_exclusiones_salvo_solo_html(tmp_path: Path) -> None:
    """Los PDF bajo /documents/ siguen siendo validos; los de login o formulario no."""
    config = _config(tmp_path)
    assert is_document_target(f"{BASE}/documents/d/informe.pdf", config)
    assert not is_document_target(f"{BASE}/login/manual.pdf", config)
    assert not is_document_target(f"{BASE}/formulario-autorizacion/f.pdf", config)
    assert not is_document_target("https://otro.com/informe.pdf", config)


def test_discover_consulta_robots_tambien_para_documentos(tmp_path: Path) -> None:
    """Issue #30: un PDF en una ruta con Disallow no entra a la lista de documentos."""
    config = _config(tmp_path)
    sitemap = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{BASE}/cuentas</loc></url>"
        f"<url><loc>{BASE}/documents/d/informe.pdf</loc></url>"
        f"<url><loc>{BASE}/privado/secreto.pdf</loc></url>"
        f"<url><loc>{BASE}/login/manual.pdf</loc></url>"
        "</urlset>"
    )
    cliente = ClienteFalso(
        {
            f"{BASE}/robots.txt": _ok(f"{BASE}/robots.txt", ROBOTS),
            f"{BASE}/sitemap.xml": _ok(f"{BASE}/sitemap.xml", sitemap, "application/xml"),
        }
    )

    resultado = discover(config, cliente, save=False)  # type: ignore[arg-type]

    assert resultado.urls == [f"{BASE}/cuentas"]
    assert resultado.documents == [f"{BASE}/documents/d/informe.pdf"]
    motivos = {s["url"]: s["motivo"] for s in resultado.skipped}
    assert motivos[f"{BASE}/privado/secreto.pdf"] == "disallow-robots"
    assert motivos[f"{BASE}/login/manual.pdf"] == "fuera-de-alcance"


def test_fetch_documents_no_descarga_lo_que_robots_prohibe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #30: la descarga de PDF consulta robots.txt antes de cada peticion."""
    config = _config(tmp_path)
    permitido = f"{BASE}/documents/d/ok.pdf"
    prohibido = f"{BASE}/privado/no.pdf"
    filas: Iterable[dict] = [
        {"url": u, "url_key": u, "titulo": u, "tipo": "financiero", "anio": 2025, "prioridad": 1}
        for u in (permitido, prohibido)
    ]
    config.paths.raw.mkdir(parents=True)
    config.paths.documents_urls.write_text(
        "\n".join(json.dumps(f) for f in filas) + "\n", encoding="utf-8"
    )
    pdf = Response(
        url=permitido,
        status=200,
        text="",
        content=b"%PDF-1.7 contenido",
        content_type="application/pdf",
        elapsed=0.01,
    )
    cliente = ClienteFalso(
        {f"{BASE}/robots.txt": _ok(f"{BASE}/robots.txt", ROBOTS), permitido: pdf}
    )
    _usar_cliente(monkeypatch, documents, cliente)

    stats = documents.fetch_documents(config)

    assert stats["ok"] == 1
    assert stats["robots"] == 1
    assert prohibido not in cliente.pedidas


# ---------------------------------------------------------------- cliente HTTP


def test_wait_cuenta_un_error_de_red_como_peticion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tras un error de red la siguiente peticion tambien espera el minimo de cortesia."""
    config = _config(tmp_path)
    config.crawl.max_retries = 1

    def falla(*args: object, **kwargs: object) -> httpx.Response:
        """Doble de ``client.get`` que siempre falla como un corte de red."""
        raise httpx.ConnectError("sin red")

    with HttpClient(config) as cliente:
        monkeypatch.setattr(cliente.client, "get", falla)
        with pytest.raises(BlockedError):
            cliente.get(f"{BASE}/a")
        assert cliente._last_request > 0


# ---------------------------------------------------------------- cmd_all


def test_cmd_all_se_detiene_si_falla_un_paso(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #30: cmd_all ya no ignora el codigo de salida de extract y gold."""
    llamados: list[str] = []

    def paso(nombre: str, codigo: int) -> Callable[[Config, argparse.Namespace], int]:
        """Fabrica un doble de ``cmd_*`` que registra la llamada y devuelve el codigo."""

        def ejecutar(config: Config, args: argparse.Namespace) -> int:
            """Doble de un paso del pipeline: anota su nombre y su codigo de salida."""
            llamados.append(nombre)
            return codigo

        return ejecutar

    monkeypatch.setattr(cli, "cmd_discover", paso("discover", 0))
    monkeypatch.setattr(cli, "cmd_fetch", paso("fetch", 0))
    monkeypatch.setattr(cli, "cmd_extract", paso("extract", 1))
    monkeypatch.setattr(cli, "cmd_gold", paso("gold", 0))
    monkeypatch.setattr(cli, "cmd_stats", paso("stats", 0))

    codigo = cli.cmd_all(_config(tmp_path), argparse.Namespace())

    assert codigo == 1
    assert llamados == ["discover", "fetch", "extract"]
