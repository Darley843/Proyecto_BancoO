# Diagramas de la entrega final

Siete diagramas para explicar Sucursal 1965 en la parte técnica de la
sustentación. Cada uno se lee de izquierda a derecha o de arriba abajo. El
recorrido completo está en el [README](../README.md#arquitectura-de-la-entrega-final)
y el encendido paso a paso en [`DESPLIEGUE.md`](./DESPLIEGUE.md).

| # | Diagrama | Qué responde |
|---|---|---|
| 1 | [Canal de Meta](#1-canal-de-meta) | ¿Qué pasa con un mensaje de WhatsApp antes de llegar a Pana? |
| 2 | [Gateway de OpenClaw](#2-gateway-de-openclaw) | ¿Cómo habla el canal con el agente y qué pasa si se cae? |
| 3 | [MCP y herramientas](#3-mcp-y-herramientas) | ¿Qué puede hacer el agente y de dónde salen las cifras? |
| 4 | [Comité de crédito](#4-comité-de-crédito) | ¿Quién decide qué recomendar en un caso amarillo o rojo? |
| 5 | [Auditor](#5-auditor) | ¿Qué revisa cada respuesta antes de salir? |
| 6 | [RAG de la Bóveda](#6-rag-de-la-bóveda) | ¿Cómo encuentra Pana el documento correcto? |
| 7 | [Escena en pantalla](#7-escena-en-pantalla) | ¿Cómo llegan los turnos a la pantalla con voz y subtítulos? |

## 1. Canal de Meta

```mermaid
flowchart LR
    I["Invitado<br/>su WhatsApp"] --> M["Meta<br/>WhatsApp Cloud API"]
    M -->|"POST /webhook<br/>firma X-Hub-Signature-256"| T["Túnel<br/>cloudflared"]
    T --> W["Webhook<br/>verifica firma<br/>descarta repetidos"]
    W --> Q["Cola<br/>un mensaje a la vez<br/>por persona"]
    Q --> H["Huella HMAC<br/>del número"]
    H --> A{"¿Número<br/>autorizado?"}
    A -->|"no"| X["Se ignora"]
    A -->|"sí"| C{"¿Aceptó el<br/>aviso Ley 1581?"}
    C -->|"no"| AV["Envía el aviso<br/>y espera «Acepto»"]
    C -->|"sí"| P["Pana responde<br/>(diagrama 2)"]
    P --> E["Enviador Meta<br/>texto, botones,<br/>imagen o audio"]
    E --> M
```

- El número de teléfono **nunca sale del canal**: todo lo demás trabaja con la
  huella. El número y el texto no se escriben en los logs.
- «Olvida mis datos» borra consentimiento, entrevistas, resultados y casos.
- Código: `canal/webhook.py`, `canal/cola.py`, `canal/identidad.py`,
  `canal/consentimiento.py`, `canal/despachador.py`, `canal/envio.py`.

## 2. Gateway de OpenClaw

```mermaid
sequenceDiagram
    participant C as Canal (FastAPI)
    participant O as OpenClaw (agente Pana)
    participant P as Servidor MCP
    participant G as Grafo actual (respaldo)
    C->>O: POST /v1/chat/completions<br/>texto + huella, token, 127.0.0.1
    O->>O: workspace de Pana<br/>identidad, reglas, límites
    O->>P: llama herramientas (diagrama 3)
    P-->>O: resultado con fuente
    O-->>C: respuesta de Pana
    alt OpenClaw no responde a tiempo
        C->>G: misma pregunta, hilo wa:huella
        G-->>C: respuesta del grafo
    end
```

- El gateway escucha solo en `127.0.0.1` y pide token: no queda expuesto a
  internet. El túnel solo publica el webhook del canal.
- Si OpenClaw falla, el invitado igual recibe respuesta: la da el grafo de
  LangGraph que ya funcionaba (digiturno, Bóveda, entrevista, tarjeta).
- ⏳ Puerto, modelo y archivos del workspace: los completa Nayla en
  [`DESPLIEGUE.md`](./DESPLIEGUE.md#5-gateway-de-openclaw).

## 3. MCP y herramientas

```mermaid
flowchart TB
    O["Agente Pana<br/>OpenClaw"] --> P["Servidor MCP<br/>esquemas Pydantic"]
    P --> N["Crédito y escena<br/>(Nayla)<br/>tasa · cuota · usura<br/>capacidad · ¿Y si…?<br/>comité · Don Gota<br/>negociación · ficha"]
    P --> D["Persona y canal<br/>(Darley)<br/>consentimiento<br/>olvidar datos ✋<br/>asesor ✋ · caso · tarjeta"]
    P --> A["Documentos y control<br/>(Anny)<br/>Bóveda · tarifas<br/>clasificar · auditar"]
    N --> F1["config/tasas.toml<br/>motor del diagnóstico"]
    D --> F2["whatsapp.sqlite<br/>(solo huellas)"]
    A --> F3["Bóveda (Qdrant)<br/>Tablero de tasas"]
```

- ✋ = la herramienta pide confirmación de la persona antes de actuar.
- Las cifras **siempre** salen de código o de configuración con fuente; el
  modelo no inventa tasas ni cuotas.
- Lista completa: [las 20 herramientas](../README.md#las-20-herramientas).

## 4. Comité de crédito

```mermaid
flowchart LR
    M["Motor del diagnóstico<br/>calcula el semáforo"] --> S{"¿Semáforo?"}
    S -->|"verde"| V["Respuesta directa<br/>sin comité"]
    S -->|"amarillo o rojo"| E["Escenarios<br/>precalculados<br/>plazo · monto · cartera"]
    E --> R["Riesgo<br/>¿la cuota es sostenible?"]
    E --> CO["Comercial<br/>hasta 2 alternativas<br/>de los escenarios"]
    R --> AU["Auditor<br/>cifras, promesas,<br/>aviso"]
    CO --> AU
    AU --> SI["Síntesis determinista<br/>gana la postura<br/>más prudente"]
    SI --> PE["Recomendación<br/>a la persona"]
```

- El comité **no cambia el semáforo**: solo decide qué recomendar.
- Una ronda, máximo 4 llamadas al modelo y 30 segundos. Si el auditor objeta
  dos veces, se responde con el texto del diagnóstico.
- Nunca recibe el nombre ni el número de la persona.
- Código: `diagnostico/comite.py`. Detalle: [`COMITE.md`](./COMITE.md).

## 5. Auditor

```mermaid
flowchart LR
    T["Texto que va<br/>a salir"] --> C1["¿Cada cifra existe<br/>en los cálculos?"]
    C1 --> C2["¿Promete aprobación?<br/>«aprobado», «te lo damos»"]
    C2 --> C3["¿Ofrece algo fuera<br/>de los escenarios?"]
    C3 --> C4["¿Tiene el aviso<br/>«orientativo»?"]
    C4 --> C5["¿Trae datos<br/>personales?"]
    C5 --> V{"Veredicto"}
    V -->|"conforme"| OK["Sale el texto"]
    V -->|"objeta"| CO["Una corrección<br/>o texto de respaldo"]
```

- Es **código**, no solo un prompt: `auditar_texto` en
  `diagnostico/comite.py` lo usan el comité, la escena y la herramienta
  `auditar_respuesta`.
- En la pantalla, el veredicto aparece solo después de que el auditor habla.

## 6. RAG de la Bóveda

```mermaid
flowchart LR
    subgraph IN["Indexar (una vez: make indice)"]
        G["Gold<br/>páginas del banco"] --> FR["Fragmentos<br/>con tipo y fuente"]
        FR --> EM["Embeddings<br/>Ollama local"]
        EM --> QD["Qdrant<br/>índice vectorial"]
        FR --> BM["BM25<br/>palabras clave"]
    end
    subgraph BU["Buscar (cada pregunta)"]
        P["Pregunta"] --> V2["Vector de<br/>la pregunta"]
        V2 --> QD
        P --> BM
        QD --> EN["Fusión híbrida<br/>pesos configurables"]
        BM --> EN
        EN --> R["Fragmentos citados<br/>documento + enlace"]
    end
```

- Híbrido: el vector entiende el sentido, BM25 atrapa nombres exactos
  («Crediestudiantil», «GMF»).
- Cada respuesta cita el documento y el fragmento de donde salió.
- Código: `boveda/recuperador.py`, `boveda/indice.py`.

## 7. Escena en pantalla

```mermaid
flowchart LR
    subgraph SE["Servidor"]
        EC["Escena<br/>Don Gota · Pana<br/>negociación · auditor"] --> API["GET /api/escena/proyectado"]
        PR["Pregunta del público"] --> AP["POST /api/escena/pregunta"]
    end
    subgraph PA["Pantalla (Edge, F11)"]
        API --> TU["Turnos<br/>TurnoEscena"]
        AP --> TU
        TU --> VO["Voz<br/>Edge o Piper"]
        TU --> SU["Subtítulos<br/>y fuente"]
        TU --> TR["Trazabilidad<br/>tecla T"]
    end
    TU -.->|"sin servidor"| RS["Escena guardada<br/>o turnos de ejemplo"]
```

- Cada turno trae quién habla, el texto, las cifras con su fuente y lo que
  dijo el auditor. La fuente va en el subtítulo, no en la voz.
- Si falla la voz: modo **solo subtítulos** (tecla S). Si falla el servidor:
  la pantalla usa la última escena guardada.
- Don Gota **nunca** es un modelo: sus cifras salen de `escena/gota.py`.
- Teclas y ensayo: [`ESCENA.md`](./ESCENA.md).
