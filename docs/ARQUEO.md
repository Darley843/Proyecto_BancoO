# Arqueo de la Sucursal 1965

Reporte reproducible de recuperacion, evaluacion y costo de la fase 2. Se genera con `make arqueo` y no llama a DeepSeek; los embeddings son locales (Ollama). El JSON con las mismas cifras vive en `data/evaluacion/arqueo.json`.

## Ficha de corrida

- Commit: `3295903`.
- Alcance del indice: `base`.
- Indice con prefijos: `data/boveda/indice.json` con modelo `nomic-embed-text-v2-moe`, prefijos si, 874 fragmentos y dimension 768.
- Indice sin prefijos: `data/boveda/experimentos/sin_prefijos/indice.json` con 874 fragmentos y dimension 768.
- Configuracion: `k=5`, pesos por defecto `0.6/0.4`, confianza `0.95` para los intervalos de Wilson.
- Preguntas: 44 (alcance 20, tabla 12, seguimiento 6, fuera 6); 36 con fuente; 22 evaluables de la Boveda (ruta B) y 14 del Tablero (ruta T).

Este es el formato de corrida que puede reutilizar la skill `boveda-rag`: commit de Git, metadatos de `indice.json`, configuracion de recuperacion y resultados por pregunta (en `detalle` del JSON).

## Como se lee este reporte

- **hit@5**: proporcion de preguntas con al menos una URL esperada entre los cinco primeros fragmentos. Solo cuentan las preguntas con fuente.
- **MRR**: media del inverso de la posicion de la primera URL esperada.
- **Wilson 95 %**: intervalo de confianza del hit@5; con 36 preguntas es ancho y no conviene leer diferencias pequenas como mejoras.
- **Comparacion principal**: fijada de antemano, pesos por defecto frente a `1/0` sobre las preguntas de ruta B, con McNemar exacto. Las demas configuraciones son exploratorias: no se declara ganador por significancia.
- **Ruta T**: la respuesta real viene del Tablero, no de la Boveda; su hit@5 se reporta aparte para no atribuir a la Boveda lo que resuelve el Tablero.

## Recuperacion por configuracion

| Configuracion | Prefijos | Evaluables | Aciertos | hit@5 | Wilson 95 % | MRR |
|---|---|---:|---:|---:|---|---:|
| 1/0 | si | 36 | 27 | 0.7500 | 0.5893 a 0.8625 | 0.5769 |
| 0/1 | si | 36 | 19 | 0.5278 | 0.3701 a 0.6801 | 0.3866 |
| 0.2/0.8 | si | 36 | 19 | 0.5278 | 0.3701 a 0.6801 | 0.4231 |
| 0.4/0.6 | si | 36 | 19 | 0.5278 | 0.3701 a 0.6801 | 0.4231 |
| 0.6/0.4 (por defecto) | si | 36 | 27 | 0.7500 | 0.5893 a 0.8625 | 0.5838 |
| 0.8/0.2 | si | 36 | 27 | 0.7500 | 0.5893 a 0.8625 | 0.5653 |
| 0.6/0.4 sin prefijos | no | 36 | 27 | 0.7500 | 0.5893 a 0.8625 | 0.6176 |

## Por tipo de pregunta

| Configuracion | Tipo | Evaluables | hit@5 | MRR |
|---|---|---:|---:|---:|
| 1/0 | alcance | 18 | 0.6111 | 0.4694 |
| 1/0 | tabla | 12 | 1.0000 | 0.8111 |
| 1/0 | seguimiento | 6 | 0.6667 | 0.4306 |
| 1/0 | fuera | 0 | — | — |
| 0/1 | alcance | 18 | 0.3333 | 0.1574 |
| 0/1 | tabla | 12 | 0.8333 | 0.7778 |
| 0/1 | seguimiento | 6 | 0.5000 | 0.2917 |
| 0/1 | fuera | 0 | — | — |
| 0.2/0.8 | alcance | 18 | 0.3333 | 0.2241 |
| 0.2/0.8 | tabla | 12 | 0.8333 | 0.7917 |
| 0.2/0.8 | seguimiento | 6 | 0.5000 | 0.2833 |
| 0.2/0.8 | fuera | 0 | — | — |
| 0.4/0.6 | alcance | 18 | 0.3333 | 0.2241 |
| 0.4/0.6 | tabla | 12 | 0.8333 | 0.7917 |
| 0.4/0.6 | seguimiento | 6 | 0.5000 | 0.2833 |
| 0.4/0.6 | fuera | 0 | — | — |
| 0.6/0.4 | alcance | 18 | 0.6111 | 0.4833 |
| 0.6/0.4 | tabla | 12 | 1.0000 | 0.8667 |
| 0.6/0.4 | seguimiento | 6 | 0.6667 | 0.3194 |
| 0.6/0.4 | fuera | 0 | — | — |
| 0.8/0.2 | alcance | 18 | 0.6111 | 0.4463 |
| 0.8/0.2 | tabla | 12 | 1.0000 | 0.8667 |
| 0.8/0.2 | seguimiento | 6 | 0.6667 | 0.3194 |
| 0.8/0.2 | fuera | 0 | — | — |
| 0.6/0.4 sin prefijos | alcance | 18 | 0.6111 | 0.4389 |
| 0.6/0.4 sin prefijos | tabla | 12 | 1.0000 | 0.9028 |
| 0.6/0.4 sin prefijos | seguimiento | 6 | 0.6667 | 0.5833 |
| 0.6/0.4 sin prefijos | fuera | 0 | — | — |

