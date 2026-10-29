"""Lecturas de solo lectura para la pestaña «Scraping» de la app.

Agrupa los artefactos que ya existen en disco (cola de URLs, capturas Bronze,
Silver, Gold, manifest del contexto y reportes) en tarjetas de etapa y en un
resumen del corpus listo para pintar. No hace peticiones de red ni escribe
nada: la app solo muestra lo que el pipeline dejó.

El análisis de repeticiones y el titular del índice se leen de sus reportes
(``_REPETIDOS.md`` y ``_INDICE.md``) en lugar de recalcularse: la pestaña es de
consulta y debe abrirse en segundos, no en minutos.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .contexto import RutasContexto
from .dedupe import is_site_page
from .gold import corpus_stats
from .section import section_label
from .utils import human_size, read_jsonl

#: Orden fijo de las etapas del pipeline en la pestaña.
STAGE_KEYS: tuple[str, ...] = ("discover", "fetch", "extract", "dedupe", "gold")

#: Nota de versionado de Bronze (siempre visible junto a la etapa).
BRONZE_NOTE = (
    "Bronze no se versiona: son las capturas del equipo que ejecutó el pipeline. "
    "En un clon solo existe lo que quedó en data/raw/."
)

#: Nota de versionado de Silver (siempre visible junto a la etapa).
SILVER_NOTE = (
    "Silver tampoco se versiona: se reconstruye desde Bronze con make extract, sin volver a la web."
)

#: Explicación del salto entre las capas cuando Gold viene completo.
GOLD_NOTE = (
    "Gold sí está versionado y proviene de la captura completa: {docs} documentos "
    "({web} páginas web + {fichas} fichas de hechos y noticias). Por eso ver "
    "{bronze} capturas en Bronze junto a {docs} documentos en Gold no es un error: "
    "son capas con distinta cobertura histórica."
)

#: Aviso cuando Gold está vacío o no hay cola de captura.
_GOLD_MISSING = "No hay documentos Gold: ejecuta make gold."
_DISCOVER_MISSING = "No hay cola de URLs en data/raw/urls.jsonl: ejecuta make discover."

_INT = re.compile(r"\d[\d,]*")
_RATIO = re.compile(r"(\d+)\s*/\s*(\d+)")
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_PIPE = re.compile(r"(?<!\\)\|")
_SEPARATOR = re.compile(r"^:?-{2,}:?$")
_HEADLINE = re.compile(r"^\*\*(?P<label>[^*]+):\*\*\s*(?P<rest>.+?)\s*$", re.MULTILINE)
_TOKENS = re.compile(r"\(([\d,]+)\s*tokens\)")


@dataclass(frozen=True, slots=True)
class Metric:
    """Etiqueta y valor ya formateado para una tarjeta de la app."""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class Stage:
    """Una etapa del pipeline con su conteo, su explicación y sus avisos."""

    key: str
    title: str
    hint: str
    metrics: tuple[Metric, ...] = ()
    note: str = ""
    warning: str = ""


@dataclass(frozen=True, slots=True)
class ThresholdRow:
    """Cobertura de líneas repetidas para un umbral de páginas."""

    threshold: int
    covered: int
    total: int
    percentage: float


@dataclass(frozen=True, slots=True)
class BlockRow:
    """Bloque repetido tal como lo publica ``_REPETIDOS.md``."""

    size: int
    pages: int
    text: str
    examples: str


@dataclass(frozen=True, slots=True)
class Repetitions:
    """Lectura estructurada del reporte de repeticiones de Gold."""

    pages: int
    content_lines: int
    thresholds: tuple[ThresholdRow, ...] = ()
    blocks: tuple[BlockRow, ...] = ()
    unique_global: float = 0.0
    unique_average: float = 0.0
    lowest: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class PipelineSummary:
    """Las cinco etapas del pipeline y el detalle de deduplicación."""

    stages: tuple[Stage, ...]
    sources: tuple[str, ...]
    repetitions: Repetitions | None = None


@dataclass(frozen=True, slots=True)
class Drop:
    """Documentos que una capa descartó, agrupados por motivo."""

    reason: str
    count: int


@dataclass(frozen=True, slots=True)
class IndexSummary:
    """Titular de ``_INDICE.md`` (solo lo que no vive en ``corpus.jsonl``)."""

    gold_pages: int | None = None
    gold_tokens: int | None = None
    total_tokens: int | None = None
    pdf: int | None = None
    pdf_tokens: int | None = None
    videos: int | None = None
    videos_tokens: int | None = None
    checklist: tuple[int, int, float] | None = None


@dataclass(frozen=True, slots=True)
class CorpusMetrics:
    """Cifras del corpus y de su contexto, listas para la pestaña."""

    site_url: str
    gold_pages: int
    gold_tokens: int
    gold_words: int
    total_tokens: int
    sections: tuple[Metric, ...] = ()
    drops: tuple[Drop, ...] = ()
    pdf: int = 0
    pdf_tokens: int = 0
    videos: int = 0
    videos_tokens: int = 0
    checklist: tuple[int, int, float] | None = None
    context_pages: int = 0
    context_tokens: int = 0
    chunks_web: int = 0
    sources: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


# ------------------------------------------------------------------- helpers


def _fold(text: str) -> str:
    """Minúsculas sin tildes: permite leer reportes con o sin acentos."""
    lowered = text.casefold()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _to_int(text: str) -> int | None:
    """Primer entero del texto, ignorando los separadores de miles."""
    match = _INT.search(text)
    return int(match.group(0).replace(",", "")) if match else None


def _to_percent(text: str) -> float:
    """Primer porcentaje del texto (acepta coma o punto decimal)."""
    match = _PERCENT.search(text)
    return float(match.group(1).replace(",", ".")) if match else 0.0


def _labelled_int(text: str, label: str) -> int | None:
    """Valor numérico de una línea ``**Etiqueta:** valor``."""
    match = re.search(rf"\*\*{re.escape(_fold(label))}:\*\*\s*([\d.,]+)", _fold(text))
    return _to_int(match.group(1)) if match else None


def _labelled_percent(text: str, label: str) -> float:
    """Porcentaje de una línea ``- **Etiqueta:** 22.3 %``."""
    match = re.search(rf"\*\*{re.escape(_fold(label))}:\*\*\s*([\d.,]+)\s*%", _fold(text))
    return float(match.group(1).replace(",", ".")) if match else 0.0


def _cells(line: str) -> list[str]:
    """Celdas de una fila Markdown, respetando los pipes escapados (``\\|``)."""
    parts = _PIPE.split(line.strip())
    return [part.strip().replace("\\|", "|") for part in parts[1:-1]]


def _table(markdown: str, heading: str) -> list[list[str]]:
    """Filas de la primera tabla Markdown que sigue al encabezado indicado."""
    lines = markdown.splitlines()
    target = _fold(heading)
    for index, line in enumerate(lines):
        if not _fold(line.strip()).startswith(target):
            continue
        rows: list[list[str]] = []
        started = False
        for row in lines[index + 1 :]:
            stripped = row.strip()
            if stripped.startswith("|"):
                started = True
                cells = _cells(stripped)
                if cells and all(_SEPARATOR.match(cell) for cell in cells if cell):
                    continue
                rows.append(cells)
            elif started:
                break
        return rows
    return []


def _count_lines(path: Path) -> int:
    """Cuenta líneas de un JSONL sin cargarlo completo en memoria."""
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for line in handle if line.strip())


def _read_json(path: Path) -> dict[str, Any] | None:
    """Lee un JSON y devuelve ``None`` si falta o no es un objeto."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------ reportes


