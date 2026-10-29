"""Pruebas del panel de solo lectura de la pestaña «Scraping» (sin red).

Todo se escribe en ``tmp_path``: no se tocan los datos del repositorio.
"""

from __future__ import annotations

import json
from pathlib import Path

from banco_occidente_corpus.config import (
    Config,
    CrawlConfig,
    DiscoveryConfig,
    GoldConfig,
    Paths,
    SiteConfig,
)
from banco_occidente_corpus.panel import (
    STAGE_KEYS,
    corpus_metrics,
    pipeline_summary,
    read_index,
    read_repetitions,
)

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://www.bancodeoccidente.com.co"


# ------------------------------------------------------------------- helpers


def _config(tmp_path: Path) -> Config:
    """Configuración aislada en ``tmp_path`` con las cuatro rutas dentro."""
    return Config(
        site=SiteConfig(
            base_url=BASE,
            allowed_hosts=["www.bancodeoccidente.com.co"],
            user_agent="TAAML-bot/1.0",
            contact="grupo@uao.edu.co",
        ),
        crawl=CrawlConfig(delay_seconds=1.5),
        discovery=DiscoveryConfig(
            document_extensions=[".pdf"],
            exclude_patterns=["/login", "/portaltransaccional"],
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


def _write(path: Path, lines: list[dict]) -> None:
    """Escribe un JSONL con las filas indicadas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in lines) + "\n",
        encoding="utf-8",
    )


def _metric(stage_metrics: tuple, label: str) -> str:
    """Valor de una métrica concreta de una tarjeta."""
    return next(item.value for item in stage_metrics if item.label == label)


def _corpus_rows() -> list[dict]:
    """Dos documentos Gold: una página web y una ficha de hechos."""
    return [
        {
            "id": "cuenta-de-ahorros-524d0d",
            "fuente": f"{BASE}/cuenta-de-ahorros",
            "titulo": "Cuenta de Ahorros",
            "seccion": "oferta",
            "tokens": 120,
            "palabras": 60,
            "archivo": "data/gold/pages/cuenta-de-ahorros-524d0d.md",
        },
        {
            "id": "hecho-2026-10-19-emision-9099ec",
            "fuente": f"{BASE}/inversionistas",
            "titulo": "Emisión de valores",
            "seccion": "presencia",
            "tokens": 30,
            "palabras": 10,
            "archivo": "data/gold/pages/hecho-2026-10-19-emision-9099ec.md",
        },
    ]


# -------------------------------------------------------------- pipeline


def test_pipeline_summary_cuenta_las_cinco_etapas(tmp_path: Path) -> None:
    """Las etapas salen en orden fijo con los conteos de cada capa."""
    # Arrange
    config = _config(tmp_path)
    _write(config.paths.urls_file, [{"url": f"{BASE}/{n}"} for n in range(3)])
    _write(
        config.paths.capture_file,
        [
            {"url": f"{BASE}/a", "status": 200, "bytes": 1000},
            {"url": f"{BASE}/b", "status": 404, "bytes": 0},
        ],
    )
    config.paths.raw_html.mkdir(parents=True, exist_ok=True)
    (config.paths.raw_html / "abc.html").write_text("<html></html>", encoding="utf-8")
    _write(config.paths.corpus_file, _corpus_rows())

    # Act
    summary = pipeline_summary(config)

    # Assert
    assert tuple(stage.key for stage in summary.stages) == STAGE_KEYS
    discover, fetch, extract, dedupe, gold = summary.stages
    assert _metric(discover.metrics, "URLs en cola") == "3"
    assert _metric(fetch.metrics, "Capturas OK") == "1"
    assert _metric(fetch.metrics, "Fallidas") == "1"
    assert _metric(fetch.metrics, "HTML en disco") == "1"
    assert _metric(extract.metrics, "Páginas Silver") == "0"
    assert _metric(gold.metrics, "Documentos Gold") == "2"
    assert _metric(gold.metrics, "Tokens") == "150"
    assert "make repetidos" in dedupe.warning


def test_pipeline_summary_explica_el_versionado(tmp_path: Path) -> None:
    """Bronze y Silver dicen que no se versionan; Gold explica el salto."""
    # Arrange
    config = _config(tmp_path)
    _write(config.paths.urls_file, [{"url": f"{BASE}/a"}])
    _write(config.paths.capture_file, [{"url": f"{BASE}/a", "status": 200, "bytes": 10}])
    _write(config.paths.corpus_file, _corpus_rows())

    # Act
    summary = pipeline_summary(config)
    notas = {stage.key: stage.note for stage in summary.stages}

    # Assert
    assert "Bronze no se versiona" in notas["fetch"]
    assert "tampoco se versiona" in notas["extract"]
    assert "versionado" in notas["gold"]
    assert "no es un error" in notas["gold"]
    assert "1 páginas web + 1 fichas" in notas["gold"]


def test_pipeline_summary_avisa_sin_silver(tmp_path: Path) -> None:
    """Con Bronze pero sin Silver, la etapa de limpieza lo advierte."""
    # Arrange
    config = _config(tmp_path)
    _write(config.paths.capture_file, [{"url": f"{BASE}/a", "status": 200, "bytes": 10}])

    # Act
    summary = pipeline_summary(config)

    # Assert
    extract = next(stage for stage in summary.stages if stage.key == "extract")
    assert "make extract" in extract.warning


def test_pipeline_summary_lee_el_reporte_de_repetidos(tmp_path: Path) -> None:
    """La tarjeta de deduplicación usa las tablas de ``_REPETIDOS.md``."""
    # Arrange
    config = _config(tmp_path)
    config.paths.gold.mkdir(parents=True, exist_ok=True)
    config.paths.repetitions_file.write_text(
        (FIXTURES / "repetidos.md").read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Act
    summary = pipeline_summary(config)
    dedupe = next(stage for stage in summary.stages if stage.key == "dedupe")

    # Assert
    assert _metric(dedupe.metrics, "Páginas analizadas") == "181"
    assert _metric(dedupe.metrics, "Repetido >= 5 / 10 / 20") == "22.3 % / 16.7 % / 9.1 %"
    assert summary.repetitions is not None
    assert len(summary.repetitions.blocks) == 2


# -------------------------------------------------------------- reportes


def test_read_repetitions_parsea_umbrales_y_bloques() -> None:
    """Las tres tablas del reporte quedan estructuradas, con pipes escapados."""
    # Arrange
    path = FIXTURES / "repetidos.md"

    # Act
    report = read_repetitions(path)

    # Assert
    assert report is not None
    assert (report.pages, report.content_lines) == (181, 8094)
    assert [row.threshold for row in report.thresholds] == [5, 10, 20]
    assert report.thresholds[0].percentage == 22.3
    assert report.blocks[1].text == "Solicitud de vinculación / Tarjeta | Cuenta"
    assert report.unique_global == 71.4
    assert report.lowest[0] == ("app-movil-banco-de-occidente-ae3601", 12.5)


def test_read_repetitions_archivo_ausente(tmp_path: Path) -> None:
    """Sin reporte no hay datos (la app muestra el aviso de make repetidos)."""
    # Arrange
    path = tmp_path / "_REPETIDOS.md"

    # Act / Assert
    assert read_repetitions(path) is None


def test_read_index_parsea_el_titular() -> None:
    """El titular del índice da PDF, videos, tokens y checklist."""
    # Arrange
    path = FIXTURES / "indice.md"

    # Act
    index = read_index(path)

    # Assert
    assert index is not None
    assert (index.gold_pages, index.gold_tokens) == (241, 196139)
    assert (index.pdf, index.pdf_tokens) == (190, 10954933)
    assert (index.videos, index.videos_tokens) == (32, 119845)
    assert index.total_tokens == 11270917
    assert index.checklist == (24, 24, 100.0)


# -------------------------------------------------------------- metricas


def test_corpus_metrics_usa_el_indice_y_el_manifest(tmp_path: Path) -> None:
    """Páginas de corpus.jsonl, PDF y checklist del índice, descartes del manifest."""
    # Arrange
    config = _config(tmp_path)
    _write(config.paths.corpus_file, _corpus_rows())
    config.paths.index_file.write_text(
        (FIXTURES / "indice.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    manifest = tmp_path / "data/contexto/manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "tokens": 1000,
                "paginas": {"leidas": 5, "incluidas": 3, "excluidas": 2},
                "excluidas": [
                    {"motivo": "url_excluida"},
                    {"motivo": "url_excluida"},
                    {"motivo": "duplicado"},
                ],
            }
        ),
        encoding="utf-8",
    )

    # Act
    metrics = corpus_metrics(config)

    # Assert
    assert metrics.site_url == BASE
    assert (metrics.gold_pages, metrics.gold_tokens) == (2, 150)
    assert (metrics.pdf, metrics.videos) == (190, 32)
    assert metrics.checklist == (24, 24, 100.0)
    assert metrics.drops[0].reason == "url_excluida"
    assert metrics.drops[0].count == 2
    assert metrics.drops[1].reason == "duplicado"
    assert (metrics.context_pages, metrics.context_tokens) == (3, 1000)
    # El fixture declara 190 PDF y el JSONL no tiene filas: se avisa del desfase.
    assert any("no coinciden" in aviso for aviso in metrics.warnings)


def test_corpus_metrics_sin_indice_cae_a_los_jsonl(tmp_path: Path) -> None:
    """Sin ``_INDICE.md`` las cifras salen de corpus.jsonl y de los JSONL."""
    # Arrange
    config = _config(tmp_path)
    _write(config.paths.corpus_file, _corpus_rows())
    _write(config.paths.documents_index, [{"id": "doc-1", "tokens": 500}])
    _write(config.paths.videos_index, [{"id": "video-1", "tokens": 50}])

    # Act
    metrics = corpus_metrics(config)

    # Assert
    assert (metrics.pdf, metrics.pdf_tokens) == (1, 500)
    assert (metrics.videos, metrics.videos_tokens) == (1, 50)
    assert metrics.total_tokens == 700
    assert metrics.checklist is None
    assert any("_INDICE.md" in aviso for aviso in metrics.warnings)
    assert any("manifest.json" in aviso for aviso in metrics.warnings)
