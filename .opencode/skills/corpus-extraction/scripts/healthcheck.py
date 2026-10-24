"""Verifica la integridad del corpus (Bronze -> Silver -> Gold).

Uso:
    uv run python .opencode/skills/corpus-extraction/scripts/healthcheck.py

Sale con codigo 1 si alguna capa o el contrato de Gold esta roto.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from banco_occidente_corpus.config import load_config
from banco_occidente_corpus.knowledge import load_knowledge, validate_knowledge

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

NEWS_PREFIXES = ("noticia-", "hecho-")

REQUIRED_NEWS_FRONTMATTER = {
    "fecha_publicacion",
    "tipo",
    "origen",
    "medio",
    "resumen",
}


def read_jsonl(path: Path) -> list[dict]:
    """Lee un JSONL y devuelve sus registros, ignorando lineas vacias."""
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def frontmatter(path: Path) -> dict:
    """Extrae el frontmatter YAML de una pagina Gold."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    data = yaml.safe_load(parts[1]) or {}
    return data if isinstance(data, dict) else {}


def is_news_page(path: Path) -> bool:
    """Indica si un archivo Gold es una ficha de noticias o de hechos."""
    return path.stem.startswith(NEWS_PREFIXES)


def validate_noticias(
    pages: list[Path],
    documents_dir: Path,
    documents: list[dict],
) -> list[str]:
    """Valida el contrato de las fichas de noticias y sus enlaces a documentos.

    Exige fecha de publicacion, tipo, origen, medio y resumen; detecta ids
    repetidos y comprueba que ``documento_archivo`` exista cuando la ficha
    declara ``documento_id`` y que ese id figure en ``documents.jsonl``.
    Devuelve una lista de errores legibles; vacia significa contrato valido.
    """
    errors: list[str] = []
    ids: dict[str, str] = {}
    documentos_por_id = {str(row.get("id") or ""): row for row in documents}

    for page in pages:
        if not is_news_page(page):
            continue
        meta = frontmatter(page)
        faltantes = [
            campo
            for campo in sorted(REQUIRED_NEWS_FRONTMATTER)
            if not str(meta.get(campo) or "").strip()
        ]
        if faltantes:
            errors.append(f"{page.name}: ficha sin {faltantes}")
            continue

        identificador = str(meta.get("id") or page.stem).strip()
        if identificador in ids:
            errors.append(
                f"{page.name}: id duplicado '{identificador}' (ya en {ids[identificador]})"
            )
        else:
            ids[identificador] = page.name

        documento_id = str(meta.get("documento_id") or "").strip()
        archivo = str(meta.get("documento_archivo") or "").strip()
        if documento_id:
            if not archivo:
                errors.append(f"{page.name}: documento_id sin documento_archivo")
            elif not (documents_dir / Path(archivo).name).exists():
                errors.append(f"{page.name}: documento_archivo no existe ({archivo})")
            if documento_id not in documentos_por_id:
                errors.append(f"{page.name}: documento_id ausente de documents.jsonl")

    return errors


def main() -> int:
    """Ejecuta el diagnostico y devuelve 0 si el corpus es consistente."""
    errors: list[str] = []
    warnings: list[str] = []

    urls = read_jsonl(RAW / "urls.jsonl")
    capture = read_jsonl(RAW / "capture.jsonl")
    bronze = sorted((RAW / "html").glob("*.html"))
    silver = sorted((PROCESSED / "markdown").glob("*.md"))
    corpus = read_jsonl(GOLD / "corpus.jsonl")
    pages = sorted((GOLD / "pages").glob("*.md"))
    documents = read_jsonl(GOLD / "documents.jsonl")
    videos = read_jsonl(GOLD / "videos.jsonl")

    ok_capture = [row for row in capture if row.get("status") == 200]
    failed_capture = [row for row in capture if row.get("status") != 200]

    print(f"Raiz        : {ROOT}")
    print(f"URLs        : {len(urls)}")
    print(
        f"Bronze      : {len(bronze)} archivos ({len(ok_capture)} capturas 200, {len(failed_capture)} fallidas)"
    )
    print(f"Silver      : {len(silver)} documentos")
    print(f"Gold        : {len(pages)} paginas, {len(corpus)} registros en corpus.jsonl")
    print(f"Docs PDF    : {len(documents)} documentos")
    print(f"Videos      : {len(videos)} transcripciones")

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

    for row in documents:
        if not (ROOT / str(row.get("archivo", ""))).exists():
            errors.append(f"documento sin archivo: {row.get('id')}")
    for row in videos:
        if not (ROOT / str(row.get("archivo", ""))).exists():
            errors.append(f"video sin archivo: {row.get('id')}")

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

    errors.extend(validate_noticias(pages, GOLD / "documents", documents))

    if len(pages) > len(corpus):
        warnings.append("hay mas paginas Gold que registros en corpus.jsonl")

    config = load_config()
    knowledge = load_knowledge(config)
    knowledge_errors, knowledge_warnings = validate_knowledge(config, knowledge)
    print(
        "Knowledge   : "
        f"{len(knowledge['entities'])} entidades, "
        f"{len(knowledge['facts'])} hechos, "
        f"{len(knowledge['relations'])} relaciones"
    )
    errors.extend(knowledge_errors)
    warnings.extend(knowledge_warnings)

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

    print("RESULTADO: OK (capas, contrato de Gold y conocimiento consistentes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
