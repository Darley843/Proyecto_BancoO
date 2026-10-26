"""Pruebas del análisis de repeticiones sobre las páginas web de Gold."""

from __future__ import annotations

import argparse
import hashlib
import socket
from pathlib import Path

import pytest

from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.dedupe import (
    RepeatedBlock,
    analyze_gold_repetitions,
    compute_unique_ratio_metrics,
    find_repeated_blocks,
    load_gold_pages,
    render_repetitions_report,
    write_repetitions_report,
)


def write_page(root: Path, page_id: str, lines: list[str]) -> Path:
    """Escribe una página Gold mínima con frontmatter y devuelve su ruta."""
    root.mkdir(parents=True, exist_ok=True)
    body = "\n".join(lines)
    content = f"---\ntitulo: {page_id}\n---\n\n{body}\n"
    path = root / f"{page_id}.md"
    path.write_text(content, encoding="utf-8")
    return path


def write_corpus(tmp_path: Path, pages: dict[str, list[str]]) -> Path:
    """Crea un directorio de páginas Gold con las páginas indicadas."""
    root = tmp_path / "pages"
    for page_id, lines in pages.items():
        write_page(root, page_id, lines)
    return root


def block_of(blocks: list[RepeatedBlock], size: int) -> RepeatedBlock:
    """Devuelve el primer bloque del tamaño indicado."""
    for block in blocks:
        if block.size == size:
            return block
    raise AssertionError(f"no hay bloque de {size} líneas")


def test_carga_paginas_solo_del_sitio(tmp_path: Path) -> None:
    """Ignora las fichas de hechos y noticias al cargar las páginas."""
    shared = ["Solicita tu tarjeta", "Sin cuota de manejo"]
    root = write_corpus(
        tmp_path,
        {
            "sitio-uno": shared,
            "sitio-dos": shared,
            "hecho-2026-01-01-demo": shared,
            "noticia-demo": shared,
        },
    )

    pages = load_gold_pages(root)

    assert [page.page_id for page in pages] == ["sitio-dos", "sitio-uno"]


def test_excluye_fichas_y_archivos_privados(tmp_path: Path) -> None:
    """Excluye prefijos de noticias y archivos internos que empiezan por guion bajo."""
    shared = ["Abre tu cuenta", "Sin cuota de manejo"]
    root = write_corpus(
        tmp_path,
        {
            "sitio": shared,
            "hecho-demo": shared,
            "noticia-demo": shared,
            "_INDICE": shared,
        },
    )

    pages = load_gold_pages(root)

    assert [page.page_id for page in pages] == ["sitio"]


def test_excluye_documentos_y_videos(tmp_path: Path) -> None:
    """No lee los directorios de documentos ni de videos del corpus."""
    shared = ["Solicita tu tarjeta", "Sin cuota de manejo"]
    root = write_corpus(
        tmp_path,
        {"sitio-uno": shared, "sitio-dos": shared, "sitio-tres": shared},
    )
    for name in ("documents", "videos"):
        directory = tmp_path / name
        directory.mkdir()
        write_page(directory, "extra", shared)

    report = analyze_gold_repetitions(root)

    assert report.pages_analyzed == 3
    assert report.top_blocks[0].pages == 3


def test_detecta_bloque_de_tarjeta_repetido(tmp_path: Path) -> None:
    """Detecta un bloque de tres líneas repetido en varias páginas."""
    card = ["Tarjeta de crédito", "Cupo inmediato", "Sin cuota de manejo"]
    root = write_corpus(
        tmp_path,
        {"pagina-a": card, "pagina-b": card, "pagina-c": card},
    )

    blocks = find_repeated_blocks(load_gold_pages(root))
    block = block_of(blocks, 3)

    assert block.pages == 3
    assert block.text == tuple(card)


def test_detecta_linea_suelta_repetida(tmp_path: Path) -> None:
    """Detecta una línea suelta que se repite como bloque de un elemento."""
    root = write_corpus(
        tmp_path,
        {
            "pagina-a": ["Solicita tu tarjeta"],
            "pagina-b": ["Solicita tu tarjeta"],
            "pagina-c": ["Solicita tu tarjeta"],
        },
    )

    blocks = find_repeated_blocks(load_gold_pages(root))
    block = block_of(blocks, 1)

    assert block.pages == 3
    assert block.text == ("Solicita tu tarjeta",)