def read_index(path: Path) -> IndexSummary | None:
    """Lee el titular de ``_INDICE.md`` (PDF, videos, checklist y tokens)."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    labels = {
        match.group("label").strip(): match.group("rest") for match in _HEADLINE.finditer(text)
    }
    if not labels:
        return None

    pdf = labels.get("Documentos PDF", "")
    videos = labels.get("Videos transcritos", "")
    checklist_text = labels.get("Cobertura del checklist", "")
    ratio = _RATIO.search(checklist_text)
    pdf_tokens = _TOKENS.search(pdf)
    video_tokens = _TOKENS.search(videos)

    return IndexSummary(
        gold_pages=_to_int(labels.get("Documentos Gold", "")),
        gold_tokens=_to_int(labels.get("Tokens totales", "")),
        total_tokens=_to_int(labels.get("Tokens del corpus completo", "")),
        pdf=_to_int(pdf),
        pdf_tokens=_to_int(pdf_tokens.group(1)) if pdf_tokens else None,
        videos=_to_int(videos),
        videos_tokens=_to_int(video_tokens.group(1)) if video_tokens else None,
        checklist=(int(ratio.group(1)), int(ratio.group(2)), _to_percent(checklist_text))
        if ratio
        else None,
    )


def read_repetitions(path: Path) -> Repetitions | None:
    """Lee ``_REPETIDOS.md`` y devuelve sus tablas; ``None`` si no es el reporte."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    pages = _labelled_int(text, "Páginas analizadas")
    lines = _labelled_int(text, "Líneas de contenido")
    if pages is None or lines is None:
        return None

    thresholds = tuple(
        ThresholdRow(
            threshold=int(row[0]),
            covered=int(row[1]),
            total=int(row[2]),
            percentage=_to_percent(row[3]),
        )
        for row in _table(text, "## Cobertura por umbral")
        if len(row) >= 4 and row[0].isdigit()
    )
    blocks = tuple(
        BlockRow(size=int(row[1]), pages=int(row[2]), text=row[3], examples=row[4])
        for row in _table(text, "## Top 20 de bloques")
        if len(row) >= 5 and row[0].isdigit()
    )
    lowest = tuple(
        (row[0], _to_percent(row[1]))
        for row in _table(text, "### Páginas con menor")
        if len(row) >= 2 and _PERCENT.search(row[1])
    )

    return Repetitions(
        pages=pages,
        content_lines=lines,
        thresholds=thresholds,
        blocks=blocks,
        unique_global=_labelled_percent(text, "Global"),
        unique_average=_labelled_percent(text, "Promedio por página"),
        lowest=lowest,
    )


