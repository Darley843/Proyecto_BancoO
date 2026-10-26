"""Pruebas del CLI: ritmo minimo, diagnostico y ausencia del fallback con navegador."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from banco_occidente_corpus import cli
from banco_occidente_corpus.config import Config, GoldConfig, Paths, SiteConfig
from banco_occidente_corpus.net import MIN_DELAY_SECONDS, HttpClient, Response


def make_config(tmp_path: Path) -> Config:
    """Configuracion aislada en tmp_path, sin tocar los datos del repositorio."""
    return Config(
        site=SiteConfig(
            allowed_hosts=["www.bancodeoccidente.com.co"],
            sitemap_url="",
            user_agent="TAAML-bot/1.0",
        ),
        gold=GoldConfig(boilerplate_min_docs=5, boilerplate_ratio=0.35),
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
        ),
    )


class _ClienteBloqueado:
    """Doble de HttpClient que responde 403 sin salir a la red."""

    def __init__(self, config: Config, *, delay: float | None = None) -> None:
        self.config = config
        self.delay = MIN_DELAY_SECONDS

    def __enter__(self) -> _ClienteBloqueado:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str) -> Response:
        return Response(
            url=url,
            status=403,
            text="",
            content_type="text/html",
            elapsed=0.0,
            error="HTTP 403",
        )


def test_cli_rechaza_delay_menor_al_minimo() -> None:
    """--delay por debajo de 1,5 s es un error de uso, no una opcion valida."""
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["fetch", "--delay", "1"])

    args = parser.parse_args(["fetch", "--delay", "2.5"])
    assert args.delay == pytest.approx(2.5)


def test_cli_no_ofrece_fallback_con_navegador() -> None:
    """--browser ya no existe: un navegador headless eludiria el WAF."""
    parser = cli.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["fetch", "--browser"])


def test_httpclient_impone_el_minimo_de_cortesia() -> None:
    """Ni el CLI ni una config relajada pueden bajar el ritmo de 1,5 s."""
    config = Config()
    config.crawl.delay_seconds = 0.0

    with HttpClient(config, delay=0.1) as client:
        assert client.delay == pytest.approx(MIN_DELAY_SECONDS)

    with HttpClient(config) as client:
        assert client.delay == pytest.approx(MIN_DELAY_SECONDS)


def test_doctor_devuelve_error_cuando_el_sitio_bloquea(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Un diagnostico bloqueado debe fallar para que scripts y CI lo noten."""
    config = make_config(tmp_path)
    monkeypatch.setattr(cli, "HttpClient", _ClienteBloqueado)

    codigo = cli.cmd_doctor(config, argparse.Namespace())

    assert codigo == 2
    assert "BLOQUEADO" in capsys.readouterr().out


def test_ningun_automatismo_borra_bronze() -> None:
    """clean --hard queda para uso manual: ningun workflow ni script lo invoca."""
    root = Path(__file__).resolve().parents[1]
    automatismos = [*sorted((root / ".github/workflows").glob("*.yml")), root / "scripts/tasks.py"]

    for archivo in automatismos:
        assert "--hard" not in archivo.read_text(encoding="utf-8"), archivo

    makefile = (root / "makefile").read_text(encoding="utf-8")
    assert makefile.count("--hard") == 1
