# Spec Delta

## ADDED Requirements

### Requirement: Interrupción y reanudación HITL

El grafo SHALL poder suspender un turno con `interrupt()` y reanudarlo después con `Command(resume=...)` sobre el mismo checkpoint. Una suspensión MUST dejar el hilo en un estado identificable, MUST NOT consumir la respuesta final y MUST admitir una sola reanudación por interrupción.

#### Scenario: Turno suspendido
- **WHEN** un nodo llama a `interrupt()` con el caso del asesor
- **THEN** el grafo termina la ejecución sin respuesta final y el estado queda suspendido

#### Scenario: Reanudación correcta
- **WHEN** llega `Command(resume={"accion": "contactar"})`
- **THEN** el grafo continúa desde el nodo interrumpido y produce la respuesta final

#### Scenario: Doble reanudación
- **WHEN** se intenta reanudar dos veces la misma interrupción
- **THEN** la segunda reanudación se rechaza sin duplicar el caso ni la respuesta

#### Scenario: Hilo sin suspensión
- **WHEN** se reanuda un hilo que no está suspendido
- **THEN** el grafo responde un error explicable y no crea un turno nuevo

### Requirement: Bifurcación de checkpoints

El grafo SHALL permitir crear una rama a partir de un checkpoint terminado, con un `thread_id` nuevo, para recalcular un escenario sin alterar el hilo original. La rama MUST heredar solo el estado necesario y MUST quedar aislada del historial original.

#### Scenario: Rama creada
- **WHEN** se bifurca el diagnóstico con un cambio de plazo
- **THEN** se crea un `thread_id` nuevo con el estado del diagnóstico y el cambio aplicado

#### Scenario: Original sin cambios
- **WHEN** termina la comparación
- **THEN** el checkpoint y los mensajes del hilo original no cambian

#### Scenario: Rama sin checkpoint
- **WHEN** se intenta bifurcar un hilo que no tiene diagnóstico terminado
- **THEN** se responde un error explicable y no se crea la rama

### Requirement: Hilos y namespaces por usuario

El grafo SHALL aislar la memoria por canal y por usuario: cada usuario del canal MUST tener su propio `thread_id` y su propio namespace del Store, y la Ventanilla MUST conservar los suyos. Ningún turno MUST leer el historial, el perfil o la caché de otro usuario.

#### Scenario: Aislamiento entre canales
- **WHEN** el mismo texto llega desde la Ventanilla y desde WhatsApp
- **THEN** cada conversación usa su propio hilo y no comparte historial

#### Scenario: Aislamiento entre usuarios
- **WHEN** dos usuarios del canal conversan a la vez
- **THEN** ninguno ve el perfil ni los mensajes del otro

#### Scenario: Namespace estable
- **WHEN** un usuario vuelve después de reiniciar el servidor
- **THEN** recupera su namespace y su perfil, no los de otro usuario
