"""Interfaz de linea de comandos del pipeline."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import Config, load_config
from .net import BlockedError, HttpClient

log = logging.getLogger("corpus")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
        stream=sys.stdout,
    )


def _urls_from_file(config: Config) -> list[str]:
    from .utils import read_jsonl

    return [row["url"] for row in read_jsonl(config.paths.urls_file) if row.get("url")]


def cmd_discover(config: Config, args: argparse.Namespace) -> int:
    from .discover import discover

    with HttpClient(config, delay=args.delay) as client:
        try:
            result = discover(config, client)
        except BlockedError as exc:
            log.error("%s", exc)
            return 2

    print(f"Sitemaps leidos      : {result.sitemaps_read} ({result.sitemaps_failed} fallidos)")
    print(f"robots.txt           : {'encontrado' if result.robots_found else 'no disponible'}")
    print(f"Crawl-delay          : {result.crawl_delay or 'no declarado'}")
    print(f"URLs HTML capturables: {result.urls}")
    print(f"Documentos (PDF...)  : {len(result.documents)}")
    print(f"Descartadas          : {len(result.skipped)}")
    if result.urls:
        print(f"Lista guardada en    : {config.paths.urls_file}")
    elif result.sitemaps_failed:
        print()
        print("Ningun sitemap respondio. Ejecuta 'make doctor':")
        print("lo mas probable es que la red actual este bloqueada (VPN).")
        return 2
    return 0


def cmd_fetch(config: Config, args: argparse.Namespace) -> int:
    from .fetch import fetch_all

    urls = _urls_from_file(config)
    if not urls:
        log.error("No hay URLs. Ejecuta 'make discover' primero.")
        return 1
    if args.limit:
        urls = urls[: args.limit]

    stats = fetch_all(
        config,
        urls,
        force=args.force,
        delay=args.delay,
        browser=args.browser,
    )
    print(
        f"Bronze: {stats.ok} nuevas, {stats.cached} en cache, "
        f"{stats.failed} fallidas, {stats.bytes / 1_048_576:.1f} MB"
    )
    if stats.failures:
        print(f"Primer error: {stats.failures[0]['error']}")
    # Un 404 suelto no invalida la captura: solo es error si no se guardo nada.
    if stats.ok == 0 and stats.cached == 0 and stats.failed:
        return 2
    return 0


def cmd_extract(config: Config, args: argparse.Namespace) -> int:
    from .extract import extract_all

    rows = extract_all(config)
    if not rows:
        return 1
    total = sum(int(row["chars"]) for row in rows)
    print(f"Silver: {len(rows)} paginas, {total:,} caracteres")
    return 0


def cmd_gold(config: Config, args: argparse.Namespace) -> int:
    from .gold import build_gold

    rows = build_gold(config, force=args.force)
    if not rows:
        return 1
    tokens = sum(int(row["tokens"]) for row in rows)
    print(f"Gold: {len(rows)} documentos, {tokens:,} tokens")
    return 0


def cmd_stats(config: Config, args: argparse.Namespace) -> int:
    from .stats import build_index, print_summary

    print_summary(config)
    if args.write:
        build_index(config)
    return 0


def cmd_chunks(config: Config, args: argparse.Namespace) -> int:
    from .knowledge import build_chunks

    rows = build_chunks(config)
    pages = len({row["page_id"] for row in rows})
    tokens = sum(int(row["tokens"]) for row in rows)
    print(f"Chunks: {len(rows)} de {pages} paginas, {tokens:,} tokens")
    print(f"Archivo: {config.paths.knowledge_chunks}")
    return 0


def cmd_knowledge(config: Config, args: argparse.Namespace) -> int:
    from .knowledge import (
        build_knowledge_index,
        load_knowledge,
        merge_draft,
        validate_knowledge,
        write_knowledge,
    )

    if args.merge or args.file:
        path = Path(args.merge or args.file)
        records, errors, warnings = merge_draft(config, path)
        target = path
    else:
        records = load_knowledge(config)
        errors, warnings = validate_knowledge(config, records)
        target = config.paths.knowledge

    for warning in warnings[:10]:
        print(f"AVISO  {warning}")
    for error in errors[:30]:
        print(f"ERROR  {error}")
    if len(errors) > 30:
        print(f"... y {len(errors) - 30} errores mas")

    if errors:
        print(f"\nKnowledge: FALLA ({len(errors)} errores) en {target}")
        return 1

    if args.merge:
        write_knowledge(config, records)
        build_knowledge_index(config)
        print(
            "Knowledge fusionado: "
            f"{len(records['entities'])} entidades, "
            f"{len(records['facts'])} hechos, "
            f"{len(records['relations'])} relaciones"
        )
        print(f"Indice: {config.paths.knowledge_index}")
    elif args.file:
        print(f"Knowledge OK: borrador valido (no se escribio) {target}")
    else:
        build_knowledge_index(config)
        print(
            "Knowledge OK: "
            f"{len(records['entities'])} entidades, "
            f"{len(records['facts'])} hechos, "
            f"{len(records['relations'])} relaciones"
        )
        print(f"Indice: {config.paths.knowledge_index}")
    return 0


def cmd_status(config: Config, args: argparse.Namespace) -> int:
    from .gold import load_corpus

    urls = _urls_from_file(config)
    corpus = load_corpus(config)
    raw_files = list(config.paths.raw_html.glob("*.html"))
    silver_files = list(config.paths.silver_markdown.glob("*.md"))

    print(f"{'Etapa':<12}{'Archivos':>10}")
    print("-" * 22)
    print(f"{'URLs':<12}{len(urls):>10}")
    print(f"{'Bronze':<12}{len(raw_files):>10}")
    print(f"{'Silver':<12}{len(silver_files):>10}")
    print(f"{'Gold':<12}{len(corpus):>10}")
    return 0


def cmd_all(config: Config, args: argparse.Namespace) -> int:
    for step, func in (
        ("discover", cmd_discover),
        ("fetch", cmd_fetch),
        ("extract", cmd_extract),
        ("gold", cmd_gold),
    ):
        print(f"\n==> {step}")
        code = func(config, args)
        if code != 0 and step in {"discover", "fetch"}:
            return code
    return cmd_stats(config, args)


def cmd_doctor(config: Config, args: argparse.Namespace) -> int:
    """Diagnostico: red, sitio, robots y estado del pipeline."""
    print(f"Python           : {sys.version.split()[0]}")
    print(f"Proyecto         : {config.paths.root}")
    print(f"Sitio            : {config.site.base_url}")
    print(f"UA               : {config.site.user_agent}")

    ok = True
    with HttpClient(config, delay=0.0) as client:
        try:
            response = client.get(config.site.base_url + "/robots.txt")
        except BlockedError as exc:
            print(f"robots.txt       : BLOQUEADO ({exc})")
            ok = False
        else:
            print(f"robots.txt       : HTTP {response.status} ({len(response.text)} bytes)")
            if response.status == 403:
                print()
                print("El sitio responde 403 a esta red. Causas tipicas:")
                print("  1. VPN activa con salida fuera de Colombia.")
                print("  2. WAF de CloudFront filtrando datacenter/bot.")
                print("Solucion: desconecta la VPN o usa una red residencial colombiana.")
                ok = False

    print(f"URLs en cola     : {len(_urls_from_file(config))}")
    print(f"Capturas Bronze  : {len(list(config.paths.raw_html.glob('*.html')))}")
    print()
    print("Diagnostico      : " + ("LISTO para capturar" if ok else "BLOQUEADO, revisa la red"))
    if not ok:
        print("Siguiente paso   : desconecta la VPN y repite 'make doctor'")
    return 0


def cmd_clean(config: Config, args: argparse.Namespace) -> int:
    targets = [config.paths.processed, config.paths.gold]
    if args.hard:
        targets.append(config.paths.raw)
    for path in targets:
        if path.exists():
            shutil.rmtree(path)
            print(f"borrado {path}")
    chunks = config.paths.knowledge_chunks
    if chunks.exists():
        chunks.unlink()
        print(f"borrado {chunks} (se regenera con 'make chunks')")
    config.paths.ensure()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="corpus",
        description="Corpus web de Banco de Occidente (Bronze -> Silver -> Gold).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", default=None, help="ruta alternativa a site.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--delay", type=float, default=None, help="segundos entre peticiones")
    parser.add_argument("--limit", type=int, default=None, help="maximo de URLs a procesar")
    parser.add_argument("--force", action="store_true", help="ignora la cache y regenera")
    parser.add_argument("--browser", action="store_true", help="usa Chromium (Playwright)")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("discover", help="lee robots.txt y sitemap.xml")
    sub.add_parser("fetch", help="descarga el HTML crudo (Bronze)")
    sub.add_parser("extract", help="limpia el HTML y genera Markdown (Silver)")
    sub.add_parser("gold", help="anade metadatos y consolida corpus.jsonl (Gold)")
    sub.add_parser("chunks", help="segmenta Gold en chunks por encabezado")
    knowledge = sub.add_parser("knowledge", help="valida entidades, hechos y relaciones")
    knowledge.add_argument("--file", default=None, help="valida un JSONL candidato")
    knowledge.add_argument("--merge", default=None, help="valida y fusiona un JSONL candidato")
    sub.add_parser("all", help="discover + fetch + extract + gold + stats")
    sub.add_parser("status", help="cuenta documentos por capa")
    sub.add_parser("doctor", help="diagnostica red y estado del pipeline")

    stats = sub.add_parser("stats", help="resumen y checklist del corpus")
    stats.add_argument("--write", action="store_true", help="escribe data/gold/_INDICE.md")

    clean = sub.add_parser("clean", help="borra capas derivadas")
    clean.add_argument("--hard", action="store_true", help="borra tambien Bronze")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    config = load_config(args.config)
    config.paths.ensure()

    handlers = {
        "discover": cmd_discover,
        "fetch": cmd_fetch,
        "extract": cmd_extract,
        "gold": cmd_gold,
        "chunks": cmd_chunks,
        "knowledge": cmd_knowledge,
        "all": cmd_all,
        "stats": cmd_stats,
        "status": cmd_status,
        "doctor": cmd_doctor,
        "clean": cmd_clean,
    }
    try:
        return handlers[args.command](config, args)
    except KeyboardInterrupt:
        print("\ninterrumpido")
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
