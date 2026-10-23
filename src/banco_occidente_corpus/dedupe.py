"""Deduplicacion del boilerplate que se repite en todas las paginas."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

_WS = re.compile(r"\s+")
_MD_NOISE = re.compile(r"^[\s|>*#\-_=~`]{3,}$")
_LINK_ONLY = re.compile(r"^\[[^\]]*\]\([^)]*\)$")


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
