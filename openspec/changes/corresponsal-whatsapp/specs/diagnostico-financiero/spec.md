# Spec Delta

## Purpose

Acompañar al usuario en una entrevista financiera breve y devolver un diagnóstico orientativo, calculado de forma determinista con tasas trazables, que pueda escalar a un asesor humano o comparar escenarios.

## ADDED Requirements

### Requirement: Entrevista guiada por rangos

El diagnóstico SHALL conducir una entrevista de una pregunta por turno, usando rangos y opciones en lugar de pedir cifras exactas cuando sea posible. MUST recoger ingresos, gastos, cuotas de deudas, valor del crédito, plazo y producto; MUST permitir cancelar o pedir un asesor en cualquier punto.

#### Scenario: Primera pregunta
- **WHEN** el usuario pide un diagnóstico
- **THEN** recibe una sola pregunta con opciones de rango y una instrucción breve

#### Scenario: Respuesta válida
- **WHEN** el usuario elige un rango
- **THEN** el sistema guarda la respuesta y avanza a la siguiente pregunta sin repetirla

#### Scenario: Respuesta ambigua
- **WHEN** el usuario responde algo que no corresponde a la pregunta
- **THEN** el sistema repite la pregunta con un ejemplo, sin inventar un valor

#### Scenario: Cancelación
- **WHEN** el usuario cancela o pide un asesor durante la entrevista
- **THEN** el diagnóstico se detiene y se ofrece el caso de asesoría

### Requirement: Cálculo determinístico

El diagnóstico SHALL calcular en Python, sin modelo, la tasa mensual equivalente, la cuota francesa, la razón de endeudamiento y la capacidad de pago. La tasa mensual MUST derivarse de la tasa efectiva anual vigente del Tablero y la cuota MUST usar la fórmula francesa; el modelo MUST NOT hacer aritmética ni sustituir una tasa ausente.

#### Scenario: Tasa efectiva anual
- **WHEN** el Tablero declara una tasa E.A. de 24 %
- **THEN** la tasa mensual se calcula como `(1 + 0,24)^(1/12) - 1`

#### Scenario: Cuota francesa
- **WHEN** hay monto, plazo y tasa mensual
- **THEN** la cuota se calcula con la fórmula francesa y se informa el total de intereses

#### Scenario: Tasa ausente
- **WHEN** el Tablero no tiene una tasa para el producto
- **THEN** el diagnóstico se detiene con un mensaje explicable y no inventa la tasa

#### Scenario: Sin modelo en la aritmética
- **WHEN** se revisa el resultado con los mismos insumos dos veces
- **THEN** las cifras son idénticas y no dependen de una llamada al modelo

### Requirement: Razón de endeudamiento y capacidad de pago

El diagnóstico SHALL comparar la suma de cuotas con el ingreso mensual y calcular la capacidad de pago como ingreso menos gastos y cuotas. Los umbrales SHALL ser configurables y MUST aplicarse de forma determinista sobre los valores calculados.

#### Scenario: Endeudamiento bajo
- **WHEN** las cuotas representan 25 % del ingreso
- **THEN** la razón se informa como 25 % y el semáforo es verde con los umbrales por defecto

#### Scenario: Capacidad negativa
- **WHEN** gastos y cuotas superan el ingreso
- **THEN** la capacidad se informa como negativa y el semáforo no puede ser verde

#### Scenario: Umbral configurado
- **WHEN** se cambia el umbral de amarillo en configuración
- **THEN** el mismo caso cambia de semáforo según el valor nuevo

### Requirement: Semáforo y recomendaciones orientativas

El diagnóstico SHALL devolver un semáforo verde, amarillo o rojo y recomendaciones deterministas asociadas al resultado. Toda respuesta MUST declarar que el diagnóstico es orientativo, que no constituye una aprobación de crédito y que la decisión final corresponde al banco.

#### Scenario: Caso verde
- **WHEN** el endeudamiento y la capacidad están dentro de los umbrales
- **THEN** el semáforo es verde y se listan recomendaciones de mantenimiento

