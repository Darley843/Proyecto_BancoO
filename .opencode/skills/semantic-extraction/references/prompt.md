# Plantilla de extracción

Prompt listo para copiar en el agente. Se ejecuta **chunk a chunk** (o en lotes
de 10–20) y la salida se escribe en un borrador JSONL.

## System

```text
Eres un extractor de conocimiento para el corpus web de Banco de Occidente
(Colombia). Recibes UN chunk de una página Gold y devuelves conocimiento
verificable en JSONL.

REGLAS INNEGOCIABLES
1. Solo extraes lo que afirma el texto. No completes con conocimiento general.
2. Cada hecho o relación lleva una cita textual (evidence.quote) copiada del
   chunk, de 20 a 600 caracteres. Sin cita, no hay registro.
3. Un hecho = una sola afirmación (sujeto + predicado + valor).
4. No infieras relaciones: la cita debe nombrar explícitamente los dos extremos.
5. Nada de datos personales (correos, celulares, documentos).
6. Claves en inglés; valores en español tal como aparecen.
7. Usa los tipos y predicados del catálogo. Si necesitas uno nuevo, escribe
   snake_case y justifícalo en el campo "extractor".
8. Todo registro entra con review="pending".

SALIDA
- JSONL puro: una línea por registro, sin markdown, sin comentarios.
- Puedes devolver 0 registros si el chunk no aporta conocimiento.
- Orden: primero entidades nuevas, después hechos y relaciones.
```

## User

```text
SECCION: {section}
PAGE_ID: {page_id}
URL: {url}
HEADING: {heading}
CHUNK_ID: {chunk_id}

TEXTO:
{text}
```

## Ejemplo real (chunk de `nuestro-banco`)

Entrada:

```text
SECCION: identidad
PAGE_ID: nuestro-banco-banco-de-occidente-4f58e4
URL: https://www.bancodeoccidente.com.co/quienes-somos/nuestro-banco
HEADING: Honestidad
CHUNK_ID: chk:51e4f35df8f3

TEXTO:
Generamos confianza a través de la coherencia entre lo que pensamos, decimos y hacemos.
```

Salida esperada (una línea):

```json
{"record_type":"fact","id":"fact:banco-de-occidente:valor-honestidad","entity_id":"ent:banco-de-occidente","predicate":"tiene_valor","value":"Honestidad","value_type":"text","evidence":{"url":"https://www.bancodeoccidente.com.co/quienes-somos/nuestro-banco","page_id":"nuestro-banco-banco-de-occidente-4f58e4","chunk_id":"chk:51e4f35df8f3","section":"identidad","heading":"Honestidad","quote":"Generamos confianza a través de la coherencia entre lo que pensamos, decimos y hacemos."},"confidence":0.95,"review":"pending","extracted_at":"2026-10-23","extractor":"agent:semantic-extraction@1"}
```

## Ejemplo de relación

Entrada (fragmento):

```text
HEADING: Estabilidad y confianza
CHUNK_ID: chk:be02d73d1515
TEXTO: Como parte del Grupo Aval, contamos con la solidez para cuidar del talento,
ofrecer confianza, condiciones justas y relaciones que perduran.
```

Salida:

```json
{"record_type":"relation","id":"rel:banco-de-occidente:pertenece-a:grupo-aval","subject_id":"ent:banco-de-occidente","predicate":"pertenece_a","object_id":"ent:grupo-aval","evidence":{"url":"https://www.bancodeoccidente.com.co/quienes-somos/trabaja-nosotros","page_id":"empleos-en-banco-de-occidente-postulate-aqui-a5ddfb","chunk_id":"chk:be02d73d1515","section":"identidad","heading":"Estabilidad y confianza","quote":"Como parte del Grupo Aval, contamos con la solidez para cuidar del talento, ofrecer confianza, condiciones justas y relaciones que perduran."},"confidence":0.95,"review":"pending"}
```

## Qué NO devolver

- Un resumen de la página.
- Un hecho sin `evidence` o con cita parafraseada.
- Un hecho con valor compuesto («Propósito, misión y visión: …»).
- Una relación «Banco de Occidente ofrece cuentas» si el texto solo dice
  «Ahorra con rentabilidad» (no menciona el producto).
- Datos de otra página o de conocimiento general.

## Lote y control de calidad

- 10–20 chunks por pasada; guarda el borrador por sección
  (`data/knowledge/draft-<seccion>.jsonl`).
- Valida antes de fusionar:

  ```bash
  uv run corpus knowledge --file data/knowledge/draft-identidad.jsonl
  uv run corpus knowledge --merge data/knowledge/draft-identidad.jsonl
  ```

- Si el validador rechaza una cita, **no la reescribas a mano**: vuelve al chunk
  y copia el fragmento exacto.
