"""Pruebas de la captura en vivo en carpeta temporal (sin red).

El doble de ``HttpClient`` responde desde un diccionario y anota las peticiones,
igual que en ``test_fetch.py``. Ninguna prueba escribe en ``data/``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from banco_occidente_corpus.config import (
    Config,
    CrawlConfig,
    DiscoveryConfig,
    GoldConfig,
    Paths,
    SiteConfig,
    load_config,
)
from banco_occidente_corpus.live_capture import (
    BLOCKED_MESSAGE,
    TEMP_ENV,
    audit_discovery,
    check_queue_robots,
    new_workdir,
    run_capture,
    select_urls,
    temp_config,
)
from banco_occidente_corpus.net import BlockedError, Response

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://www.bancodeoccidente.com.co"
ROBOTS_ABIERTO = "User-agent: *\nAllow: /\n"
ROBOTS_CERRADO = "User-agent: *\nDisallow: /privado/\n"


# ------------------------------------------------------------------- dobles


def _ok(url: str, text: str = "", content_type: str = "text/html") -> Response:
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
    """Doble de ``HttpClient``: responde por URL y anota lo pedido."""

    def __init__(self, respuestas: dict[str, Response | Exception]) -> None:
        """Guarda las respuestas; lo que no este responde 404."""
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
        """Anota el cierre."""
        self.cerrado = True

    def __enter__(self) -> ClienteFalso:
        """Soporta ``with``."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Soporta ``with``."""


# ------------------------------------------------------------------ helpers


def _config(tmp_path: Path) -> Config:
    """Configuración aislada en ``tmp_path`` con las rutas del corpus dentro."""
    return Config(
        site=SiteConfig(
            base_url=BASE,
            allowed_hosts=["www.bancodeoccidente.com.co"],
            sitemap_url=f"{BASE}/sitemap.xml",
            user_agent="TAAML-bot/1.0",
            contact="grupo@uao.edu.co",
        ),
        crawl=CrawlConfig(delay_seconds=1.5),
        discovery=DiscoveryConfig(
            document_extensions=[".pdf"],
            exclude_patterns=["/portaltransaccional", "/login"],
        ),
        gold=GoldConfig(boilerplate_min_docs=5, boilerplate_ratio=0.35),
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
            knowledge=tmp_path / "data/knowledge",
        ),
    )


def _write_queue(config: Config, urls: list[str]) -> None:
    """Escribe la cola de URLs en ``urls.jsonl``."""
    config.paths.urls_file.parent.mkdir(parents=True, exist_ok=True)
    config.paths.urls_file.write_text(
        "\n".join(f'{{"url": "{url}"}}' for url in urls) + "\n", encoding="utf-8"
    )


def _write_capture(config: Config, urls: list[tuple[str, int]]) -> None:
    """Escribe registros de captura con su estado."""
    config.paths.capture_file.parent.mkdir(parents=True, exist_ok=True)
    config.paths.capture_file.write_text(
        "\n".join(f'{{"url": "{url}", "status": {status}}}' for url, status in urls) + "\n",
        encoding="utf-8",
    )


def _html(name: str) -> str:
    """HTML de ejemplo que vive dentro de ``test/``."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client(**urls: Response | Exception) -> ClienteFalso:
    """Cliente con robots.txt abierto mas las respuestas indicadas."""
    respuestas: dict[str, Response | Exception] = {f"{BASE}/robots.txt": _ok("", ROBOTS_ABIERTO)}
    respuestas.update(urls)
    return ClienteFalso(respuestas)


# --------------------------------------------------------------------- cola


def test_select_urls_salta_capturadas_y_fallidas(tmp_path: Path) -> None:
    """La cola propone las primeras URLs sin registro previo, hasta el tope."""
    # Arrange
    config = _config(tmp_path)
    _write_queue(config, [f"{BASE}/{name}" for name in ("a", "b", "c", "d", "e")])
    _write_capture(config, [(f"{BASE}/a", 200), (f"{BASE}/c", 404)])

    # Act
    seleccion = select_urls(config, limit=3)

    # Assert
    assert seleccion == [f"{BASE}/b", f"{BASE}/d", f"{BASE}/e"]


def test_select_urls_no_devuelve_nada_sin_cola(tmp_path: Path) -> None:
    """Sin ``urls.jsonl`` no hay nada que capturar (la app deshabilita el botón)."""
    # Arrange
    config = _config(tmp_path)

    # Act / Assert
    assert select_urls(config) == []


# ---------------------------------------------------------- entorno temporal


def test_temp_config_usa_las_variables_y_restaura_al_salir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Las capas apuntan al temporal por CORPUS_*_DIR y el entorno se restaura."""
    # Arrange
    for name in TEMP_ENV:
        monkeypatch.delenv(name, raising=False)
    config = _config(tmp_path)
    workdir = tmp_path / "vivo"

    # Act
    with temp_config(config, workdir) as temporal:
        raw, processed, gold = (
            Path(os.environ["CORPUS_RAW_DIR"]),
            Path(os.environ["CORPUS_PROCESSED_DIR"]),
            Path(os.environ["CORPUS_GOLD_DIR"]),
        )
        root = temporal.paths.root
        rutas = (temporal.paths.raw, temporal.paths.processed, temporal.paths.gold)

    # Assert
    assert root == workdir.resolve()
    assert (raw, processed, gold) == rutas
    assert all(workdir.resolve() in ruta.parents for ruta in rutas)
    assert all(name not in os.environ for name in TEMP_ENV)


