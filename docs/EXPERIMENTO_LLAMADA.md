# Experimento: llamada de voz por WhatsApp

OpenSpec `corresponsal-whatsapp`, tarea 8.1 y decisión 17. Responsable: Yoldy.

| Campo | Valor |
| --- | --- |
| Fecha de la decisión | 2026-11-20 (viernes; la prueba estaba planeada para el martes 17) |
| Número de negocio | Número de prueba de Meta (*Public Test Number*) del canal |
| Resultado | La prueba en vivo no se ejecutó: el tiempo se usó en el canal de texto. El análisis previo muestra que el audio en tiempo real no cabe antes del sábado 21. |
| Decisión | **Aplazado** |

> Este documento no guarda números de teléfono, tokens ni capturas con datos personales (Ley 1581 de 2012).

## 1. Pregunta

¿Puede la Sucursal 1965 atender una **llamada de voz por WhatsApp** con el número de prueba de Meta dentro del plazo de la entrega (congelamiento el sábado 21)? La alternativa que se usa si no se puede es el canal de texto, que no depende de esta decisión.

## 2. Qué sabemos antes de probar

Fuentes leídas el 2026-11-16. La página oficial de Meta (`developers.facebook.com/docs/whatsapp/cloud-api/calling/`) no se pudo abrir desde la herramienta de consulta, así que estos datos salen de documentación de socios de Meta y **se confirman en el panel de Meta durante la prueba**.

| Tema | Lo que dicen las fuentes | Qué significa para nosotros |
| --- | --- | --- |
| Número de prueba | Los números de prueba tienen límites relajados: no exigen el mínimo de 2.000 destinatarios diarios. Las llamadas vienen **desactivadas** y hay que activarlas. | La prueba es posible sin verificación empresarial. |
| Activación | `POST /<PHONE_NUMBER_ID>/settings` con `{"calling": {"status": "ENABLED"}}` y suscribir el webhook al campo `calls`. | Lo hace quien administra la app de Meta (Darley). |
| Medio de pago | Se pide un método de pago o línea de crédito en la cuenta de WhatsApp Business **incluso para recibir llamadas**. | **Posible bloqueo**: el equipo no tiene tarjeta registrada en Meta. |
| Colombia | Las llamadas que inicia el usuario funcionan donde funciona Cloud API. Las que inicia el negocio no están bloqueadas para Colombia. | No hay bloqueo por país. |
| Costo | Las llamadas que inicia el usuario son gratis. Las que inicia el negocio se cobran por pulsos de 6 segundos. | Solo probaríamos llamadas entrantes (gratis). |
| Audio | La señalización llega por webhook con una oferta SDP; el audio es **WebRTC** (ICE, DTLS, SRTP, códec OPUS). El servidor debe responder con su propia SDP y manejar el audio. | Hace falta una pila WebRTC en el servidor (por ejemplo `aiortc`), además de voz a texto y texto a voz en tiempo real. |
| Red | Meta no permite telefonía tradicional (PSTN) en ningún tramo de la llamada. | No sirve un puente telefónico tipo Twilio. |
| Límites | Máximo 100 llamadas conectadas por día entre el negocio y un usuario. | Suficiente para una demo. |

## 3. Protocolo de la prueba (planeado para el martes 17)

Requiere que el canal de Darley ya tenga la app de Meta, el número de prueba y el webhook recibiendo mensajes por el túnel.

1. En el panel de Meta, confirmar si el número de prueba muestra la opción de llamadas y si pide medio de pago. **Si pide medio de pago y no lo hay, la prueba termina aquí: descartado.**
2. Activar las llamadas con `POST /<PHONE_NUMBER_ID>/settings` (`calling.status = ENABLED`) y suscribir la app al campo `calls`.
3. Desde uno de los cinco teléfonos autorizados, llamar al número de prueba por WhatsApp.
4. Revisar en el registro del webhook (sin guardar el número) si llega el evento de llamada con la oferta SDP.
5. Si llega, intentar contestar con una SDP de respuesta desde un script de prueba fuera del repositorio, solo para ver si se establece el audio (no se integra al grafo).
6. Anotar en la sección 4 qué pasó en cada paso, con la hora.

Tiempo máximo de la prueba: **2 horas**. Si al cumplirse no hay audio, se registra como aplazado o descartado.

## 4. Resultado

| Paso | ¿Funcionó? | Observación |
| --- | --- | --- |
| 1. Opción de llamadas en el panel | No se hizo | El equipo priorizó dejar el canal de texto funcionando de punta a punta. |
| 2. Activación y webhook `calls` | No se hizo | Se prioriza el canal de texto, que ya recibe mensajes. |
| 3. Llamada desde un número autorizado | No se hizo | |
| 4. Evento con oferta SDP | No se hizo | |
| 5. Audio establecido | No se hizo | |

## 5. Criterios de decisión

| Decisión | Cuándo |
| --- | --- |
| **Adoptado** | Pasos 1 a 5 funcionan el martes y quedan al menos 3 días para integrar voz a texto, el grafo y texto a voz antes del sábado 21. |
| **Aplazado** | El evento de llamada llega (paso 4), pero el audio en tiempo real no cabe en el plazo. Se documenta como trabajo futuro. |
| **Descartado** | Meta exige medio de pago o verificación, o el número de prueba no ofrece llamadas, o no llega el evento. |

## 6. Decisión y justificación

**Aplazado** como trabajo futuro. Según las fuentes, el número de prueba puede activar llamadas, pero contestar exige una pila WebRTC en el servidor (ICE, DTLS, SRTP y OPUS) y encadenar voz a texto, el grafo y texto a voz con baja latencia. Con el congelamiento el sábado 21, ese trabajo no cabe sin quitar tiempo al canal de texto, que ya recibe mensajes por el webhook. Las notas de voz quedan como alternativa más barata si el equipo la aprueba.

**Hipótesis antes de probar:** lo más probable es **aplazado o descartado**. Aunque la señalización sea posible, contestar exige montar WebRTC en el servidor y encadenar voz a texto, el grafo y texto a voz con baja latencia, que es más trabajo del que cabe hasta el sábado 21. El resto del cambio (canal de texto, diagnóstico, HITL, comité, Roba la Bóveda) no depende de esta decisión.

## Fuentes

- Dualhook, documentación de Cloud API Calling (socio de Meta): <https://dualhook.com/docs/calling>, <https://dualhook.com/docs/calling-configuration>, <https://dualhook.com/docs/calling-permissions>, <https://dualhook.com/docs/calling-pricing>
- WATI, *WhatsApp Business Calling API: 2026 Setup & Eligibility Guide* (4 de noviembre de 2026): <https://www.wati.io/en/blog/gcr-seo-whatsapp-business-calling-api-complete-guide-2026-1/>
- Meta for Developers, *Calling – WhatsApp Cloud API* (para confirmar durante la prueba): <https://developers.facebook.com/docs/whatsapp/cloud-api/calling/>
