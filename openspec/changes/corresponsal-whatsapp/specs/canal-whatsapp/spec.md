# Spec Delta

## Purpose

Recibir, verificar e identificar los mensajes de WhatsApp de la Sucursal 1965, para que el grafo existente responda por un canal real con consentimiento, aislamiento por usuario y envío trazable.

## ADDED Requirements

### Requirement: Verificación del webhook

El canal SHALL exponer una verificación `GET` para Meta Cloud API que compare `hub.mode` con `subscribe` y `hub.verify_token` con el token del entorno. Si ambos coinciden, MUST devolver el `hub.challenge` como texto plano; en cualquier otro caso MUST responder 403 sin revelar el token esperado.

#### Scenario: Verificación correcta
- **WHEN** Meta envía `hub.mode=subscribe` y el token correcto
- **THEN** el webhook responde 200 con el `hub.challenge` exacto

#### Scenario: Token incorrecto
- **WHEN** el token no coincide o falta `hub.mode`
- **THEN** el webhook responde 403 y no registra el valor recibido

#### Scenario: Token ausente en el entorno
- **WHEN** el servidor arranca sin `WHATSAPP_VERIFY_TOKEN`
- **THEN** la verificación falla de forma explicable y el canal queda deshabilitado, sin usar un valor por defecto

### Requirement: Firma del webhook

El canal SHALL validar cada `POST` con la cabecera `X-Hub-Signature-256`, calculando HMAC-SHA256 sobre el cuerpo crudo con `WHATSAPP_APP_SECRET` y comparando en tiempo constante. Una firma ausente o inválida MUST responder 401 y MUST NOT encolar ni procesar el mensaje.

#### Scenario: Firma válida
- **WHEN** la firma corresponde al cuerpo y al secreto configurado
- **THEN** el mensaje pasa a deduplicación y se procesa

#### Scenario: Firma inválida
- **WHEN** el cuerpo cambia después de firmar o el secreto no coincide
- **THEN** responde 401 y no se crea ningún registro de mensaje

#### Scenario: Cuerpo alterado
- **WHEN** se recalcula la firma sobre el JSON reserializado en vez del cuerpo crudo
- **THEN** la validación falla, porque el contrato exige el cuerpo original

### Requirement: Respuesta inmediata y procesamiento en segundo plano

El canal SHALL responder 200 a Meta en cuanto la firma y el id del mensaje son válidos, sin esperar la respuesta del grafo. El procesamiento MUST continuar en segundo plano y un fallo posterior MUST quedar registrado sin cambiar la respuesta ya enviada.

#### Scenario: Respuesta dentro del plazo
- **WHEN** llega un mensaje de texto válido
- **THEN** el webhook responde 200 en menos de un segundo y el turno sigue en segundo plano

#### Scenario: Fallo del grafo
- **WHEN** el grafo tarda o falla después del 200
- **THEN** el error se registra sin PII y Meta no recibe un 500 por ese mensaje

#### Scenario: Evento sin texto
- **WHEN** llega un estado de entrega, una imagen o un audio
- **THEN** el webhook responde 200 y no intenta responder con el grafo

### Requirement: Deduplicación por id de mensaje

El canal SHALL registrar el id de cada mensaje entrante antes de procesarlo y MUST ignorar los reintentos con el mismo id. La deduplicación MUST sobrevivir a un reinicio del proceso y MUST NOT depender de la memoria del servidor.

#### Scenario: Primer mensaje
- **WHEN** llega un id desconocido
- **THEN** se registra y se procesa una sola vez

#### Scenario: Reintento de Meta
- **WHEN** Meta reenvía el mismo id minutos después
- **THEN** responde 200 y no se ejecuta un segundo turno ni se envía una segunda respuesta

#### Scenario: Reinicio del servidor
- **WHEN** el proceso se reinicia y llega un id ya visto
- **THEN** la deduplicación lo reconoce porque vive en almacenamiento local persistente

### Requirement: Números autorizados

El canal SHALL aceptar mensajes solo de los cinco números de prueba declarados en configuración y normalizados en formato E.164. Un número no autorizado MUST recibir un aviso breve y MUST NOT crear perfil, consentimiento ni turno en el grafo.

#### Scenario: Número de la lista
- **WHEN** escribe uno de los cinco números autorizados
- **THEN** el mensaje sigue el flujo normal de consentimiento e identificación

#### Scenario: Número desconocido
- **WHEN** escribe un número fuera de la lista
- **THEN** se responde que el canal está en prueba y no se guarda ningún dato del remitente