# -------------------------------------------------------------------- etapas


def _bronze_stats(config: Config) -> tuple[int, int, int, int]:
    """(ok, fallidas, bytes, archivos html) de la capa Bronze."""
    rows = list(read_jsonl(config.paths.capture_file))
    ok = sum(1 for row in rows if row.get("status") == 200)
    failed = sum(1 for row in rows if row.get("status") != 200)
    total_bytes = sum(int(row.get("bytes") or 0) for row in rows if row.get("status") == 200)
    files = len(list(config.paths.raw_html.glob("*.html")))
    return ok, failed, total_bytes, files


def _silver_stats(config: Config) -> tuple[int, int]:
    """(documentos, caracteres) de la capa Silver."""
    rows = list(read_jsonl(config.paths.silver_file))
    return len(rows), sum(int(row.get("chars") or 0) for row in rows)


def _discover_stage(config: Config, queue: int, documents: int) -> Stage:
    """Tarjeta de descubrimiento con lo que sí queda en disco."""
    return Stage(
        key="discover",
        title="Descubrir",
        hint=(
            "Lee robots.txt y el índice de sitemaps, normaliza las URLs /w/ y "
            "descarta rutas fuera de alcance."
        ),
        metrics=(
            Metric("URLs en cola", f"{queue:,}"),
            Metric("Documentos en cola", f"{documents:,}"),
            Metric("Patrones de exclusión", str(len(config.discovery.exclude_patterns))),
            Metric("Pausa de cortesía", f"{config.crawl.delay_seconds:.1f} s"),
        ),
        note=(
            "Los descartes por robots.txt o por patrones no se persisten en disco: "
            "se obtienen con el chequeo de robots de la cola y, completo, con la "
            "auditoría opcional."
        ),
        warning="" if queue else _DISCOVER_MISSING,
    )


