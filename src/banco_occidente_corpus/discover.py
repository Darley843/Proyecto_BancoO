"""Descubrimiento de URLs: robots.txt + sitemap.xml (indice de indices)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from .config import Config
from .net import HttpClient
from .utils import is_excluded_url, utc_now, write_jsonl


@dataclass(slots=True)
class DiscoveryResult:
    urls: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    sitemaps_read: int = 0
    sitemaps_failed: int = 0
    robots_found: bool = False
    crawl_delay: float | None = None
    sitemap_from_robots: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.urls) + len(self.documents)


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(xml_text: str) -> tuple[str, list[str]]:
    """Devuelve (tipo, locs). tipo es 'sitemapindex', 'urlset' o '' si es invalido."""
    if not xml_text or not xml_text.strip():
        return "", []
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        return "", []
    kind = _localname(root.tag)
    if kind not in {"sitemapindex", "urlset", "url"}:
        return "", []
    locs = [
        element.text.strip()
        for element in root.iter()
        if _localname(element.tag) == "loc" and element.text and element.text.strip()
    ]
    return ("urlset" if kind == "url" else kind), locs


def parse_robots(text: str) -> tuple[RobotFileParser, float | None, list[str]]:
    """Parsea robots.txt y devuelve las reglas, el Crawl-delay y los Sitemap."""
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    crawl_delay: float | None = None
    sitemaps: list[str] = []
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key_lower = key.strip().lower()
        value = value.strip()
        if key_lower == "crawl-delay":
            try:
                crawl_delay = float(value)
            except ValueError:
                continue
        elif key_lower == "sitemap" and value:
            sitemaps.append(value)
    return parser, crawl_delay, sitemaps


def normalize_url(url: str) -> str:
    """Quita el fragmento y normaliza el esquema/host, conservando la query.

    Liferay publica el sitemap con el prefijo ``/w/`` (friendly URL) pero sirve
    el contenido sin el: ``/w/cuenta-de-ahorros`` responde 404 y
    ``/cuenta-de-ahorros`` responde 200. Se normaliza para no capturar 404 en
    masa.
    """
    parts = urlsplit(url.strip())
    if not parts.scheme:
        return url.strip()
    host = parts.netloc.lower()
    path = parts.path or "/"
    if path.startswith("/w/"):
        path = path[2:]
    return urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))


def _suffix(url: str) -> str:
    path = urlsplit(url).path.lower()
    dot = path.rfind(".")
    return path[dot:] if dot > path.rfind("/") else ""


def is_document(url: str, config: Config) -> bool:
    """True si la URL apunta a un documento descargable (PDF, Office, etc.)."""
    return _suffix(url) in {ext.lower() for ext in config.discovery.document_extensions}


def is_capture_target(url: str, config: Config) -> bool:
    """Filtra: mismo sitio, no excluido y con extension HTML."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        return False
    if parts.netloc.lower() not in {h.lower() for h in config.site.allowed_hosts}:
        return False
    if is_document(url, config):
        return False
    suffix = _suffix(url)
    if suffix and suffix not in {ext.lower() for ext in config.discovery.html_extensions}:
        return False
    return not is_excluded_url(url, config.discovery.exclude_patterns)


def discover(config: Config, client: HttpClient, *, save: bool = True) -> DiscoveryResult:
    """Lee robots.txt, expande el sitemap y devuelve las URLs capturables."""
    result = DiscoveryResult()
    base = config.site.base_url.rstrip("/")

    robots_url = urljoin(base + "/", "robots.txt")
    robots_response = client.get_optional(robots_url)
    robots_parser: RobotFileParser | None = None
    if robots_response and robots_response.ok:
        robots_parser, crawl_delay, sitemaps = parse_robots(robots_response.text)
        result.robots_found = True
        result.crawl_delay = crawl_delay
        result.sitemap_from_robots = sitemaps
        if crawl_delay and crawl_delay > client.delay:
            client.delay = crawl_delay

    seeds = [config.site.sitemap_url] if config.site.sitemap_url else []
    seeds.extend(result.sitemap_from_robots)

    queue: deque[tuple[str, int]] = deque((url, 0) for url in seeds if url)
    seen_sitemaps: set[str] = set()
    found: list[str] = []
    documents: list[str] = []

    while queue and result.sitemaps_read < config.crawl.max_sitemaps:
        sitemap_url, depth = queue.popleft()
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        response = client.get_optional(sitemap_url)
        result.sitemaps_read += 1
        if not response or not response.ok:
            result.sitemaps_failed += 1
            continue

        kind, locs = parse_sitemap(response.text)
        if kind == "sitemapindex" and depth < config.crawl.max_sitemap_depth:
            queue.extend((loc, depth + 1) for loc in locs)
            continue
        found.extend(locs)

    # Fallback: si no hay sitemap utilizable, se deduce navegando la home.
    if not found:
        home = client.get_optional(base + "/")
        if home and home.ok:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(home.text, "lxml")
            for anchor in soup.select("a[href]"):
                href = anchor.get("href")
                if isinstance(href, str) and href:
                    found.append(urljoin(base + "/", href))

    urls: list[str] = []
    seen: set[str] = set()
    for raw in found:
        url = normalize_url(urljoin(base + "/", raw))
        if url in seen:
            continue
        seen.add(url)

        if is_document(url, config):
            documents.append(url)
            continue
        if not is_capture_target(url, config):
            result.skipped.append({"url": url, "motivo": "fuera-de-alcance"})
            continue
        if (
            config.crawl.respect_robots
            and robots_parser
            and not robots_parser.can_fetch(config.site.user_agent, url)
        ):
            result.skipped.append({"url": url, "motivo": "disallow-robots"})
            continue
        urls.append(url)

    if len(urls) > config.crawl.max_urls:
        result.skipped.extend(
            {"url": url, "motivo": "tope-max-urls"} for url in urls[config.crawl.max_urls :]
        )
        urls = urls[: config.crawl.max_urls]

    result.urls = urls
    result.documents = sorted(set(documents))

    if save:
        now = utc_now()
        write_jsonl(
            config.paths.urls_file,
            ({"url": url, "fuente": "sitemap", "fecha": now} for url in urls),
        )
        if result.documents:
            write_jsonl(
                config.paths.pdfs_file,
                ({"url": url, "fuente": "sitemap", "fecha": now} for url in result.documents),
            )

    return result
