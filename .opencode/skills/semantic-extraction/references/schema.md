# Esquema de conocimiento

Contrato formal: `config/knowledge.schema.json` (JSON Schema 2020-12).
Validador: `uv run corpus knowledge`.

## Archivos

| Archivo | Contenido | Versionado |
|---|---|---|
| `data/knowledge/entities.jsonl` | Entidades canónicas | Sí |
| `data/knowledge/facts.jsonl` | Hechos atómicos | Sí |
| `data/knowledge/relations.jsonl` | Relaciones entre entidades | Sí |
| `data/knowledge/chunks.jsonl` | Segmentos de Gold | No (derivado) |
| `data/knowledge/_INDICE.md` | Conteos y revisión | Sí |

## Evidencia (`evidence`)

Todo hecho y relación la incluye. Es lo que hace verificable el conocimiento.

| Campo | Tipo | Obligatorio | Regla |
|---|---|:---:|---|
| `url` | string | Sí | Debe ser la `fuente` exacta de la página Gold |
| `page_id` | string | Sí | Nombre del archivo Gold sin `.md` |
| `chunk_id` | string | Sí | `chk:` + 12 hex; debe existir para esa página |
| `section` | enum | Sí | Debe coincidir con la sección de la página |
| `heading` | string | No | Encabezado del chunk |
| `quote` | string | Sí | 20–600 caracteres, textual dentro del chunk |

La cita se compara **sin markdown, sin distinguir mayúsculas y colapsando
espacios**. Aun así, copia el texto tal cual: es la prueba que verá el revisor.

## Entidad

```json
{
  "record_type": "entity",
  "id": "ent:banco-de-occidente",
  "type": "organizacion",
  "name": "Banco de Occidente",
  "aliases": ["Banco de Occidente S.A."],
  "attributes": {},
  "sources": ["https://www.bancodeoccidente.com.co/quienes-somos/nuestro-banco"],
  "confidence": 0.98
}
```

| Campo | Tipo | Obligatorio | Regla |
|---|---|:---:|---|
| `id` | string | Sí | `ent:<slug>`; único |
| `type` | enum | Sí | Ver `taxonomy.md` |
| `name` | string | Sí | 2–120 caracteres |
| `aliases` | string[] | Sí | Variantes y siglas; sin duplicados |
| `attributes` | object | No | Solo string/number/boolean |
| `sources` | string[] | Sí | Al menos una URL del sitio |
| `confidence` | number | Sí | 0–1 |

## Hecho

```json
{
  "record_type": "fact",
  "id": "fact:banco-de-occidente:tiene-proposito",
  "entity_id": "ent:banco-de-occidente",
  "predicate": "tiene_proposito",
  "value": "Hacer realidad el desarrollo de las personas, el crecimiento de los negocios y la transformación del país.",
  "value_type": "text",
  "evidence": {
    "url": "https://www.bancodeoccidente.com.co/quienes-somos/nuestro-banco",
    "page_id": "nuestro-banco-banco-de-occidente-4f58e4",
    "chunk_id": "chk:128cb3d27d99",
    "section": "identidad",
    "heading": "Banco de Occidente",
    "quote": "Hacer realidad el desarrollo de las personas, el crecimiento de los negocios y la transformación del país."
  },
  "confidence": 0.98,
  "review": "pending",
  "extracted_at": "2026-10-23",
  "extractor": "agent:semantic-extraction@1"
}
```

| Campo | Tipo | Obligatorio | Regla |
|---|---|:---:|---|
| `id` | string | Sí | `fact:<entidad>:<predicado-corto>` |
| `entity_id` | string | Sí | Debe existir en `entities.jsonl` |
| `predicate` | string | Sí | `snake_case` del catálogo |
| `value` | string/number/bool | Sí | Una sola afirmación |
| `value_type` | enum | Sí | `text`, `number`, `date`, `boolean`, `currency`, `percentage` |
| `qualifiers` | object | No | Vigencia, moneda, segmento… |
| `review` | enum | Sí | `pending`, `approved`, `rejected` |
| `extracted_at` | date | Sí | `YYYY-MM-DD` |
| `extractor` | string | Sí | Identifica el agente/versión |

## Relación

```json
{
  "record_type": "relation",
  "id": "rel:banco-de-occidente:pertenece-a:grupo-aval",
  "subject_id": "ent:banco-de-occidente",
  "predicate": "pertenece_a",
  "object_id": "ent:grupo-aval",
  "evidence": {
    "url": "https://www.bancodeoccidente.com.co/quienes-somos/trabaja-nosotros",
    "page_id": "empleos-en-banco-de-occidente-postulate-aqui-a5ddfb",
    "chunk_id": "chk:be02d73d1515",
    "section": "identidad",
    "heading": "Estabilidad y confianza",
    "quote": "Como parte del Grupo Aval, contamos con la solidez para cuidar del talento, ofrecer confianza, condiciones justas y relaciones que perduran."
  },
  "confidence": 0.95,
  "review": "pending"
}
```

Regla de oro: si la cita no dice explícitamente que A se relaciona con B, no hay
relación. Las relaciones transitivas (A→B→C) no se infieren.

## Convenciones de IDs

- Minúsculas, sin acentos, sin artículos ni preposiciones: `ent:cuenta-de-ahorros`.
- Entidad: nombre canónico en singular (`ent:grupo-aval`).
- Hecho: entidad + predicado corto (`fact:banco-de-occidente:tiene-mision`).
- Relación: sujeto + predicado + objeto (`rel:...:ofrece:...`).
- Si el hecho se repite en otra página, **reutiliza el id** y actualiza la
  evidencia o añade el dato en `qualifiers`; no crees otro hecho.

## Qué valida el comando

1. Esquema JSON (campos, tipos, patrones, enums, confianza 0–1).
2. `page_id` existe en Gold y `url` coincide con su `fuente`.
3. `chunk_id` existe para esa página.
4. La cita aparece dentro del chunk.
5. `entity_id`, `subject_id` y `object_id` existen.
6. No hay ids ni hechos/relaciones duplicados.
7. No hay correos, celulares ni documentos en la cita o el valor.
8. Avisa si la `section` de la evidencia no coincide con la de la página.
