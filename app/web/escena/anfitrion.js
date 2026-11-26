/**
 * Sucursal 1965 · Pana como anfitrión de la escena «Pana vs. el gota a gota».
 *
 * Dos partes:
 *
 * 1. **Presentación**: Pana se presenta, presenta a cada agente (cada uno dice
 *    una frase con su voz) y anuncia la actividad práctica. Es un guion fijo
 *    (`origen: "guion_fijo"`); `GET /api/escena/introduccion` puede reemplazarlo.
 * 2. **Preguntas del público**: primero las reglas fijas de la página
 *    (pregunta vacía o larga, datos personales, Karol G y Shakira); luego
 *    `POST /api/escena/pregunta` (tarea 6.13), que enruta a la ficha de
 *    preguntas del profesor, al proyecto o al banco. Si el servidor no
 *    responde, la **ficha corta de respaldo** de este archivo contesta lo más
 *    probable del proyecto y lo demás recibe «No tengo información sobre eso».
 *
 * Todos los turnos cumplen el contrato de `contrato.js`. La pregunta del
 * público es un dato no confiable: no se guarda y nunca cambia lo que hace
 * Pana. Este módulo no toca la página.
 */

import { erroresDelTurno } from "./contrato.js";

/** Rutas del servidor (las publica el orquestador de la escena). */
const RUTA_INTRODUCCION = "/api/escena/introduccion";
const RUTA_PREGUNTA = "/api/escena/pregunta";

/** Largo máximo de una pregunta del público, en caracteres. */
export const LARGO_MAXIMO = 300;

/**
 * Arma un turno `TurnoEscena` sin cifras, escenario ni hallazgos.
 *
 * @param {string} personaje Quién habla.
 * @param {string} texto Lo que dice.
 * @param {"guion_fijo" | "reglas" | "llm"} origen De dónde sale el texto.
 * @param {string} [id] Identificador del turno.
 * @param {number} [orden] Posición del turno.
 * @returns {object} Turno que cumple el contrato.
 */
export function turnoSimple(personaje, texto, origen, id = "pana.respuesta", orden = 0) {
  return {
    id,
    orden,
    personaje,
    texto,
    cifras: [],
    escenario: null,
    origen,
    hallazgos: [],
  };
}

/** Guion fijo de la presentación (siete turnos, ids `anfitrion.presentacion.N`). */
export const INTRODUCCION = Object.freeze(
  [
    turnoSimple(
      "pana",
      "¡Hola a todos! Soy Pana, un agente de inteligencia artificial que acompaña a jóvenes que van a pedir su primer crédito. Hoy no hay diapositivas: vamos a hacer una actividad práctica, en vivo, y ustedes participan desde su celular.",
      "guion_fijo",
    ),
    turnoSimple(
      "pana",
      "Muchos jóvenes terminan en el gota a gota: presta rápido, pero cobra cerca de 791 % efectivo anual, casi 28 veces la usura. Les presento a mi equipo: todos somos agentes de inteligencia artificial, menos el villano, que es un guion.",
      "guion_fijo",
    ),
    turnoSimple(
      "don_gota",
      "Yo soy Don Gota, el prestamista gota a gota. Presto rápido y sin papeles… pero cobro el veinte por ciento cada mes.",
      "guion_fijo",
    ),
    turnoSimple(
      "agente_joven",
      "Yo soy el agente del joven: defiendo a nuestro voluntario y cuido que la cuota le quepa en el bolsillo.",
      "guion_fijo",
    ),
    turnoSimple(
      "agente_banco",
      "Yo soy la agente del banco: pongo sobre la mesa las condiciones y las tasas que el banco publica.",
      "guion_fijo",
    ),
    turnoSimple(
      "auditor",
      "Yo soy el auditor: reviso que cada cifra exista, venga de una fuente y cuadre. Si algo no cuadra, lo digo.",
      "guion_fijo",
    ),
    turnoSimple(
      "pana",
      "Los protagonistas son ustedes: elegiré a un voluntario y los demás pueden escribirme por WhatsApp, siempre con datos inventados. Uso las tasas que publica el Banco de Occidente, pero soy un proyecto académico. Al final, háganme preguntas.",
      "guion_fijo",
    ),
  ].map((turno, orden) => Object.freeze({ ...turno, id: `anfitrion.presentacion.${orden + 1}`, orden })),
);

