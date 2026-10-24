"""Capa Knowledge: segmentacion de Gold y validacion del conocimiento semantico.

Gold sigue siendo la fuente de verdad. Esta capa deriva entidades, hechos y
relaciones con evidencia textual, para que el agente y el RAG puedan citar.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from .config import PROJECT_ROOT, Config
from .utils import estimate_tokens, read_jsonl, sha256_text, utc_now, write_jsonl

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
MARKDOWN_NOISE = re.compile(r"[*_`#>|]+")
PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")),
    ("celular", re.compile(r"(?<!\d)(?:\+57\s?)?3\d{2}[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")),
    ("documento", re.compile(r"(?<!\d)\d{1,3}(?:\.\d{3}){2,3}(?:-\d)?(?!\d)")),
]
MIN_CHUNK_CHARS = 40


def _norm(text: str) -> str:
    """Normaliza para comparar citas: sin markdown, sin espacios extra."""
    return " ".join(MARKDOWN_NOISE.sub(" ", text).split()).casefold()


def load_page(path: Path) -> tuple[dict, str]:
    """Devuelve (frontmatter, cuerpo) de una pagina Gold."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    return (meta if isinstance(meta, dict) else {}), parts[2].lstrip("\n")


def split_page(page_id: str, meta: dict, body: str) -> list[dict]:
    """Trocea una pagina por encabezados; cada chunk queda autocontenido."""
    chunks: list[dict] = []
    heading = ""
    level = 0
    buffer: list[str] = []

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if len(text) < MIN_CHUNK_CHARS:
            return
        digest = sha256_text(f"{page_id}|{heading}|{text}")
        chunks.append(
            {
                "chunk_id": f"chk:{digest[:12]}",
                "page_id": page_id,
                "url": meta.get("fuente", ""),
                "section": meta.get("seccion", "otros"),
                "heading": heading,
                "level": level,
                "text": text,
                "tokens": estimate_tokens(text),
                "hash": digest,
            }
        )

    for line in body.splitlines():
        match = HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            heading = match.group(2).strip()
            buffer = []
        else:
            buffer.append(line)
    flush()
    return chunks


def build_chunks(config: Config) -> list[dict]:
    """Gold -> data/knowledge/chunks.jsonl (determinista, sin red)."""
    rows: list[dict] = []
    for path in sorted(config.paths.gold_markdown.glob("*.md")):
        meta, body = load_page(path)
        rows.extend(split_page(path.stem, meta, body))
    config.paths.knowledge.mkdir(parents=True, exist_ok=True)
    write_jsonl(config.paths.knowledge_chunks, rows)
    return rows


def _all_chunks(config: Config) -> dict[tuple[str, str], dict]:
    """Chunks en memoria: permite validar sin depender de haber corrido 'chunks'."""
    index: dict[tuple[str, str], dict] = {}
    for path in sorted(config.paths.gold_markdown.glob("*.md")):
        meta, body = load_page(path)
        for chunk in split_page(path.stem, meta, body):
            index[(chunk["page_id"], chunk["chunk_id"])] = chunk
    return index


def load_knowledge(config: Config) -> dict[str, list[dict]]:
    """Lee las tres colecciones de la capa Knowledge."""
    return {
        "entities": list(read_jsonl(config.paths.knowledge_entities)),
        "facts": list(read_jsonl(config.paths.knowledge_facts)),
        "relations": list(read_jsonl(config.paths.knowledge_relations)),
    }


def _schema_validators() -> dict[str, Any]:
    """Un validador por tipo: los errores salen concretos, no como 'oneOf'."""
    schema_path = PROJECT_ROOT / "config" / "knowledge.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return {
        kind: Draft202012Validator(
            {
                "$schema": schema["$schema"],
                "$ref": f"#/$defs/{kind}",
                "$defs": schema["$defs"],
            },
            format_checker=FormatChecker(),
        )
        for kind in ("entity", "fact", "relation")
    }


def _pii(text: str) -> list[str]:
    found: list[str] = []
    for label, pattern in PII_PATTERNS:
        if pattern.search(text):
            found.append(label)
    return found