## Boveda frente a Tablero

hit@5 con las 36 evaluables y sin las preguntas de ruta T:

| Configuracion | hit@5 (36) | hit@5 (sin T) | MRR (36) | MRR (sin T) |
|---|---:|---:|---:|---:|
| 1/0 | 0.7500 | 0.6364 | 0.5769 | 0.4902 |
| 0/1 | 0.5278 | 0.4091 | 0.3866 | 0.2083 |
| 0.2/0.8 | 0.5278 | 0.4091 | 0.4231 | 0.2606 |
| 0.4/0.6 | 0.5278 | 0.4091 | 0.4231 | 0.2606 |
| 0.6/0.4 | 0.7500 | 0.6364 | 0.5838 | 0.4712 |
| 0.8/0.2 | 0.7500 | 0.6364 | 0.5653 | 0.4409 |
| 0.6/0.4 sin prefijos | 0.7500 | 0.6364 | 0.6176 | 0.4955 |

## Comparacion principal: pesos por defecto frente a 1/0

Preguntas de ruta B con fuente: 22. `b` cuenta los pares donde acierta la configuracion por defecto y falla `1/0`; `c`, lo contrario.

| b | c | n | p exacta | Excluidos |
|---:|---:|---:|---:|---:|
| 0 | 0 | 0 | 1.000000 | 0 |

Analisis secundario sobre las 36 preguntas evaluables (incluye ruta T): b=0, c=0, n=0, p=1.000000, excluidos=0.

## Vectorial frente a hibrido, pregunta por pregunta

Posicion 1 a 5 de la primera URL esperada en el top 5; `—` significa que no aparece. Vectorial es `1/0`; hibrido es la configuracion por defecto.

| # | Tipo | Ruta | Fuente indexada | Vectorial 1/0 | Hibrido por defecto | Diferencia |
|---:|---|---|---|---:|---:|---|
| 1 | alcance | B | — | — | — | igual (fuera) |
| 2 | alcance | B | si | — | — | igual (fuera) |
| 3 | alcance | B | si | — | — | igual (fuera) |
| 4 | alcance | B | si | — | — | igual (fuera) |
| 5 | alcance | B | si | 1 | 1 | igual |
| 6 | alcance | B | si | 1 | 1 | igual |
| 7 | alcance | B | si | 1 | 1 | igual |
| 8 | alcance | B | si | 1 | 1 | igual |
| 9 | alcance | B | si | 1 | 1 | igual |
| 10 | alcance | B | si | — | — | igual (fuera) |
| 11 | alcance | B | si | 1 | 1 | igual |
| 12 | alcance | B | si | 4 | 1 | gana hibrido |
| 13 | alcance | B | si | — | — | igual (fuera) |
| 14 | alcance | B | — | — | — | igual (fuera) |
| 15 | alcance | B | si | 5 | 5 | igual |
| 16 | alcance | B | si | — | — | igual (fuera) |
| 17 | alcance | B | si | 2 | 2 | igual |
| 18 | alcance | B | si | 1 | 2 | gana vectorial |
| 19 | alcance | B | si | 2 | 2 | igual |
| 20 | alcance | B | si | — | — | igual (fuera) |
| 21 | tabla | T | si | 1 | 1 | igual |
| 22 | tabla | T | si | 5 | 5 | igual |
| 23 | tabla | T | si | 1 | 1 | igual |
| 24 | tabla | T | si | 1 | 1 | igual |
| 25 | tabla | T | si | 1 | 1 | igual |
| 26 | tabla | T | si | 1 | 1 | igual |
| 27 | tabla | T | si | 1 | 1 | igual |
| 28 | tabla | T | si | 1 | 1 | igual |
| 29 | seguimiento | B | si | — | — | igual (fuera) |
| 30 | seguimiento | B | si | 3 | 3 | igual |
| 31 | seguimiento | B | si | 1 | 3 | gana vectorial |
| 32 | seguimiento | T | si | 4 | 4 | igual |
| 33 | seguimiento | B | si | 1 | 1 | igual |
| 34 | seguimiento | T | si | — | — | igual (fuera) |
| 35 | fuera | X | — | — | — | igual (fuera) |
| 36 | fuera | X | — | — | — | igual (fuera) |
| 37 | fuera | X | — | — | — | igual (fuera) |
| 38 | fuera | X | — | — | — | igual (fuera) |
| 39 | fuera | X | — | — | — | igual (fuera) |
| 40 | fuera | X | — | — | — | igual (fuera) |
| 41 | tabla | T | si | 5 | 5 | igual |
| 42 | tabla | T | si | 3 | 1 | gana hibrido |
| 43 | tabla | T | si | 1 | 1 | igual |
| 44 | tabla | T | si | 1 | 1 | igual |

