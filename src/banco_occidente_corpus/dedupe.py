"""Deduplicación del boilerplate de Silver y medición de repeticiones en Gold.

El análisis de Gold es de solo lectura: detecta líneas y bloques consecutivos
que se repiten entre páginas y calcula porcentajes por umbral. Nunca modifica
las páginas ni los índices del corpus.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config

_WS = re.compile(r"\s+")
_MD_NOISE = re.compile(r"^[\s|>*#\-_=~`]{3,}$")
_LINK_ONLY = re.compile(r"^\[[^\]]*\]\([^)]*\)$")

#: Umbrales absolutos, en número de páginas, que reporta el análisis de Gold.
DEFAULT_THRESHOLDS: tuple[int, ...] = (5, 10, 20)
#: Máximo de bloques repetidos que se conservan para el reporte.
DEFAULT_TOP: int = 20
#: Tamaño máximo de un bloque consecutivo, en líneas de contenido.
DEFAULT_MAX_BLOCK_LINES: int = 3
#: Máximo de páginas de ejemplo por bloque.
DEFAULT_MAX_EXAMPLES: int = 3
#: Máximo de páginas con menor contenido único que se destacan.
DEFAULT_LOWEST_UNIQUE: int = 10
#: Prefijos de archivo que no son páginas web del sitio.
EXCLUDED_PAGE_PREFIXES: tuple[str, ...] = ("hecho-", "noticia-", "_")


def normalize_line(line: str) -> str:
    """Normaliza para comparar: sin markdown, sin numeros de linea, sin espacios extra."""
    text = line.strip()
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = re.sub(r"^[>\-\*\+]\s+", "", text)
    text = _WS.sub(" ", text)
    return text.casefold()


def is_noise(line: str) -> bool:
    """Lineas que nunca aportan: separadores, solo enlaces, migas de pan."""
    stripped = line.strip()
    if not stripped:
        return True
    if _MD_NOISE.match(stripped):
        return True
    if _LINK_ONLY.match(stripped):
        return True
    return len(normalize_line(stripped)) < 3


def find_boilerplate(
    documents: Iterable[Iterable[str]],
    *,
    min_docs: int = 5,
    ratio: float = 0.35,
) -> set[str]:
    """Lineas normalizadas que aparecen en demasiados documentos.

    Una linea de footer (NIT, direccion, redes) se repite en las ~800 URLs del
    sitio; si se deja, el buscador vectorial la devuelve en cada consulta.
    """
    docs = [list(doc) for doc in documents]
    if len(docs) < min_docs:
        return set()

    counts: Counter[str] = Counter()
    for doc in docs:
        seen_in_doc = {normalize_line(line) for line in doc}
        seen_in_doc.discard("")
        counts.update(seen_in_doc)

    threshold = max(min_docs, int(len(docs) * ratio))
    return {line for line, count in counts.items() if count >= threshold}


def strip_boilerplate(text: str, boilerplate: set[str]) -> str:
    """Quita las lineas marcadas como boilerplate conservando la estructura."""
    if not boilerplate:
        return text
    kept: list[str] = []
    for line in text.splitlines():
        if normalize_line(line) in boilerplate:
            continue
        if is_noise(line):
            continue
        kept.append(line.rstrip())
    # Colapsa 3+ lineas en blanco.
    result = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def unique_ratio(lines: list[str]) -> float:
    """Proporcion de contenido unico: diagnostico rapido de una pagina."""
    if not lines:
        return 0.0
    normalized = [normalize_line(line) for line in lines if not is_noise(line)]
    if not normalized:
        return 0.0
    return len(set(normalized)) / len(normalized)


@dataclass(frozen=True, slots=True)
class GoldPage:
    """Página Gold ya separada de su frontmatter."""

    page_id: str
    path: Path
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RepeatedBlock:
    """Bloque consecutivo que aparece en dos o más páginas del sitio."""

    key: tuple[str, ...]
    text: tuple[str, ...]
    size: int
    pages: int
    examples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ThresholdCoverage:
    """Cobertura de líneas de contenido para un umbral de páginas."""

    threshold: int
    covered_lines: int
    total_lines: int
    percentage: float


@dataclass(frozen=True, slots=True)
class PageUniqueRatio:
    """Proporción de contenido único de una página concreta."""

    page_id: str
    ratio: float


@dataclass(frozen=True, slots=True)
class UniqueRatioMetrics:
    """Resumen de la métrica existente ``unique_ratio`` sobre el corpus."""

    global_ratio: float
    average: float
    lowest: tuple[PageUniqueRatio, ...]


@dataclass(frozen=True, slots=True)
class RepetitionReport:
    """Resultado completo del análisis de repeticiones sobre Gold."""

    pages_analyzed: int
    content_lines: int
    thresholds: tuple[ThresholdCoverage, ...]
    top_blocks: tuple[RepeatedBlock, ...]
    unique_ratio: UniqueRatioMetrics


@dataclass(slots=True)
class _BlockStats:
    """Conteo interno de un bloque y sus posiciones por página."""

    key: tuple[str, ...]
    text: tuple[str, ...]
    size: int
    starts: dict[str, set[int]] = field(default_factory=dict)


def normalize_for_comparison(line: str) -> str:
    """Normaliza para comparar sin mayúsculas ni tildes, conservando el texto original aparte."""
    text = normalize_line(line)
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def split_frontmatter(text: str) -> tuple[str, str]:
    """Separa el bloque YAML inicial del cuerpo Markdown de una página Gold."""
    cleaned = text.lstrip("\ufeff")
    lines = cleaned.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", cleaned
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :])
    return "", cleaned


def is_site_page(stem: str) -> bool:
    """Indica si el nombre de archivo corresponde a una página web del sitio."""
    return not stem.startswith(EXCLUDED_PAGE_PREFIXES)


def load_gold_pages(pages_dir: Path) -> list[GoldPage]:
    """Carga las páginas web de Gold, ordenadas por nombre y sin fichas ni índices."""
    if not pages_dir.is_dir():
        return []
    pages: list[GoldPage] = []
    for path in sorted(pages_dir.glob("*.md"), key=lambda item: item.name):
        if not is_site_page(path.stem):
            continue
        _, body = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        pages.append(GoldPage(page_id=path.stem, path=path, lines=tuple(body.splitlines())))
    return pages


def build_content_lines(lines: Iterable[str]) -> tuple[str, ...]:
    """Devuelve las líneas con contenido real en el orden en que aparecen."""
    return tuple(line.strip() for line in lines if not is_noise(line))


def _detect_blocks(
    pages: Sequence[GoldPage],
    *,
    max_block_lines: int = DEFAULT_MAX_BLOCK_LINES,
) -> dict[tuple[str, ...], _BlockStats]:
    """Detecta bloques consecutivos y registra sus posiciones sin duplicar páginas."""
    stats: dict[tuple[str, ...], _BlockStats] = {}
    for page in pages:
        content = build_content_lines(page.lines)
        normalized = [normalize_for_comparison(line) for line in content]
        for size in range(1, max_block_lines + 1):
            if size > len(content):
                break
            for start in range(len(content) - size + 1):
                key = tuple(normalized[start : start + size])
                if any(not part for part in key):
                    continue
                block = stats.get(key)
                if block is None:
                    block = _BlockStats(
                        key=key,
                        text=tuple(content[start : start + size]),
                        size=size,
                    )
                    stats[key] = block
                block.starts.setdefault(page.page_id, set()).add(start)
    return stats


def _blocks_from_stats(
    stats: dict[tuple[str, ...], _BlockStats],
    *,
    max_examples: int = DEFAULT_MAX_EXAMPLES,
) -> list[RepeatedBlock]:
    """Convierte los conteos internos en bloques repetidos ordenados de forma estable."""
    blocks = [
        RepeatedBlock(
            key=block.key,
            text=block.text,
            size=block.size,
            pages=len(block.starts),
            examples=tuple(sorted(block.starts)[:max_examples]),
        )
        for block in stats.values()
        if len(block.starts) >= 2
    ]
    return sorted(blocks, key=lambda item: (-item.pages, -item.size, item.key))


def find_repeated_blocks(
    pages: Sequence[GoldPage],
    *,
    max_block_lines: int = DEFAULT_MAX_BLOCK_LINES,
    max_examples: int = DEFAULT_MAX_EXAMPLES,
) -> list[RepeatedBlock]:
    """Lista los bloques de 1 a ``max_block_lines`` líneas que se repiten entre páginas."""
    stats = _detect_blocks(pages, max_block_lines=max_block_lines)
    return _blocks_from_stats(stats, max_examples=max_examples)


def _threshold_coverage(
    pages: Sequence[GoldPage],
    stats: dict[tuple[str, ...], _BlockStats],
    threshold: int,
) -> ThresholdCoverage:
    """Calcula la cobertura única de líneas para un umbral absoluto de páginas."""
    covered: dict[str, set[int]] = {}
    for block in stats.values():
        if len(block.starts) < threshold:
            continue
        for page_id, starts in block.starts.items():
            positions = covered.setdefault(page_id, set())
            for start in starts:
                positions.update(range(start, start + block.size))
    total_lines = sum(len(build_content_lines(page.lines)) for page in pages)
    covered_lines = sum(len(positions) for positions in covered.values())
    percentage = round(covered_lines / total_lines * 100, 1) if total_lines else 0.0
    return ThresholdCoverage(
        threshold=threshold,
        covered_lines=covered_lines,
        total_lines=total_lines,
        percentage=percentage,
    )


def compute_unique_ratio_metrics(
    pages: Sequence[GoldPage],
    *,
    max_lowest: int = DEFAULT_LOWEST_UNIQUE,
) -> UniqueRatioMetrics:
    """Resume ``unique_ratio`` global, promedio por página y páginas con menor proporción."""
    per_page = [
        PageUniqueRatio(page_id=page.page_id, ratio=unique_ratio(list(page.lines)))
        for page in pages
    ]
    all_lines = [line for page in pages for line in page.lines]
    average = sum(item.ratio for item in per_page) / len(per_page) if per_page else 0.0
    lowest = tuple(sorted(per_page, key=lambda item: (item.ratio, item.page_id))[:max_lowest])
    return UniqueRatioMetrics(
        global_ratio=unique_ratio(all_lines),
        average=average,
        lowest=lowest,
    )


def analyze_gold_repetitions(
    pages_dir: Path,
    *,
    thresholds: tuple[int, ...] = DEFAULT_THRESHOLDS,
    top: int = DEFAULT_TOP,
    max_block_lines: int = DEFAULT_MAX_BLOCK_LINES,
) -> RepetitionReport:
    """Analiza las páginas web de Gold sin modificar ningún artefacto del corpus."""
    pages = load_gold_pages(pages_dir)
    stats = _detect_blocks(pages, max_block_lines=max_block_lines)
    blocks = _blocks_from_stats(stats)
    return RepetitionReport(
        pages_analyzed=len(pages),
        content_lines=sum(len(build_content_lines(page.lines)) for page in pages),
        thresholds=tuple(_threshold_coverage(pages, stats, value) for value in thresholds),
        top_blocks=tuple(blocks[:top]),
        unique_ratio=compute_unique_ratio_metrics(pages),
    )


def _escape_cell(text: str, *, limit: int = 160) -> str:
    """Escapa barras verticales y recorta el texto para que quepa en una celda Markdown."""
    collapsed = " ".join(text.split())
    escaped = collapsed.replace("|", "\\|")
    if len(escaped) <= limit:
        return escaped
    return escaped[: limit - 3].rstrip() + "..."


def _format_block(block: RepeatedBlock) -> str:
    """Une las líneas de un bloque en una sola celda legible."""
    return _escape_cell(" / ".join(block.text))


def render_repetitions_report(report: RepetitionReport) -> str:
    """Renderiza el reporte Markdown de repeticiones de forma determinista y sin fecha."""
    lines: list[str] = [
        "# Repeticiones en Gold",
        "",
        "Diagnóstico de solo lectura sobre las páginas web de Gold. No modifica "
        "páginas, índices ni `corpus.jsonl`.",
        "",
        f"**Páginas analizadas:** {report.pages_analyzed}  ",
        f"**Líneas de contenido:** {report.content_lines}  ",
        "",
        "## Cobertura por umbral",
        "",
        "Porcentaje de líneas de contenido que pertenecen a algún bloque presente "
        "en al menos el umbral de páginas indicado.",
        "",
        "| Umbral (páginas) | Líneas cubiertas | Total | Porcentaje |",
        "|---:|---:|---:|---:|",
    ]
    for row in report.thresholds:
        lines.append(
            f"| {row.threshold} | {row.covered_lines} | {row.total_lines} "
            f"| {row.percentage:.1f} % |"
        )
    lines.extend(
        [
            "",
            "## Top 20 de bloques",
            "",
            "Bloques de 1 a 3 líneas consecutivas ordenados por páginas, tamaño y "
            "texto. Cada página cuenta una sola vez por bloque.",
            "",
            "| # | Tamaño | Páginas | Bloque | Ejemplos |",
            "|---:|---:|---:|---|---|",
        ]
    )
    if report.top_blocks:
        for index, block in enumerate(report.top_blocks, start=1):
            examples = _escape_cell(", ".join(block.examples))
            lines.append(
                f"| {index} | {block.size} | {block.pages} | {_format_block(block)} "
                f"| {examples} |"
            )
    else:
        lines.append("| - | - | 0 | Sin bloques repetidos | - |")

    unique = report.unique_ratio
    lines.extend(
        [
            "",
            "## Contenido único (`unique_ratio`)",
            "",
            "Métrica existente que compara líneas normalizadas por página; es sensible "
            "a mayúsculas y tildes y no equivale al porcentaje de texto repetido.",
            "",
            f"- **Global:** {unique.global_ratio * 100:.1f} %",
            f"- **Promedio por página:** {unique.average * 100:.1f} %",
            "",
            "### Páginas con menor proporción de contenido único",
            "",
            "| Página | Contenido único |",
            "|---|---:|",
        ]
    )
    if unique.lowest:
        for item in unique.lowest:
            lines.append(f"| {_escape_cell(item.page_id)} | {item.ratio * 100:.1f} % |")
    else:
        lines.append("| - | - |")
    lines.append("")
    return "\n".join(lines)


def write_repetitions_report(config: Config) -> Path:
    """Analiza Gold y escribe solo ``data/gold/_REPETIDOS.md`` en UTF-8 con saltos ``\\n``."""
    report = analyze_gold_repetitions(config.paths.gold_markdown)
    target = config.paths.repetitions_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_repetitions_report(report), encoding="utf-8", newline="\n")
    return target