#### Scenario: Caso amarillo
- **WHEN** el endeudamiento supera el umbral verde sin llegar al rojo
- **THEN** el semáforo es amarillo y se recomienda revisar gastos o plazo

#### Scenario: Caso rojo
- **WHEN** el endeudamiento supera el umbral rojo o la capacidad es negativa
- **THEN** el semáforo es rojo y se ofrece hablar con un asesor

#### Scenario: Aviso obligatorio
- **WHEN** se muestra cualquier resultado
- **THEN** aparece el aviso de que es orientativo y no una aprobación

### Requirement: HITL con el asesor

El diagnóstico SHALL suspender el hilo con `interrupt()` cuando el resultado es rojo o cuando el usuario pide asesoría. La suspensión MUST presentar el caso y los botones «Contactar» y «Descartar»; la reanudación MUST usar `Command(resume=...)` sobre el mismo checkpoint.

#### Scenario: Caso rojo
- **WHEN** el resultado es rojo
- **THEN** el turno se suspende y se muestran el resumen y los botones, sin respuesta final inventada

#### Scenario: Contactar
- **WHEN** el usuario pulsa «Contactar»
- **THEN** el hilo se reanuda, se crea un `CasoAsesor` y se confirma que un asesor revisará el caso

#### Scenario: Descartar
- **WHEN** el usuario pulsa «Descartar»
- **THEN** el hilo se reanuda, el caso se cierra sin escalar y se agradece

#### Scenario: Reanudación sin checkpoint
- **WHEN** llega una reanudación para un hilo que no está suspendido
- **THEN** se responde un error explicable y no se crea un caso nuevo

### Requirement: Caso de asesor estructurado

El HITL SHALL producir un `CasoAsesor` con `usuario_id`, motivo, semáforo, resultado del diagnóstico, fecha y estado. El caso MUST NOT incluir el número de teléfono, el nombre ni el texto libre de la conversación.

#### Scenario: Caso creado
- **WHEN** el usuario contacta a un asesor
- **THEN** el `CasoAsesor` guarda el motivo y el resultado, sin PII

#### Scenario: Caso descartado
- **WHEN** el usuario descarta la asesoría
- **THEN** el caso queda cerrado con estado `descartado`

#### Scenario: Consulta del asesor
- **WHEN** el tablero de operación lista los casos
- **THEN** muestra el motivo y el semáforo, no la conversación ni el número

### Requirement: Escenarios «¿Y si…?»

El diagnóstico SHALL permitir bifurcar el checkpoint de un diagnóstico terminado para recalcular con un cambio en monto, plazo, tasa o ingreso. La bifurcación MUST comparar el escenario con el resultado original y MUST NOT modificar la conversación original.

#### Scenario: Cambio de plazo
- **WHEN** el usuario pide «¿y si el plazo fuera 48 meses?»
- **THEN** se crea una rama con el nuevo plazo y se comparan cuota y semáforo

#### Scenario: Original intacto
- **WHEN** termina la comparación
- **THEN** el diagnóstico original conserva sus valores y su checkpoint

#### Scenario: Cambio inválido
- **WHEN** el escenario pide un plazo o monto fuera de rango
- **THEN** se explica el límite y no se crea la rama

### Requirement: Contratos del diagnóstico

El diagnóstico SHALL validar la entrada y la salida con `EntradaDiagnostico` y `ResultadoDiagnostico`. El resultado MUST incluir los insumos usados, la tasa y su fuente, la versión de la fórmula, el semáforo, la capacidad, las recomendaciones y el aviso orientativo.

#### Scenario: Resultado completo
- **WHEN** termina un diagnóstico
- **THEN** el objeto devuelto contiene todos los campos del contrato y la fuente de la tasa

#### Scenario: Entrada incompleta
- **WHEN** falta un insumo obligatorio
- **THEN** la validación falla y no se calcula un resultado parcial

#### Scenario: Revisión posterior
- **WHEN** se audita un resultado
- **THEN** se pueden reproducir las cifras con los insumos y la versión de fórmula guardados