def _fetch_stage(ok: int, failed: int, total_bytes: int, files: int) -> Stage:
    """Tarjeta de captura Bronze."""
    return Stage(
        key="fetch",
        title="Extraer (Bronze)",
        hint=(
            "Descarga el HTML crudo una sola vez y lo guarda con su hash; la "
            "captura es reanudable (no repite lo ya bajado)."
        ),
        metrics=(
            Metric("Capturas OK", f"{ok:,}"),
            Metric("Fallidas", f"{failed:,}"),
            Metric("Tamaño Bronze", human_size(total_bytes)),
            Metric("HTML en disco", f"{files:,}"),
        ),
        note=BRONZE_NOTE,
        warning="" if ok else "Sin capturas en disco: ejecuta make fetch.",
    )


def _extract_stage(pages: int, chars: int) -> Stage:
    """Tarjeta de limpieza Silver."""
    return Stage(
        key="extract",
        title="Limpiar (Silver)",
        hint=(
            "trafilatura con respaldo BeautifulSoup: quita menús, cookies y "
            "formularios, y aplica el boilerplate repetido antes de escribir."
        ),
        metrics=(
            Metric("Páginas Silver", f"{pages:,}"),
            Metric("Caracteres útiles", f"{chars:,}"),
        ),
        note=SILVER_NOTE,
        warning="Silver no está en este clon: make extract lo reconstruye." if not pages else "",
    )


def _dedupe_stage(report: Repetitions | None) -> Stage:
    """Tarjeta de deduplicación (solo medición sobre Gold)."""
    if report is None:
        return Stage(
            key="dedupe",
            title="Deduplicar",
            hint=(
                "Cuenta líneas de menú/pie y bloques de 1 a 3 líneas repetidos "
                "entre páginas; es solo medición."
            ),
            note="La deduplicación de Gold no borra contenido.",
            warning="Falta data/gold/_REPETIDOS.md: ejecuta make repetidos.",
        )

    coverage = " / ".join(f"{row.percentage:.1f} %" for row in report.thresholds)
    return Stage(
        key="dedupe",
        title="Deduplicar",
        hint=(
            "Cuenta líneas de menú/pie y bloques de 1 a 3 líneas repetidos entre "
            "páginas. La deduplicación de Gold es solo de medición: no borra "
            "líneas del corpus (CONSTITUTION §7.6)."
        ),
        metrics=(
            Metric("Páginas analizadas", f"{report.pages:,}"),
            Metric("Líneas de contenido", f"{report.content_lines:,}"),
            Metric("Repetido >= 5 / 10 / 20", coverage or "n/d"),
            Metric("Bloques en el top", f"{len(report.blocks):,}"),
        ),
    )


def _gold_stage(config: Config, corpus: list[dict], bronze_pages: int, chunks_web: int) -> Stage:
    """Tarjeta de enriquecimiento Gold."""
    stats = corpus_stats(corpus)
    web = sum(1 for row in corpus if is_site_page(str(row.get("id", ""))))
    fichas = len(corpus) - web
    return Stage(
        key="gold",
        title="Enriquecer (Gold)",
        hint=(
            "Añade frontmatter (fuente, sección, tokens, hash, keywords), escribe "
            "corpus.jsonl y segmenta el cuerpo por ## en chunks."
        ),
        metrics=(
            Metric("Documentos Gold", f"{stats['documentos']:,}"),
            Metric("Tokens", f"{stats['tokens']:,}"),
            Metric("Secciones", f"{len(stats['secciones']):,}"),
            Metric("Chunks web", f"{chunks_web:,}"),
        ),
        note=GOLD_NOTE.format(
            docs=stats["documentos"], web=web, fichas=fichas, bronze=bronze_pages
        ),
        warning="" if corpus else _GOLD_MISSING,
    )


def queue_urls_file(config: Config) -> list[str]:
    """URLs de la cola de captura (``data/raw/urls.jsonl``)."""
    return [row["url"] for row in read_jsonl(config.paths.urls_file) if row.get("url")]


