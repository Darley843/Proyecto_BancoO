"""Capa Gold: Markdown enriquecido con metadatos, listo para el RAG."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

import yaml

from .config import Config
from .extract import load_silver
from .section import classify, extract_keywords
from .utils import (
    count_words,
    estimate_tokens,
    page_slug,
    read_jsonl,
    sha256_text,
    utc_now,
    write_jsonl,
)

log = logging.getLogger(__name__)


def build_frontmatter(row: dict, config: Config, *, text_hash: str, tokens: int) -> dict:
    """Metadatos del estandar del curso (mismo orden que los slides)."""
    from datetime import date

    raw_date = (row.get("fecha_captura") or row.get("fecha_proceso") or utc_now())[:10]
    try:
        capture_date: object = date.fromisoformat(raw_date)
    except ValueError:
        capture_date = raw_date

    return {
        "fuente": row["url"],
        "titulo": row.get("titulo") or "Sin titulo",
        "seccion": row.get("seccion") or classify(row["url"], row.get("titulo", "")),
        "empresa": config.site.name,
        "fecha_captura": capture_date,
        "idioma": row.get("idioma") or config.site.language,
        "tokens": tokens,
        "hash": text_hash[:8],
        "palabras": count_words(row.get("texto", "")),
        "metodo": row.get("metodo", "trafilatura"),
        "keywords": extract_keywords(row.get("texto", "")),
    }


def render_document(frontmatter: dict, body: str) -> str:
    """Une YAML frontmatter + cuerpo Markdown."""
    header = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=100,
    ).strip()
    return f"---\n{header}\n---\n\n{body.strip()}\n"


def build_gold(config: Config, *, force: bool = False) -> list[dict]:
    """Silver -> Gold: un .md por pagina + corpus.jsonl consolidado."""
    rows = load_silver(config)
    if not rows:
        log.warning("No hay silver. Ejecuta 'make extract' primero.")
        return []

    if force:
        for old in config.paths.gold_markdown.glob("*.md"):
            old.unlink()

    config.paths.gold_markdown.mkdir(parents=True, exist_ok=True)
    corpus: list[dict] = []
    seen_hashes: dict[str, str] = {}
    duplicates = 0

    for row in rows:
        text = (row.get("texto") or "").strip()
        if not text:
            continue

        text_hash = sha256_text(text)
        if text_hash in seen_hashes:
            duplicates += 1
            continue  # paginas clonadas: mismo cuerpo en otra URL
        seen_hashes[text_hash] = row["url"]

        tokens = estimate_tokens(text)
        frontmatter = build_frontmatter(row, config, text_hash=text_hash, tokens=tokens)
        slug = page_slug(row["url"], frontmatter["titulo"])
        path = config.paths.gold_markdown / f"{slug}.md"
        path.write_text(render_document(frontmatter, text), encoding="utf-8", newline="\n")

        corpus.append(
            {
                "id": slug,
                "fuente": frontmatter["fuente"],
                "titulo": frontmatter["titulo"],
                "seccion": frontmatter["seccion"],
                "empresa": frontmatter["empresa"],
                "fecha_captura": str(frontmatter["fecha_captura"]),
                "idioma": frontmatter["idioma"],
                "tokens": tokens,
                "palabras": frontmatter["palabras"],
                "hash": text_hash,
                "archivo": path.relative_to(config.paths.root).as_posix(),
            }
        )

    write_jsonl(config.paths.corpus_file, corpus)
    log.info(
        "Gold: %d documentos (%d duplicados descartados) -> %s",
        len(corpus),
        duplicates,
        config.paths.corpus_file,
    )
    return corpus


def load_corpus(config: Config) -> list[dict]:
    return list(read_jsonl(config.paths.corpus_file))


def corpus_stats(corpus: list[dict]) -> dict:
    """Resumen numerico del corpus, para el indice y para la sustentacion."""
    tokens = sum(int(row.get("tokens", 0)) for row in corpus)
    words = sum(int(row.get("palabras", 0)) for row in corpus)
    by_section = Counter(row.get("seccion", "otros") for row in corpus)
    return {
        "documentos": len(corpus),
        "tokens": tokens,
        "palabras": words,
        "promedio_tokens": round(tokens / len(corpus), 1) if corpus else 0,
        "secciones": dict(by_section.most_common()),
    }


def gold_files(config: Config) -> list[Path]:
    return sorted(config.paths.gold_markdown.glob("*.md"))