/** Lo que dice Pana al abrir las preguntas (incluye el aviso de privacidad). */
export const APERTURA_PREGUNTAS = Object.freeze(
  turnoSimple(
    "pana",
    "¡Ahora sí, pregúntenme! Respondo sobre el proyecto, la tecnología, las decisiones del equipo y la actividad de hoy. Ojo: el micrófono usa el reconocimiento de voz de Microsoft Edge.",
    "guion_fijo",
    "anfitrion.apertura_preguntas",
  ),
);

/** Respuestas fijas de las reglas. */
export const RESPUESTAS = Object.freeze({
  invalida: "No alcancé a entender la pregunta. ¿Me la repites más corta?",
  datos_personales:
    "Prefiero no recibir datos personales aquí. Pregúntame sin números de documento, teléfonos ni correos.",
  artistas:
    "Sé que al profesor Jan le gustan mucho Karol G y Shakira, ¡y a nosotros también! Pero eso no tiene nada que ver con nuestro proyecto. Si quieren, les cuento cómo funciona Pana.",
  fuera_de_tema:
    "No tengo información sobre eso; del proyecto sí les cuento. Para productos y tasas, escríbanme por WhatsApp.",
});

/**
 * Ficha corta de respaldo, solo para cuando el servidor no responde: preguntas
 * del proyecto, la tecnología, las decisiones del equipo y la actividad.
 * Palabras clave y respuesta corta (menos de 40 palabras); gana la primera que
 * coincide. Las palabras van sin tildes. La ficha completa del presentador
 * vive en el servidor (`docs/PRESENTADOR.md`, `config/escena.toml`).
 */
