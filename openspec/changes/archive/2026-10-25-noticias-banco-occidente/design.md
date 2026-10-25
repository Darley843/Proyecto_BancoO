# Design

## Context

Ver `proposal.md` para la motivación y `specs/corpus-noticias/spec.md` para los requisitos. El pipeline actual separa Bronze, Silver y Gold. `knowledge.py` segmenta `data/gold/pages/`, `data/gold/documents/` y `data/gold/videos/`; `stats.py` lee `corpus.jsonl`, `documents.jsonl` y `videos.jsonl`. El `makefile` ya incluye `docs`, `docs-finanzas`, `videos` y `media`, mientras que `make all`, `make gold` y `make deliver` siguen sin incluirlos. La página de inversionistas contiene la tabla “Información Relevante” con enlaces a anexos, pero `trafilatura` pierde esos enlaces y la página también incluye una tabla de accionistas con datos personales. En este checkout no existen `data/raw/` ni `data/processed/`; Gold ya contiene páginas, 190 PDFs y 32 videos versionados.

Restricciones:

- `uv` es el único gestor; no se añaden dependencias.
- No se modifican `make all`, `make gold` ni `make deliver`.
- El sitio puede responder `403` por WAF; no se evade.
- Toda función nueva o tocada lleva docstring en español y anotaciones de tipo.
- No se guardan claves ni tokens en comandos.

## Goals / Non-Goals

**Goals:**

- Añadir una ingesta reproducible de hechos relevantes oficiales y fichas de prensa externa.
- Publicar las fichas en Gold sin romper el contrato existente ni el chunker.
- Mantener la curaduría externa fuera de Gold para sobrevivir a `make clean`.
- Garantizar privacidad, trazabilidad, idempotencia y detención segura ante bloqueo.
- Dejar pruebas offline y documentación actualizada.

**Non-Goals:**

- Descargar artículos completos, imágenes, audio o PDFs de prensa.
- Descargar, copiar o re-extraer PDFs y anexos oficiales; si ya existen en `data/gold/documents/`, solo se enlazan.
- Extraer texto de los PDFs oficiales; solo se enlazan.
- Modificar `documents.py`, `videos.py` o `knowledge.py`.
- Automatizar la verificación humana de prensa externa.
- Cambiar la clasificación de la página de inversionistas existente.
- Poblar la capa Knowledge con entidades/hechos/relaciones de noticias.
- Modificar `make all`, `make gold`, `make deliver`, `make docs`, `make docs-finanzas`, `make videos` o `make media`.
- Evadir `403`, usar proxies o cambiar el User-Agent.

## Decisions

### 1. Fichas Gold en `data/gold/pages/` y fuente externa en `data/noticias/prensa.yaml`

Las fichas se renderizan como `noticia-*.md` o `hecho-*.md` dentro de `data/gold/pages/`. Así `build_chunks`, `healthcheck`, `stats` y el RAG las leen sin cambios. La curaduría externa vive en `data/noticias/prensa.yaml`, versionada y fuera de Gold, porque `make clean` borra Gold.

Alternativa descartada: `data/gold/noticias/` separado. Obligaría a cambiar el chunker, el healthcheck y el contrato de entrega.

### 2. Parseo selectivo de la tabla de hechos relevantes

El parser buscará la tabla cuyos encabezados sean `Fecha`, `Tema`, `Resumen` y `Anexo Descargable`. No usará el texto completo de la página. Así conserva el enlace “Ver Anexo” que `trafilatura` elimina y evita la tabla de accionistas.

Alternativa descartada: reutilizar el Markdown Gold de la página de inversionistas. Pierde los enlaces y arrastra datos personales.

### 3. Selección oficial acotada a 30-40 hitos materiales

Se incluyen absorciones, acuerdos materiales, créditos subordinados, emisiones y calificaciones, resultados, asambleas, junta, nombramientos, sostenibilidad, reconocimientos y productos. Se excluyen los avisos mensuales de dividendos. Si hay más de 40 hitos, se aplica un orden de relevancia documentado y se reporta el excedente.

