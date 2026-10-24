"""Verifica la integridad del corpus (Bronze -> Silver -> Gold).

Uso:
    uv run python .opencode/skills/corpus-extraction/scripts/healthcheck.py

Sale con codigo 1 si alguna capa o el contrato de Gold esta roto.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
GOLD = ROOT / "data" / "gold"

REQUIRED_FRONTMATTER = {
    "fuente",
    "titulo",
    "seccion",
    "fecha_captura",
    "tokens",
    "hash",
}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    data = yaml.safe_load(parts[1]) or {}
    return data if isinstance(data, dict) else {}


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    urls = read_jsonl(RAW / "urls.jsonl")
    capture = read_jsonl(RAW / "capture.jsonl")
    bronze = sorted((RAW / "html").glob("*.html"))
    silver = sorted((PROCESSED / "markdown").glob("*.md"))
    corpus = read_jsonl(GOLD / "corpus.jsonl")
    pages = sorted((GOLD / "pages").glob("*.md"))

    ok_capture = [row for row in capture if row.get("status") == 200]
    failed_capture = [row for row in capture if row.get("status") != 200]

    print(f"Raiz        : {ROOT}")
    print(f"URLs        : {len(urls)}")
    print(
        f"Bronze      : {len(bronze)} archivos ({len(ok_capture)} capturas 200, {len(failed_capture)} fallidas)"
    )
    print(f"Silver      : {len(silver)} documentos")
    print(f"Gold        : {len(pages)} paginas, {len(corpus)} registros en corpus.jsonl")

    if not urls:
        errors.append("data/raw/urls.jsonl vacio: ejecuta 'make discover'")
    if not bronze:
        errors.append("data/raw/html sin archivos: ejecuta 'make fetch'")
    if not silver:
        errors.append("data/processed/markdown sin archivos: ejecuta 'make extract'")
    if not pages:
        errors.append("data/gold/pages sin archivos: ejecuta 'make gold'")
    if not corpus:
        errors.append("data/gold/corpus.jsonl vacio: ejecuta 'make gold'")

    ids = [row.get("id") for row in corpus]
    if len(ids) != len(set(ids)):
        errors.append("corpus.jsonl tiene ids duplicados")

    for row in corpus:
        archivo = row.get("archivo")
        if not archivo or not (ROOT / archivo).exists():
            errors.append(f"registro sin archivo valido: {archivo!r}")
            continue
        for key in ("fuente", "titulo", "seccion", "tokens"):
            if not row.get(key):
                errors.append(f"{archivo}: falta {key} en corpus.jsonl")

    for page in pages:
        meta = frontmatter(page)
        missing = REQUIRED_FRONTMATTER - set(meta)
        if missing:
            errors.append(f"{page.name}: frontmatter sin {sorted(missing)}")
            continue
        if not isinstance(meta.get("tokens"), int) or meta["tokens"] <= 0:
            errors.append(f"{page.name}: tokens invalido ({meta.get('tokens')!r})")
        if not str(meta.get("fuente", "")).startswith("http"):
            errors.append(f"{page.name}: fuente no es URL")

    if len(pages) > len(corpus):
        warnings.append("hay mas paginas Gold que registros en corpus.jsonl")

    print()
    for warning in warnings:
        print(f"AVISO  {warning}")
    if errors:
        for error in errors[:20]:
            print(f"ERROR  {error}")
        if len(errors) > 20:
            print(f"... y {len(errors) - 20} errores mas")
        print(f"\nRESULTADO: FALLA ({len(errors)} errores)")
        return 1

    print("RESULTADO: OK (capas y contrato de Gold consistentes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