const FICHA = Object.freeze([
  {
    claves: ["gota a gota", "don gota", "prestamista", "villano"],
    texto:
      "Don Gota representa al prestamista gota a gota: presta sin papeles, pero cobra cerca del veinte por ciento mensual, muy por encima de la tasa de usura. Es un guion, no una inteligencia artificial.",
  },
  {
    claves: ["auditor", "agente del joven", "agente del banco", "agentes", "negoci"],
    texto:
      "El agente del joven defiende al voluntario, la agente del banco trae las condiciones publicadas y el auditor revisa que cada cifra exista y cuadre antes del veredicto.",
  },
  {
    claves: ["qdrant", "vector", "embedding", "boveda", "bm25", "ollama", "busqueda", "rag"],
    texto:
      "La Bóveda guarda el sitio público del banco en fragmentos. Los convierte en vectores con nomic-embed-text en Ollama, los guarda en Qdrant y mezcla esa búsqueda con BM25.",
  },
  {
    claves: ["deepseek", "modelo", "llm", "inteligencia artificial", "langgraph", "langchain"],
    texto:
      "Uso DeepSeek para redactar, con LangGraph organizando los pasos. Las cifras no las inventa el modelo: salen del motor del diagnóstico y de las tasas que publica el banco.",
  },
  {
    claves: ["voz", "voces", "piper", "edge", "hablas", "suena"],
    texto:
      "Mi voz es una voz de Microsoft Edge. Las de los demás salen de Piper, que corre en este computador, y si no hay internet yo también uso Piper.",
  },
  {
    claves: ["whatsapp", "canal de"],
    texto:
      "Además de esta pantalla, atiendo por WhatsApp: hago la entrevista del diagnóstico, mando la tarjeta con el resultado y respondo el ¿Y si…?",
  },
  {
    claves: ["pull request", "repositorio", "github", "commits", "ramas"],
    texto:
      "El repositorio es público y está en GitHub. Cada cambio entra por una rama y un pull request que aprueba otra persona; la tecla G muestra su QR.",
  },
  {
    claves: ["token", "tokens", "secretos", "credencial"],
    texto:
      "Un token es una credencial, no un archivo del repositorio. Las claves van por variables de entorno y nunca se versionan; el repositorio no guarda secretos.",
  },
  {
    claves: ["codigo", "src", "organizado", "capas", "modulos"],
    texto:
      "Está en capas: corpus, asistente, Bóveda, sucursal, canal, diagnóstico y escena. Cada módulo vive en su carpeta de src y tiene su prueba en test.",
  },
  {
    claves: ["diagrama", "arquitectura", "archify"],
    texto:
      "Sí: arquitectura, flujo de datos, canal y diagnóstico son diagramas interactivos hechos con Archify. La tecla G abre el panel con los seis.",
  },
  {
    claves: ["pruebas", "pytest", "make check", "integracion continua"],
    texto:
      "Con pruebas automáticas sin red: lint, tipos y pytest. make check corre las tres y el pipeline de GitHub las repite en cada pull request.",
  },
  {
    claves: ["privacidad", "consentimiento", "1581", "datos personales", "mis datos"],
    texto:
      "Los datos del voluntario son inventados. En WhatsApp pido consentimiento antes de guardar algo, se puede revocar y los datos se borran, como pide la Ley 1581.",
  },
  {
    claves: ["publico", "jovenes", "para quien", "primer credito"],
    texto:
      "Pana es para jóvenes que piden su primer crédito: les explica en palabras sencillas si la cuota les cabe y por qué un banco es mejor que el gota a gota.",
  },
  {
    claves: ["equipo", "quienes son", "integrantes"],
    texto: "Somos Darley, Anny, Nayla y Yoldy, del curso, y construimos la Sucursal 1965 en tres fases.",
  },
  {
    claves: ["actividad", "ejercicio", "voluntario", "escena"],
    texto:
      "Un voluntario del público pide un crédito inventado, Don Gota le ofrece plata rápida, yo comparo con el banco, los agentes negocian y el auditor revisa las cifras.",
  },
  {
    // Va al final para no tapar las respuestas específicas que también
    // mencionan el proyecto: solo responde la pregunta general.
    claves: ["proyecto", "sucursal 1965", "de que se trata", "de que trata"],
    texto:
      "Somos Pana, un asistente que responde por WhatsApp con la información pública de Banco de Occidente y cita la fuente. Prepara a los jóvenes para su primer crédito. Se llama Sucursal 1965 porque el banco nació en 1965.",
  },
]);

/**
 * Pasa a minúsculas, quita tildes y deja espacios simples.
 *
 * @param {string} texto Texto de la pregunta.
 * @returns {string} Texto normalizado.
 */
