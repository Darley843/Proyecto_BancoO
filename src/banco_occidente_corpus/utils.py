"""Utilidades compartidas: hashing, slugs, JSONL y conteo de tokens."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def utc_now() -> str:
    """Fecha ISO-8601 en UTC, sin microsegundos."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sha256_text(text: str) -> str:
    """Hash SHA-256 del texto en UTF-8, usado como huella estable de contenido."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def short_hash(text: str, length: int = 8) -> str:
    """Prefijo del SHA-256, para identificadores cortos y estables."""
    return sha256_text(text)[:length]


def slugify(text: str, max_length: int = 60) -> str:
    """Convierte texto libre en un slug ASCII seguro para nombres de archivo."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_STRIP.sub("-", ascii_text).strip("-")
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or "sin-titulo"


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Lee un JSONL ignorando lineas corruptas (el crudo no siempre es perfecto)."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]], *, overwrite: bool = True) -> int:
    """Escribe registros en JSONL (una linea = un registro)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "a"
    count = 0
    with path.open(mode, encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """Anexa un registro a un JSONL creando el directorio si hace falta."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()


def estimate_tokens(text: str) -> int:
    """Conteo de tokens: exacto con tiktoken si esta instalado, si no ~4 chars/token.

    La regla de 4 caracteres es la aproximacion estandar para texto en espanol;
    sirve para presupuestar contexto, no para facturar.
    """
    if not text:
        return 0
    try:  # pragma: no cover - depende de un extra opcional
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text, disallowed_special=()))
    except Exception:
        return max(1, round(len(text) / 4))


def count_words(text: str) -> int:
    """Cuenta palabras (secuencias de letras o digitos) sin depender del idioma."""
    return len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))


def human_size(num_bytes: int) -> str:
    """Formatea bytes en B/KB/MB/GB con un decimal, para los logs."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def is_excluded_url(url: str, patterns: Iterable[str]) -> bool:
    """Indica si la URL contiene alguno de los patrones de exclusion del sitio."""
    lowered = url.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def page_slug(url: str, title: str = "") -> str:
    """Nombre de archivo estable y legible para una pagina."""
    from urllib.parse import urlsplit

    path = urlsplit(url).path.rstrip("/")
    segment = path.split("/")[-1] if path else "home"
    stem = slugify(title) if len(title.strip()) >= 4 else slugify(segment)
    if len(stem) < 4:
        stem = slugify(segment)
    return f"{stem[:60]}-{short_hash(url, 6)}"
