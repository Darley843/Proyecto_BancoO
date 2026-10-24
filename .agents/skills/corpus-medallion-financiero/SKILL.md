---
name: corpus-medallion-financiero
description: Construye un corpus Medallion (bronze, silver, gold) listo para RAG a partir de páginas web públicas de entidades financieras como bancos, aseguradoras o fondos. Úsala siempre que haya que capturar, limpiar o estructurar contenido web de una entidad financiera para un asistente con RAG, aunque el pedido no mencione Medallion, por ejemplo productos, tasas y tarifas, requisitos, defensor del consumidor o políticas de datos.
license: MIT
---

# Corpus Medallion financiero

Convierte páginas públicas de una entidad financiera en un corpus Markdown citable y
reproducible. Está pensada para entidades vigiladas: las tasas cambian, los textos legales
se repiten en todas las páginas y nunca se toca información de clientes.

## Límites (revísalos antes de escribir código)

1. Solo páginas públicas. Nunca banca en línea, páginas con login, simuladores, formularios
   de solicitud ni PQRS: ahí hay datos personales (en Colombia, Ley 1581 de 2012).
2. Consulta robots.txt antes de cada URL y respeta su Crawl-delay; si no lo declara, espera
   al menos 1 segundo entre peticiones.
3. Identifica el cliente con un User-Agent propio del proyecto y usa siempre un timeout.
4. No evadas protecciones anti-bot ni captchas. Si una página las tiene, queda fuera del alcance.
5. Usa semillas explícitas y acotadas en la configuración; no rastrees el sitio completo.

## Capas

- **Bronze** (`data/raw/`): HTML crudo tal como llegó, con su URL y fecha de captura.
  Permite reprocesar sin volver a la web.
- **Silver** (`data/processed/`): Markdown limpio. La extracción recibe HTML ya descargado
  y nunca hace peticiones de red.
- **Gold** (`data/gold/`): Markdown con front matter más un índice JSONL. Es el contrato con
  el proyecto que consume el corpus y se versiona en Git.

## Extracción (silver)

- Conserva encabezados, listas, enlaces y, sobre todo, tablas: las de tasas, tarifas y
  requisitos son el contenido que más consultan los usuarios.
- Descarta header, nav, footer, formularios, modales, avisos de cookies y scripts.
- Prefiere un extractor propio sobre el DOM a los extractores genéricos de artículos, que
  suelen perder las tarjetas y los acordeones de las páginas institucionales.

## Gold

Usa este front matter y no dupliques los metadatos en el cuerpo:

    titulo: "Cuenta de ahorros"
    url: "https://www.ejemplo-banco.com/personas/ahorro"
    categoria: "ahorro"        # ahorro | tarjetas | credito | tasas | legal
    fecha_captura: "2026-10-22"
    sha256: "..."              # hash del Markdown de silver

- Escribe una línea por documento en el índice JSONL de gold, con los mismos campos.
- Las tasas y tarifas tienen vigencia: la fecha de captura es obligatoria para que el
  asistente no las presente como actuales.
- Retira los bloques repetidos entre documentos (avisos de vigilancia, textos legales) cuando
  su hash normalizado aparece en varios documentos. Nunca retires encabezados y deja un
  reporte de lo retirado.

## Verificación

- Pruebas sin red, con HTML de ejemplo guardado en el repositorio.
- Comprueba que gold no contiene menús ni pie de página, que las tablas sobreviven y que
  reprocesar dos veces produce exactamente el mismo resultado.