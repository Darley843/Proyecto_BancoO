# Spec Delta

## Purpose

Medir con evidencia la recuperación y el asistente de la fase 2: comparar configuraciones del índice, evaluar v1 y v2 con las mismas preguntas y publicar un reporte reproducible.

## ADDED Requirements

### Requirement: Experimentos de recuperación

`arqueo/experimentos.py` SHALL medir hit@5 y MRR sobre las preguntas de `config/evaluacion/preguntas_fase2.toml` que declaran `fuentes_esperadas`, variando los pesos del recuperador híbrido y comparando el índice con y sin prefijos. MUST usar `arqueo/metricas.py` y MUST NOT llamar a DeepSeek.

#### Scenario: Barrido de pesos

- **WHEN** se ejecuta el experimento
- **THEN** el reporte incluye hit@5 y MRR para los pesos `1/0`, `0/1`, `0.2/0.8`, `0.4/0.6`, `0.6/0.4` y `0.8/0.2`, con `1/0` y `0/1` como líneas base vectorial y BM25 pura

#### Scenario: Pesos sin reindexar

- **WHEN** cambian los pesos del híbrido
- **THEN** el experimento reutiliza el mismo índice y no lo reconstruye

#### Scenario: Con y sin prefijos

- **WHEN** se comparan las dos variantes de prefijos
- **THEN** la variante sin prefijos usa un único índice extra en `data/boveda/experimentos/sin_prefijos` y se mide con los pesos por defecto

#### Scenario: Sin gasto de modelo

- **WHEN** corre `make arqueo`
- **THEN** no hay llamadas a DeepSeek y el costo registrado es cero

### Requirement: Comparación v1 y v2 con McNemar

El Arqueo SHALL comparar las respuestas v1 y v2 sobre las 20 preguntas de tipo `alcance` usando la revisión humana de `config/evaluacion/revision_humana.toml` y `revision_humana_v2.toml`, y MUST calcular la prueba exacta de McNemar con `arqueo/metricas.mcnemar`.

#### Scenario: Pares completos

- **WHEN** ambas revisiones tienen veredicto para una pregunta
- **THEN** la pregunta entra en el cálculo de McNemar

#### Scenario: Revisión faltante

- **WHEN** falta el veredicto de una de las dos versiones
- **THEN** el par se excluye y el reporte informa cuántos pares quedaron fuera

#### Scenario: Sin pares discordantes

- **WHEN** v1 y v2 aciertan o fallan en las mismas preguntas
- **THEN** el reporte informa `p = 1` y no atribuye una mejora

### Requirement: Reporte reproducible del Arqueo

El Arqueo SHALL escribir `data/evaluacion/arqueo.json` y `docs/ARQUEO.md`. El JSON MUST incluir recuperación por configuración, uso y costo, exactitud, citas correctas y el resultado de McNemar; el Markdown MUST presentar las mismas cifras de forma legible.

#### Scenario: JSON completo

- **WHEN** termina `make arqueo`
- **THEN** `arqueo.json` existe con las secciones de recuperación, uso, exactitud, citas y McNemar

#### Scenario: Markdown coherente

- **WHEN** se comparan `ARQUEO.md` y `arqueo.json`
- **THEN** las cifras coinciden

#### Scenario: Ejecución repetida

- **WHEN** se ejecuta dos veces con los mismos datos y revisiones
- **THEN** ambos archivos son idénticos

### Requirement: Evaluación v2 con el grafo

`make evaluar VERSION=v2` SHALL responder con el grafo de la Sucursal en lugar del contexto completo. En las preguntas de tipo `seguimiento` MUST enviar primero el texto de `previa` en el mismo `thread_id` y después la pregunta.

#### Scenario: Pregunta de seguimiento

- **WHEN** una pregunta declara `previa`
- **THEN** la evaluación envía la previa y la pregunta en el mismo hilo y registra la respuesta a la segunda

#### Scenario: Pregunta autónoma

- **WHEN** una pregunta no declara `previa`
- **THEN** se envía sola en un hilo nuevo

#### Scenario: Resultados separados

- **WHEN** se evalúa v2
- **THEN** los resultados no sobrescriben los de v1

### Requirement: Métricas en un solo lugar

El Arqueo SHALL reutilizar `arqueo/metricas.py` para hit@k, MRR, exactitud, citas correctas, resumen de uso, McNemar y las tarifas. Los módulos nuevos MUST NOT duplicar esas fórmulas ni los precios.

#### Scenario: Una sola fórmula

- **WHEN** la Sucursal calcula el costo de una llamada
- **THEN** importa las tarifas de `arqueo/metricas.py`

#### Scenario: Una sola normalización

- **WHEN** se comparan términos de una respuesta con los esperados
- **THEN** se usa `banco_occidente_corpus.texto.normalizar`, la misma normalización sin tildes que reutiliza `asistente/evaluacion.py`

### Requirement: Comandos independientes

`make arqueo` SHALL ejecutar solo los experimentos y el reporte, sin tocar `make all`, `make gold` ni `make deliver`. `make evaluar VERSION=v2` MUST seguir siendo la vía para responder las preguntas con el modelo.

#### Scenario: Target aislado

- **WHEN** se revisan `make all`, `make gold` y `make deliver`
- **THEN** ninguno ejecuta `arqueo`

#### Scenario: Arqueo sin modelo

- **WHEN** se ejecuta `make arqueo` sin `DEEPSEEK_API_KEY`
- **THEN** termina correctamente porque no llama a DeepSeek

### Requirement: Pruebas del Arqueo sin red

Las pruebas del Arqueo MUST usar datos sintéticos y `DeterministicFakeEmbedding`; MUST NOT llamar a Ollama, a DeepSeek ni al sitio del banco.

#### Scenario: Suite offline

- **WHEN** corre `make test`
- **THEN** las pruebas del Arqueo pasan sin conexión
