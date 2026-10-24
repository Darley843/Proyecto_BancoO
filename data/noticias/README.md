# Noticias de prensa externa

`prensa.yaml` es la fuente curada de las noticias de prensa externa sobre Banco
de Occidente. Es un archivo versionado y vive fuera de `data/gold/` para que
`make clean` no borre la curaduría. Las fichas Gold se generarán a partir de
este archivo con el flujo de noticias.

## Límites

- El registro debe tener entre **15 y 20** fichas.
- Cada ficha contiene solo los cinco datos mínimos: **título, fecha, medio,
  enlace original y resumen propio**.
- No se guarda el cuerpo del artículo, imágenes, audio ni PDFs de prensa.
- El resumen es propio: no se copian párrafos del artículo.
- Todas las fichas nuevas entran con `estado: pendiente`.

## Verificación humana

1. Abrir el enlace original.
2. Confirmar que la nota se refiere al **Banco de Occidente de Colombia**.
3. Confirmar que la fecha de publicación coincide con `fecha`.
4. Revisar que el resumen sea propio y no reproduzca el artículo.
5. Solo entonces cambiar `estado: pendiente` a `estado: verificado`.

Una ficha `pendiente` no se publica en Gold. Si el enlace no corresponde al
banco o la fecha no coincide, se rechaza la ficha y se explica el motivo.

## Campos

| Campo | Obligatorio | Descripción |
|---|---|---|
| `id` | sí | Identificador estable con prefijo `noticia-` |
| `fecha` | sí | Fecha de publicación en formato `YYYY-MM-DD` |
| `medio` | sí | Medio que publicó la nota |
| `titulo` | sí | Titular verificado |
| `url` | sí | Enlace original, no un redirect de agregador |
| `resumen` | sí | Resumen propio de 2-4 frases |
| `temas` | sí | Lista de temas del vocabulario controlado |
| `relevancia` | sí | `alta`, `media` o `baja` |
| `evento` | no | Agrupa coberturas del mismo hecho |
| `estado` | sí | `pendiente` o `verificado` |

## Vocabulario de `temas`

`resultados`, `fusiones`, `financiacion`, `digital`, `productos`,
`sostenibilidad`, `energia`, `infraestructura`, `empresas`, `inversion`,
`gobierno-corporativo`, `regulacion`, `reconocimientos`, `talento-humano`,
`responsabilidad-social`, `inteligencia-artificial`.

## Cómo añadir una ficha

Añadir una entrada al final de `prensa.yaml` con el mismo formato. Mantener el
`id` estable y no reutilizarlo. Si dos medios cubren el mismo hecho, usar el
mismo `evento`; el flujo de noticias aplicará el límite `max_por_evento`.
