"""Genera data/gold/_INDICE.md: el reporte que se muestra en la sustentacion."""

from __future__ import annotations

import logging

from .checklist import CHECKLIST, coverage, evaluate
from .config import Config
from .gold import corpus_stats, gold_files, load_corpus
from .section import section_label

log = logging.getLogger(__name__)


def _read_gold_texts(config: Config) -> dict[str, str]:
    """Texto de cada documento Gold, indexado por id, para evaluar el checklist."""
    texts: dict[str, str] = {}
    for row in load_corpus(config):
        path = config.paths.root / row.get("archivo", "")
        if path.exists():
            texts[row["id"]] = path.read_text(encoding="utf-8", errors="replace")
    return texts


def build_index(config: Config) -> str:
    corpus = load_corpus(config)
    stats = corpus_stats(corpus)
    texts = _read_gold_texts(config)
    items = evaluate(corpus, texts)
    found, total, percent = coverage(items)

    lines: list[str] = []
    lines.append("# Indice del corpus")
    lines.append("")
    lines.append(f"**Empresa:** {config.site.name}  ")
    lines.append(f"**Fuente:** {config.site.base_url}  ")
    lines.append(f"**Documentos Gold:** {stats['documentos']}  ")
    lines.append(
        f"**Tokens totales:** {stats['tokens']:,} (promedio {stats['promedio_tokens']:,})  "
    )
    lines.append(f"**Cobertura del checklist:** {found}/{total} ({percent:.0f}%) — heuristica")
    lines.append("")

    lines.append("## Documentos por seccion")
    lines.append("")
    lines.append("| Seccion | Documentos |")
    lines.append("|---|---:|")
    for section, count in stats["secciones"].items():
        lines.append(f"| {section_label(section)} (`{section}`) | {count} |")
    lines.append("")

    top = sorted(corpus, key=lambda row: int(row.get("tokens", 0)), reverse=True)[:10]
    if top:
        lines.append("## Documentos mas extensos")
        lines.append("")
        lines.append("| Titulo | Seccion | Tokens | Fuente |")
        lines.append("|---|---|---:|---|")
        for row in top:
            title = (row.get("titulo") or "Sin titulo").replace("|", "/")[:70]
            lines.append(
                f"| {title} | {row.get('seccion')} | {row.get('tokens'):,} | {row.get('fuente')} |"
            )
        lines.append("")

    lines.append("## Checklist del Taller 1")
    lines.append("")
    for categoria in CHECKLIST:
        category_items = [item for item in items if item.categoria == categoria]
        category_found = sum(1 for item in category_items if item.encontrado)
        lines.append(f"### {section_label(categoria)} — {category_found}/{len(category_items)}")
        lines.append("")
        for item in category_items:
            mark = "x" if item.encontrado else " "
            evidence = f" - _{item.evidencia[:180]}_" if item.evidencia else ""
            lines.append(f"- [{mark}] {item.item}{evidence}")
        lines.append("")

    lines.append("## Como se genero")
    lines.append("")
    lines.append("```")
    lines.append("make all      # discover -> fetch -> extract -> gold -> stats")
    lines.append("```")
    lines.append("")
    lines.append(
        "Capas: `data/raw/` (Bronze, crudo) -> `data/processed/` (Silver, limpio) -> "
        "`data/gold/` (Gold, con metadatos). Solo Gold alimenta al RAG."
    )
    lines.append("")

    content = "\n".join(lines)
    config.paths.index_file.parent.mkdir(parents=True, exist_ok=True)
    config.paths.index_file.write_text(content, encoding="utf-8", newline="\n")
    log.info("Indice escrito en %s", config.paths.index_file)
    return content


def print_summary(config: Config) -> str:
    """Version de consola, corta, del indice."""
    corpus = load_corpus(config)
    stats = corpus_stats(corpus)
    texts = _read_gold_texts(config)
    found, total, percent = coverage(evaluate(corpus, texts))
    files = gold_files(config)

    out = [
        f"Empresa          : {config.site.name}",
        f"Documentos Gold  : {stats['documentos']} ({len(files)} archivos .md)",
        f"Tokens totales   : {stats['tokens']:,}",
        f"Palabras totales : {stats['palabras']:,}",
        f"Checklist        : {found}/{total} ({percent:.0f}%)",
        "Secciones        : " + ", ".join(f"{k}={v}" for k, v in stats["secciones"].items()),
    ]
    return "\n".join(out)
