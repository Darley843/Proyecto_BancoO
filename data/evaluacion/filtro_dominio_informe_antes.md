## Filtro de dominio del Digiturno: reglas + modelo (DeepSeek), 3 corridas

| Corrida | Fuga | Rechazo indebido | Acierto en frontera | Dudas sin respuesta |
|---:|---|---|---|---:|
| 1 | 0/50 | 5/50 | 10/14 | 4 |
| 2 | 0/50 | 5/50 | 10/14 | 5 |
| 3 | 0/50 | 5/50 | 10/14 | 4 |
| **Rango** | 0/50 (0,0 %) | 5/50 (10,0 %) | 10/14 (71,4 %) | |

### Casos con error en al menos una corrida

Un caso con error en todas las corridas es un fallo estable de la regla o del prompt; uno con error en algunas es inestable.

| Caso | Texto | Esperado | Corridas con error | Letra por corrida |
|---|---|---|---:|---|
| dentro-029 | Quiero saber si me alcanza para pagar un crédito | aceptar | 3 de 3 | X, X, X |
| dentro-030 | Hazme el diagnóstico financiero | aceptar | 3 de 3 | X, X, X |
| dentro-031 | ¿Qué significa que mi semáforo salió amarillo? | aceptar | 1 de 3 | B, B, X |
| dentro-033 | ¿Cuánto de mi sueldo debería ir a pagar deudas? | aceptar | 3 de 3 | X, X, X |
| dentro-049 | Muchas gracias por la información | aceptar | 2 de 3 | X, X, B |
| dentro-050 | nuevo | aceptar | 3 de 3 | X, X, X |
| frontera-001 | ¿Qué es la inflación? | aceptar | 3 de 3 | X, X, X |
| frontera-004 | ¿Me van a aprobar el crédito? | aceptar | 3 de 3 | X, X, X |
| frontera-010 | Estoy muy endeudado y no sé qué hacer | aceptar | 3 de 3 | X, X, X |
| frontera-014 | Ayúdame a declarar renta | rechazar | 3 de 3 | B, B, B |

> **Atención:** 13 dudas quedaron sin respuesta del modelo (sumando todas las corridas) y se aceptaron por defecto; esas cifras no reflejan al modelo.

**Llamadas al modelo:** 296. Uso acumulado: input_token_details.cache_read 0, input_tokens 69771, output_token_details.reasoning 27489, output_tokens 36297, total_tokens 106068.