## Evaluacion v1 y v2

| Version | Aciertos | Total | Exactitud | Citas correctas | Revisadas |
|---|---:|---:|---:|---:|---:|
| v1 | 16 | 20 | 0.8000 | 0.9444 | 20 |
| v2 | 11 | 20 | 0.5500 | 0.5556 | 20 |

## McNemar v1 frente a v2 (20 preguntas de alcance)

| b | c | n | p exacta | p minimo | Excluidos |
|---:|---:|---:|---:|---:|---:|
| 5 | 0 | 5 | 0.062500 | 0.062500 | 0 |

v1 acierta 16 de 20 y v2 acierta 11 de 20. De los 5 pares discordantes, b=5 son pares donde v1 acierta y v2 falla, y c=0 son pares donde v2 acierta y v1 falla; la direccion favorece a v1. El p exacto (0.062500) no llega al umbral de 0.05. Con 5 pares discordantes, el p minimo posible es 2·(1/2)^5 = 0.062500, que ya es >= 0.05: ningun reparto de esos pares podria ser significativo.

## Sensibilidad de la revision humana

Escenario alterno con la nota de **Nayla Ledesma**. No cambia el veredicto principal ni la segunda firma.

| # | Veredicto principal | Veredicto de sensibilidad | Nota |
|---:|---|---|---|
| 2 | incorrecta | rechazo_correcto | El corpus solo cita la Carrera 3 No. 8-13 de Cali como lugar de la asamblea de accionistas; no dice que sea una oficina, asi que no encontrar el dato es un rechazo correcto. |

| Escenario | Aciertos v2 | Exactitud v2 | b | c | n | p exacta | p minimo |
|---|---:|---:|---:|---:|---:|---:|---:|
| Principal | 11 | 0.5500 | 5 | 0 | 5 | 0.062500 | 0.062500 |
| Sensibilidad | 12 | 0.6000 | 5 | 1 | 6 | 0.218750 | 0.031250 |

v1 acierta 16 de 20 y v2 acierta 12 de 20. De los 6 pares discordantes, b=5 son pares donde v1 acierta y v2 falla, y c=1 son pares donde v2 acierta y v1 falla; la direccion favorece a v1. El p exacto (0.218750) no llega al umbral de 0.05. Con 6 pares discordantes, el p minimo posible es 2·(1/2)^6 = 0.031250, aunque el p observado no llega al umbral de 0.05.

## Costo y uso

| Concepto | Valor |
|---|---:|
| Costo del Arqueo (DeepSeek) | 0.000000 |
| Costo historico de v1 (20 de alcance) | 0.027624 |
| Costo historico de v2 (44 preguntas, cota inferior) | 0.015728 |
| Costo de v2 en las 20 de alcance (cota inferior) | 0.011873 |
| Ahorro maximo en las 20 de alcance | hasta 57.0 % menos |
| Preguntas de alcance con clasificador en v2 | 15 de 20 |
| Preguntas del banco | 44 |