def test_temp_config_restaura_el_entorno_si_falla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una excepción dentro del bloque no deja las variables apuntando al temporal."""
    # Arrange
    for name in TEMP_ENV:
        monkeypatch.delenv(name, raising=False)
    config = _config(tmp_path)

    # Act / Assert
    with pytest.raises(RuntimeError), temp_config(config, tmp_path / "vivo"):
        raise RuntimeError("fallo simulado")
    assert all(name not in os.environ for name in TEMP_ENV)


def test_new_workdir_es_unico_y_temporal() -> None:
    """Cada captura estrena carpeta, fuera del repositorio."""
    # Act
    primero = new_workdir()
    segundo = new_workdir()

    # Assert
    assert primero != segundo
    assert primero.is_dir() and segundo.is_dir()
    assert primero.name.startswith("corpus-live-")


# ------------------------------------------------------------------ robots


def test_check_queue_robots_usa_una_sola_peticion(tmp_path: Path) -> None:
    """robots.txt se descarga una vez y se evalua toda la cola en memoria."""
    # Arrange
    config = _config(tmp_path)
    _write_queue(
        config,
        [f"{BASE}/cuentas", f"{BASE}/privado/informe", f"{BASE}/tarjetas"],
    )
    cliente = ClienteFalso({f"{BASE}/robots.txt": _ok("", ROBOTS_CERRADO)})

    # Act
    check = check_queue_robots(config, cliente)  # type: ignore[arg-type]

    # Assert
    assert check.allowed == (f"{BASE}/cuentas", f"{BASE}/tarjetas")
    assert check.blocked == (f"{BASE}/privado/informe",)
    assert check.robots_found is True
    assert cliente.pedidas == [f"{BASE}/robots.txt"]


def test_audit_discovery_cuenta_descartes_por_motivo(tmp_path: Path) -> None:
    """La auditoria completa separa URLs, documentos y motivos de descarte."""
    # Arrange
    config = _config(tmp_path)
    sitemap = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{BASE}/personas</loc></url>"
        f"<url><loc>{BASE}/privado/x</loc></url>"
        f"<url><loc>{BASE}/portaltransaccional/login</loc></url>"
        f"<url><loc>{BASE}/documents/catalogo.pdf</loc></url>"
        "</urlset>"
    )
    cliente = ClienteFalso(
        {
            f"{BASE}/robots.txt": _ok("", ROBOTS_CERRADO),
            f"{BASE}/sitemap.xml": _ok("", sitemap, "application/xml"),
        }
    )

    # Act
    audit = audit_discovery(config, cliente)  # type: ignore[arg-type]

    # Assert
    assert audit.sitemaps_read == 1
    assert (audit.urls, audit.documents) == (1, 1)
    assert dict(audit.skipped) == {"disallow-robots": 1, "fuera-de-alcance": 1}
    assert audit.seconds >= 0


# ----------------------------------------------------------------- captura


def test_run_capture_escribe_solo_en_la_carpeta_temporal(tmp_path: Path) -> None:
    """Bronze, Silver y Gold se crean dentro del temporal; data/ no se toca."""
    # Arrange
    config = _config(tmp_path)
    urls = [f"{BASE}/quienes-somos", f"{BASE}/nuestro-banco"]
    cliente = _client(
        **{
            urls[0]: _ok(urls[0], _html("quienes_somos.html")),
            urls[1]: _ok(urls[1], _html("nuestro_banco.html")),
        }
    )
    workdir = tmp_path / "vivo"

    # Act
    resultado = run_capture(config, urls, workdir=workdir, client=cliente)  # type: ignore[arg-type]

    # Assert
    assert resultado.error == ""
    assert [stage.key for stage in resultado.stages] == [
        "robots",
        "capture",
        "clean",
        "dedupe",
        "gold",
    ]
    assert (workdir / "raw/capture.jsonl").exists()
    assert (workdir / "processed/silver.jsonl").exists()
    assert (workdir / "gold/corpus.jsonl").exists()
    assert len(resultado.corpus) == 2
    assert not (config.paths.root / "data/gold/corpus.jsonl").exists()
    assert cliente.cerrado is False


def test_run_capture_devuelve_el_frontmatter(tmp_path: Path) -> None:
    """La página Gold generada se devuelve con su frontmatter y su cuerpo."""
    # Arrange
    config = _config(tmp_path)
    url = f"{BASE}/quienes-somos"
    cliente = _client(**{url: _ok(url, _html("quienes_somos.html"))})

    # Act
    resultado = run_capture(
        config,
        [url],
        workdir=tmp_path / "vivo",
        client=cliente,  # type: ignore[arg-type]
    )

    # Assert
    assert resultado.page_path is not None
    assert resultado.page_path.exists()
    assert resultado.frontmatter["fuente"] == url
    assert resultado.frontmatter["empresa"] == "Banco de Occidente"
    assert resultado.frontmatter["seccion"] == "identidad"
    assert resultado.frontmatter["tokens"] > 0
    assert len(resultado.frontmatter["hash"]) == 8
    assert resultado.frontmatter_text.startswith("fuente:")
    assert "1965" in resultado.body_excerpt


def test_run_capture_reporta_un_404_sin_abortar(tmp_path: Path) -> None:
    """Un 404 se registra como fallo y la captura sigue con las demas URLs."""
    # Arrange
    config = _config(tmp_path)
    buenas = [f"{BASE}/quienes-somos", f"{BASE}/nuestro-banco"]
    cliente = _client(
        **{
            buenas[0]: _ok(buenas[0], _html("quienes_somos.html")),
            buenas[1]: _ok(buenas[1], _html("nuestro_banco.html")),
        }
    )

    # Act
    resultado = run_capture(
        config,
        [*buenas, f"{BASE}/no-existe"],
        workdir=tmp_path / "vivo",
        client=cliente,  # type: ignore[arg-type]
    )

    # Assert
    assert resultado.error == ""
    capture = next(stage for stage in resultado.stages if stage.key == "capture")
    assert "1 fallidas" in capture.detail
    assert len(resultado.corpus) == 2


def test_run_capture_se_detiene_si_robots_lo_prohibe(tmp_path: Path) -> None:
    """Si robots.txt prohibe la URL, no se descarga y la corrida se detiene."""
    # Arrange
    config = _config(tmp_path)
    url = f"{BASE}/privado/informe"
    cliente = ClienteFalso({f"{BASE}/robots.txt": _ok("", ROBOTS_CERRADO)})

    # Act
    resultado = run_capture(
        config,
        [url],
        workdir=tmp_path / "vivo",
        client=cliente,  # type: ignore[arg-type]
    )

    # Assert
    assert "robots.txt" in resultado.error
    assert resultado.blocked == (url,)
    assert cliente.pedidas == [f"{BASE}/robots.txt"]
    assert not (tmp_path / "vivo/raw/capture.jsonl").exists()


def test_run_capture_se_detiene_ante_un_403_sin_sugerir_otra_red(tmp_path: Path) -> None:
    """Un 403 detiene la captura con el mensaje documentado, no con el de net.py."""
    # Arrange
    config = _config(tmp_path)
    url = f"{BASE}/cuentas"
    cliente = _client(**{url: _error(url, 403)})

    # Act
    resultado = run_capture(
        config,
        [url],
        workdir=tmp_path / "vivo",
        client=cliente,  # type: ignore[arg-type]
    )

    # Assert
    assert resultado.error == BLOCKED_MESSAGE
    assert "limitación documentada" in resultado.error
    assert "residencial" not in resultado.error
    assert "VPN" not in resultado.error
    assert "desconecta" not in resultado.error
    assert resultado.stages[-1].state == "error"


def test_run_capture_no_copia_el_texto_de_blocked_error(tmp_path: Path) -> None:
    """El mensaje de net.py (sugiere otra red) no llega a la app."""
    # Arrange
    config = _config(tmp_path)
    url = f"{BASE}/cuentas"
    crudo = (
        f"{url} respondio HTTP 403 tras 3 intentos. Si es 403 persistente, el sitio "
        "esta bloqueando la red actual (VPN, datacenter o WAF de CloudFront): prueba "
        "desde una conexion residencial colombiana."
    )
    cliente = _client(**{url: BlockedError(crudo)})

    # Act
    resultado = run_capture(
        config,
        [url],
        workdir=tmp_path / "vivo",
        client=cliente,  # type: ignore[arg-type]
    )

    # Assert
    assert resultado.error == BLOCKED_MESSAGE
    assert "residencial" not in resultado.error
    assert "CloudFront" not in resultado.error


def test_run_capture_no_toca_el_corpus_real(tmp_path: Path) -> None:
    """Una corrida con la configuración real deja data/gold intacto."""
    # Arrange
    real = load_config()
    if not real.paths.corpus_file.exists():
        pytest.skip("el checkout no tiene corpus.jsonl")
    antes = real.paths.corpus_file.read_bytes()
    url = f"{BASE}/quienes-somos"
    cliente = _client(**{url: _ok(url, _html("quienes_somos.html"))})

    # Act
    run_capture(real, [url], workdir=tmp_path / "vivo", client=cliente)  # type: ignore[arg-type]

    # Assert
    assert real.paths.corpus_file.read_bytes() == antes
