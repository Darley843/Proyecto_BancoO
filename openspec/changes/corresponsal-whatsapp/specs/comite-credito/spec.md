# Spec Delta

## Purpose

Revisar los casos de diagnóstico rojos o amarillos con tres perspectivas independientes en una sola ronda, para producir una recomendación estructurada, trazable y auditable que apoye al asesor.

## ADDED Requirements

### Requirement: Activación acotada del comité

El comité SHALL ejecutarse solo cuando el diagnóstico termina en rojo o amarillo. En verde MUST NOT convocarse; si el usuario pide una revisión explícita en verde, el sistema MUST explicar que el caso no requiere comité.

#### Scenario: Caso rojo
- **WHEN** el diagnóstico termina en rojo
- **THEN** se convoca el comité con una sola ronda

#### Scenario: Caso amarillo
- **WHEN** el diagnóstico termina en amarillo
- **THEN** se convoca el comité con una sola ronda

#### Scenario: Caso verde
- **WHEN** el diagnóstico termina en verde
- **THEN** no se convoca el comité y se explica por qué

### Requirement: Tres roles con alcance separado

El comité SHALL producir tres opiniones: riesgo, comercial y auditor. Riesgo MUST evaluar endeudamiento y capacidad; comercial MUST evaluar la adecuación del producto y el plazo; auditor MUST revisar consistencia, citas y cumplimiento del aviso orientativo.

#### Scenario: Opinión de riesgo
- **WHEN** corre el comité
- **THEN** riesgo emite un veredicto sobre endeudamiento y capacidad con referencia al resultado del diagnóstico

#### Scenario: Opinión comercial
- **WHEN** corre el comité
- **THEN** comercial emite un veredicto sobre producto y plazo sin prometer aprobación

#### Scenario: Opinión del auditor
- **WHEN** corre el comité
- **THEN** auditor revisa que las otras dos opiniones no inventen cifras ni omitan el aviso

### Requirement: Una sola ronda

El comité SHALL completar su trabajo en una única ronda de tres opiniones y una síntesis. MUST NOT abrir turnos adicionales, debates o reintentos por desacuerdo; un desacuerdo MUST quedar registrado tal cual.

#### Scenario: Una ronda
- **WHEN** se convoca el comité
- **THEN** hay exactamente tres opiniones y una síntesis, sin segunda ronda

#### Scenario: Desacuerdo
- **WHEN** los tres roles no coinciden
- **THEN** la síntesis conserva las tres opiniones y explica la diferencia sin forzar unanimidad

#### Scenario: Fallo de un rol
- **WHEN** uno de los tres no puede responder
- **THEN** el comité entrega las opiniones disponibles y marca la faltante, sin repetir la ronda

### Requirement: Salida estructurada y trazable

El comité SHALL devolver una salida validada con los campos de veredicto, confianza, evidencias, riesgos, condiciones y aviso. Cada afirmación MUST citar el resultado del diagnóstico o una fila del Tablero; si falta la evidencia, el rol MUST abstenerse en vez de inventar.

#### Scenario: Evidencia disponible
- **WHEN** un rol afirma una cifra
- **THEN** la salida incluye la referencia al insumo o a la fila que la sostiene

#### Scenario: Evidencia ausente
- **WHEN** un rol no encuentra la evidencia para una afirmación
- **THEN** marca la abstención y no completa el dato

#### Scenario: Salida inválida
- **WHEN** el modelo devuelve un esquema incompleto o un veredicto desconocido
- **THEN** la salida se rechaza y se informa el error sin inventar una decisión

### Requirement: Recomendación final sin aprobación

La síntesis SHALL emitir una recomendación entre `apto`, `apto_con_condiciones`, `no_apto` o `requiere_asesor`. Toda recomendación MUST declarar que es una opinión del comité y que la aprobación de crédito corresponde a un humano del banco.

#### Scenario: Apto con condiciones
- **WHEN** el comité acepta el caso con ajustes de plazo o monto
- **THEN** la recomendación es `apto_con_condiciones` y lista las condiciones

#### Scenario: No apto
- **WHEN** riesgo y comercial coinciden en que el caso no es viable
- **THEN** la recomendación es `no_apto` con los motivos citados

#### Scenario: Aviso final
- **WHEN** se muestra la recomendación
- **THEN** aparece que no es una aprobación y que la decisión final es humana

### Requirement: Privacidad y costo acotados

El comité SHALL recibir solo el resultado del diagnóstico y las filas necesarias, nunca el número, el nombre ni el texto libre de la conversación. El comité MUST NOT convocar herramientas externas, escribir en la Bóveda ni modificar el diagnóstico original.

#### Scenario: Sin PII
- **WHEN** se revisan los mensajes enviados al comité
- **THEN** no aparece el número ni el nombre del usuario

#### Scenario: Sin escritura
- **WHEN** termina el comité
- **THEN** la Bóveda, el Tablero y el diagnóstico permanecen sin cambios

#### Scenario: Costo visible
- **WHEN** se ejecuta el comité
- **THEN** el uso de tokens y el costo quedan registrados en el turno como una sola operación