def test_no_duplica_paginas_con_bloque_repetido(tmp_path: Path) -> None:
    """Cuenta una sola vez la página aunque el bloque aparezca dos veces en ella."""
    repeated = ["Pide tu tarjeta", "Sin cuota de manejo"]
    root = write_corpus(
        tmp_path,
        {
            "pagina-a": repeated + repeated,
            "pagina-b": repeated,
            "pagina-c": repeated,
            "pagina-d": repeated,
            "pagina-e": repeated,
        },
    )

    blocks = find_repeated_blocks(load_gold_pages(root))
    block = block_of(blocks, 2)

    assert block.pages == 5
    assert len(block.examples) == 3


def test_comparacion_ignora_mayusculas_y_tildes(tmp_path: Path) -> None:
    """Unifica mayúsculas y tildes y conserva la grafía de la primera aparición."""
    root = write_corpus(
        tmp_path,
        {
            "pagina-a": ["Cuenta de Nómina"],
            "pagina-b": ["Cuenta de Nomina"],
            "pagina-c": ["CUENTA DE NÓMINA"],
        },
    )

    blocks = find_repeated_blocks(load_gold_pages(root))
    block = block_of(blocks, 1)

    assert block.pages == 3
    assert block.text == ("Cuenta de Nómina",)


def test_umbrales_calculan_porcentaje(tmp_path: Path) -> None:
    """Calcula cobertura por umbral y deja en cero los umbrales no alcanzados."""
    shared = ["Solicita tu tarjeta", "Sin cuota de manejo"]
    pages = {f"pagina-{index}": [*shared, f"Contenido propio {index}"] for index in range(5)}
    root = write_corpus(tmp_path, pages)

    report = analyze_gold_repetitions(root)

    by_threshold = {row.threshold: row for row in report.thresholds}
    assert set(by_threshold) == {5, 10, 20}
    assert by_threshold[5].covered_lines == 10
    assert by_threshold[5].total_lines == 15
    assert by_threshold[5].percentage == 66.7
    assert by_threshold[10].percentage == 0.0
    assert by_threshold[20].percentage == 0.0


def test_bloques_solapados_cuentan_una_vez(tmp_path: Path) -> None:
    """No duplica la cobertura cuando una línea pertenece a bloques de distinto tamaño."""
    shared = ["Solicita tu tarjeta", "Sin cuota de manejo"]
    pages = {f"pagina-{index}": shared for index in range(5)}
    root = write_corpus(tmp_path, pages)

    report = analyze_gold_repetitions(root, thresholds=(5,))

    coverage = report.thresholds[0]
    assert coverage.covered_lines == 10
    assert coverage.total_lines == 10
    assert coverage.percentage == 100.0


def test_unique_ratio_global_promedio_y_paginas_repetitivas(tmp_path: Path) -> None:
    """Resume el ratio global, el promedio y destaca la página más repetitiva."""
    root = write_corpus(
        tmp_path,
        {
            "a-repetitiva": ["Abre tu cuenta", "Abre tu cuenta", "Abre tu cuenta"],
            "b-unica": ["Solicita tu tarjeta", "Sin cuota de manejo"],
        },
    )

    metrics = compute_unique_ratio_metrics(load_gold_pages(root))

    assert metrics.global_ratio == pytest.approx(0.6)
    assert metrics.average == pytest.approx((1 / 3 + 1) / 2)
    assert metrics.lowest[0].page_id == "a-repetitiva"
    assert metrics.lowest[0].ratio == pytest.approx(1 / 3)


def test_ruta_reporte_repetidos_sin_crear_artefactos(tmp_path: Path) -> None:
    """Resuelve el reporte dentro de Gold sin crear el archivo ni el directorio."""
    paths = Paths(gold=tmp_path / "gold")

    target = paths.repetitions_file

    assert target == tmp_path / "gold" / "_REPETIDOS.md"
    assert not target.exists()
    assert not (tmp_path / "gold").exists()


