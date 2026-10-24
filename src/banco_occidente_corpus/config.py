"""Configuracion del proyecto y rutas de las capas Medallion."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

#: Raiz del proyecto (dos niveles arriba de este archivo: src/<paquete>/).
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    """Permite sobreescribir una ruta por variable de entorno."""
    raw = os.getenv(name)
    return Path(raw).expanduser().resolve() if raw else default


@dataclass(slots=True)
class Paths:
    """Ubicacion de cada capa del corpus."""

    root: Path = field(default_factory=lambda: PROJECT_ROOT)
    raw: Path = field(
        default_factory=lambda: _env_path("CORPUS_RAW_DIR", PROJECT_ROOT / "data/raw")
    )
    processed: Path = field(
        default_factory=lambda: _env_path("CORPUS_PROCESSED_DIR", PROJECT_ROOT / "data/processed")
    )
    gold: Path = field(
        default_factory=lambda: _env_path("CORPUS_GOLD_DIR", PROJECT_ROOT / "data/gold")
    )

    @property
    def raw_html(self) -> Path:
        return self.raw / "html"

    @property
    def raw_documents(self) -> Path:
        return self.raw / "documents"

    @property
    def urls_file(self) -> Path:
        return self.raw / "urls.jsonl"

    @property
    def capture_file(self) -> Path:
        return self.raw / "capture.jsonl"

    @property
    def pdfs_file(self) -> Path:
        return self.raw / "documents.jsonl"

    @property
    def silver_markdown(self) -> Path:
        return self.processed / "markdown"

    @property
    def silver_file(self) -> Path:
        return self.processed / "silver.jsonl"

    @property
    def gold_markdown(self) -> Path:
        return self.gold / "pages"

    @property
    def corpus_file(self) -> Path:
        return self.gold / "corpus.jsonl"

    @property
    def index_file(self) -> Path:
        return self.gold / "_INDICE.md"

    def ensure(self) -> None:
        for path in (
            self.raw_html,
            self.raw_documents,
            self.silver_markdown,
            self.gold_markdown,
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class SiteConfig:
    name: str = "Banco de Occidente"
    slug: str = "banco-occidente"
    base_url: str = "https://www.bancodeoccidente.com.co"
    sitemap_url: str = ""
    allowed_hosts: list[str] = field(default_factory=list)
    language: str = "es"
    user_agent: str = "TAAML-bot/1.0 (uso academico)"
    #: Contacto academico; se envia en el header `From` de cada peticion.
    contact: str = ""


@dataclass(slots=True)
class CrawlConfig:
    delay_seconds: float = 1.5
    timeout_seconds: float = 30.0
    max_retries: int = 3
    max_urls: int = 1500
    max_sitemap_depth: int = 2
    max_sitemaps: int = 250
    respect_robots: bool = True
    pause_every: int = 50
    pause_seconds: float = 10.0


@dataclass(slots=True)
class DiscoveryConfig:
    html_extensions: list[str] = field(default_factory=lambda: ["", ".html"])
    document_extensions: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GoldConfig:
    sections: list[str] = field(default_factory=list)
    boilerplate_min_docs: int = 5
    boilerplate_ratio: float = 0.35


@dataclass(slots=True)
class Config:
    site: SiteConfig = field(default_factory=SiteConfig)
    crawl: CrawlConfig = field(default_factory=CrawlConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    gold: GoldConfig = field(default_factory=GoldConfig)
    paths: Paths = field(default_factory=Paths)


def _build(cls: Any, data: dict[str, Any]) -> Any:
    """Construye un dataclass ignorando claves desconocidas."""
    known = {field.name for field in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


def load_config(path: str | Path | None = None) -> Config:
    """Carga config/site.toml y devuelve la configuracion tipada."""
    config_path = Path(path) if path else PROJECT_ROOT / "config" / "site.toml"
    if not config_path.exists():
        return Config()

    with config_path.open("rb") as fh:
        data = tomllib.load(fh)

    crawl_raw = dict(data.get("crawl", {}))
    politeness = crawl_raw.pop("politeness", {})
    crawl_raw.update(
        {
            "pause_every": politeness.get("pause_every", 50),
            "pause_seconds": politeness.get("pause_seconds", 10.0),
        }
    )

    return Config(
        site=_build(SiteConfig, data.get("site", {})),
        crawl=_build(CrawlConfig, crawl_raw),
        discovery=_build(DiscoveryConfig, data.get("discovery", {})),
        gold=_build(GoldConfig, data.get("gold", {})),
        paths=Paths(),
    )
