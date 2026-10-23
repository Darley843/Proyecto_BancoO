# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx[http2]", "trafilatura", "pyyaml"]
# ///
"""Scraper autocontenido (PEP 723) del sitio de Banco de Occidente.

    uv run scripts/scrape_empresa.py --limit 50

Hace lo minimo: sitemap -> HTML -> Markdown con frontmatter. El proyecto
completo (capas Bronze/Silver/Gold, deduplicacion, indice) vive en src/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import yaml
from trafilatura import extract

BASE = "https://www.bancodeoccidente.com.co"
SITEMAP = f"{BASE}/sitemap.xml"
UA = "TAAML-bot/1.0 (curso UAO; uso academico; contacto: darley.idarraga@uao.edu.co)"
OUT = Path("data/gold/pages")


def localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def leer_sitemap(client: httpx.Client, url: str, depth: int = 0, max_depth: int = 2):
    """Devuelve las URLs de un sitemap, expandiendo indices."""
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        print(f"  ! {url} -> {exc}")
        return []
    if response.status_code != 200:
        print(f"  ! {url} -> HTTP {response.status_code}")
        return []
    try:
        root = ET.fromstring(response.text.strip())
    except ET.ParseError:
        return []

    locs = [
        el.text.strip()
        for el in root.iter()
        if localname(el.tag) == "loc" and el.text and el.text.strip()
    ]
    if localname(root.tag) == "sitemapindex":
        if depth >= max_depth:
            return []
        urls: list[str] = []
        for child in locs:
            urls.extend(leer_sitemap(client, child, depth + 1, max_depth))
        return urls
    return locs


def normalizar(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))


def capturar(client: httpx.Client, url: str, delay: float) -> bool:
    time.sleep(delay)
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        print(f"  ! {url} -> {exc}")
        return False
    if response.status_code != 200:
        print(f"  ! {url} -> HTTP {response.status_code}")
        return False

    texto = extract(
        response.text,
        url=url,
        output_format="markdown",
        include_tables=True,
        favor_recall=True,
    )
    if not texto or len(texto.strip()) < 200:
        return False

    OUT.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode()).hexdigest()[:8]
    slug = (urlsplit(url).path.rstrip("/").split("/")[-1] or "home")[:50]
    destino = OUT / f"{slug}-{digest}.md"

    meta = {
        "fuente": url,
        "titulo": (texto.strip().splitlines()[0].lstrip("# ").strip()[:120]),
        "seccion": "identidad" if "quienes" in url else "otros",
        "empresa": "Banco de Occidente",
        "fecha_captura": time.strftime("%Y-%m-%d"),
        "idioma": "es",
        "tokens": max(1, len(texto) // 4),
        "hash": hashlib.sha256(texto.encode()).hexdigest()[:8],
    }
    cabecera = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    destino.write_text(f"---\n{cabecera}\n---\n\n{texto.strip()}\n", encoding="utf-8")
    print(f"  + {destino}  ({meta['tokens']:,} tokens)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--sitemap", default=SITEMAP)
    args = parser.parse_args()

    headers = {"User-Agent": UA, "Accept-Language": "es-CO,es;q=0.9"}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=30, http2=True) as client:
        print(f"Leyendo {args.sitemap} ...")
        encontradas = leer_sitemap(client, args.sitemap)
        vistos: set[str] = set()
        urls: list[str] = []
        for raw in encontradas:
            url = normalizar(urljoin(BASE + "/", raw))
            if url in vistos or not url.startswith(BASE):
                continue
            vistos.add(url)
            if any(x in url.lower() for x in ("portaltransaccional", "/wps/", ".pdf", ".jpg")):
                continue
            urls.append(url)
        urls = urls[: args.limit]

        print(f"{len(urls)} URLs a capturar (de {len(encontradas)} en el sitemap)")
        ok = 0
        for url in urls:
            ok += capturar(client, url, args.delay)

    print(f"\nListo: {ok}/{len(urls)} paginas en {OUT}")
    print(json.dumps({"capturadas": ok, "intentadas": len(urls)}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