#### Scenario: Formato del número
- **WHEN** el mismo número llega con o sin el prefijo de país
- **THEN** se normaliza al mismo E.164 antes de comparar y de calcular el usuario

### Requirement: Identificación por número

El canal SHALL calcular `usuario_id` como HMAC-SHA256 del número normalizado con `WHATSAPP_ID_SALT`. El número en claro MUST NOT guardarse en perfiles, checkpoints, caché, marcadores ni logs; el `usuario_id` MUST ser estable entre reinicios y MUST cambiar si cambia la sal.

#### Scenario: Mismo número, mismo usuario
- **WHEN** el mismo número vuelve a escribir después de un reinicio
- **THEN** obtiene el mismo `usuario_id` y recupera su perfil

#### Scenario: Sin número en claro
- **WHEN** se revisan la base de perfiles, los checkpoints y los logs
- **THEN** no aparece el número, solo su HMAC

#### Scenario: Sal distinta
- **WHEN** se cambia `WHATSAPP_ID_SALT`
- **THEN** los usuarios anteriores quedan aislados y no se mezclan con los nuevos

### Requirement: Perfil y aislamiento por usuario

El canal SHALL mantener un perfil mínimo por `usuario_id` con nombre y rol `cliente` o `asesor`, fuera del repositorio. Cada usuario MUST tener su propio `thread_id` y su propio namespace del Store; MUST NOT compartir historial, perfil ni caché con otro usuario.

#### Scenario: Dos usuarios
- **WHEN** dos números autorizados conversan a la vez
- **THEN** cada uno ve solo su historial y su perfil

#### Scenario: Perfil fuera de Git
- **WHEN** se revisa el repositorio después de conversar
- **THEN** los perfiles y las bases del canal no aparecen versionados

#### Scenario: Rol del perfil
- **WHEN** un perfil se registra como asesor
- **THEN** el rol queda disponible para las respuestas y para el tablero de operación, sin datos de clientes

### Requirement: Consentimiento de datos personales

Antes de la primera respuesta funcional, el canal SHALL presentar el aviso de tratamiento de datos de la Ley 1581 de 2012 y un botón «Acepto». Sin aceptación MUST responder solo el aviso y las opciones de aceptar o retirarse. La aceptación MUST registrar fecha, versión del aviso y `usuario_id`; el usuario MUST poder revocar el consentimiento y borrar su perfil.

#### Scenario: Primer contacto
- **WHEN** un número autorizado escribe por primera vez
- **THEN** recibe el aviso y el botón «Acepto», y no recibe una respuesta del grafo

#### Scenario: Aceptación
- **WHEN** el usuario pulsa «Acepto»
- **THEN** se registra el consentimiento y el siguiente mensaje ya se atiende con el grafo

#### Scenario: Rechazo o silencio
- **WHEN** el usuario no acepta
- **THEN** no se crea perfil funcional ni se procesan preguntas

#### Scenario: Revocación
- **WHEN** el usuario pide «olvida mis datos»
- **THEN** se borran perfil y consentimiento y se confirma la revocación

### Requirement: Envío real y envío falso

El canal SHALL enviar respuestas por la API de Meta con `timeout` explícito cuando el modo real esté habilitado, y MUST ofrecer un modo falso que registre el envío sin red para pruebas y demostraciones. El modo MUST seleccionarse por configuración del entorno; el real MUST rechazar cualquier destino que no sea uno de los cinco números autorizados.

#### Scenario: Envío real
- **WHEN** el modo real está activo y el destino es autorizado
- **THEN** se envía el texto y se registra el id de salida sin guardar el token

#### Scenario: Envío falso
- **WHEN** el modo falso está activo
- **THEN** la respuesta se guarda en la bandeja local y no hay petición a Meta

#### Scenario: Destino no autorizado
- **WHEN** el modo real intenta enviar a un número fuera de la lista
- **THEN** el envío se rechaza y se registra el intento sin el número en claro

### Requirement: Contratos compartidos del canal

El canal SHALL validar los mensajes y las respuestas con los modelos Pydantic `MensajeEntrante`, `RespuestaCanal` y `PerfilUsuario`. `MensajeEntrante` MUST rechazar payloads sin id, remitente o texto; `RespuestaCanal` MUST distinguir texto, botones, lista, error e imagen, y MUST NOT mezclar botones, filas de lista e imagen en el mismo mensaje; `PerfilUsuario` MUST limitar el rol a `cliente` o `asesor`.

