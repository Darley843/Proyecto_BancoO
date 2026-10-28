# Alcance del sistema Q&A — Banco de Occidente

## Objetivo

Responder las preguntas que haría un cliente en su primer contacto con el banco, usando solo información pública del sitio oficial y fuentes verificadas. Si el corpus no tiene el dato, el asistente lo dice y remite al canal oficial; nunca inventa.

## Fuentes identificadas

| Fuente | Uso en el corpus |
|---|---|
| Sitio oficial (bancodeoccidente.com.co) | Capturado con robots.txt respetado (Bronze → Silver → Gold) |
| Documentos PDF públicos | Capturados (informes, estados financieros); no se usan en el prompt por tamaño |
| Videos de YouTube con subtítulos | Capturados (32) |
| Prensa y hechos relevantes | 60 fichas verificadas (40 oficiales, 20 de prensa) |
| Redes sociales oficiales | Identificadas, no capturadas (sus términos prohíben el scraping): LinkedIn, Facebook, Instagram, YouTube, X |

## Las 20 preguntas del alcance

| # | Pregunta | Cobertura en el corpus |
|---|---|---|
| 1 | ¿Cuál es el horario de atención de las oficinas? | No: el buscador de oficinas usa JavaScript y un servicio externo. Responder con el enlace oficial |
| 2 | ¿Dónde hay una oficina en Cali? | No: mismo caso. Responder con el enlace oficial |
| 3 | ¿Cuál es la línea de atención telefónica? | Sí (Líneas de servicio al cliente) |
| 4 | ¿Cómo presento una petición, queja o reclamo? | Sí, por verificar |
| 5 | ¿Quién es el Defensor del Consumidor Financiero y cómo lo contacto? | Sí |
| 6 | ¿Cuál es el propósito o misión del banco? | Parcial: el sitio publica "propósito", pilares y valores, no una misión |
| 7 | ¿Cuándo y dónde se fundó el banco? | Sí (cronología de la página institucional: 3 de mayo de 1965, Cali), recuperada en el PR #20 |
| 8 | ¿A qué grupo empresarial pertenece? | Sí (Grupo Aval) |
| 9 | ¿Quién es el presidente del banco? | Sí (perfil de Gerardo Silva Castro, presidente desde agosto de 2023), recuperado en el PR #20 |
| 10 | ¿Qué tipos de cuentas de ahorro ofrece? | Sí |
| 11 | ¿Qué requisitos necesito para abrir una cuenta? | Sí |
| 12 | ¿Puedo abrir una cuenta en línea? | Sí |
| 13 | ¿Qué tarjetas de crédito ofrece y cuál es su cuota de manejo? | Sí |
| 14 | ¿Qué es un CDT y cuál es su tasa? | Parcial: el corpus explica el CDT, sus documentos y el monto mínimo, pero no publica la tasa (la única cifra venía de un formulario excluido en el issue #33). Debe remitir al canal oficial para la tasa |
| 15 | ¿Qué créditos de vivienda ofrece? | Sí |
| 16 | ¿Ofrece crédito de vehículo? | Sí |
| 17 | ¿Qué hago si pierdo mi tarjeta o me la roban? | Sí, por verificar |
| 18 | ¿Cómo uso la banca móvil o la app? | Sí |
| 19 | ¿Qué acciones de sostenibilidad realiza? | Sí, por verificar |
| 20 | ¿Cuáles son las noticias recientes del banco? | Sí (fichas de noticias) |

## Fuera del alcance

Saldos, movimientos, transacciones y cualquier dato de clientes: requieren autenticación y no son información pública.
