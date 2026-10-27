"""Pruebas de la capa Knowledge: chunks, esquema, evidencia y referencias."""

from __future__ import annotations

from pathlib import Path

from banco_occidente_corpus.config import Config, Paths
from banco_occidente_corpus.knowledge import (
    build_chunks,
    build_knowledge_index,
    split_page,
    validate_knowledge,
)

URL = "https://www.bancodeoccidente.com.co/quienes-somos/nuestro-banco"
PAGE_ID = "nuestro-banco-demo"

GOLD = f"""---
fuente: {URL}
titulo: Nuestro Banco
seccion: identidad
fecha_captura: 2026-10-23
---

## Banco de Occidente
Nuestro proposito

Hacer realidad el desarrollo de las personas, el crecimiento de los negocios
y la transformacion del pais.

### Honestidad

Generamos confianza a traves de la coherencia entre lo que pensamos, decimos
y hacemos.

### Contacto

Escribe a cliente@example.com para recibir ayuda.
"""


def make_config(tmp_path: Path) -> Config:
    return Config(
        paths=Paths(
            root=tmp_path,
            raw=tmp_path / "data/raw",
            processed=tmp_path / "data/processed",
            gold=tmp_path / "data/gold",
            knowledge=tmp_path / "data/knowledge",
        )
    )


def write_gold(config: Config) -> None:
    config.paths.gold_markdown.mkdir(parents=True, exist_ok=True)
    (config.paths.gold_markdown / f"{PAGE_ID}.md").write_text(GOLD, encoding="utf-8")


def chunk_id_for(config: Config, heading: str) -> str:
    for chunk in build_chunks(config):
        if chunk["heading"] == heading:
            return chunk["chunk_id"]
    raise AssertionError(f"no hay chunk con heading {heading}")


def entity() -> dict:
    return {
        "record_type": "entity",
        "id": "ent:banco-de-occidente",
        "type": "organizacion",
        "name": "Banco de Occidente",
        "aliases": [],
        "attributes": {},
        "sources": [URL],
        "confidence": 0.98,
    }


def fact(chunk_id: str, *, quote: str, value: str = "Honestidad", id_: str = "f1") -> dict:
    return {
        "record_type": "fact",
        "id": f"fact:banco-de-occidente:{id_}",
        "entity_id": "ent:banco-de-occidente",
        "predicate": "tiene_valor",
        "value": value,
        "value_type": "text",
        "evidence": {
            "url": URL,
            "page_id": PAGE_ID,
            "chunk_id": chunk_id,
            "section": "identidad",
            "heading": "Honestidad",
            "quote": quote,
        },
        "confidence": 0.95,
        "review": "pending",
        "extracted_at": "2026-10-23",
        "extractor": "test",
    }


def test_split_page_por_encabezados():
    body = GOLD.split("---", 2)[2]
    chunks = split_page(PAGE_ID, {"fuente": URL, "seccion": "identidad"}, body)
    headings = [chunk["heading"] for chunk in chunks]
    assert "Banco de Occidente" in headings
    assert "Honestidad" in headings
    assert "Contacto" in headings
    assert all(chunk["chunk_id"].startswith("chk:") for chunk in chunks)


def test_chunk_ids_son_estables(tmp_path: Path):
    config = make_config(tmp_path)
    write_gold(config)
    first = [chunk["chunk_id"] for chunk in build_chunks(config)]
    second = [chunk["chunk_id"] for chunk in build_chunks(config)]
    assert first == second


def test_chunks_web_solo_incluye_paginas(tmp_path: Path) -> None:
    """chunks_web.jsonl (versionado) toma solo las paginas web, no PDF ni videos."""
    import json

    config = make_config(tmp_path)
    write_gold(config)
    config.paths.documents_gold.mkdir(parents=True, exist_ok=True)
    (config.paths.documents_gold / "informe.md").write_text(
        "---\nfuente: https://x.co/informe.pdf\nseccion: datos\n---\n## Informe\n"
        + "Texto largo del informe anual del banco. " * 3,
        encoding="utf-8",
    )

    todos = build_chunks(config)
    web = [
        json.loads(linea)
        for linea in config.paths.knowledge_chunks_web.read_text(encoding="utf-8").splitlines()
    ]

    assert {c["page_id"] for c in todos} >= {"informe", PAGE_ID}
    assert {c["page_id"] for c in web} == {PAGE_ID}