def validate_knowledge(
    config: Config, records: dict[str, list[dict]] | None = None
) -> tuple[list[str], list[str]]:
    """Valida esquema, evidencia y referencias. Devuelve (errores, avisos)."""
    records = records or load_knowledge(config)
    errors: list[str] = []
    warnings: list[str] = []
    validators = _schema_validators()
    chunks = _all_chunks(config)

    pages: dict[str, dict] = {}
    for path in sorted(config.paths.gold_markdown.glob("*.md")):
        meta, _ = load_page(path)
        pages[path.stem] = meta

    for collection, rows in records.items():
        seen_ids: set[str] = set()
        for position, row in enumerate(rows, start=1):
            label = f"{collection}[{position}]"
            if not isinstance(row, dict):
                errors.append(f"{label}: no es un objeto JSON")
                continue
            record_id = str(row.get("id", ""))
            if record_id in seen_ids:
                errors.append(f"{label}: id duplicado {record_id}")
            seen_ids.add(record_id)

            validator = validators.get(str(row.get("record_type")))
            if validator is None:
                errors.append(f"{label}: record_type invalido ({row.get('record_type')!r})")
                continue
            for error in validator.iter_errors(row):
                path = "/".join(str(part) for part in error.path)
                errors.append(f"{label} ({path or 'raiz'}): {error.message}")

            evidence = row.get("evidence")
            if not isinstance(evidence, dict):
                continue
            page_id = str(evidence.get("page_id", ""))
            chunk_id = str(evidence.get("chunk_id", ""))
            quote = str(evidence.get("quote", ""))

            meta = pages.get(page_id)
            if meta is None:
                errors.append(f"{label}: page_id inexistente ({page_id})")
                continue
            if evidence.get("url") != meta.get("fuente"):
                errors.append(f"{label}: la url no coincide con la pagina {page_id}")

            chunk = chunks.get((page_id, chunk_id))
            if chunk is None:
                errors.append(f"{label}: chunk_id inexistente para {page_id} ({chunk_id})")
            elif _norm(quote) not in _norm(f"{chunk['heading']} {chunk['text']}"):
                errors.append(f"{label}: la cita no aparece en el chunk {chunk_id}")

            section = evidence.get("section")
            if section != meta.get("seccion"):
                warnings.append(
                    f"{label}: seccion '{section}' distinta a la de la pagina "
                    f"'{meta.get('seccion')}'"
                )

            for label_pii in _pii(f"{quote} {row.get('value', '')}"):
                errors.append(f"{label}: posible dato personal ({label_pii})")

    entities = {str(row.get("id")) for row in records.get("entities", [])}
    for fact in records.get("facts", []):
        if fact.get("entity_id") not in entities:
            errors.append(f"{fact.get('id')}: entity_id no existe ({fact.get('entity_id')})")
    for relation in records.get("relations", []):
        for key in ("subject_id", "object_id"):
            if relation.get(key) not in entities:
                errors.append(f"{relation.get('id')}: {key} no existe ({relation.get(key)})")

    fact_signatures: Counter[tuple[str, str, str]] = Counter()
    for fact in records.get("facts", []):
        signature = (
            str(fact.get("entity_id")),
            str(fact.get("predicate")),
            _norm(str(fact.get("value", ""))),
        )
        fact_signatures[signature] += 1
    for signature, count in fact_signatures.items():
        if count > 1:
            errors.append(f"hecho duplicado {signature} ({count} veces)")

    relation_signatures: Counter[tuple[str, str, str]] = Counter()
    for relation in records.get("relations", []):
        signature = (
            str(relation.get("subject_id")),
            str(relation.get("predicate")),
            str(relation.get("object_id")),
        )
        relation_signatures[signature] += 1
    for signature, count in relation_signatures.items():
        if count > 1:
            errors.append(f"relacion duplicada {signature} ({count} veces)")

    if not records.get("entities") and (records.get("facts") or records.get("relations")):
        errors.append("hay hechos/relaciones sin entidades: crea primero las entidades")

    return errors, warnings


def _stats(records: dict[str, list[dict]]) -> dict[str, Any]:
    entities = records.get("entities", [])
    facts = records.get("facts", [])
    relations = records.get("relations", [])
    confidences = [float(row.get("confidence", 0)) for row in entities + facts + relations]
    return {
        "entity_types": Counter(str(row.get("type")) for row in entities),
        "predicates": Counter(str(row.get("predicate")) for row in facts),
        "sections": Counter(
            str(row.get("evidence", {}).get("section")) for row in facts + relations
        ),
        "pending": sum(1 for row in facts + relations if row.get("review") == "pending"),
        "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0,
    }


