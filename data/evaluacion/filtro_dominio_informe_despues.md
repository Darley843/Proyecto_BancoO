## Filtro de dominio del Digiturno: reglas + modelo (DeepSeek), 3 corridas

| Corrida | Fuga | Rechazo indebido | Acierto en frontera | Dudas sin respuesta |
|---:|---|---|---|---:|
| 1 | 0/50 | 3/50 | 14/14 | 2 |
| 2 | 0/50 | 1/50 | 14/14 | 0 |
| 3 | 0/50 | 2/50 | 14/14 | 1 |
| **Rango** | 0/50 (0,0 %) | 1 a 3 de 50 (2,0 a 6,0 %) | 14/14 (100,0 %) | |

### Casos con error en al menos una corrida

Un caso con error en todas las corridas es un fallo estable de la regla o del prompt; uno con error en algunas es inestable.

| Caso | Texto | Esperado | Corridas con error | Letra por corrida |
|---|---|---|---:|---|
| dentro-005 | ¿Qué es la compra de cartera y me conviene? | aceptar | 1 de 3 | X, B, B |
| dentro-027 | ¿Le cobran retención en la fuente a los rendimientos del CDT? | aceptar | 2 de 3 | X, T, X |
| dentro-050 | nuevo | aceptar | 3 de 3 | X, X, X |

> **Atención:** 3 dudas quedaron sin respuesta del modelo (sumando todas las corridas); el Digiturno las resolvió con su respaldo y no con el modelo.

**Llamadas al modelo:** 261. Uso acumulado: input_token_details.cache_read 33408, input_tokens 93870, output_token_details.reasoning 20969, output_tokens 28385, total_tokens 122255.
