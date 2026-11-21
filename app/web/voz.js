/**
 * Sucursal 1965 · voces de la escena «Pana vs. el gota a gota».
 *
 * Cada personaje tiene su voz y su motor, según `config/voz.toml` (lo entrega
 * `GET /api/voz/personajes`):
 *
 * - `piper`: pide el audio a `POST /api/voz`, que lo genera en el computador
 *   (el texto no sale a internet). Si no hay voz (503), no responde o el texto
 *   es muy largo, usa la voz del navegador como respaldo.
 * - `navegador`: usa directamente la voz del navegador (`speechSynthesis`) que
 *   nombra la configuración, por ejemplo una voz de Windows con acento
 *   colombiano, con su tono y su velocidad.
 *
 * Si la API no responde, todos usan el navegador con los valores de
 * `RESPALDO_NAVEGADOR`. Nunca guarda los textos.
 */

/** Personajes del contrato del turno de escena, en el orden de la escena. */
export const PERSONAJES = Object.freeze([
  "pana",
  "don_gota",
  "joven",
  "agente_joven",
  "agente_banco",
  "auditor",
]);

/**
 * Respaldo del navegador por personaje: tono (0 a 2) y velocidad (0,1 a 10).
 * Los valores separan a los rivales (Pana agudo y claro, Don Gota grave y lento).
 */
const RESPALDO_NAVEGADOR = Object.freeze({
  pana: { voz: "", tono: 1.15, velocidad: 1.0 },
  don_gota: { voz: "", tono: 0.6, velocidad: 0.9 },
  joven: { voz: "", tono: 1.35, velocidad: 1.05 },
  agente_joven: { voz: "", tono: 1.0, velocidad: 1.1 },
  agente_banco: { voz: "", tono: 0.85, velocidad: 0.95 },
  auditor: { voz: "", tono: 0.75, velocidad: 1.0 },
});

/** Promesa con la configuración de voces de la API (se pide una sola vez). */
let configuracionPedida = null;

/** Tope de caracteres que acepta `POST /api/voz`. */
const LARGO_MAXIMO_VOZ = 900;

/** Tiempo límite para recibir el audio de Pana antes de usar el navegador. */
const ESPERA_VOZ_MS = 20000;

/** Audio de Pana que suena ahora, si hay uno. */
let audioActual = null;

/** URL temporal del audio actual, para liberarla al terminar. */
let urlActual = null;

/** Cuenta cada lectura: una respuesta que llega tarde no pisa a la siguiente. */
let lecturaActual = 0;

/**
 * Indica si el navegador puede leer en voz alta por su cuenta.
 *
 * @returns {boolean} `true` si existe `speechSynthesis`.
 */
export function hayVozDelNavegador() {
  return (
    "speechSynthesis" in window &&
    typeof window.SpeechSynthesisUtterance === "function"
  );
}

/**
 * Indica si hay alguna forma de escuchar a Pana en este navegador.
 *
 * @returns {boolean} `true` si se puede reproducir audio o usar la voz del navegador.
 */
export function puedeHablar() {
  return typeof window.Audio === "function" || hayVozDelNavegador();
}

/**
 * Lee un texto con la voz de Pana, o con la del navegador si no hay otra.
 *
 * @param {string} texto Texto de Pana que se leerá.
 * @param {{alTerminar?: () => void}} [opciones] `alTerminar` se llama al acabar o al fallar.
 * @returns {Promise<"piper" | "navegador" | "ninguna" | "cancelada">} Qué voz sonó.
 */
export function decirComoPana(texto, opciones = {}) {
  return decirComo("pana", texto, opciones);
}

/**
 * Lee un texto con la voz de un personaje de la escena.
 *
 * Si `opciones.soloSubtitulos` es `true` no suena nada (modo de respaldo en
 * vivo): solo llama a `alTerminar`, para que la pantalla siga con subtítulos.
 *
 * @param {string} personaje Uno de `PERSONAJES`; otro valor habla como Pana.
 * @param {string} texto Texto que dirá el personaje.
 * @param {{alTerminar?: () => void, soloSubtitulos?: boolean}} [opciones] Ajustes de la lectura.
 * @returns {Promise<"piper" | "navegador" | "ninguna" | "cancelada">} Qué voz sonó.
 */
