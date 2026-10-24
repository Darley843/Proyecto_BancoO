# Design

## Context

Ver `proposal.md` para la motivación y `specs/corpus-noticias/spec.md` para los requisitos. El pipeline actual ya separa Bronze, Silver y Gold; `knowledge.py` segmenta únicamente `data/gold/pages/*.md` y `stats.py` lee `data/gold/corpus.jsonl`. La página de inversionistas contiene la tabla “Información Relevante” con enlaces a anexos, pero `trafilatura` pierde esos enlaces y la página también incluye una tabla de accionistas con datos personales. En este checkout no existen `data/raw/` ni `data/processed/`; solo Gold está versionado.

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
- Extraer texto de los PDFs oficiales; solo se enlazan.
- Automatizar la verificación humana de prensa externa.
- Cambiar la clasificación de la página de inversionistas existente.
- Poblar la capa Knowledge con entidades/hechos/relaciones de noticias.
- Modificar `make all`, `make gold` o `make deliver`.
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

Se añade `uv run corpus noticias` y `make noticias`. No se tocan `make all`, `make gold` ni `make deliver`. La ingesta puede ejecutarse sola y es idempotente.

Alternativa descartada: encadenarla dentro de `make all` o `make gold`. El usuario pidió explícitamente no modificar esos targets.

### 6. Nuevo módulo `news.py` con funciones pequeñas y tipadas

Funciones previstas:

- `parse_fecha_es(texto: str) -> date`
- `parse_hechos_relevantes(html: str, desde: date, hasta: date) -> list[dict]`
- `load_prensa(path: Path) -> list[dict]`
- `validar_ficha(row: dict) -> list[str]`
- `deduplicar(rows: list[dict]) -> list[dict]`
- `render_ficha(row: dict, config: Config) -> tuple[dict, str]`
- `build_noticias(config: Config, *, desde: date, hasta: date, sin_red: bool = False) -> list[dict]`
- `merge_corpus(config: Config, rows: list[dict]) -> list[dict]`
- `write_noticias_index(config: Config, rows: list[dict]) -> str`

Todas con docstring en español y anotaciones. Se reutilizan `httpx`, `BeautifulSoup`, `yaml`, `hashlib` y los helpers de `utils.py`.

### 7. Idempotencia y actualización de `corpus.jsonl`

Antes de escribir, se eliminan las filas antiguas cuyo `id` empiece por `noticia-` o `hecho-`; luego se añaden las nuevas. Las filas del sitio se conservan. Si una ficha no cambió (mismo hash de título + resumen), no se reescribe y se conserva su `fecha_captura`. Así los diffs son estables y no se duplican registros.

### 8. Verificación y campos de ficha

Campos obligatorios: `id`, `tipo`, `origen`, `seccion`, `empresa`, `titulo`, `fecha_publicacion`, `fecha_captura`, `idioma`, `fuente`, `medio`, `resumen`, `temas`, `relevancia`, `estado`, `tokens`, `hash`, `palabras`, `metodo`. Opcionales: `evento`, `categoria`, `anexo`, `autor`. La prensa externa solo se publica si `estado: verificado`. Los hechos oficiales usan el resumen oficial corto; la prensa externa usa resumen propio.

### 9. Privacidad y bloqueo

- Se ignora la tabla de accionistas por selección de encabezados.
- Se aplica un chequeo de PII a título y resumen antes de escribir.
- Ante `403` o bloqueo persistente, el comando termina con error y no escribe nuevas fichas oficiales. No cambia UA, no usa proxies y no aumenta la velocidad.
- `--sin-red` permite pruebas y regeneración desde Bronze o fixture.

### 10. Validación y pruebas sin red

Se añade un fixture HTML con una tabla mínima y un YAML de ejemplo. Las pruebas cubren fechas, filtro, selección de tabla, exclusión de accionistas, PII, deduplicación, idempotencia, contrato de frontmatter y aparición en chunks. `healthcheck.py` exigirá los campos de noticias y rechazará duplicados.

## Risks / Trade-offs

- **WAF `403`** → el comando se detiene y explica que se necesita red residencial colombiana; no se reintenta con identidades distintas.
- **Derechos de autor** → solo ficha mínima y resumen propio; nunca cuerpo, imágenes o PDFs de prensa.
- **Datos personales** → tabla de accionistas excluida y validación de PII antes de escribir.
- **Curaduría sesgada o incompleta** → criterios documentados, campo `evento` y revisión humana; el índice muestra conteos y fechas.
- **Pérdida de Gold en `make clean`** → la fuente externa queda en `data/noticias/prensa.yaml`; las fichas se regeneran con `make noticias`.
- **Diffs ruidosos** → hash estable y omisión de reescritura cuando el contenido no cambia.
- **Datos oficiales desactualizados** → se registra la fecha de captura y se lee Bronze; si no existe, se permite una única petición puntual o se salta con aviso en `--sin-red`.

## Migration Plan

1. Añadir rutas y configuración de noticias sin tocar los targets existentes.
2. Crear `data/noticias/prensa.yaml` con las fichas verificadas y su documentación.
3. Implementar `news.py`, el subcomando y `make noticias`.
4. Añadir fixture y pruebas; extender `healthcheck.py`.
5. Actualizar `CONSTITUTION.md`, `docs/ESTANDAR.md`, `docs/FUENTES.md`, `README.md` y `AGENTS.md`.
6. Ejecutar `make fmt`, `make check`, `make demo` y pruebas de noticias con `--sin-red`.
7. Ejecutar la ingesta real desde red residencial colombiana y revisar `_NOTICIAS.md`.

Rollback: al ser un target y archivos nuevos, basta con retirar el target, el subcomando y las fichas generadas; `make all`, `make gold` y `make deliver` no cambian.

## Open Questions

Ninguna que cambie el alcance, el enfoque o el desglose de tareas. La selección final de los 30-40 hitos y las 15-20 fichas se hará durante la implementación con la revisión humana prevista.