def test_render_reporte_con_secciones_y_limite(tmp_path: Path) -> None:
    """Renderiza las secciones pedidas, limita el top a veinte y conserva tildes."""
    pages: dict[str, list[str]] = {}
    for index in range(22):
        card = [
            "Cuenta de Nómina",
            f"Tarjeta | Premium {index}",
            f"Cupo inmediato {index}",
        ]
        pages[f"pagina-{index:02d}-a"] = card
        pages[f"pagina-{index:02d}-b"] = card
    root = write_corpus(tmp_path, pages)

    report = analyze_gold_repetitions(root)
    text = render_repetitions_report(report)

    assert "**Páginas analizadas:** 44" in text
    assert "## Cobertura por umbral" in text
    assert "## Top 20 de bloques" in text
    assert "## Contenido único (`unique_ratio`)" in text
    assert "| 5 |" in text
    assert "| 10 |" in text
    assert "| 20 |" in text
    assert "Cuenta de Nómina" in text
    assert "\\|" in text
    assert len(report.top_blocks) == 20
    top_section = text.split("## Top 20 de bloques", 1)[1].split("\n## ", 1)[0]
    rows = [
        line
        for line in top_section.splitlines()
        if line.startswith("| ") and not line.startswith("| #")
    ]
    assert len(rows) == 20


def test_escritura_solo_crea_reporte_y_no_altera_gold(tmp_path: Path) -> None:
    """Escribe solo ``_REPETIDOS.md`` en UTF-8, sin CRLF y sin tocar los demás artefactos."""
    shared = ["Cuenta de Nómina", "Sin cuota de manejo"]
    write_corpus(
        tmp_path,
        {
            "pagina-a": shared,
            "pagina-b": shared,
            "hecho-2026-01-01-demo": shared,
        },
    )
    for name in ("corpus.jsonl", "documents.jsonl", "videos.jsonl"):
        (tmp_path / name).write_text(f'{{"archivo": "{name}"}}\n', encoding="utf-8")
    config = Config(paths=Paths(gold=tmp_path))
    before = {
        path: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    target = write_repetitions_report(config)
    first = target.read_bytes()
    write_repetitions_report(config)
    second = target.read_bytes()

    assert target == tmp_path / "_REPETIDOS.md"
    assert first == second
    assert b"\r\n" not in first
    assert "**Páginas analizadas:** 2" in first.decode("utf-8")
    after = {path for path in tmp_path.rglob("*") if path.is_file()}
    assert after - set(before) == {target}
    for path, digest in before.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_parser_incluye_repetidos() -> None:
    """El CLI reconoce el subcomando ``repetidos``."""
    from banco_occidente_corpus.cli import build_parser

    args = build_parser().parse_args(["repetidos"])

    assert args.command == "repetidos"


def test_cmd_repetidos_termina_sin_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """El subcomando ``repetidos`` genera el reporte sin abrir conexiones de red."""
    from banco_occidente_corpus import cli

    def bloquear_conexiones(*_: object, **__: object) -> None:
        """Falla si el comando intenta abrir un socket."""
        raise AssertionError("repetidos no debe abrir conexiones de red")

    monkeypatch.setattr(socket, "socket", bloquear_conexiones)
    monkeypatch.setattr(socket, "create_connection", bloquear_conexiones)
    shared = ["Solicita tu tarjeta", "Sin cuota de manejo"]
    root = write_corpus(tmp_path, {"pagina-a": shared, "pagina-b": shared})
    config = Config(paths=Paths(gold=root.parent))

    code = cli.cmd_repetidos(config, argparse.Namespace())

    salida = capsys.readouterr().out
    assert code == 0
    assert config.paths.repetitions_file.exists()
    assert "Paginas analizadas  : 2" in salida
    assert "Repetido >=  5 pag." in salida
    assert "Repetido >= 10 pag." in salida
    assert "Repetido >= 20 pag." in salida
    assert str(config.paths.repetitions_file) in salida
