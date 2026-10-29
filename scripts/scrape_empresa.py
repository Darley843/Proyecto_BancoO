"""Scraper de demostración: capa delgada sobre el pipeline del proyecto.

    uv run python scripts/scrape_empresa.py
    uv run scripts/scrape_empresa.py --limit 3 --out .demo/prueba

Descubre hasta ``--limit`` URLs del índice de sitemaps respetando ``robots.txt``
y los filtros de ``config/site.toml``. Después ejecuta el pipeline real
(Bronze -> Silver -> Gold) con ``live_capture.run_capture``, sin cliente HTTP ni
formato propios. La salida por defecto es ``.demo/scrape_empresa/``.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from banco_occidente_corpus.config import PROJECT_ROOT, Config, load_config
from banco_occidente_corpus.discover import is_capture_target, normalize_url, parse_sitemap
from banco_occidente_corpus.live_capture import (
    BLOCKED_MESSAGE,
    LiveCapture,
    run_capture,
)
from banco_occidente_corpus.net import (
    MIN_DELAY_SECONDS,
    BlockedError,
    HttpClient,
    RobotsGuard,
)

#: Carpeta de demostración: ya está cubierta por ``.demo/`` en ``.gitignore``.
DEFAULT_OUT = Path(".demo/scrape_empresa")
DEFAULT_LIMIT = 5

#: Mensaje neutro ante un bloqueo del sitio o una caída de red.
MENSAJE_BLOQUEO = (
    "El sitio rechazo la peticion (HTTP 403/429) o no hubo red. "
    "Captura detenida: no se reintenta con otro cliente ni se cambia de red."
)


class SitioBloqueado(RuntimeError):
    """El sitio respondió 403 o 429 durante el descubrimiento."""


@dataclass(frozen=True, slots=True)
class Seleccion:
    """URLs capturables y número de sitemaps leídos en el descubrimiento."""

    urls: tuple[str, ...]
    sitemaps: int


def _dentro_de(path: Path, base: Path) -> bool:
    """True si ``path`` es ``base`` o queda debajo, sin distinguir mayúsculas."""
    partes = tuple(parte.casefold() for parte in path.resolve().parts)
    base_partes = tuple(parte.casefold() for parte in base.resolve().parts)
    return len(partes) >= len(base_partes) and partes[: len(base_partes)] == base_partes


def _out_path(value: str) -> Path:
    """Valida ``--out``: cualquier carpeta fuera de ``data/``."""
    out = Path(value).expanduser()
    if _dentro_de(out, PROJECT_ROOT / "data"):
        raise argparse.ArgumentTypeError(
            "--out no puede escribir dentro de data/ (el corpus real no se toca); "
            "usa .demo/scrape_empresa/ u otra carpeta fuera de data"
        )
    return out


def _delay(value: str) -> float:
    """Valida ``--delay`` con el mínimo de cortesía que impone ``net.py``."""
    try:
        delay = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}' no es un numero de segundos") from exc
    if delay < MIN_DELAY_SECONDS:
        raise argparse.ArgumentTypeError(
            f"el minimo es {MIN_DELAY_SECONDS} s entre peticiones (cortesia con el sitio)"
        )
    return delay


def _limite(value: str) -> int:
    """Valida que ``--limit`` sea al menos una página."""
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}' no es un numero entero") from exc
    if limit < 1:
        raise argparse.ArgumentTypeError("--limit debe ser mayor o igual a 1")
    return limit


def _leer_sitemap(client: HttpClient, url: str) -> str | None:
    """Descarga un sitemap; se detiene de inmediato ante 403 o 429."""
    response = client.get(url)
    if response.status in (403, 429):
        raise SitioBloqueado(
            f"{url} respondio HTTP {response.status}. Captura detenida: "
            "no se reintenta con otro cliente ni se cambia de red."
        )
    if not response.ok:
        return None
    return response.text


def recolectar_urls(
    client: HttpClient,
    guard: RobotsGuard,
    config: Config,
    limit: int,
) -> Seleccion:
    """Recorre el índice de sitemaps y reúne hasta ``limit`` URLs capturables.

    Se detiene en cuanto junta las URLs pedidas, así que no recorre los ~210
    sitemaps del sitio. Aplica ``is_capture_target`` y ``robots.txt`` antes de
    aceptar cada URL.
    """
    base = config.site.base_url.rstrip("/")
    if not config.site.sitemap_url:
        return Seleccion((), 0)

    cola: deque[tuple[str, int]] = deque([(config.site.sitemap_url, 0)])
    sitemaps_vistos: set[str] = set()
    urls_vistas: set[str] = set()
    urls: list[str] = []
    sitemaps = 0

    while cola and len(urls) < limit:
        sitemap_url, depth = cola.popleft()
        if sitemap_url in sitemaps_vistos:
            continue
        sitemaps_vistos.add(sitemap_url)
        if not guard.allowed(sitemap_url):
            continue

        texto = _leer_sitemap(client, sitemap_url)
        sitemaps += 1
        if texto is None:
            continue

        kind, locs = parse_sitemap(texto)
        if kind == "sitemapindex" and depth < config.crawl.max_sitemap_depth:
            cola.extend((normalize_url(urljoin(base + "/", loc)), depth + 1) for loc in locs)
            continue
        if kind not in {"urlset", "url"}:
            continue

        for raw in locs:
            url = normalize_url(urljoin(base + "/", raw))
            if url in urls_vistas:
                continue
            urls_vistas.add(url)
            if not is_capture_target(url, config):
                continue
            if not guard.allowed(url):
                continue
            urls.append(url)
            if len(urls) >= limit:
                break

    return Seleccion(tuple(urls), sitemaps)


def imprimir_resumen(captura: LiveCapture) -> None:
    """Imprime cada etapa del pipeline y la ruta de una página Gold generada."""
    print("\nResumen por etapa")
    for stage in captura.stages:
        print(f"  [{stage.state}] {stage.title}: {stage.detail}")
        for metric in stage.metrics:
            print(f"      {metric.label}: {metric.value}")
    print(f"\nCarpeta de trabajo: {captura.workdir}")
    if captura.page_path is not None:
        print(f"Gold: {captura.page_path}")
    else:
        print("Gold: no se genero ninguna pagina")


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser del scraper con sus validaciones."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--limit",
        type=_limite,
        default=DEFAULT_LIMIT,
        help=f"maximo de paginas a capturar (por defecto {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--delay",
        type=_delay,
        default=MIN_DELAY_SECONDS,
        help=f"segundos entre peticiones (minimo {MIN_DELAY_SECONDS})",
    )
    parser.add_argument(
        "--out",
        type=_out_path,
        default=DEFAULT_OUT,
        help=f"carpeta de salida (por defecto {DEFAULT_OUT}; nunca dentro de data/)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Descubre, captura y construye Bronze, Silver y Gold para la demo."""
    args = build_parser().parse_args(argv)
    config = load_config()
    config.crawl.delay_seconds = args.delay

    captura: LiveCapture | None = None
    try:
        with HttpClient(config, delay=args.delay) as client:
            guard = RobotsGuard(client, config.site.user_agent)
            seleccion = recolectar_urls(client, guard, config, args.limit)
            print(f"Descubrimiento: {len(seleccion.urls)} URLs en {seleccion.sitemaps} sitemaps")
            for url in seleccion.urls:
                print(f"  - {url}")
            if not seleccion.urls:
                print("No se encontraron URLs capturables en el sitemap.")
                return 1

            captura = run_capture(config, seleccion.urls, workdir=args.out, client=client)
    except SitioBloqueado as exc:
        print(f"\n! {exc}")
        return 3
    except BlockedError:
        print(f"\n! {MENSAJE_BLOQUEO}")
        return 3

    if captura is None:
        return 1
    imprimir_resumen(captura)
    if captura.error:
        print(f"\n! {captura.error}")
        return 3 if captura.error == BLOCKED_MESSAGE else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