def test_validacion_acepta_registro_con_evidencia(tmp_path: Path):
    config = make_config(tmp_path)
    write_gold(config)
    chunk_id = chunk_id_for(config, "Honestidad")
    records = {
        "entities": [entity()],
        "facts": [
            fact(
                chunk_id,
                quote="Generamos confianza a traves de la coherencia entre lo que pensamos, decimos y hacemos.",
            )
        ],
        "relations": [],
    }
    errors, _ = validate_knowledge(config, records)
    assert errors == []


def test_validacion_rechaza_cita_inventada(tmp_path: Path):
    config = make_config(tmp_path)
    write_gold(config)
    chunk_id = chunk_id_for(config, "Honestidad")
    records = {
        "entities": [entity()],
        "facts": [fact(chunk_id, quote="Somos el mejor banco del universo conocido.")],
        "relations": [],
    }
    errors, _ = validate_knowledge(config, records)
    assert any("cita no aparece" in error for error in errors)


def test_validacion_rechaza_chunk_inexistente(tmp_path: Path):
    config = make_config(tmp_path)
    write_gold(config)
    records = {
        "entities": [entity()],
        "facts": [fact("chk:000000000000", quote="Generamos confianza a traves de la coherencia.")],
        "relations": [],
    }
    errors, _ = validate_knowledge(config, records)
    assert any("chunk_id inexistente" in error for error in errors)


def test_validacion_rechaza_dato_personal(tmp_path: Path):
    config = make_config(tmp_path)
    write_gold(config)
    chunk_id = chunk_id_for(config, "Contacto")
    records = {
        "entities": [entity()],
        "facts": [
            fact(
                chunk_id,
                quote="Escribe a cliente@example.com para recibir ayuda.",
                value="cliente@example.com",
                id_="contacto",
            )
        ],
        "relations": [],
    }
    errors, _ = validate_knowledge(config, records)
    assert any("dato personal" in error for error in errors)


def test_validacion_rechaza_hecho_duplicado(tmp_path: Path):
    config = make_config(tmp_path)
    write_gold(config)
    chunk_id = chunk_id_for(config, "Honestidad")
    quote = (
        "Generamos confianza a traves de la coherencia entre lo que pensamos, decimos y hacemos."
    )
    records = {
        "entities": [entity()],
        "facts": [
            fact(chunk_id, quote=quote, id_="uno"),
            fact(chunk_id, quote=quote, id_="dos"),
        ],
        "relations": [],
    }
    errors, _ = validate_knowledge(config, records)
    assert any("hecho duplicado" in error for error in errors)


def test_validacion_rechaza_entidad_inexistente(tmp_path: Path):
    config = make_config(tmp_path)
    write_gold(config)
    chunk_id = chunk_id_for(config, "Honestidad")
    records = {
        "entities": [],
        "facts": [
            fact(
                chunk_id,
                quote="Generamos confianza a traves de la coherencia entre lo que pensamos, decimos y hacemos.",
            )
        ],
        "relations": [],
    }
    errors, _ = validate_knowledge(config, records)
    assert any("sin entidades" in error for error in errors)


def test_indice_lista_conteos(tmp_path: Path):
    config = make_config(tmp_path)
    write_gold(config)
    chunk_id = chunk_id_for(config, "Honestidad")
    config.paths.knowledge.mkdir(parents=True, exist_ok=True)
    from banco_occidente_corpus.utils import write_jsonl

    write_jsonl(config.paths.knowledge_entities, [entity()])
    write_jsonl(
        config.paths.knowledge_facts,
        [
            fact(
                chunk_id,
                quote="Generamos confianza a traves de la coherencia entre lo que pensamos, decimos y hacemos.",
            )
        ],
    )
    write_jsonl(config.paths.knowledge_relations, [])
    content = build_knowledge_index(config)
    assert "Entidades:** 1" in content
    assert "Hechos:** 1" in content