El Arqueo no llama a DeepSeek: su costo es cero. `v1_alcance_usd`, `v2_usd` y `v2_alcance_usd` son el costo historico de las evaluaciones, calculado con las tarifas de `arqueo/metricas.py`. Las dos cifras de v2 son cotas inferiores: se midieron antes del arreglo del #93 y no incluian el clasificador de dudas (se uso en 15 de las 20 preguntas de alcance) ni la reformulacion. Una corrida nueva ya suma las tres llamadas del turno, pero los numeros publicados no se re-midieron y siguen siendo cotas inferiores historicas. v1 no usa clasificador, asi que el ahorro en alcance se lee como hasta 57.0 % menos; la cifra de v2 en alcance es una cota inferior, no una medicion cerrada.

## Verificacion local contra el anexo A

Referencia medida por el grupo con el script del anexo A sobre 36 preguntas con fuente. No es un umbral: sirve para comprobar que el barrido reproduce el orden del recuperador. Esa referencia se midio con el indice de 846 fragmentos, sin los 81 de PDF (faltaba `data/knowledge/chunks.jsonl`, ver #78). Con el indice completo, `medir_recuperacion.py` de la skill boveda-rag da las mismas cifras que este Arqueo; por eso lo medido supera a lo esperado.

| Configuracion | hit@5 esperado | hit@5 medido | MRR esperado | MRR medido |
|---|---:|---:|---:|---:|
| 1/0 | 0.6400 | 0.7500 | 0.5200 | 0.5769 |
| por_defecto | 0.6400 | 0.7500 | 0.4800 | 0.5838 |

Diferencias por normalizacion de URL y por deduplicacion de texto se reportan como avisos del JSON y en la seccion de limites.

## Limites

- El costo de v2 en las 20 preguntas de alcance es una cota inferior historica: se midio antes del arreglo del #93, sin el clasificador de dudas (se uso en 15 de las 20 preguntas de alcance) ni la reformulacion. El total de 44 tambien es una cota inferior historica. Una corrida nueva ya suma las tres llamadas del turno; los numeros publicados no se re-midieron. Por eso el ahorro frente a v1, que no usa clasificador, se lee como hasta 57.0 % menos, no como una cifra cerrada.
- El indice sin prefijos se reutiliza si coinciden modelo, alcance, numero de fragmentos y huella del contenido; si no, se reconstruye.
- El acierto se mide por URL, no por fragmento: una pregunta cuenta como acierto si aparece la pagina esperada aunque el fragmento con el dato no este en el top 5 (por ejemplo, la pregunta 7 y el fragmento de la fundacion en 1965).
- El set no nombra el banco en sus preguntas. La prueba de robustez del #85 (indice de 893 fragmentos) mostro que agregar la marca a la consulta baja el hit@5 de 0.75 a 0.53 (McNemar p de 0.02).
- `hit_at_5` y `mrr` comparan las URL exactamente. El script del anexo A normalizaba minusculas y barra final; el JSON informa en `avisos` si esa regla cambia algun resultado.
- `EnsembleRetriever` deduplica por `page_content`. Si dos fragmentos comparten texto, `1/0` puede devolver menos de cinco resultados que una busqueda vectorial directa; la diferencia se cuenta, no se corrige en el recuperador.
- `citas_correctas` no se compara entre versiones: v1 usa el campo `fuente` de `resultados.jsonl`, que registra una sola URL por respuesta, y v2 usa la lista `metricas["fuentes"]` con todas las URL citadas.
- El barrido tiene en la practica dos estados. `EnsembleRetriever` fusiona por rangos reciprocos (peso / (posicion + 60)): con esa constante el orden depende sobre todo de que peso supera 0.5, no de su valor exacto. Dentro de cada lado (peso vectorial menor o mayor que 0.5) el hit@5 casi no cambia; lo que cambia es el orden dentro del top 5, que se ve en el MRR.
- Los seguimientos se buscan uniendo `previa` y `pregunta`, como `medir_recuperacion.py`. En produccion la Sucursal reformula con el nodo `reformular` del grafo, asi que su cifra real puede ser distinta.
- Las preguntas de ruta T responden desde el Tablero: su hit@5 no mide la Boveda y se reporta con y sin ellas.

## Comando

```bash
make arqueo
make arqueo ALCANCE=completo
```

No requiere `DEEPSEEK_API_KEY`. Requiere Ollama para los embeddings locales y el indice construido con `make indice`; si falta el indice sin prefijos, esta corrida lo construye una vez en `data/boveda/experimentos/sin_prefijos`.
