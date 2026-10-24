"""Documentos (PDF): inventario desde el HTML, descarga y extraccion a Gold."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import yaml
from bs4 import BeautifulSoup

from .config import Config
from .net import HttpClient
from .utils import (
    estimate_tokens,
    page_slug,
    read_jsonl,
    utc_now,
    write_jsonl,
)

log = logging.getLogger(__name__)

DOCUMENT_EXTENSIONS = {".pdf"}
EXCLUDED_FRAGMENTS = ("/libre-inversion-digital/",)
MAX_BYTES_PER_DOC = 80 * 1024 * 1024

FINANCIERO = (
    "estado financiero",
    "estados financieros",
    "balance",
    "eeff",
    "informe de gestion",
    "informe gestion",
    "informe periodico",
    "resultados",
    "utilidades",
    "certificacion estados",
)
GOBIERNO = (
    "estatuto",
    "codigo de gobierno",
    "reglamento",
    "junta",
    "asamblea",
    "prospecto",
    "emision",
    "bonos",
    "calificacion",
    "revisor fiscal",
    "organigrama",
    "nombramiento",
    "conflicto de interes",
)
LEGAL = (
    "tratamiento de datos",
    "habeas",
    "terminos",
    "politica",
    "cookies",
    "ley ",
)
PRODUCTO = (
    "brochure",
    "tarifario",
    "tarifas",
    "guia",
    "contrato",
    "solicitud",
    "formato",
    "ficha",
    "ayudaventas",
)

GENERIC_TITLES = {
    "descargar",
    "ver anexo",
    "ver anexos",
    "conocela aqui",
    "conocelo aqui",
    "ver mas",
    "conocer mas",
    "ver todas las caracteristicas",
    "brochure",
    "documento",
    "descarga",
}


def _normalize_title(text: str) -> str:
    value = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in value if not unicodedata.combining(char)).strip()


def _canonical(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "", ""))


def _is_document(url: str) -> bool:
    parts = urlsplit(url)
    path = parts.path.lower()
    lowered = url.lower()
    if any(fragment in lowered for fragment in EXCLUDED_FRAGMENTS):
        return False
    if path.endswith(".pdf"):
        return True
    # Liferay sirve los adjuntos sin extension en /documents/d/...
    return "/documents/d/" in path and parts.netloc.endswith("bancodeoccidente.com.co")


def _title_from_url(url: str) -> str:
    name = unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    name = re.sub(r"[-_+]+", " ", name)
    title = unicodedata.normalize("NFC", " ".join(name.split()))[:120] or "Documento"
    return title[:1].upper() + title[1:]


def _clean_title(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())[:160]


def _classify(title: str, url: str) -> str:
    path = unquote(url).replace("_", " ").replace("-", " ")
    haystack = f"{title} {path}".lower()
    if any(word in haystack for word in FINANCIERO):
        return "financiero"
    if any(word in haystack for word in GOBIERNO):
        return "gobierno"
    if any(word in haystack for word in LEGAL):
        return "legal"
    if any(word in haystack for word in PRODUCTO):
        return "producto"
    return "otro"


def _year(text: str) -> int | None:
    years = [int(match) for match in re.findall(r"\b(20\d{2})\b", text)]
    if not years:
        return None
    plausible = [year for year in years if 2000 <= year <= 2030]
    return max(plausible) if plausible else None


def _priority(tipo: str, year: int | None) -> int:
    if year and year >= 2024 and tipo in {"financiero", "gobierno"}:
        return 1
    if (year and year >= 2022) or tipo in {"financiero", "gobierno"}:
        return 2
    return 3


def discover_documents(config: Config) -> list[dict]:
    """Inventaria todos los PDF enlazados desde el HTML Bronze."""
    base = config.site.base_url.rstrip("/") + "/"
    found: dict[str, dict] = {}
    for html_path in sorted(config.paths.raw_html.glob("*.html")):
        soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "lxml")
        for anchor in soup.select("a[href]"):
            href = anchor.get("href")
            if not isinstance(href, str) or not href:
                continue
            url = urljoin(base, href)
            if not _is_document(url):
                continue
            key = _canonical(url)
            if key in found:
                continue
            anchor_text = _clean_title(anchor.get_text(" ", strip=True))
            if len(anchor_text) > 3 and _normalize_title(anchor_text) not in GENERIC_TITLES:
                title = anchor_text
            else:
                title = _title_from_url(url)
            tipo = _classify(title, url)
            year = _year(f"{title} {unquote(url)}")
            found[key] = {
                "url": url,
                "url_key": key,
                "titulo": title,
                "tipo": tipo,
                "anio": year,
                "idioma": "en" if re.search(r"\b(ing|english)\b", title.lower()) else "es",
                "prioridad": _priority(tipo, year),
                "host": urlsplit(url).netloc,
            }

    rows = sorted(
        found.values(),
        key=lambda row: (row["prioridad"], -(row["anio"] or 0), row["titulo"].lower()),
    )
    config.paths.raw_documents.mkdir(parents=True, exist_ok=True)
    write_jsonl(config.paths.documents_urls, rows)
    return rows


def _fallback_url(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.netloc == "www.bancodeoccidente.com.co" and "/documents/d/" in parts.path:
        return url.replace(
            "www.bancodeoccidente.com.co", "portalpublico.bancodeoccidente.com.co", 1
        )
    return None


def fetch_documents(
    config: Config,
    *,
    limit: int | None = None,
    max_mb: float = 400,
    priority_max: int = 2,
    force: bool = False,
    delay: float | None = None,
    types: str | None = None,
) -> dict[str, int]:
    """Descarga los PDF seleccionados con cortesia y guarda el crudo."""
    rows = list(read_jsonl(config.paths.documents_urls))
    if not rows:
        rows = discover_documents(config)
    selected = [row for row in rows if row["prioridad"] <= priority_max]
    if types:
        wanted = {value.strip() for value in types.split(",") if value.strip()}
        selected = [row for row in selected if row["tipo"] in wanted]
    if limit:
        selected = selected[:limit]

    cached = {
        row.get("url_key"): row
        for row in read_jsonl(config.paths.documents_capture)
        if row.get("status") == 200
    }
    stats = {"ok": 0, "cached": 0, "failed": 0, "bytes": 0, "skipped": 0}
    config.paths.raw_documents.mkdir(parents=True, exist_ok=True)

    with (
        HttpClient(config, delay=delay) as client,
        config.paths.documents_capture.open("a", encoding="utf-8", newline="\n") as out,
    ):

        def save(record: dict) -> None:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()

        for index, row in enumerate(selected, start=1):
            key = row["url_key"]
            if key in cached and not force:
                stats["cached"] += 1
                continue

            url = row["url"]
            response = client.get(url)
            if not response.ok:
                alternative = _fallback_url(url)
                if alternative:
                    response = client.get(alternative)
            if not response.ok:
                stats["failed"] += 1
                save(
                    {
                        **row,
                        "status": response.status,
                        "error": response.error,
                        "fecha": utc_now(),
                    }
                )
                log.warning("[%d] %s -> %s", index, url, response.error)
                continue

            is_pdf = response.content.startswith(b"%PDF") or "pdf" in response.content_type
            if not is_pdf:
                stats["failed"] += 1
                save({**row, "status": response.status, "error": "no es PDF", "fecha": utc_now()})
                log.warning("[%d] %s -> no es PDF (%s)", index, url, response.content_type)
                continue
            if len(response.content) > MAX_BYTES_PER_DOC:
                stats["skipped"] += 1
                save({**row, "status": 200, "error": "excede 80 MB", "fecha": utc_now()})
                continue
            if stats["bytes"] + len(response.content) > max_mb * 1024 * 1024:
                stats["skipped"] += 1
                log.info("Tope de %.0f MB alcanzado; se detiene la descarga", max_mb)
                break

            digest = hashlib.sha256(response.content).hexdigest()
            path = config.paths.raw_documents / f"{digest[:16]}.pdf"
            path.write_bytes(response.content)
            record = {
                **row,
                "status": 200,
                "fecha": utc_now(),
                "bytes": len(response.content),
                "sha256": digest,
                "archivo": path.relative_to(config.paths.root).as_posix(),
                "error": None,
            }
            save(record)
            stats["ok"] += 1
            stats["bytes"] += len(response.content)
            log.info(
                "[%d] %s (%.1f MB)",
                index,
                row["titulo"][:60],
                len(response.content) / 1_048_576,
            )

    return stats


def _frontmatter(row: dict, config: Config, *, pages: int, text: str, digest: str) -> dict:
    return {
        "fuente": row["url"],
        "titulo": row["titulo"],
        "tipo": "pdf",
        "seccion": "datos" if row["tipo"] in {"financiero", "gobierno"} else "otros",
        "empresa": config.site.name,
        "fecha_captura": utc_now()[:10],
        "fecha_documento": row.get("anio"),
        "paginas": pages,
        "idioma": row.get("idioma", "es"),
        "tokens": estimate_tokens(text),
        "hash": digest[:8],
        "palabras": len(text.split()),
        "metodo": "pypdf",
        "categoria_documento": row["tipo"],
    }


def extract_documents(config: Config) -> list[dict]:
    """PDF -> Markdown Gold (una seccion por pagina) + indice documents.jsonl."""
    import pypdfium2 as pdfium

    logging.getLogger("pypdfium2").setLevel(logging.ERROR)
    captured = [
        row for row in read_jsonl(config.paths.documents_capture) if row.get("status") == 200
    ]
    inventory = {row["url_key"]: row for row in read_jsonl(config.paths.documents_urls)}
    previous = {
        row.get("sha256_pdf"): row
        for row in read_jsonl(config.paths.documents_index)
        if row.get("sha256_pdf")
    }
    config.paths.documents_gold.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    skipped = 0
    seen_hashes: set[str] = set()

    for row in captured:
        path = config.paths.root / str(row.get("archivo") or "")
        if not path.exists():
            continue
        info = inventory.get(row.get("url_key"), {})
        row = {
            **row,
            "titulo": info.get("titulo") or row.get("titulo") or path.stem,
            "tipo": info.get("tipo") or row.get("tipo") or "otro",
            "anio": info.get("anio") or row.get("anio"),
        }
        cached = previous.get(row.get("sha256"))
        sha = str(row.get("sha256") or "")
        if sha and sha in seen_hashes:
            skipped += 1
            continue
        if cached and (config.paths.root / str(cached.get("archivo", ""))).exists():
            seen_hashes.add(sha)
            index.append(
                {
                    **cached,
                    "titulo": row["titulo"],
                    "anio": row.get("anio"),
                    "categoria_documento": row["tipo"],
                }
            )
            continue
        try:
            pdf = pdfium.PdfDocument(str(path))
            try:
                total_pages = len(pdf)
                parts: list[str] = []
                for number in range(total_pages):
                    text = (pdf[number].get_textpage().get_text_range() or "").replace("\x00", " ")
                    text = re.sub(r"[ \t]+", " ", text)
                    text = re.sub(r"\n{3,}", "\n\n", text).strip()
                    if text:
                        parts.append(f"## Pagina {number + 1}\n\n{text}")
            finally:
                pdf.close()
        except Exception as exc:  # noqa: BLE001 - un PDF roto no detiene el lote
            log.warning("PDF ilegible %s: %s", path.name, exc)
            skipped += 1
            continue

        body = "\n\n".join(parts).strip()
        if len(body) < 500:
            log.warning("PDF sin texto util (escaneado?): %s", row["titulo"][:70])
            skipped += 1
            continue

        title = str(row.get("titulo") or path.stem)
        slug = page_slug(str(row.get("url") or ""), f"{title}-{row.get('anio') or ''}")
        digest = str(row.get("sha256") or "")
        meta = _frontmatter(row, config, pages=total_pages, text=body, digest=digest)
        document = (
            "---\n"
            + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=100).strip()
            + f"\n---\n\n# {title}\n\n{body}\n"
        )
        target = config.paths.documents_gold / f"{slug}.md"
        target.write_text(document, encoding="utf-8", newline="\n")
        index.append(
            {
                "id": slug,
                "titulo": title,
                "tipo": "pdf",
                "categoria_documento": row["tipo"],
                "anio": row.get("anio"),
                "fuente": row["url"],
                "archivo": target.relative_to(config.paths.root).as_posix(),
                "paginas": total_pages,
                "tokens": meta["tokens"],
                "idioma": meta["idioma"],
                "hash": meta["hash"],
                "sha256_pdf": row.get("sha256"),
            }
        )
        seen_hashes.add(sha)

    write_jsonl(config.paths.documents_index, index)
    keep = {str(row["archivo"]).rsplit("/", 1)[-1] for row in index}
    for stale in config.paths.documents_gold.glob("*.md"):
        if stale.name not in keep:
            stale.unlink()
    log.info("Documentos Gold: %d (%d omitidos)", len(index), skipped)
    return index