export async function decirComo(personaje, texto, opciones = {}) {
  const alTerminar = opciones.alTerminar ?? (() => {});
  const quien = PERSONAJES.includes(personaje) ? personaje : "pana";
  detenerVoz();
  const lectura = ++lecturaActual;
  const limpio = String(texto ?? "").trim();
  if (!limpio || opciones.soloSubtitulos) {
    alTerminar();
    return "ninguna";
  }
  const ajuste = await configuracionDe(quien);
  if (lectura !== lecturaActual) {
    return "cancelada";
  }
  if (ajuste.motor === "piper" && limpio.length <= LARGO_MAXIMO_VOZ) {
    const audio = await pedirAudio(quien, limpio);
    if (lectura !== lecturaActual) {
      return "cancelada";
    }
    if (audio && (await reproducir(audio, alTerminar))) {
      return "piper";
    }
  }
  if (lectura !== lecturaActual) {
    return "cancelada";
  }
  if (decirConElNavegador(limpio, ajuste.navegador, quien, alTerminar)) {
    return "navegador";
  }
  alTerminar();
  return "ninguna";
}

/**
 * Devuelve cómo habla un personaje: motor y voz del navegador.
 *
 * @param {string} personaje Personaje de la escena.
 * @returns {Promise<{motor: string, navegador: {voz: string, tono: number, velocidad: number}}>} Ajuste del personaje.
 */
export async function configuracionDe(personaje) {
  const todos = await pedirConfiguracion();
  return (
    todos?.[personaje] ?? {
      motor: "piper",
      navegador: RESPALDO_NAVEGADOR[personaje] ?? RESPALDO_NAVEGADOR.pana,
    }
  );
}

/**
 * Pide una sola vez a la API cómo habla cada personaje.
 *
 * @returns {Promise<Object<string, {motor: string, piper: boolean, navegador: object}> | null>} Configuración, o `null` sin API.
 */
export function pedirConfiguracion() {
  if (!configuracionPedida) {
    configuracionPedida = fetch("/api/voz/personajes", {
      signal: AbortSignal.timeout(ESPERA_VOZ_MS),
    })
      .then((respuesta) => (respuesta.ok ? respuesta.json() : null))
      .then((datos) => datos?.personajes ?? null)
      .catch(() => null);
  }
  return configuracionPedida;
}

/**
 * Lista las voces en español que tiene este navegador (incluye las de Windows).
 *
 * @returns {Array<{nombre: string, idioma: string}>} Voces disponibles; vacía si no hay.
 */
export function vocesEspanolas() {
  if (!hayVozDelNavegador()) {
    return [];
  }
  try {
    return window.speechSynthesis
      .getVoices()
      .filter((voz) => voz.lang?.toLowerCase().startsWith("es"))
      .map((voz) => ({ nombre: voz.name, idioma: voz.lang }));
  } catch {
    return [];
  }
}

/**
 * Detiene cualquier lectura de Pana (nombre que usa la Ventanilla).
 *
 * @returns {void}
 */
export function detenerVozPana() {
  detenerVoz();
}

/**
 * Detiene cualquier lectura de cualquier personaje o del navegador.
 *
 * @returns {void}
 */
export function detenerVoz() {
  lecturaActual += 1;
  if (audioActual) {
    audioActual.pause();
  }
  liberarAudio();
  try {
    window.speechSynthesis?.cancel();
  } catch {
    // Sin voz del navegador: no hay nada que detener.
  }
}

/**
 * Pide a la API el audio OGG de un personaje.
 *
 * @param {string} personaje Personaje que habla.
 * @param {string} texto Texto que dirá.
 * @returns {Promise<Blob | null>} El audio, o `null` si no hay voz en el servidor.
 */
