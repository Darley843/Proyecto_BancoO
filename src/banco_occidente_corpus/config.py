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
    knowledge: Path = field(
        default_factory=lambda: _env_path("CORPUS_KNOWLEDGE_DIR", PROJECT_ROOT / "data/knowledge")
    )

    @property
    def raw_html(self) -> Path:
        """Ruta ``self.raw / "html"``."""
        return self.raw / "html"

    @property
    def raw_documents(self) -> Path:
        """Ruta ``self.raw / "documents"``."""
        return self.raw / "documents"

    @property
    def documents_urls(self) -> Path:
        """Ruta ``self.raw / "documents_urls.jsonl"``."""
        return self.raw / "documents_urls.jsonl"

    @property
    def documents_capture(self) -> Path:
        """Ruta ``self.raw / "documents_capture.jsonl"``."""
        return self.raw / "documents_capture.jsonl"

    @property
    def documents_gold(self) -> Path:
        """Ruta ``self.gold / "documents"``."""
        return self.gold / "documents"

    @property
    def documents_index(self) -> Path:
        """Ruta ``self.gold / "documents.jsonl"``."""
        return self.gold / "documents.jsonl"

    @property
    def videos_raw(self) -> Path:
        """Ruta ``self.raw / "videos"``."""
        return self.raw / "videos"

    @property
    def videos_urls(self) -> Path:
        """Ruta ``self.raw / "videos_urls.jsonl"``."""
        return self.raw / "videos_urls.jsonl"

    @property
    def videos_capture(self) -> Path:
        """Ruta ``self.raw / "videos_capture.jsonl"``."""
        return self.raw / "videos_capture.jsonl"

    @property
    def videos_gold(self) -> Path:
        """Ruta ``self.gold / "videos"``."""
        return self.gold / "videos"

    @property
    def videos_index(self) -> Path:
        """Ruta ``self.gold / "videos.jsonl"``."""
        return self.gold / "videos.jsonl"

    @property
    def urls_file(self) -> Path:
        """Ruta ``self.raw / "urls.jsonl"``."""
        return self.raw / "urls.jsonl"

    @property
    def capture_file(self) -> Path:
        """Ruta ``self.raw / "capture.jsonl"``."""
        return self.raw / "capture.jsonl"

    @property
    def pdfs_file(self) -> Path:
        """Ruta ``self.raw / "documents.jsonl"``."""
        return self.raw / "documents.jsonl"

    @property
    def silver_markdown(self) -> Path:
        """Ruta ``self.processed / "markdown"``."""
        return self.processed / "markdown"

    @property
    def silver_file(self) -> Path:
        """Ruta ``self.processed / "silver.jsonl"``."""
        return self.processed / "silver.jsonl"

    @property
    def gold_markdown(self) -> Path:
        """Ruta ``self.gold / "pages"``."""
        return self.gold / "pages"

    @property
    def knowledge_chunks(self) -> Path:
        """Ruta ``self.knowledge / "chunks.jsonl"``."""
        return self.knowledge / "chunks.jsonl"

    @property
    def knowledge_chunks_web(self) -> Path:
        """Chunks de las paginas web (versionados): la base del web scraping."""
        return self.knowledge / "chunks_web.jsonl"

    @property
    def knowledge_entities(self) -> Path:
        """Ruta ``self.knowledge / "entities.jsonl"``."""
        return self.knowledge / "entities.jsonl"

    @property
    def knowledge_facts(self) -> Path:
        """Ruta ``self.knowledge / "facts.jsonl"``."""
        return self.knowledge / "facts.jsonl"

    @property
    def knowledge_relations(self) -> Path:
        """Ruta ``self.knowledge / "relations.jsonl"``."""
        return self.knowledge / "relations.jsonl"

    @property
    def knowledge_index(self) -> Path:
        """Ruta ``self.knowledge / "_INDICE.md"``."""
        return self.knowledge / "_INDICE.md"

    @property
    def corpus_file(self) -> Path:
        """Ruta ``self.gold / "corpus.jsonl"``."""
        return self.gold / "corpus.jsonl"

    @property
    def index_file(self) -> Path:
        """Ruta ``self.gold / "_INDICE.md"``."""
        return self.gold / "_INDICE.md"

    @property
    def repetitions_file(self) -> Path:
        """Ruta del reporte de repeticiones dentro de Gold."""
        return self.gold / "_REPETIDOS.md"

    @property
    def news_source(self) -> Path:
        """Directorio versionado con la curaduria de noticias."""
        return _env_path("CORPUS_NEWS_DIR", self.root / "data/noticias")

    @property
    def news_prensa(self) -> Path:
        """Archivo YAML con las fichas de prensa externa."""
        return self.news_source / "prensa.yaml"

    @property
    def news_index(self) -> Path:
        """Indice Markdown de noticias dentro de Gold."""
        return self.gold / "_NOTICIAS.md"

    def ensure(self) -> None:
        """Crea los directorios de trabajo de las capas si no existen."""
        for path in (
            self.raw_html,
            self.raw_documents,
            self.silver_markdown,
            self.gold_markdown,
            self.knowledge,
            self.documents_gold,
            self.videos_raw,
            self.videos_gold,
            self.news_source,
        ):
            path.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class SiteConfig:
    """Identidad del sitio y contacto academico para el header `From`."""

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
    """Ritmo, timeouts y topes de la captura."""

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
    """Extensiones aceptadas y patrones de exclusion del descubrimiento."""

    html_extensions: list[str] = field(default_factory=lambda: ["", ".html"])
    document_extensions: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GoldConfig:
    """Secciones del checklist y umbrales para detectar boilerplate."""

    sections: list[str] = field(default_factory=list)
    boilerplate_min_docs: int = 5
    boilerplate_ratio: float = 0.35


@dataclass(slots=True)
class NewsConfig:
    """Parametros de la ingesta de noticias y prensa externa."""

    desde: str = "2025-01-01"
    hasta: str = ""
    prensa: str = "data/noticias/prensa.yaml"
    max_por_evento: int = 2
    max_oficiales: int = 40
    relevancia_minima: str = "media"
    incluir_dividendos: bool = False


@dataclass(slots=True)
class Config:
    """Configuracion completa del pipeline (sitio, crawl, Gold y rutas)."""

    site: SiteConfig = field(default_factory=SiteConfig)
    crawl: CrawlConfig = field(default_factory=CrawlConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    gold: GoldConfig = field(default_factory=GoldConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
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
        news=_build(NewsConfig, data.get("noticias", {})),
        paths=Paths(),
    )