def build_knowledge_index(config: Config) -> str:
    """Escribe data/knowledge/_INDICE.md con el estado de la capa Knowledge."""
    records = load_knowledge(config)
    stats = _stats(records)
    entities = records.get("entities", [])
    facts = records.get("facts", [])
    relations = records.get("relations", [])

    lines = [
        "# Conocimiento semantico",
        "",
        f"**Fuente:** {config.site.name} — `data/gold/`  ",
        f"**Entidades:** {len(entities)}  ",
        f"**Hechos:** {len(facts)}  ",
        f"**Relaciones:** {len(relations)}  ",
        f"**Pendientes de revision:** {stats['pending']}  ",
        f"**Confianza media:** {stats['avg_confidence']}",
        "",
    ]

    if not (entities or facts or relations):
        lines += [
            "## Sin registros todavia",
            "",
            "La skill `semantic-extraction` define como poblarlos. Pasos:",
            "",
            "```bash",
            "make chunks     # segmenta Gold por encabezados",
            "# extraer con el agente y validar",
            "make knowledge  # valida esquema y evidencia",
            "```",
            "",
        ]
    else:
        lines += ["## Entidades por tipo", "", "| Tipo | Entidades |", "|---|---:|"]
        for kind, count in stats["entity_types"].most_common():
            lines.append(f"| `{kind}` | {count} |")
        lines += ["", "## Hechos por predicado", "", "| Predicado | Hechos |", "|---|---:|"]
        for predicate, count in stats["predicates"].most_common():
            lines.append(f"| `{predicate}` | {count} |")
        lines += ["", "## Evidencia por seccion", "", "| Seccion | Registros |", "|---|---:|"]
        for section, count in stats["sections"].most_common():
            lines.append(f"| `{section}` | {count} |")
        lines.append("")

    content = "\n".join(lines)
    config.paths.knowledge.mkdir(parents=True, exist_ok=True)
    config.paths.knowledge_index.write_text(content, encoding="utf-8", newline="\n")
    return content


def _draft_collections(rows: list[dict]) -> dict[str, list[dict]]:
    return {
        "entities": [row for row in rows if row.get("record_type") == "entity"],
        "facts": [row for row in rows if row.get("record_type") == "fact"],
        "relations": [row for row in rows if row.get("record_type") == "relation"],
    }


def write_knowledge(config: Config, records: dict[str, list[dict]]) -> None:
    """Escribe las tres colecciones (entities, facts, relations)."""
    config.paths.knowledge.mkdir(parents=True, exist_ok=True)
    write_jsonl(config.paths.knowledge_entities, records.get("entities", []))
    write_jsonl(config.paths.knowledge_facts, records.get("facts", []))
    write_jsonl(config.paths.knowledge_relations, records.get("relations", []))


def merge_draft(config: Config, path: Path) -> tuple[dict[str, list[dict]], list[str], list[str]]:
    """Valida un borrador contra el conocimiento actual y devuelve la fusion.

    El borrador es un JSONL con cualquier mezcla de entidades, hechos y
    relaciones. La fusion es por `id`: el borrador pisa el registro existente
    con el mismo id, y los ids nuevos se agregan.
    """
    draft = _draft_collections(list(read_jsonl(path)))
    current = load_knowledge(config)
    merged: dict[str, dict[str, dict]] = {
        kind: {str(row.get("id")): row for row in current[kind]}
        for kind in ("entities", "facts", "relations")
    }
    for kind, rows in draft.items():
        for row in rows:
            merged[kind][str(row.get("id"))] = row
    records = {kind: list(by_id.values()) for kind, by_id in merged.items()}
    errors, warnings = validate_knowledge(config, records)
    return records, errors, warnings


def validate_file(config: Config, path: Path) -> tuple[list[str], list[str]]:
    """Valida un JSONL candidato fusionado con data/knowledge (sin escribir)."""
    _, errors, warnings = merge_draft(config, path)
    return errors, warnings


def now_date() -> str:
    return utc_now()[:10]
