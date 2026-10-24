# Taxonomía de entidades y predicados

Vocabulario controlado para que el conocimiento sea consistente y consultable.
Si necesitas algo que no está aquí, añádelo a este archivo en el mismo commit
que introduce el primer uso.

## Tipos de entidad

| Tipo | Qué representa | Ejemplo de id | Ejemplo |
|---|---|---|---|
| `organizacion` | Empresa, grupo, filial | `ent:grupo-aval` | Grupo Aval |
| `producto` | Producto financiero | `ent:cuenta-de-ahorros` | Cuenta de Ahorros |
| `canal` | Canal de atención o digital | `ent:banca-movil` | Banca Móvil |
| `sede` | Oficina, agencia, sede | `ent:sede-cali` | Sede Cali |
| `directivo` | Persona en cargo directivo | `ent:presidente-banco` | Presidente |
| `segmento` | Segmento de clientes | `ent:segmento-pymes` | Pymes |
| `normativa` | Ley, circular, regulación | `ent:ley-1581` | Ley 1581 de 2012 |
| `indicador` | Métrica o KPI | `ent:indicador-mora` | Indicador de mora |
| `certificacion` | Sello o certificación | `ent:iso-9001` | ISO 9001 |
| `aliado` | Aliado o filial no bancaria | `ent:aval-villas` | AV Villas |
| `evento` | Evento o hito | `ent:asamblea-2026` | Asamblea 2026 |

## Predicados de hecho

| Predicado | Sujeto | Valor | `value_type` | Ejemplo |
|---|---|---|---|---|
| `tiene_proposito` | organizacion | texto | `text` | Hacer realidad el desarrollo… |
| `tiene_mision` | organizacion | texto | `text` | … |
| `tiene_vision` | organizacion | texto | `text` | … |
| `tiene_valor` | organizacion | nombre del valor | `text` | Honestidad |
| `fue_fundado_en` | organizacion | año | `number` | 1965 |
| `tiene_presidente` | organizacion | nombre | `text` | … |
| `tiene_sede_principal` | organizacion | ciudad | `text` | Cali |
| `ofrece_producto` | organizacion | nombre | `text` | Cuenta de Ahorros |
| `tiene_tasa` | producto | porcentaje | `percentage` | 4.5 |
| `tiene_costo` | producto | monto | `currency` | 15000 |
| `tiene_requisito` | producto | texto | `text` | Ser mayor de edad |
| `tiene_beneficio` | producto | texto | `text` | Transacciones ilimitadas |
| `esta_dirigido_a` | producto | segmento | `text` | Pymes |
| `atiende_segmento` | organizacion | segmento | `text` | Personas |
| `publica_informe` | organizacion | título | `text` | Informe de gestión 2025 |
| `reporta_indicador` | organizacion | valor | `number` | … |
| `obtuvo_reconocimiento` | organizacion | texto | `text` | … |
| `tiene_certificacion` | organizacion | nombre | `text` | ISO 9001 |
| `opera_en` | organizacion | país/ciudad | `text` | Colombia |
| `publico_noticia` | organizacion | titular | `text` | … |

Reglas:

- `value` nunca repite el sujeto ni el predicado («Banco de Occidente tiene
  propósito: …», no «Banco de Occidente tiene el propósito de Banco…»).
- Fechas: `value_type: "date"` y `value` en `YYYY-MM-DD`; si solo hay año,
  `value_type: "number"` + `qualifiers: {"granularidad": "anio"}`.
- Porcentajes: número sin `%` y `value_type: "percentage"`.
- Moneda: número y `qualifiers: {"moneda": "COP"}`.

## Predicados de relación

| Predicado | Sujeto | Objeto | Ejemplo de cita |
|---|---|---|---|
| `pertenece_a` | organizacion | organizacion | «Como parte del Grupo Aval…» |
| `ofrece` | organizacion | producto | «Cuenta de Ahorros…» |
| `opera_en` | organizacion | sede | «Oficinas del Banco…» |
| `dirige` | directivo | organizacion | «Presidente del Banco…» |
| `es_aliado_de` | organizacion | aliado | «En alianza con…» |
| `regula_a` | normativa | organizacion | «La Ley 1581 aplica a…» |
| `compite_con` | organizacion | organizacion | «…frente a otros bancos» |
| `depende_de` | organizacion | organizacion | «Filial de…» |

Una relación exige que la cita mencione **explícitamente** a los dos extremos.
No se aceptan relaciones inferidas por co-ocurrencia en la misma página.

## Normalización de nombres

1. Singular y sin artículo: `ent:cuenta-de-ahorros` (no `ent:las-cuentas`).
2. Sin acentos ni mayúsculas en el id; el `name` conserva la grafía oficial.
3. Siglas al `aliases`, no al id: `ent:banco-de-occidente` con alias `BDO`.
4. Si dudas entre dos ids, elige el más general y documenta la variante en
   `aliases`.

## Cobertura mínima por sección

| Sección | Qué debería quedar en Knowledge |
|---|---|
| `identidad` | propósito, misión/visión, valores, historia, grupo, directivos, sedes |
| `oferta` | productos, requisitos, beneficios, tasas, segmentos |
| `presencia` | noticias, alianzas, eventos, reconocimientos |
| `datos` | informes, indicadores, certificaciones, normativa |
| `atencion` | canales, líneas, PQRS |
| `legal` | políticas, tratamiento de datos, términos |

Si una sección no aporta hechos verificables, se documenta en `_INDICE.md` y no
se fuerza la extracción.
