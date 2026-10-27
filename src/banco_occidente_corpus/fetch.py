"""Capa Bronze: descarga y guarda el crudo, tal cual lo devolvio la web."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .net import BlockedError, HttpClient
from .utils import human_size, read_jsonl, sha256_text, utc_now

log = logging.getLogger(__name__)


@dataclass(slots=True)
class FetchStats:
    """Contadores de una corrida de captura (Bronze)."""

    ok: int = 0
    cached: int = 0
    failed: int = 0
    bytes: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)


def _raw_path(config: Config, url: str) -> Path:
    """Nombre estable y reproducible: hash de la URL."""
    return config.paths.raw_html / f"{sha256_text(url)[:16]}.html"


def load_capture(config: Config) -> dict[str, dict]:
    """Registros ya capturados, indexados por URL."""
    return {row["url"]: row for row in read_jsonl(config.paths.capture_file) if row.get("url")}


#: Tipos de contenido que la capa Bronze acepta como pagina HTML.
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


def is_html(content_type: str) -> bool:
    """True si el ``Content-Type`` es HTML (o no vino, como en pruebas locales)."""
    tipo = content_type.split(";", 1)[0].strip().lower()
    return not tipo or tipo in HTML_CONTENT_TYPES


def save_bronze(config: Config, url: str, html: str, *, content_type: str = "text/html") -> dict:
    """Guarda el HTML crudo y devuelve el registro de captura.

    Falla con ``ValueError`` si ``content_type`` no es HTML: Bronze HTML solo
    guarda paginas, los PDF van por ``documents.py``.
    """
    if not is_html(content_type):
        raise ValueError(f"{url} no es HTML ({content_type}); no se guarda en Bronze")
    path = _raw_path(config, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8", newline="")
    payload = html.encode("utf-8", errors="replace")
    return {
        "url": url,
        "status": 200,
        "fecha_captura": utc_now(),
        "content_type": content_type.split(";", 1)[0].strip().lower() or "text/html",
        "bytes": len(payload),
        "sha256": sha256_text(html),
        "archivo": path.relative_to(config.paths.root).as_posix(),
        "error": None,
    }


def fetch_all(
    config: Config,
    urls: Iterable[str],
    *,
    force: bool = False,
    delay: float | None = None,
) -> FetchStats:
    """Recorre las URLs y llena data/raw. Reanudable: no repite lo ya bajado.

    Cada captura se anexa a ``capture.jsonl`` en el momento: si el proceso se
    interrumpe, lo ya descargado queda registrado y la siguiente ejecucion
    continua donde quedo.
    """
    stats = FetchStats()
    cached = load_capture(config)
    config.paths.capture_file.parent.mkdir(parents=True, exist_ok=True)

    client = HttpClient(config, delay=delay)

    try:
        with config.paths.capture_file.open("a", encoding="utf-8", newline="\n") as log_file:

            def save(record: dict) -> None:
                """Anexa un registro de captura y lo escribe de inmediato."""
                log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                log_file.flush()

            for index, url in enumerate(urls, start=1):
                previous = cached.get(url)
                if previous and previous.get("status") == 200 and not force:
                    stats.cached += 1
                    continue

                try:
                    response = client.get(url)
                except BlockedError as exc:
                    log.error("%s", exc)
                    stats.failed += 1
                    stats.failures.append({"url": url, "error": str(exc)})
                    save(
                        {
                            "url": url,
                            "status": 0,
                            "fecha_captura": utc_now(),
                            "bytes": 0,
                            "sha256": None,
                            "archivo": None,
                            "error": str(exc),
                        }
                    )
                    break  # si bloquean una URL, bloquean todas: no insistir

                if not response.ok:
                    stats.failed += 1
                    stats.failures.append({"url": url, "error": response.error or ""})
                    save(
                        {
                            "url": url,
                            "status": response.status,
                            "fecha_captura": utc_now(),
                            "bytes": 0,
                            "sha256": None,
                            "archivo": None,
                            "error": response.error,
                        }
                    )
                    log.warning("[%d] %s -> %s", index, url, response.error)
                    continue

                if not is_html(response.content_type):
                    stats.failed += 1
                    error = f"no es HTML ({response.content_type})"
                    stats.failures.append({"url": url, "error": error})
                    save(
                        {
                            "url": url,
                            "status": response.status,
                            "fecha_captura": utc_now(),
                            "bytes": 0,
                            "sha256": None,
                            "archivo": None,
                            "error": error,
                        }
                    )
                    log.warning("[%d] %s -> %s", index, url, error)
                    continue

                record = save_bronze(config, url, response.text, content_type=response.content_type)
                save(record)
                stats.ok += 1
                stats.bytes += record["bytes"]
                log.info(
                    "[%d] %s (%s, %.2fs)",
                    index,
                    url,
                    human_size(record["bytes"]),
                    response.elapsed,
                )
    finally:
        client.close()

    return stats


def iter_bronze(config: Config, *, only_ok: bool = True) -> Iterator[dict]:
    """Itera los registros utilizables leyendo un HTML a la vez (memoria acotada)."""
    for row in load_capture(config).values():
        if only_ok and row.get("status") != 200:
            continue
        path = row.get("archivo")
        if not path:
            continue
        file_path = config.paths.root / path
        if not file_path.exists():
            continue
        row = dict(row)
        row["html"] = file_path.read_text(encoding="utf-8", errors="replace")
        yield row


def load_bronze(config: Config, *, only_ok: bool = True) -> list[dict]:
    """Registros de captura utilizables, con su HTML ya leido."""
    return sorted(iter_bronze(config, only_ok=only_ok), key=lambda r: r["url"])


def pending_urls(config: Config, urls: Iterable[str]) -> list[str]:
    """URLs que aun no tienen captura satisfactoria."""
    captured = {u for u, r in load_capture(config).items() if r.get("status") == 200}
    return [url for url in urls if url not in captured]
