"""Capa Silver: del HTML crudo al texto util, en Markdown."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .config import Config
from .dedupe import find_boilerplate, strip_boilerplate
from .fetch import load_bronze
from .section import classify
from .utils import page_slug, read_jsonl, utc_now, write_jsonl

log = logging.getLogger(__name__)

_NOISE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "iframe",
    "svg",
    ".cookie",
    "#cookie",
    "[class*=cookie]",
    "[class*=Cookie]",
    "[class*=breadcrumb]",
    "[class*=menu]",
    "[class*=Menu]",
    "[class*=navbar]",
    "[class*=social]",
    "[class*=share]",
    "[role=navigation]",
    "[role=banner]",
    "[aria-hidden=true]",
)


@dataclass(slots=True)
class ExtractedPage:
    url: str
    title: str
    markdown: str
    language: str
    method: str
    section: str
    date: str | None = None


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for selector in _NOISE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()
    return str(soup)


def _title_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    if soup.h1 and soup.h1.get_text(strip=True):
        return soup.h1.get_text(" ", strip=True)
    if soup.title and soup.title.string:
        return soup.title.string.split("|")[0].strip()
    return ""


def _trafilatura(html: str, url: str) -> tuple[str, str, str | None]:
    """Extraccion semantica: solo el cuerpo del articulo, en Markdown."""
    try:
        from trafilatura import extract, extract_metadata
    except ImportError:  # pragma: no cover - dependencia declarada
        return "", "", None

    cleaned = _clean_html(html)
    body = (
        extract(
            cleaned,
            url=url,
            output_format="markdown",
            include_tables=True,
            include_links=False,
            include_comments=False,
            favor_recall=True,
            deduplicate=True,
        )
        or ""
    )
    meta = extract_metadata(cleaned, extensive=True)
    title = (getattr(meta, "title", None) or "").strip() if meta else ""
    date = (getattr(meta, "date", None) or None) if meta else None
    return body, title, date


def _fallback(html: str) -> str:
    """Si trafilatura no encuentra cuerpo, se usa main/article y luego body."""
    soup = BeautifulSoup(html, "lxml")
    for selector in _NOISE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()
    container = soup.select_one("main") or soup.select_one("article") or soup.body
    if not container:
        return ""
    blocks: list[str] = []
    for node in container.select("h1, h2, h3, h4, p, li, td, th, blockquote"):
        text = node.get_text(" ", strip=True)
        if not text:
            continue
        if node.name == "h1":
            blocks.append(f"# {text}")
        elif node.name == "h2":
            blocks.append(f"## {text}")
        elif node.name == "h3":
            blocks.append(f"### {text}")
        elif node.name == "h4":
            blocks.append(f"#### {text}")
        elif node.name == "li":
            blocks.append(f"- {text}")
        else:
            blocks.append(text)
    return "\n\n".join(blocks)


def extract_page(html: str, url: str, *, language: str = "es") -> ExtractedPage:
    """Extrae una pagina; nunca lanza por contenido pobre."""
    body, meta_title, date = _trafilatura(html, url)
    method = "trafilatura"
    if len(body.strip()) < 200:
        fallback = _fallback(html)
        if len(fallback.strip()) > len(body.strip()):
            body, method = fallback, "fallback"
    title = meta_title or _title_from_html(html)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return ExtractedPage(
        url=url,
        title=title,
        markdown=body,
        language=language,
        method=method,
        section=classify(url, title),
        date=date,
    )


def extract_all(config: Config, *, min_chars: int = 120) -> list[dict]:
    """Bronze -> Silver: extrae, deduplica boilerplate y escribe JSONL + .md."""
    rows = load_bronze(config)
    if not rows:
        log.warning("No hay capturas en %s. Ejecuta 'make fetch' primero.", config.paths.raw_html)
        return []

    pages: list[ExtractedPage] = []
    for row in rows:
        page = extract_page(row["html"], row["url"], language=config.site.language)
        if len(page.markdown) < min_chars:
            continue
        pages.append(page)

    boilerplate = find_boilerplate(
        (page.markdown.splitlines() for page in pages),
        min_docs=config.gold.boilerplate_min_docs,
        ratio=config.gold.boilerplate_ratio,
    )
    if boilerplate:
        log.info("Boilerplate detectado: %d lineas repetidas", len(boilerplate))

    silver_rows: list[dict] = []
    config.paths.silver_markdown.mkdir(parents=True, exist_ok=True)
    for page in pages:
        clean = strip_boilerplate(page.markdown, boilerplate)
        if len(clean) < min_chars:
            continue
        slug = page_slug(page.url, page.title)
        path = config.paths.silver_markdown / f"{slug}.md"
        path.write_text(clean + "\n", encoding="utf-8", newline="\n")
        silver_rows.append(
            {
                "url": page.url,
                "titulo": page.title,
                "seccion": page.section,
                "idioma": page.language,
                "fecha_documento": page.date,
                "metodo": page.method,
                "chars": len(clean),
                "archivo": path.relative_to(config.paths.root).as_posix(),
                "texto": clean,
                "fecha_proceso": utc_now(),
            }
        )

    write_jsonl(config.paths.silver_file, silver_rows)
    log.info("Silver: %d paginas utiles de %d capturadas", len(silver_rows), len(rows))
    return silver_rows


def load_silver(config: Config) -> list[dict]:
    return list(read_jsonl(config.paths.silver_file))
