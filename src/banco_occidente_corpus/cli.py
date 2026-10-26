"""Interfaz de linea de comandos del pipeline."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .config import Config, load_config
from .net import MIN_DELAY_SECONDS, BlockedError, HttpClient

log = logging.getLogger("corpus")


def _delay_seconds(value: str) -> float:
    """Valida ``--delay`` contra el minimo de cortesia del proyecto."""
    try:
        delay = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}' no es un numero de segundos") from exc
    if delay < MIN_DELAY_SECONDS:
        raise argparse.ArgumentTypeError(
            f"el minimo es {MIN_DELAY_SECONDS} s entre peticiones (cortesia con el sitio)"
        )
    return delay


def _setup_logging(verbose: bool) -> None:
    """Configura el logging a stdout, tolerante a la consola cp1252 de Windows."""
    # La consola de Windows usa cp1252: un titulo con caracteres combinados
    # (p. ej. "n" + tilde) rompe logging. Se degrada a 'replace' sin perder el log.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="replace")
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
        stream=sys.stdout,
    )


def _urls_from_file(config: Config) -> list[str]:
    """Lee las URLs descubiertas en ``data/raw/urls.jsonl``."""
    from .utils import read_jsonl

    return [row["url"] for row in read_jsonl(config.paths.urls_file) if row.get("url")]


def cmd_discover(config: Config, args: argparse.Namespace) -> int:
    """Lee robots.txt y el sitemap y deja la lista de URLs a capturar."""
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
    """Descarga el HTML crudo de la lista de URLs y llena Bronze."""
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
    """Limpia el HTML de Bronze y genera Markdown en Silver (sin red)."""
    from .extract import extract_all

    rows = extract_all(config)
    if not rows:
        return 1
    total = sum(int(row["chars"]) for row in rows)
    print(f"Silver: {len(rows)} paginas, {total:,} caracteres")
    return 0


def cmd_gold(config: Config, args: argparse.Namespace) -> int:
    """Convierte Silver en Gold: Markdown con frontmatter y ``corpus.jsonl``."""
    from .gold import build_gold

    rows = build_gold(config, force=args.force)
    if not rows:
        return 1
    tokens = sum(int(row["tokens"]) for row in rows)
    print(f"Gold: {len(rows)} documentos, {tokens:,} tokens")
    return 0


def cmd_stats(config: Config, args: argparse.Namespace) -> int:
    """Imprime el resumen del corpus y, con ``--write``, reescribe el indice."""
    from .stats import build_index, print_summary

    print_summary(config)
    if args.write:
        build_index(config)
    return 0


def cmd_repetidos(config: Config, args: argparse.Namespace) -> int:
    """Escribe el reporte de repeticiones de Gold e imprime su resumen sin usar la red."""
    from .dedupe import analyze_gold_repetitions, write_repetitions_report

    report = analyze_gold_repetitions(config.paths.gold_markdown)
    target = write_repetitions_report(config)
    print(f"Paginas analizadas  : {report.pages_analyzed}")
    for coverage in report.thresholds:
        print(
            f"Repetido >= {coverage.threshold:>2} pag.: "
            f"{coverage.percentage:.1f} % "
            f"({coverage.covered_lines}/{coverage.total_lines} lineas)"
        )
    print(f"Reporte             : {target}")
    return 0


def cmd_chunks(config: Config, args: argparse.Namespace) -> int:
    """Segmenta Gold en chunks por encabezado para la capa Knowledge."""
    from .knowledge import build_chunks

    rows = build_chunks(config)
    pages = len({row["page_id"] for row in rows})
    tokens = sum(int(row["tokens"]) for row in rows)
    print(f"Chunks: {len(rows)} de {pages} paginas, {tokens:,} tokens")
    print(f"Archivo: {config.paths.knowledge_chunks}")
    return 0


def cmd_knowledge(config: Config, args: argparse.Namespace) -> int:
    """Valida la capa Knowledge y fusiona un borrador cuando se pide."""
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


def cmd_docs(config: Config, args: argparse.Namespace) -> int:
    """Inventaria, descarga y extrae los PDF a Gold."""
    from .documents import discover_documents, extract_documents, fetch_documents

    if args.docs_action in {"discover", "all"}:
        rows = discover_documents(config)
        by_priority: dict[int, int] = {}
        for row in rows:
            by_priority[row["prioridad"]] = by_priority.get(row["prioridad"], 0) + 1
        print(f"Documentos inventariados: {len(rows)} {by_priority}")

    if args.docs_action in {"fetch", "all"}:
        stats = fetch_documents(
            config,
            limit=args.limit,
            max_mb=args.max_mb,
            priority_max=3 if args.all_docs else args.priority_max,
            force=args.force,
            delay=args.delay,
            types=args.doc_types,
        )
        print(
            "Documentos: "
            f"{stats['ok']} nuevos, {stats['cached']} en cache, "
            f"{stats['failed']} fallidos, {stats['skipped']} omitidos, "
            f"{stats['bytes'] / 1_048_576:.1f} MB"
        )

    if args.docs_action in {"extract", "all"}:
        rows = extract_documents(config)
        print(f"Documentos Gold: {len(rows)}")

    return 0


def cmd_videos(config: Config, args: argparse.Namespace) -> int:
    """Inventaria videos, descarga subtitulos y los transcribe a Gold."""
    from .videos import discover_videos, extract_videos, fetch_videos

    if args.videos_action in {"discover", "all"}:
        rows = discover_videos(config, channel_limit=args.channel_limit)
        print(f"Videos inventariados: {len(rows)}")

    if args.videos_action in {"fetch", "all"}:
        stats = fetch_videos(config, limit=args.limit, force=args.force)
        print(
            "Videos: "
            f"{stats['ok']} nuevos, {stats['cached']} en cache, "
            f"{stats['failed']} fallidos, {stats['sin_subtitulos']} sin subtitulos"
        )

    if args.videos_action in {"extract", "all"}:
        rows = extract_videos(config)
        print(f"Videos Gold: {len(rows)}")

    return 0


def cmd_noticias(config: Config, args: argparse.Namespace) -> int:
    """Regenera hechos oficiales y fichas de prensa en Gold.

    Usa Bronze si existe; solo hace una peticion puntual cuando falta y no se
    ejecuto ``--sin-red``. Ante ``403`` o bloqueo persistente se detiene con
    codigo 2 y no escribe fichas oficiales nuevas.
    """
    from .news import build_noticias, parse_fecha_es

    desde_texto = args.desde or config.news.desde or "2025-01-01"
    hasta_texto = args.hasta or config.news.hasta or date.today().isoformat()
    try:
        desde = parse_fecha_es(str(desde_texto))
        hasta = parse_fecha_es(str(hasta_texto))
    except ValueError as exc:
        log.error("Ventana de noticias invalida: %s", exc)
        return 1

    try:
        rows = build_noticias(
            config,
            desde=desde,
            hasta=hasta,
            sin_red=bool(args.sin_red),
            force=bool(args.force),
        )
    except BlockedError as exc:
        log.error("Noticias detenidas: %s", exc)
        log.error("No se escribieron fichas oficiales nuevas.")
        return 2
    except ValueError as exc:
        log.error("Noticias: %s", exc)
        return 1

    oficiales = sum(1 for row in rows if row.get("origen") == "oficial")
    print(f"Hechos oficiales    : {oficiales}")
    print(f"Fichas de prensa    : {len(rows) - oficiales}")
    print(f"Paginas Gold        : {config.paths.gold_markdown}")
    print(f"Indice              : {config.paths.news_index}")
    return 0


def cmd_status(config: Config, args: argparse.Namespace) -> int:
    """Cuenta archivos por capa (URLs, Bronze, Silver, Gold, PDF y videos)."""
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
    print(f"{'Docs PDF':<12}{len(list(config.paths.documents_gold.glob('*.md'))):>10}")
    print(f"{'Videos':<12}{len(list(config.paths.videos_gold.glob('*.md'))):>10}")
    return 0


def cmd_all(config: Config, args: argparse.Namespace) -> int:
    """Encadena discover, fetch, extract, gold y stats en una sola corrida."""
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
    with HttpClient(config) as client:
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
            elif not response.ok:
                print(f"El sitio no responde sano (HTTP {response.status}).")
                ok = False

    print(f"URLs en cola     : {len(_urls_from_file(config))}")
    print(f"Capturas Bronze  : {len(list(config.paths.raw_html.glob('*.html')))}")
    print()
    print("Diagnostico      : " + ("LISTO para capturar" if ok else "BLOQUEADO, revisa la red"))
    if not ok:
        print("Siguiente paso   : desconecta la VPN y repite 'make doctor'")
        return 2
    return 0


def cmd_clean(config: Config, args: argparse.Namespace) -> int:
    """Borra Silver y Gold; con ``--hard`` borra tambien Bronze (manual)."""
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
    """Construye el parser de argumentos del CLI ``corpus``."""
    parser = argparse.ArgumentParser(
        prog="corpus",
        description="Corpus web de Banco de Occidente (Bronze -> Silver -> Gold).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", default=None, help="ruta alternativa a site.toml")
    parser.add_argument("-v", "--verbose", action="store_true")

    # Opciones de captura: viven en cada subcomando (``corpus fetch --delay 2``),
    # no en la raiz, porque argparse no acepta opciones globales tras el verbo.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--delay",
        type=_delay_seconds,
        default=None,
        help=f"segundos entre peticiones (minimo {MIN_DELAY_SECONDS})",
    )
    common.add_argument("--limit", type=int, default=None, help="maximo de URLs a procesar")
    common.add_argument("--force", action="store_true", help="ignora la cache y regenera")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("discover", help="lee robots.txt y sitemap.xml", parents=[common])
    sub.add_parser("fetch", help="descarga el HTML crudo (Bronze)", parents=[common])
    sub.add_parser("extract", help="limpia el HTML y genera Markdown (Silver)")
    sub.add_parser("gold", help="anade metadatos y consolida corpus.jsonl (Gold)", parents=[common])
    sub.add_parser("chunks", help="segmenta Gold en chunks por encabezado")
    knowledge = sub.add_parser("knowledge", help="valida entidades, hechos y relaciones")
    knowledge.add_argument("--file", default=None, help="valida un JSONL candidato")
    knowledge.add_argument("--merge", default=None, help="valida y fusiona un JSONL candidato")
    docs = sub.add_parser(
        "docs", help="documentos PDF: discover | fetch | extract | all", parents=[common]
    )
    docs.add_argument("docs_action", choices=["discover", "fetch", "extract", "all"])
    docs.add_argument("--max-mb", type=float, default=400, help="tope de descarga en MB")
    docs.add_argument("--priority-max", type=int, default=2, help="prioridad maxima (1-3)")
    docs.add_argument("--all", dest="all_docs", action="store_true", help="sin filtro de prioridad")
    docs.add_argument(
        "--tipo", dest="doc_types", default=None, help="filtrar: financiero,gobierno,producto,legal"
    )
    videos = sub.add_parser(
        "videos", help="videos de YouTube: discover | fetch | extract | all", parents=[common]
    )
    videos.add_argument("videos_action", choices=["discover", "fetch", "extract", "all"])
    videos.add_argument("--channel-limit", type=int, default=30, help="videos del canal a listar")
    noticias = sub.add_parser("noticias", help="hechos oficiales y prensa curada a Gold")
    noticias.add_argument("--desde", default=None, help="fecha inicial (ISO o espanol)")
    noticias.add_argument("--hasta", default=None, help="fecha final (ISO o espanol)")
    noticias.add_argument(
        "--sin-red",
        action="store_true",
        help="no toca la red: usa solo Bronze y la curaduria",
    )
    noticias.add_argument(
        "--force",
        action="store_true",
        help="refresca Bronze y regenera las fichas",
    )
    sub.add_parser("all", help="discover + fetch + extract + gold + stats", parents=[common])
    sub.add_parser("status", help="cuenta documentos por capa")
    sub.add_parser("doctor", help="diagnostica red y estado del pipeline")

    stats = sub.add_parser("stats", help="resumen y checklist del corpus")
    stats.add_argument("--write", action="store_true", help="escribe data/gold/_INDICE.md")

    sub.add_parser("repetidos", help="mide repeticiones en las paginas Gold (sin red)")

    clean = sub.add_parser("clean", help="borra capas derivadas")
    clean.add_argument("--hard", action="store_true", help="borra tambien Bronze")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada: despacha el subcomando y devuelve el codigo de salida."""
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
        "docs": cmd_docs,
        "videos": cmd_videos,
        "noticias": cmd_noticias,
        "all": cmd_all,
        "stats": cmd_stats,
        "repetidos": cmd_repetidos,
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
