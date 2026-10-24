---
name: Extracción semántica del corpus
description: Convierte las páginas Gold de Banco de Occidente en conocimiento verificable (entidades, hechos y relaciones) con citas textuales, IDs estables y validación. Úsala para poblar o revisar la capa Knowledge que alimenta al agente y al RAG.
---

# Extracción semántica del corpus

La captura (`corpus-extraction`) produce texto. Esta skill produce **conocimiento**:
afirmaciones atómicas que el agente puede citar y el RAG puede filtrar.

## Qué produce

```text
data/knowledge/
├── entities.jsonl     # entidades canónicas (organización, producto, sede…)
├── facts.jsonl        # hechos atómicos con cita textual y fuente
├── relations.jsonl    # relaciones entre entidades, también con cita
├── chunks.jsonl       # derivado de Gold (no se versiona)
└── _INDICE.md         # conteos y estado de revisión
```

El contrato está en `config/knowledge.schema.json` y se explica en
`references/schema.md`. **Gold sigue siendo la fuente de verdad**; Knowledge es
una capa derivada y reproducible.

## Cuándo usarla

- Poblar la capa Knowledge desde `data/gold/pages/`.
- Revisar hechos dudosos o citas que no coinciden con la página.
- Añadir una sección nueva al conocimiento (identidad, oferta, datos…).
- Preparar el contexto estructurado del agente del Módulo 3.

No la uses para: scrapear (eso es `corpus-extraction`), resumir páginas completas
o inventar datos que no estén en Gold.

## Precondiciones

```bash
make health     # capas y contrato de Gold en verde
make chunks     # segmenta Gold por encabezados -> data/knowledge/chunks.jsonl
```

## Flujo (por sección, nunca todo de golpe)

1. **Elige el alcance.** Una sección (`identidad`, `oferta`, `datos`…), un
   documento PDF o un conjunto de 10–20 chunks. El corpus tiene ~14.300 chunks
   (páginas, PDFs y videos): no caben en un prompt y la calidad cae.
2. **Lee los chunks** con su `chunk_id`, `page_id`, `url`, `section` y `heading`.
   El chunk es la unidad de evidencia: no cites texto de otro chunk.
3. **Normaliza entidades primero.** Crea o reutiliza la entidad (`ent:...`)
   antes de los hechos. Si el nombre ya existe con otra variante, añádela a
   `aliases`; no crees otra entidad.
4. **Extrae hechos atómicos.** Un hecho = un sujeto + un predicado + un valor.
   Si una frase tiene dos afirmaciones, son dos hechos.
5. **Cita literal.** `evidence.quote` debe ser un fragmento **textual** del
   chunk (el validador lo comprueba; ignora markdown, mayúsculas y espacios).
   Sin cita no hay hecho.
6. **Escribe el borrador** en `data/knowledge/draft-<seccion>.jsonl` (una línea
   JSON por registro).
7. **Valida y fusiona**:

   ```bash
   uv run corpus knowledge --file data/knowledge/draft-identidad.jsonl
   uv run corpus knowledge --merge data/knowledge/draft-identidad.jsonl
   ```

   El primer comando no escribe nada; el segundo valida contra lo existente y
   hace *upsert* por `id`. Si hay errores, corrige el borrador y repite.

## Reglas de extracción

1. **Cero invención.** Todo valor debe estar respaldado por una cita del chunk.
   Si el dato no está, no se extrae.
2. **Atomicidad.** `value` es una sola afirmación (≤ 280 caracteres). Nada de
   párrafos con tres ideas.
3. **Sin inferencia entre páginas.** Una relación solo se registra si la cita la
   afirma explícitamente. «Banco de Occidente es del Grupo Aval» sí; «por tanto
   comparte clientes con AV Villas» no.
4. **Una entidad, un id.** `ent:cuenta-de-ahorros`, no `ent:cuenta-ahorros` y
   `ent:cuenta_de_ahorros`.
5. **Datos personales fuera.** Nada de correos, celulares o documentos. El
   validador rechaza el registro.
6. **Idioma.** Claves en inglés, valores en español tal como aparecen.
7. **Vigencia.** Si el dato tiene fecha o versión, va en `qualifiers`
   (`{"vigencia": "2026"}`); si no, se omite.
8. **Revisión.** Todo entra con `review: "pending"`. Solo una persona pasa a
   `approved`.

## Confianza

| Rango | Cuándo | Acción |
|---|---|---|
| 0.95–1.00 | Dato explícito, sin ambigüedad, en el chunk | `approved` posible |
| 0.80–0.94 | Explícito pero requiere normalizar el valor | Revisar |
| 0.60–0.79 | Tabla, encabezado ambiguo o dato parcial | `pending` obligatorio |
| < 0.60 | Inferencia o duda | **No extraer** |

## Tipos y predicados

Catálogo en `references/taxonomy.md`. Si necesitas un predicado nuevo, usa
`snake_case` y documéntalo allí en el mismo commit.

## Errores comunes

| Error | Causa | Solución |
|---|---|---|
| `la cita no aparece en el chunk` | Cita parafraseada o de otro chunk | Copiar el texto exacto del chunk |
| `chunk_id inexistente` | Chunks regenerados tras editar Gold | `make chunks` y recalcular |
| `entity_id no existe` | Hecho antes que entidad | Crear la entidad primero |
| `hecho duplicado` | Mismo sujeto/predicado/valor con otro id | Reutilizar el id existente |
| `posible dato personal` | Correo, celular o documento en la cita | Reescribir el hecho sin el dato |
| `is not valid under any of the given schemas` | Falta un campo obligatorio | Ver `references/schema.md` |

## Criterios de aceptación

- `uv run corpus knowledge` termina en `Knowledge OK`.
- Cada hecho/relación tiene `evidence.url`, `page_id`, `chunk_id` y `quote`.
- `make check` en verde.
- `_INDICE.md` actualizado con conteos y pendientes de revisión.

## Referencias

- `references/schema.md` — campos, IDs y ejemplos completos.
- `references/taxonomy.md` — tipos de entidad y catálogo de predicados.
- `references/prompt.md` — plantilla de extracción para el agente.
- `templates/` — un registro de ejemplo por tipo (válido).
- `config/knowledge.schema.json` — esquema JSON formal.
- `src/banco_occidente_corpus/knowledge.py` — segmentación y validación.
