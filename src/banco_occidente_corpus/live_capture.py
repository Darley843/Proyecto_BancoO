"""Captura en vivo de unas pocas URLs en un directorio temporal.

La pestaña «Scraping» de la app enseña el pipeline con datos reales sin tocar el
corpus: copia la configuración, apunta las variables ``CORPUS_*_DIR`` a una
carpeta temporal y ejecuta Bronze -> Silver -> Gold allí dentro.

Reglas que se heredan del pipeline y no se relajan aquí:

1. Toda petición pasa por ``net.HttpClient``: User-Agent, header ``From``,
   timeout y la pausa mínima de 1,5 s. No hay HTTP directo.
2. ``robots.txt`` se consulta con ``RobotsGuard`` antes de descargar, con el
   mismo cliente que hace las capturas (así la pausa cubre ambas).
3. Ante un bloqueo persistente o falta de red la captura se detiene con un
   mensaje neutro: nunca se sugiere cambiar de red, usar VPN o un navegador
   (``CONSTITUTION.md`` §10). Tampoco se copia el texto de ``BlockedError``,
   que menciona una salida por red residencial.
4. Nada se escribe en ``data/``: todo vive en la carpeta temporal.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import Config, Paths
from .dedupe import find_boilerplate, find_repeated_blocks, load_gold_pages, split_frontmatter
from .discover import discover, is_capture_target
from .extract import extract_all
from .fetch import fetch_all
from .gold import build_gold
from .net import HttpClient, RobotsGuard
from .panel import Metric, queue_urls_file
from .utils import human_size, read_jsonl

#: URLs que la app captura por defecto.
DEFAULT_SAMPLE = 3

#: Variables con las que ``config.Paths`` resuelve las capas del corpus.
TEMP_ENV: tuple[str, ...] = ("CORPUS_RAW_DIR", "CORPUS_PROCESSED_DIR", "CORPUS_GOLD_DIR")

#: Serializa la mutación del entorno: Streamlit comparte proceso entre sesiones.
_LOCK = threading.Lock()

#: Mensaje de parada ante un bloqueo o una caída de red. Sin recomendaciones.
BLOCKED_MESSAGE = (
    "El sitio rechazó la petición de forma persistente (HTTP 403) o no hubo red. "
    "Captura detenida: es una limitación documentada (CONSTITUTION.md §10). "
    "El proyecto no usa navegadores, proxies ni otra red para sortear el WAF."
)


@dataclass(frozen=True, slots=True)
class DiscoveryAudit:
    """Resultado de una auditoría completa de descubrimiento (solo lectura)."""

    robots_found: bool
    crawl_delay: float | None
    sitemaps_read: int
    sitemaps_failed: int
    urls: int
    documents: int
    skipped: tuple[tuple[str, int], ...] = ()
    seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class RobotCheck:
    """Veredicto de robots.txt sobre la cola de captura."""

    allowed: tuple[str, ...]
    blocked: tuple[str, ...]
    robots_found: bool


@dataclass(frozen=True, slots=True)
class LiveStage:
    """Una etapa de la captura en vivo con su resultado."""

    key: str
    title: str
    detail: str
    state: str = "ok"
    metrics: tuple[Metric, ...] = ()


@dataclass(frozen=True, slots=True)
class LiveCapture:
    """Resultado completo de la captura en vivo (páginas, etapas y frontmatter)."""

    workdir: Path
    urls: tuple[str, ...]
    allowed: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()
    robots_found: bool = False
    stages: tuple[LiveStage, ...] = ()
    corpus: tuple[dict[str, Any], ...] = ()
    page_path: Path | None = None
    frontmatter_text: str = ""
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body_excerpt: str = ""
    error: str = ""


# ------------------------------------------------------------------ cola


def captured_urls(config: Config) -> set[str]:
    """URLs con algún registro en ``capture.jsonl`` (éxitos o fallos conocidos)."""
    return {str(row["url"]) for row in read_jsonl(config.paths.capture_file) if row.get("url")}


def select_urls(config: Config, *, limit: int = DEFAULT_SAMPLE) -> list[str]:
    """Primeras URLs de la cola sin captura previa y dentro del alcance."""
    known = captured_urls(config)
    selected: list[str] = []
    for url in queue_urls_file(config):
        if len(selected) >= limit:
            break
        if url in known or not is_capture_target(url, config):
            continue
        selected.append(url)
    return selected


# ------------------------------------------------------------ entorno temporal


def new_workdir(prefix: str = "corpus-live-") -> Path:
    """Crea una carpeta temporal única para una captura."""
    return Path(tempfile.mkdtemp(prefix=prefix)).resolve()


@contextmanager
def temp_config(config: Config, workdir: Path) -> Generator[Config]:
    """Apunta las capas a ``workdir`` con ``CORPUS_*_DIR`` y restaura al salir.

    ``Paths(root=workdir)`` es necesario además de las variables: Bronze y Gold
    guardan rutas relativas a ``Paths.root``.
    """
    base = Path(workdir).expanduser().resolve()
    previous = {name: os.environ.get(name) for name in TEMP_ENV}
    os.environ.update(
        {
            "CORPUS_RAW_DIR": str(base / "raw"),
            "CORPUS_PROCESSED_DIR": str(base / "processed"),
            "CORPUS_GOLD_DIR": str(base / "gold"),
        }
    )
    try:
        paths = Paths(root=base)
        temporal = Config(
            site=config.site,
            crawl=config.crawl,
            discovery=config.discovery,
            gold=config.gold,
            news=config.news,
            paths=paths,
        )
        paths.ensure()
        yield temporal
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# --------------------------------------------------------------- descubrir


def _robots_found(guard: RobotsGuard) -> bool:
    """``net.py`` no expone si encontró robots.txt: se lee la caché del guard."""
    return any(parser is not None for parser in guard._parsers.values())


def check_queue_robots(config: Config, client: HttpClient) -> RobotCheck:
    """Consulta robots.txt una sola vez y evalúa toda la cola sin descargar nada."""
    guard = RobotsGuard(client, config.site.user_agent)
    allowed: list[str] = []
    blocked: list[str] = []
    for url in queue_urls_file(config):
        (allowed if guard.allowed(url) else blocked).append(url)
    return RobotCheck(
        allowed=tuple(allowed),
        blocked=tuple(blocked),
        robots_found=_robots_found(guard),
    )


def audit_discovery(config: Config, client: HttpClient) -> DiscoveryAudit:
    """Repite el descubrimiento sin escribir: sitemaps, robots y descartes.

    Es una operación lenta (una petición por sitemap con la pausa de cortesía),
    por eso la app la ofrece como acción opcional y avisa del tiempo.
    """
    started = time.monotonic()
    result = discover(config, client, save=False)
    seconds = time.monotonic() - started
    counts = Counter(str(item.get("motivo") or "sin motivo") for item in result.skipped)
    return DiscoveryAudit(
        robots_found=result.robots_found,
        crawl_delay=result.crawl_delay,
        sitemaps_read=result.sitemaps_read,
        sitemaps_failed=result.sitemaps_failed,
        urls=len(result.urls),
        documents=len(result.documents),
        skipped=tuple(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))),
        seconds=round(seconds, 1),
    )


# -------------------------------------------------------------------- captura


#: Códigos que el sitio usa para rechazar la petición (WAF / rate limit).
BLOCKING_CODES: tuple[str, ...] = ("HTTP 403", "HTTP 429")


def _stop_message(failures: list[dict[str, str]]) -> str:
    """Mensaje de parada sin repetir el texto de ``BlockedError``.

    ``net.py`` sugiere probar una red residencial; la app no puede mostrar eso,
    así que un fallo de red o un bloqueo persistente se resume en un texto
    neutro y documentado.
    """
    errors = [str(item.get("error") or "") for item in failures]
    blocked = any(
        error in BLOCKING_CODES or not error.startswith(("HTTP ", "no es HTML")) for error in errors
    )
    if blocked:
        return BLOCKED_MESSAGE
    codes = sorted({error for error in errors if error.startswith("HTTP ")})
    detalle = ", ".join(codes) if codes else "contenido no HTML"
    return (
        f"Ninguna de las URLs elegidas se pudo capturar ({detalle}). "
        "Captura detenida; no se escribió nada fuera de la carpeta temporal."
    )


def run_capture(
    config: Config,
    urls: Sequence[str],
    *,
    workdir: Path | None = None,
    client: HttpClient | None = None,
    on_stage: Callable[[LiveStage], None] | None = None,
) -> LiveCapture:
    """Ejecuta Bronze -> Silver -> deduplicación -> Gold sobre unas pocas URLs.

    ``on_stage`` recibe cada etapa terminada para que la app actualice su
    ``st.status`` sin que este módulo dependa de Streamlit.
    """
    target = Path(workdir).expanduser().resolve() if workdir else new_workdir()
    target.mkdir(parents=True, exist_ok=True)
    chosen = tuple(dict.fromkeys(urls))
    stages: list[LiveStage] = []

    def emit(stage: LiveStage) -> None:
        """Guarda la etapa y avisa a la app."""
        stages.append(stage)
        if on_stage is not None:
            on_stage(stage)

    def stop(
        error: str,
        detail: str,
        *,
        allowed: tuple[str, ...] = (),
        blocked: tuple[str, ...] = (),
        robots_found: bool = False,
    ) -> LiveCapture:
        """Cierra la corrida con el error visible en la última etapa."""
        emit(LiveStage(key="stop", title="Captura detenida", detail=detail, state="error"))
        return LiveCapture(
            workdir=target,
            urls=chosen,
            allowed=allowed,
            blocked=blocked,
            robots_found=robots_found,
            stages=tuple(stages),
            error=error,
        )

    if not chosen:
        return stop("No hay URLs seleccionadas.", "Elige entre una y tres URLs de la cola.")
    with _LOCK, temp_config(config, target) as temporal:
        http = client if client is not None else HttpClient(temporal)
        try:
            guard = RobotsGuard(http, temporal.site.user_agent)
            allowed = tuple(url for url in chosen if guard.allowed(url))
            blocked = tuple(url for url in chosen if url not in allowed)
            found = _robots_found(guard)
            emit(
                LiveStage(
                    key="robots",
                    title="robots.txt",
                    detail=(
                        "robots.txt disponible: se aplican sus Disallow"
                        if found
                        else "robots.txt no disponible: se asume permitido"
                    ),
                    state="ok" if found else "warning",
                    metrics=(
                        Metric("URLs elegidas", str(len(chosen))),
                        Metric("Permitidas", str(len(allowed))),
                        Metric("Bloqueadas", str(len(blocked))),
                    ),
                )
            )
            if not allowed:
                return stop(
                    "robots.txt no permite capturar ninguna de las URLs elegidas.",
                    "robots.txt prohíbe las URLs elegidas: no se descargó nada.",
                    blocked=blocked,
                    robots_found=found,
                )

            stats = fetch_all(temporal, allowed, client=http)
            emit(
                LiveStage(
                    key="capture",
                    title="Capturar Bronze",
                    detail=(
                        f"{stats.ok} capturas nuevas, {stats.cached} en caché, "
                        f"{stats.failed} fallidas"
                    ),
                    state="ok" if stats.ok else "error",
                    metrics=(
                        Metric("OK", str(stats.ok)),
                        Metric("Fallidas", str(stats.failed)),
                        Metric("Tamaño", human_size(stats.bytes)),
                    ),
                )
            )
            if not stats.ok:
                return stop(
                    _stop_message(stats.failures),
                    "No se guardó ninguna captura.",
                    allowed=allowed,
                    blocked=blocked,
                    robots_found=found,
                )

            silver = extract_all(temporal)
            methods = Counter(str(row.get("metodo") or "n/d") for row in silver)
            emit(
                LiveStage(
                    key="clean",
                    title="Limpiar Silver",
                    detail=f"{len(silver)} páginas útiles de {stats.ok} capturadas",
                    state="ok" if silver else "error",
                    metrics=(
                        Metric("Páginas", str(len(silver))),
                        Metric(
                            "Caracteres",
                            f"{sum(int(row.get('chars') or 0) for row in silver):,}",
                        ),
                        Metric(
                            "Método",
                            ", ".join(f"{name} {count}" for name, count in methods.items())
                            or "n/d",
                        ),
                    ),
                )
            )
            if not silver:
                return stop(
                    "La extracción no dejó texto útil.",
                    "Las páginas capturadas quedaron vacías o demasiado cortas.",
                    allowed=allowed,
                    blocked=blocked,
                    robots_found=found,
                )

            boilerplate = find_boilerplate(
                (str(row.get("texto") or "").splitlines() for row in silver),
                min_docs=temporal.gold.boilerplate_min_docs,
                ratio=temporal.gold.boilerplate_ratio,
            )
            emit(
                LiveStage(
                    key="dedupe",
                    title="Deduplicar",
                    detail=(
                        f"{len(boilerplate)} líneas comunes retiradas "
                        f"(mínimo {temporal.gold.boilerplate_min_docs} documentos)"
                    ),
                    metrics=(
                        Metric("Líneas comunes", str(len(boilerplate))),
                        Metric("Documentos", str(len(silver))),
                    ),
                )
            )

            corpus = build_gold(temporal)
            blocks = find_repeated_blocks(load_gold_pages(temporal.paths.gold_markdown))
            emit(
                LiveStage(
                    key="gold",
                    title="Enriquecer Gold",
                    detail=f"{len(corpus)} documentos con frontmatter + corpus.jsonl",
                    state="ok" if corpus else "error",
                    metrics=(
                        Metric("Documentos", str(len(corpus))),
                        Metric(
                            "Tokens",
                            f"{sum(int(row.get('tokens') or 0) for row in corpus):,}",
                        ),
                        Metric("Duplicados descartados", str(len(silver) - len(corpus))),
                        Metric("Bloques repetidos", str(len(blocks))),
                    ),
                )
            )
            if not corpus:
                return stop(
                    "Gold quedó vacío: revisa el texto de Silver.",
                    "No se escribieron páginas Gold.",
                    allowed=allowed,
                    blocked=blocked,
                    robots_found=found,
                )

            page_path: Path | None = None
            frontmatter_text = ""
            frontmatter: dict[str, Any] = {}
            body = ""
            candidate = temporal.paths.root / str(corpus[0].get("archivo", ""))
            if candidate.exists():
                page_path = candidate
                text = candidate.read_text(encoding="utf-8", errors="replace")
                frontmatter_text, body = split_frontmatter(text)
                loaded = yaml.safe_load(frontmatter_text) or {}
                frontmatter = loaded if isinstance(loaded, dict) else {}
                body = body.strip()

            return LiveCapture(
                workdir=target,
                urls=chosen,
                allowed=allowed,
                blocked=blocked,
                robots_found=found,
                stages=tuple(stages),
                corpus=tuple(corpus),
                page_path=page_path,
                frontmatter_text=frontmatter_text.strip(),
                frontmatter=frontmatter,
                body_excerpt="\n".join(body.splitlines()[:40]),
            )
        finally:
            if client is None:
                http.close()