export function normalizar(texto) {
  return String(texto ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Detecta lo que parece un documento, un teléfono o un correo.
 *
 * Un monto con puntos (1.000.000) no cuenta: solo ocho o más dígitos seguidos,
 * un celular de 3-3-4 dígitos o un correo.
 *
 * @param {string} texto Pregunta ya normalizada.
 * @returns {boolean} `true` si parece un dato personal.
 */
export function pareceDatoPersonal(texto) {
  const sinGuiones = texto.replace(/-/g, "");
  return (
    /\d{8,}/.test(sinGuiones) ||
    /\b\d{3} \d{3} \d{4}\b/.test(texto) ||
    /[^\s@]+@[^\s@]+\.[a-z]{2,}/.test(texto)
  );
}

/**
 * Aplica las reglas fijas antes de llamar al servidor.
 *
 * @param {string} pregunta Pregunta del público.
 * @returns {{tema: string, turno: object} | null} Respuesta fija o `null`.
 */
export function reglaFija(pregunta) {
  const texto = normalizar(pregunta);
  if (!texto || texto.length > LARGO_MAXIMO) {
    return { tema: "invalida", turno: turnoSimple("pana", RESPUESTAS.invalida, "reglas") };
  }
  if (pareceDatoPersonal(texto)) {
    return {
      tema: "invalida",
      turno: turnoSimple("pana", RESPUESTAS.datos_personales, "reglas"),
    };
  }
  if (/karol ?g\b|shakira|bichota/.test(texto)) {
    return { tema: "artistas", turno: turnoSimple("pana", RESPUESTAS.artistas, "reglas") };
  }
  return null;
}

/**
 * Busca la respuesta en la ficha del proyecto.
 *
 * @param {string} pregunta Pregunta del público.
 * @returns {{tema: string, turno: object} | null} Respuesta de la ficha o `null`.
 */
export function respuestaDeLaFicha(pregunta) {
  const texto = normalizar(pregunta);
  const entrada = FICHA.find(({ claves }) => claves.some((clave) => texto.includes(clave)));
  return entrada ? { tema: "proyecto", turno: turnoSimple("pana", entrada.texto, "reglas") } : null;
}

/**
 * Respuesta cuando ni la ficha ni el servidor responden.
 *
 * @returns {{tema: string, turno: object}} «No tengo información sobre eso».
 */
export function respuestaFueraDeTema() {
  return { tema: "fuera_de_tema", turno: turnoSimple("pana", RESPUESTAS.fuera_de_tema, "reglas") };
}

/**
 * Pide la presentación al servidor; si no responde, usa el guion fijo.
 *
 * @returns {Promise<object[]>} Turnos de la presentación.
 */
export async function cargarIntroduccion() {
  try {
    const respuesta = await fetch(RUTA_INTRODUCCION, { signal: AbortSignal.timeout(5000) });
    if (respuesta.ok) {
      const datos = await respuesta.json();
      const turnos = datos?.turnos;
      if (Array.isArray(turnos) && turnos.length > 0 && turnos.every((t) => erroresDelTurno(t).length === 0)) {
        return turnos;
      }
    }
  } catch {
    // Sin servidor: se usa el guion fijo.
  }
  return INTRODUCCION.map((turno) => ({ ...turno, cifras: [], hallazgos: [] }));
}

/**
 * Turnos del servidor que no responden la pregunta: el rechazo fijo y el
 * respaldo (`escena/pregunta.py`). Con ellos se prueba antes la ficha local.
 */
export const SIN_RESPUESTA_DEL_SERVIDOR = Object.freeze(["pana.pregunta.rechazo.v1", "pana.pregunta.respaldo.v1"]);

/**
 * Responde una pregunta del público.
 *
 * Orden: reglas fijas → servidor (`POST /api/escena/pregunta`) → ficha de
 * respaldo → «No tengo información sobre eso». El servidor debe devolver un
 * turno del contrato hablado por Pana (puede traer además `tema`); si no
 * responde, `respaldo` queda en `true`. Si el servidor contesta con su rechazo
 * o su respaldo fijo (`SIN_RESPUESTA_DEL_SERVIDOR`) y la ficha local sí tiene
 * la respuesta, gana la ficha: es mejor que «No tengo información».
 *
 * @param {string} pregunta Pregunta del público.
 * @returns {Promise<{tema: string, turno: object, respaldo: boolean}>} Respuesta.
 */
export async function responderPregunta(pregunta) {
  const fija = reglaFija(pregunta);
  if (fija) {
    return { ...fija, respaldo: false };
  }
  try {
    const respuesta = await fetch(RUTA_PREGUNTA, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pregunta: String(pregunta).trim() }),
      signal: AbortSignal.timeout(12000),
    });
    if (respuesta.ok) {
      const datos = await respuesta.json();
      const turno = datos?.turno ?? datos;
      if (erroresDelTurno(turno).length === 0 && turno.personaje === "pana") {
        const ficha = SIN_RESPUESTA_DEL_SERVIDOR.includes(turno.id) ? respuestaDeLaFicha(pregunta) : null;
        return ficha
          ? { ...ficha, respaldo: false }
          : { tema: String(datos?.tema ?? "proyecto"), turno, respaldo: false };
      }
    }
  } catch {
    // Sin servidor: responde la ficha de respaldo.
  }
  return { ...(respuestaDeLaFicha(pregunta) ?? respuestaFueraDeTema()), respaldo: true };
}