def pipeline_summary(config: Config) -> PipelineSummary:
    """Resume las cinco etapas del pipeline leyendo solo lo que hay en disco."""
    queue = len(queue_urls_file(config))
    ok, failed, total_bytes, files = _bronze_stats(config)
    pages, chars = _silver_stats(config)
    report = read_repetitions(config.paths.repetitions_file)
    corpus = list(read_jsonl(config.paths.corpus_file))
    documents = len(list(read_jsonl(config.paths.pdfs_file)))
    chunks_web = _count_lines(config.paths.knowledge_chunks_web)

    return PipelineSummary(
        stages=(
            _discover_stage(config, queue, documents),
            _fetch_stage(ok, failed, total_bytes, files),
            _extract_stage(pages, chars),
            _dedupe_stage(report),
            _gold_stage(config, corpus, ok, chunks_web),
        ),
        sources=(
            config.paths.urls_file.as_posix(),
            config.paths.capture_file.as_posix(),
            config.paths.silver_file.as_posix(),
            config.paths.repetitions_file.as_posix(),
            config.paths.corpus_file.as_posix(),
            config.paths.knowledge_chunks_web.as_posix(),
        ),
        repetitions=report,
    )


# ------------------------------------------------------------------- métricas


def _contexto_manifest(config: Config) -> Path:
    """Ruta del manifest del contexto segun la configuración de la capa Contexto."""
    return RutasContexto.desde(config).manifest


def corpus_metrics(config: Config) -> CorpusMetrics:
    """Cifras del corpus, su contexto y sus descartes con su motivo."""
    warnings: list[str] = []
    sources: list[str] = [config.paths.corpus_file.as_posix()]

    corpus = list(read_jsonl(config.paths.corpus_file))
    stats = corpus_stats(corpus)
    index = read_index(config.paths.index_file)

    documents = list(read_jsonl(config.paths.documents_index))
    videos = list(read_jsonl(config.paths.videos_index))
    pdf, pdf_tokens = len(documents), sum(int(row.get("tokens") or 0) for row in documents)
    video_count = len(videos)
    video_tokens = sum(int(row.get("tokens") or 0) for row in videos)

    if index is not None:
        sources.append(config.paths.index_file.as_posix())
        if index.pdf is not None and index.pdf != pdf:
            warnings.append("El índice y documents.jsonl no coinciden: ejecuta make stats.")
        if index.videos is not None and index.videos != video_count:
            warnings.append("El índice y videos.jsonl no coinciden: ejecuta make stats.")
        pdf = index.pdf if index.pdf is not None else pdf
        pdf_tokens = index.pdf_tokens if index.pdf_tokens is not None else pdf_tokens
        video_count = index.videos if index.videos is not None else video_count
        video_tokens = index.videos_tokens if index.videos_tokens is not None else video_tokens
    else:
        warnings.append("Sin data/gold/_INDICE.md: PDF y videos se cuentan en los JSONL.")

    total = stats["tokens"] + pdf_tokens + video_tokens
    if index is not None and index.total_tokens is not None:
        total = index.total_tokens

    manifest_path = _contexto_manifest(config)
    manifest = _read_json(manifest_path)
    drops: tuple[Drop, ...] = ()
    context_pages = 0
    context_tokens = 0
    if manifest is None:
        warnings.append(f"Sin {manifest_path.as_posix()}: no hay descartes ni tokens del contexto.")
    else:
        sources.append(manifest_path.as_posix())
        paginas = manifest.get("paginas") or {}
        context_pages = int(paginas.get("incluidas") or 0)
        context_tokens = int(manifest.get("tokens") or 0)
        counts = Counter(
            str(item.get("motivo") or "sin motivo")
            for item in manifest.get("excluidas") or []
            if isinstance(item, dict)
        )
        drops = tuple(
            Drop(reason=reason, count=count)
            for reason, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
        )

    sections = tuple(
        Metric(label=section_label(section), value=f"{count:,}")
        for section, count in stats["secciones"].items()
    )

    return CorpusMetrics(
        site_url=config.site.base_url,
        gold_pages=stats["documentos"],
        gold_tokens=stats["tokens"],
        gold_words=stats["palabras"],
        total_tokens=total,
        sections=sections,
        drops=drops,
        pdf=pdf,
        pdf_tokens=pdf_tokens,
        videos=video_count,
        videos_tokens=video_tokens,
        checklist=index.checklist if index is not None else None,
        context_pages=context_pages,
        context_tokens=context_tokens,
        chunks_web=_count_lines(config.paths.knowledge_chunks_web),
        sources=tuple(sources),
        warnings=tuple(warnings),
    )