Alternativa descartada: incluir los ~142 eventos 2025-2026. Añade ruido y diluye la señal para el RAG.

### 4. Prensa externa curada y verificada, no scrapeada

`data/noticias/prensa.yaml` contendrá 15-20 fichas. Cada una se marca `verificado` solo después de abrir el enlace original y confirmar que es el Banco de Occidente de Colombia y que la fecha corresponde. El resumen es propio. No se descarga el artículo.

Alternativa descartada: descubrimiento y resumen automáticos desde RSS. No garantiza identidad, fecha ni derechos de autor.

### 5. Comando y target separados

Se añade `uv run corpus noticias` y `make noticias`. No se tocan `make all`, `make gold`, `make deliver`, `make docs`, `make docs-finanzas`, `make videos` ni `make media`. La ingesta puede ejecutarse sola y es idempotente.

Alternativa descartada: encadenarla dentro de `make all`, `make gold`, `make docs` o `make media`. El usuario pidió explícitamente no modificar los targets existentes.

### 6. Nuevo módulo `news.py` con funciones pequeñas y tipadas

Funciones previstas:

- `parse_fecha_es(texto: str) -> date`
- `parse_hechos_relevantes(html: str, desde: date, hasta: date) -> list[dict]`
- `load_prensa(path: Path) -> list[dict]`
- `validar_ficha(row: dict) -> list[str]`
- `vincular_documento(anexo: str, indice: dict[str, dict]) -> dict | None`
- `deduplicar(rows: list[dict]) -> list[dict]`
- `render_ficha(row: dict, config: Config) -> tuple[dict, str]`
- `build_noticias(config: Config, *, desde: date, hasta: date, sin_red: bool = False) -> list[dict]`
- `merge_corpus(config: Config, rows: list[dict]) -> list[dict]`
- `write_noticias_index(config: Config, rows: list[dict]) -> str`

Todas con docstring en español y anotaciones. Se reutilizan `httpx`, `BeautifulSoup`, `yaml`, `hashlib` y los helpers de `utils.py`.

### 7. Idempotencia y actualización de `corpus.jsonl`

Antes de escribir, se eliminan las filas antiguas cuyo `id` empiece por `noticia-` o `hecho-`; luego se añaden las nuevas. Las filas del sitio se conservan. Si una ficha no cambió (mismo hash de título + resumen), no se reescribe y se conserva su `fecha_captura`. Así los diffs son estables y no se duplican registros.

### 8. Verificación y campos de ficha

Campos obligatorios: `id`, `tipo`, `origen`, `seccion`, `empresa`, `titulo`, `fecha_publicacion`, `fecha_captura`, `idioma`, `fuente`, `medio`, `resumen`, `temas`, `relevancia`, `estado`, `tokens`, `hash`, `palabras`, `metodo`. Opcionales: `evento`, `categoria`, `anexo`, `autor`, `documento_id`, `documento_archivo`, `documento_titulo`. La prensa externa solo se publica si `estado: verificado`. Los hechos oficiales usan el resumen oficial corto; la prensa externa usa resumen propio.

### 9. Privacidad y bloqueo

- Se ignora la tabla de accionistas por selección de encabezados.
- Se aplica un chequeo de PII a título y resumen antes de escribir.
- Ante `403` o bloqueo persistente, el comando termina con error y no escribe nuevas fichas oficiales. No cambia UA, no usa proxies y no aumenta la velocidad.
- `--sin-red` permite pruebas y regeneración desde Bronze o fixture.

### 10. Validación y pruebas sin red

Se añade un fixture HTML con una tabla mínima y un YAML de ejemplo. Las pruebas cubren fechas, filtro, selección de tabla, exclusión de accionistas, PII, deduplicación, idempotencia, contrato de frontmatter, enlace con documentos y aparición en chunks. `healthcheck.py` exigirá los campos de noticias y rechazará duplicados.