#### Scenario: Payload válido
- **WHEN** llega un texto con id, remitente y cuerpo
- **THEN** se construye `MensajeEntrante` y el flujo continúa

#### Scenario: Payload incompleto
- **WHEN** falta el id o el remitente
- **THEN** el mensaje se descarta con un error registrado y sin respuesta al usuario

#### Scenario: Lista interactiva
- **WHEN** una respuesta lleva más de tres opciones
- **THEN** viaja como lista con hasta diez filas y sin botones

#### Scenario: Rol inválido
- **WHEN** un perfil declara un rol distinto de cliente o asesor
- **THEN** la validación falla y no se guarda el perfil

### Requirement: Entrevista del diagnóstico en el canal

Con consentimiento, el canal SHALL atender la entrevista del diagnóstico antes del grafo: una pregunta por turno, con botones hasta tres opciones y lista cuando hay más. La sesión MUST guardar solo los ids canónicos por `usuario_id`, MUST borrarse al terminar o al cancelar, y el resultado MUST enviar el texto del motor y la tarjeta de Pana como imagen. «Asesor» MUST dejar un caso en la tabla `casos` sin nombre ni número.

#### Scenario: Invitación
- **WHEN** un usuario con consentimiento pide un diagnóstico y no tiene entrevista en curso
- **THEN** recibe la invitación con «Empezar» y «Ahora no» sin llamar al modelo

#### Scenario: Un paso por turno
- **WHEN** el usuario elige una de las opciones de la pregunta pendiente
- **THEN** el canal confirma lo anotado y envía el paso siguiente, sin repetir preguntas

#### Scenario: Respuesta fuera de la lista
- **WHEN** el usuario escribe algo que no es una de las opciones
- **THEN** la entrevista no avanza y se repite la pregunta con el aviso

#### Scenario: Resultado con tarjeta
- **WHEN** se responde el último paso
- **THEN** el canal calcula con el motor, envía el texto del resultado y después la tarjeta PNG

#### Scenario: Cancelar o pedir asesor
- **WHEN** el usuario escribe «cancelar» o «asesor», o toca su botón
- **THEN** la sesión se borra y responde el texto fijo; «asesor» además deja el caso sin datos personales

### Requirement: Servidor local con túnel externo

El webhook SHALL servirse desde la misma app FastAPI que escucha solo en `127.0.0.1`. La exposición a Meta MUST hacerse con un túnel externo al proceso y MUST NOT cambiar el host de uvicorn ni abrir `0.0.0.0`.

#### Scenario: Escucha local
- **WHEN** se arranca `make app`
- **THEN** uvicorn sigue en `127.0.0.1:8000` y el webhook está en una ruta local

#### Scenario: Túnel
- **WHEN** se publica el webhook para la prueba de Meta
- **THEN** el túnel es un proceso aparte y la configuración del servidor no cambia

#### Scenario: Sin exposición accidental
- **WHEN** se revisa la configuración y los comandos del canal
- **THEN** no hay un host público ni un flag para abrirlo

### Requirement: Tarjetas de Pana con imagen

El canal SHALL poder acompañar el diagnóstico y el «¿Y si…?» con una tarjeta PNG de Pana, el personaje del asistente. La tarjeta MUST acompañar al texto y MUST NOT reemplazarlo: el texto lleva los mismos datos (semáforo, cuota en rango, tasa con vigencia y fuente, y el aviso). La imagen MUST NOT llevar nombre, número ni documento de la persona, MUST generarse en memoria y MUST NOT guardarse en disco después del envío. El aviso MUST decir que Pana es el asistente de un proyecto académico, no del banco. Se usa Pillow con versión fija y una fuente libre versionada en el repositorio con su licencia. Los stickers quedan fuera de este cambio.

#### Scenario: Texto antes que la imagen
- **WHEN** la respuesta trae tarjeta y el canal está en modo real o falso
- **THEN** el texto sale primero y la imagen después, con los mismos datos

#### Scenario: Texto completo aunque falle la imagen
- **WHEN** el envío de la tarjeta falla
- **THEN** la persona ya recibió el texto con los mismos datos

#### Scenario: Sin datos personales en la imagen
- **WHEN** se intenta crear una tarjeta con un teléfono o un documento en un texto, o con un campo de nombre
- **THEN** la validación lo rechaza y no se genera la imagen

#### Scenario: Igual en Windows y en la CI
- **WHEN** se genera la misma tarjeta dos veces
- **THEN** salen los mismos bytes, con la fuente del repositorio y no la del sistema