async function pedirAudio(personaje, texto) {
  try {
    const respuesta = await fetch("/api/voz", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto, personaje }),
      signal: AbortSignal.timeout(ESPERA_VOZ_MS),
    });
    if (!respuesta.ok) {
      return null;
    }
    return await respuesta.blob();
  } catch {
    return null;
  }
}

/**
 * Reproduce un audio y avisa al terminar.
 *
 * @param {Blob} audio Audio OGG/Opus.
 * @param {() => void} alTerminar Se llama al acabar o al fallar la reproducción.
 * @returns {Promise<boolean>} `true` si empezó a sonar.
 */
async function reproducir(audio, alTerminar) {
  if (typeof window.Audio !== "function") {
    return false;
  }
  urlActual = URL.createObjectURL(audio);
  audioActual = new window.Audio(urlActual);
  const reproductor = audioActual;
  const cerrar = () => {
    if (audioActual === reproductor) {
      liberarAudio();
    }
    alTerminar();
  };
  reproductor.onended = cerrar;
  reproductor.onerror = cerrar;
  try {
    await reproductor.play();
    return true;
  } catch {
    if (audioActual === reproductor) {
      liberarAudio();
    }
    return false;
  }
}

/**
 * Suelta el audio actual y su URL temporal.
 *
 * @returns {void}
 */
function liberarAudio() {
  if (urlActual) {
    URL.revokeObjectURL(urlActual);
  }
  urlActual = null;
  audioActual = null;
}

/**
 * Lee un texto con una voz del navegador, su tono y su velocidad.
 *
 * @param {string} texto Texto que se leerá.
 * @param {{voz?: string, tono?: number, velocidad?: number}} ajuste `voz` es parte del nombre de la voz.
 * @param {string} [personaje] Personaje, para repartir voces si `voz` está vacío.
 * @param {() => void} [alTerminar] Se llama al acabar o al fallar.
 * @returns {boolean} `true` si empezó a leer.
 */
export function decirConElNavegador(texto, ajuste, personaje = "pana", alTerminar = () => {}) {
  if (!hayVozDelNavegador()) {
    return false;
  }
  try {
    const locucion = new window.SpeechSynthesisUtterance(texto);
    const voz = elegirVoz(ajuste?.voz ?? "", personaje);
    if (voz) {
      locucion.voice = voz;
    }
    locucion.lang = voz?.lang ?? "es-CO";
    locucion.pitch = ajuste?.tono ?? 1;
    locucion.rate = ajuste?.velocidad ?? 1;
    locucion.onend = alTerminar;
    locucion.onerror = alTerminar;
    window.speechSynthesis.speak(locucion);
    return true;
  } catch {
    return false;
  }
}

/**
 * Elige la voz del navegador para un personaje.
 *
 * Si `nombre` no está vacío, toma la primera voz cuyo nombre lo contenga (sin
 * importar mayúsculas). Si no, Pana prefiere `es-CO` y los demás reparten las
 * voces en español en orden, para que dos personajes seguidos no suenen igual.
 *
 * @param {string} nombre Parte del nombre de la voz, o vacío.
 * @param {string} personaje Personaje que habla.
 * @returns {SpeechSynthesisVoice | null} Voz elegida o `null`.
 */
function elegirVoz(nombre, personaje) {
  try {
    const todas = window.speechSynthesis.getVoices();
    const buscado = nombre.trim().toLowerCase();
    if (buscado) {
      const exacta = todas.find((voz) => voz.name.toLowerCase().includes(buscado));
      if (exacta) {
        return exacta;
      }
    }
    const espanolas = todas.filter((voz) => voz.lang?.toLowerCase().startsWith("es"));
    if (espanolas.length === 0) {
      return null;
    }
    if (personaje === "pana") {
      return (
        espanolas.find((voz) => voz.lang.toLowerCase().startsWith("es-co")) ??
        espanolas[0]
      );
    }
    const posicion = Math.max(0, PERSONAJES.indexOf(personaje));
    return espanolas[posicion % espanolas.length];
  } catch {
    return null;
  }
}