### 11. Enlace con documentos Gold existentes sin duplicar descargas

Antes de renderizar cada hecho relevante, `news.py` leerá `data/gold/documents.jsonl` y buscará el `anexo` por URL canónica: sin query ni fragmento, host en minúsculas y prueba del host alterno `www` ↔ `portalpublico`. Si encuentra coincidencia, añadirá `documento_id`, `documento_archivo` y `documento_titulo`, y un enlace relativo `../documents/<archivo>.md` en el cuerpo. Si no encuentra coincidencia, conservará `anexo` y seguirá sin error.

No se llama a `discover_documents`, `fetch_documents` ni `extract_documents`; el índice es de solo lectura. Esto evita duplicar PDFs y mantiene `data/gold/documents/` intacto. El índice actual tiene 190 PDFs y no incluye los anexos `ir-final-*`, así que el enlace será oportunista hasta que esos PDFs se inventaríen y extraigan por el flujo existente.

Alternativas descartadas: re-descargar el anexo desde la ficha (duplica PDFs y golpea el sitio) y copiar el PDF a una carpeta de noticias (rompe la separación de `documents.py`).

## Risks / Trade-offs

- **WAF `403`** → el comando se detiene, explica que el sitio bloqueó la petición, que la ingesta no evade el bloqueo y que se puede intentar más tarde; no se reintenta con identidades distintas.
- **Derechos de autor** → solo ficha mínima y resumen propio; nunca cuerpo, imágenes o PDFs de prensa.
- **Datos personales** → tabla de accionistas excluida y validación de PII antes de escribir.
- **Curaduría sesgada o incompleta** → criterios documentados, campo `evento` y revisión humana; el índice muestra conteos y fechas.
- **Pérdida de Gold en `make clean`** → la fuente externa queda en `data/noticias/prensa.yaml`; las fichas se regeneran con `make noticias`.
- **Diffs ruidosos** → hash estable y omisión de reescritura cuando el contenido no cambia.
- **Datos oficiales desactualizados** → se registra la fecha de captura y se lee Bronze; si no existe, se permite una única petición puntual o se salta con aviso en `--sin-red`.
- **Índice de documentos incompleto o desactualizado** → el enlace es oportunista; si no hay coincidencia se conserva `anexo` y no se falla. No se descargan PDFs para “completar” el índice.
- **Enlace roto a documento Gold** → `healthcheck.py` verifica que `documento_archivo` exista y que el `documento_id` esté en `documents.jsonl`.

## Migration Plan

1. Añadir rutas y configuración de noticias sin tocar los targets existentes.
2. Crear `data/noticias/prensa.yaml` con las fichas verificadas y su documentación.
3. Implementar `news.py`, el enlace de solo lectura con `documents.jsonl`, el subcomando y `make noticias`.
4. Añadir fixtures de tabla y de índice de documentos, pruebas y extensión de `healthcheck.py`.
5. Actualizar `CONSTITUTION.md`, `docs/ESTANDAR.md`, `docs/FUENTES.md`, `README.md` y `AGENTS.md` sin reescribir las secciones de PDF y videos.
6. Ejecutar `make fmt`, `make check`, `make demo` y pruebas de noticias con `--sin-red`.
7. Ejecutar la ingesta real y revisar `_NOTICIAS.md` y los enlaces a documentos.

Rollback: al ser un target y archivos nuevos, basta con retirar el target, el subcomando y las fichas generadas; `make all`, `make gold`, `make deliver`, `make docs`, `make docs-finanzas`, `make videos` y `make media` no cambian. `data/gold/documents/` y `data/gold/videos/` quedan intactos.

## Open Questions

Ninguna que cambie el alcance, el enfoque o el desglose de tareas. La selección final de los 30-40 hitos y las 15-20 fichas se hará durante la implementación con la revisión humana prevista.
