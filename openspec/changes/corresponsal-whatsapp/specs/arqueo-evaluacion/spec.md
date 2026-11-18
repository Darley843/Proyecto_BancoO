# Spec Delta

## ADDED Requirements

### Requirement: Filtro de dominio del canal

El Arqueo SHALL evaluar el filtro de dominio con casos dentro y fuera de tema, incluyendo intentos de inyección, y MUST reportar la tasa de fuga (casos fuera de tema respondidos como si fueran del banco) y la tasa de rechazo indebido (casos dentro del alcance rechazados). Cada tasa MUST acompañarse de su intervalo de confianza de Wilson al 95 % y del tamaño de muestra.

#### Scenario: Caso fuera de tema
- **WHEN** el caso pregunta por el clima o por otro banco y el asistente responde con información del banco
- **THEN** el caso cuenta como fuga

#### Scenario: Caso dentro del alcance
- **WHEN** el caso es una pregunta legítima y el asistente la rechaza
- **THEN** el caso cuenta como rechazo indebido

#### Scenario: Intervalo de Wilson
- **WHEN** se calcula una tasa con `n` casos
- **THEN** el reporte incluye el límite inferior y superior de Wilson al 95 %

#### Scenario: Muestra pequeña
- **WHEN** una categoría tiene pocos casos
- **THEN** el reporte informa el tamaño de muestra y no presenta el intervalo como una certeza

### Requirement: Matriz de confusión del filtro

El Arqueo SHALL publicar la matriz de confusión del filtro con verdaderos positivos, falsos positivos, verdaderos negativos y falsos negativos. La matriz MUST construirse con la etiqueta esperada de cada caso y la decisión observada, sin intervención del modelo en la clasificación del resultado.

#### Scenario: Matriz completa
- **WHEN** termina la evaluación del filtro
- **THEN** el reporte incluye las cuatro celdas y el total de casos

#### Scenario: Etiqueta faltante
- **WHEN** un caso no declara si está dentro o fuera del alcance
- **THEN** se excluye y el reporte informa cuántos quedaron fuera

#### Scenario: Reproducibilidad
- **WHEN** se repite la evaluación con los mismos casos y respuestas
- **THEN** la matriz y las tasas coinciden

### Requirement: Latencia p50 y p95 por flujo

El Arqueo SHALL medir la latencia de cada flujo del canal y del diagnóstico y MUST reportar los percentiles p50 y p95. Cada flujo MUST tener al menos 30 corridas y MUST separar los aciertos de caché de las corridas que usaron el modelo.

#### Scenario: Treinta corridas
- **WHEN** un flujo tiene 30 o más corridas
- **THEN** el reporte publica p50 y p95 de ese flujo

#### Scenario: Menos de treinta
- **WHEN** un flujo tiene menos de 30 corridas
- **THEN** el reporte lo marca como insuficiente y no presenta el percentil como conclusión

#### Scenario: Caché separada
- **WHEN** una corrida se responde desde la caché
- **THEN** se contabiliza aparte y no se mezcla con la latencia del modelo

#### Scenario: Flujos cubiertos
- **WHEN** se revisa el reporte
- **THEN** incluye webhook, diagnóstico, reanudación HITL y consulta MCP

### Requirement: Reporte del canal en el Arqueo

El Arqueo SHALL agregar al reporte las secciones de filtro de dominio y latencia, y MUST presentar las mismas cifras en `arqueo.json` y en `docs/ARQUEO.md`. Las secciones MUST ser deterministas y MUST NOT incluir datos personales ni el texto completo de los mensajes.

#### Scenario: JSON y Markdown
- **WHEN** se comparan ambos archivos
- **THEN** las tasas, intervalos y percentiles coinciden

#### Scenario: Sin PII
- **WHEN** se revisa el reporte
- **THEN** no aparecen números, nombres ni conversaciones

#### Scenario: Ejecución sin red
- **WHEN** corre `make arqueo` sin conexión
- **THEN** las secciones nuevas se generan con los datos locales
