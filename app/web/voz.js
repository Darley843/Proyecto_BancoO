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
 *   Si esa voz no está en este navegador, o es una voz «Online» de Edge y no
 *   hay internet (Edge la cambiaría por una voz local de Windows), usa su voz
 *   de Piper como respaldo en vez de otra voz cualquiera.
 *
 * Don Gota siempre busca una voz de hombre (`config/escena.toml [voces]`:
 * «Jorge» y luego «Raul»), nunca una de mujer y nunca la de Pana. La lista de
 * `getVoices()` puede llegar vacía al cargar: se espera `voiceschanged` antes
 * de elegir.
 *
 * Si la API no responde, todos usan el navegador con los valores de
 * `RESPALDO_NAVEGADOR`. Nunca guarda los textos en el navegador: el audio
 * adelantado (`adelantarVoz`) vive solo en memoria y se descarta al usarse.
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
 * Voz de Pana, según `config/voz.toml`: solo se usa para que Don Gota no la
 * repita cuando el navegador no trae ninguna voz masculina.
 */
const VOZ_PANA = "Gonzalo";

/**
 * Preferencia de Don Gota, en orden: se busca cada fragmento dentro del nombre
 * de las voces en español, sin distinguir mayúsculas ni tildes. Es la misma
 * lista de `config/escena.toml [voces] don_gota`; una prueba comprueba que no
 * se separen.
 */
const PREFERENCIA_DON_GOTA = Object.freeze(["Jorge", "Raul"]);

/**
 * Nombres que identifican una voz de mujer. Se comparan como palabras
 * completas del nombre de la voz, para no confundir «Julia» con «Julián».
 */
const VOCES_FEMENINAS = Object.freeze([
  "salome",
  "dalia",
  "sabina",
  "elena",
  "sofia",
  "beatriz",
  "elvira",
  "daniela",
  "paulina",
  "monica",
  "lucia",
  "maria",
  "laura",
  "isabel",
  "carmen",
  "andrea",
  "camila",
  "valentina",
  "ximena",
  "renata",
  "esperanza",
  "paloma",
  "teresa",
  "rosa",
  "julia",
  "irene",
  "nuria",
  "laia",
  "abril",
  "alba",
  "clara",
  "celia",
  "eva",
  "lola",
  "marta",
  "natalia",
  "patricia",
  "silvia",
  "victoria",
  "carolina",
  "catalina",
  "gabriela",
  "mariana",
  "alejandra",
  "ana",
  "sara",
  "paula",
  "noelia",
  "alicia",
  "cecilia",
  "gloria",
  "susana",
  "veronica",
  "lorena",
  "adriana",
  "marcela",
  "claudia",
  "diana",
  "liliana",
  "sandra",
  "angela",
  "rocio",
  "pilar",
  "mercedes",
  "guadalupe",
  "lupita",
  "amparo",
  "consuelo",
  "soledad",
  "piedad",
  "milagros",
  "dolores",
]);

/** Nombres que identifican una voz de hombre en las voces de Windows/Edge. */
const VOCES_MASCULINAS = Object.freeze([
  "jorge",
  "raul",
  "gonzalo",
  "juan",
  "pablo",
  "diego",
  "carlos",
  "miguel",
  "alvaro",
  "dario",
  "enrique",
  "alejandro",
  "andres",
  "felipe",
  "santiago",
  "mateo",
  "luis",
  "javier",
  "manuel",
  "pedro",
  "ramon",
  "tomas",
  "vicente",
  "arturo",
  "roberto",
  "ricardo",
  "fernando",
  "sergio",
  "mauricio",
  "camilo",
  "sebastian",
  "david",
  "daniel",
  "gabriel",
  "adrian",
  "hector",
  "hugo",
  "ivan",
  "joaquin",
  "julio",
  "mario",
  "martin",
  "nicolas",
  "oscar",
  "rafael",
  "ruben",
  "salvador",
  "victor",
  "jose",
  "antonio",
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

/** Tope de espera de `voiceschanged` cuando la lista de voces llega vacía. */
const ESPERA_VOCES_MS = 2000;

/** Máximo de audios pedidos por adelantado que se guardan en memoria. */
const MAXIMO_ADELANTADOS = 4;

/** Audios de Piper pedidos antes de su turno: `personaje + texto` → promesa del audio. */
const adelantados = new Map();

/** Audio de Pana que suena ahora, si hay uno. */
let audioActual = null;

/** URL temporal del audio actual, para liberarla al terminar. */
let urlActual = null;

/** Cuenta cada lectura: una respuesta que llega tarde no pisa a la siguiente. */
let lecturaActual = 0;

/** `true` si el navegador no avisó nunca de sus voces: no se vuelve a esperar. */
let vocesSinAviso = false;

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
  if (usaPiper(ajuste, limpio) && piperMasculinoDisponible(quien, ajuste)) {
    const audio = await (tomarAdelantado(quien, limpio) ?? pedirAudio(quien, limpio));
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
  await esperarVoces();
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
 * Pide ya el audio de Piper de un turno que viene, para que suene sin espera.
 *
 * La escena lo llama mientras suena el turno actual: Piper tarda en generar
 * cada audio y, sin esto, entre un personaje y otro queda un silencio. Si el
 * personaje no usa Piper no hace nada. Guarda como máximo
 * `MAXIMO_ADELANTADOS` audios, solo en memoria.
 *
 * @param {string} personaje Personaje que hablará.
 * @param {string} texto Texto que dirá (el mismo que recibirá `decirComo`).
 * @returns {Promise<void>} Se resuelve cuando el pedido quedó hecho (no espera el audio).
 */
export async function adelantarVoz(personaje, texto) {
  const quien = PERSONAJES.includes(personaje) ? personaje : "pana";
  const limpio = String(texto ?? "").trim();
  const clave = claveAdelantado(quien, limpio);
  if (!limpio || adelantados.has(clave)) {
    return;
  }
  const ajuste = await configuracionDe(quien);
  if (
    !usaPiper(ajuste, limpio) ||
    !piperMasculinoDisponible(quien, ajuste) ||
    adelantados.has(clave)
  ) {
    return;
  }
  while (adelantados.size >= MAXIMO_ADELANTADOS) {
    adelantados.delete(adelantados.keys().next().value);
  }
  adelantados.set(clave, pedirAudio(quien, limpio));
}

/**
 * Saca el audio adelantado de un turno, si se pidió antes.
 *
 * @param {string} personaje Personaje que habla.
 * @param {string} texto Texto ya limpio.
 * @returns {Promise<Blob | null> | null} La promesa del audio, o `null` si no se adelantó.
 */
function tomarAdelantado(personaje, texto) {
  const clave = claveAdelantado(personaje, texto);
  const audio = adelantados.get(clave) ?? null;
  adelantados.delete(clave);
  return audio;
}

/**
 * Arma la clave de un audio adelantado.
 *
 * @param {string} personaje Personaje que habla.
 * @param {string} texto Texto ya limpio.
 * @returns {string} Clave única para ese personaje y ese texto.
 */
function claveAdelantado(personaje, texto) {
  return `${personaje}\n${texto}`;
}

/**
 * Indica si un texto de un personaje se dice con Piper.
 *
 * @param {{motor: string, navegador?: {voz?: string}}} ajuste Ajuste del personaje.
 * @param {string} texto Texto ya limpio.
 * @returns {boolean} `true` si se pide el audio a `POST /api/voz`.
 */
function usaPiper(ajuste, texto) {
  const porMotor =
    ajuste.motor === "piper" ||
    (ajuste.motor === "navegador" && !tieneVozDelNavegador(ajuste.navegador?.voz ?? ""));
  return porMotor && texto.length <= LARGO_MAXIMO_VOZ;
}

/**
 * Indica si Don Gota puede usar su modelo masculino de Piper en este equipo.
 *
 * El modelo ya viene en `config/voz.toml` (`es_ES-davefx-medium`, una voz de
 * hombre); si no está descargado, la API responde `piper: false` y Don Gota
 * pasa a la voz del navegador en vez de esperar un 503. Los demás personajes
 * conservan el comportamiento de siempre.
 *
 * @param {string} personaje Personaje que hablará.
 * @param {{motor: string, piper?: boolean}} ajuste Ajuste del personaje.
 * @returns {boolean} `true` si puede pedir el audio de Piper.
 */
function piperMasculinoDisponible(personaje, ajuste) {
  if (personaje !== "don_gota" || ajuste.motor !== "piper") {
    return true;
  }
  return ajuste.piper !== false;
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
    const eleccion = elegirVoz(ajuste?.voz ?? "", personaje);
    if (eleccion.voz) {
      locucion.voice = eleccion.voz;
    }
    locucion.lang = eleccion.voz?.lang ?? "es-CO";
    const tono = ajuste?.tono ?? 1;
    const velocidad = ajuste?.velocidad ?? 1;
    locucion.pitch = eleccion.grave ? Math.max(0.1, tono * 0.75) : tono;
    locucion.rate = eleccion.grave ? Math.max(0.1, velocidad * 0.9) : velocidad;
    locucion.onend = alTerminar;
    locucion.onerror = alTerminar;
    window.speechSynthesis.speak(locucion);
    return true;
  } catch {
    return false;
  }
}

/**
 * Indica si el navegador puede decir el texto con la voz pedida por su nombre.
 *
 * Un nombre vacío significa «la primera en español», así que cuenta como
 * disponible si hay alguna voz. Las voces «Online» de Edge (`localService`
 * falso) siguen en la lista sin internet, pero Edge las cambia en silencio por
 * una voz local de Windows; por eso, sin conexión (`navigator.onLine` falso),
 * una voz en línea cuenta como no disponible y el personaje usa su Piper.
 *
 * @param {string} nombre Parte del nombre de la voz, o vacío.
 * @returns {boolean} `true` si la voz está y puede sonar ahora.
 */
export function tieneVozDelNavegador(nombre) {
  if (!hayVozDelNavegador()) {
    return false;
  }
  const buscado = nombre.trim().toLowerCase();
  if (!buscado) {
    return true;
  }
  try {
    const voz = window.speechSynthesis
      .getVoices()
      .find((candidata) => candidata.name.toLowerCase().includes(buscado));
    if (!voz) {
      return false;
    }
    return voz.localService !== false || hayInternet();
  } catch {
    return false;
  }
}

/**
 * Indica si el navegador cree que hay conexión a internet.
 *
 * `navigator.onLine` falso es seguro (no hay red); verdadero solo dice que hay
 * alguna red, que es lo que necesitan las voces en línea de Edge.
 *
 * @returns {boolean} `false` solo si el navegador sabe que no hay conexión.
 */
function hayInternet() {
  return typeof navigator === "undefined" || navigator.onLine !== false;
}

/**
 * Normaliza el nombre de una voz: minúsculas, sin tildes y sin espacios de más.
 *
 * @param {string} texto Nombre de la voz o fragmento buscado.
 * @returns {string} Texto comparable.
 */
function normalizarNombreVoz(texto) {
  return String(texto ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Separa el nombre de una voz en palabras comparables.
 *
 * @param {{name?: string}} voz Voz del navegador.
 * @returns {Set<string>} Palabras normalizadas del nombre.
 */
function palabrasDeVoz(voz) {
  return new Set(
    normalizarNombreVoz(voz?.name)
      .split(/[^a-z0-9]+/)
      .filter(Boolean),
  );
}

/**
 * Indica si una voz tiene nombre de mujer.
 *
 * Se comparan palabras completas, no fragmentos: así «Julia» no marca como
 * femenina una voz llamada «Julián».
 *
 * @param {{name?: string}} voz Voz del navegador.
 * @returns {boolean} `true` si es una voz de mujer conocida.
 */
function esVozFemenina(voz) {
  const palabras = palabrasDeVoz(voz);
  return VOCES_FEMENINAS.some((nombre) => palabras.has(normalizarNombreVoz(nombre)));
}

/**
 * Indica si una voz tiene nombre de hombre.
 *
 * @param {{name?: string}} voz Voz del navegador.
 * @returns {boolean} `true` si es una voz de hombre conocida.
 */
function esVozMasculina(voz) {
  const palabras = palabrasDeVoz(voz);
  return VOCES_MASCULINAS.some((nombre) => palabras.has(normalizarNombreVoz(nombre)));
}

/**
 * Indica si una voz es la de Pana, que Don Gota no debe repetir.
 *
 * @param {{name?: string}} voz Voz del navegador.
 * @returns {boolean} `true` si coincide con la voz configurada de Pana.
 */
function esVozPana(voz) {
  return palabrasDeVoz(voz).has(normalizarNombreVoz(VOZ_PANA));
}

/**
 * Busca una voz por un fragmento de su nombre, sin mayúsculas ni tildes.
 *
 * @param {Array<{name: string}>} voces Voces donde buscar.
 * @param {string} fragmento Parte del nombre que se busca.
 * @returns {SpeechSynthesisVoice | null} La primera voz que coincide o `null`.
 */
function buscarVozPorFragmento(voces, fragmento) {
  const buscado = normalizarNombreVoz(fragmento);
  if (!buscado) {
    return null;
  }
  return voces.find((voz) => normalizarNombreVoz(voz.name).includes(buscado)) ?? null;
}

/**
 * Elige la voz de Don Gota: hombre, distinta de Pana y nunca de mujer.
 *
 * Primero busca «Jorge» y luego «Raul» por fragmento del nombre. Si no están,
 * usa otra voz de hombre conocida. Si no hay ninguna voz masculina, toma la
 * primera voz en español que no sea de mujer ni de Pana y pide bajarle el tono.
 * Si solo quedan voces de mujer, devuelve `null` antes que usar una.
 *
 * @param {Array<SpeechSynthesisVoice>} espanolas Voces en español del navegador.
 * @returns {{voz: SpeechSynthesisVoice | null, grave: boolean}} Voz y si hay que hacerla más grave.
 */
function elegirVozDonGota(espanolas) {
  const candidatas = espanolas.filter((voz) => !esVozFemenina(voz) && !esVozPana(voz));
  for (const fragmento of PREFERENCIA_DON_GOTA) {
    const voz = buscarVozPorFragmento(candidatas, fragmento);
    if (voz) {
      return { voz, grave: false };
    }
  }
  const masculina = candidatas.find((voz) => esVozMasculina(voz));
  if (masculina) {
    return { voz: masculina, grave: false };
  }
  if (candidatas.length > 0) {
    return { voz: candidatas[0], grave: true };
  }
  return { voz: null, grave: true };
}

/**
 * Elige la voz del navegador para un personaje.
 *
 * Si `nombre` no está vacío, toma la primera voz cuyo nombre lo contenga (sin
 * importar mayúsculas ni tildes). Si no, Pana prefiere `es-CO` y los demás
 * reparten las voces en español en orden, para que dos personajes seguidos no
 * suenen igual. Don Gota tiene su propia regla masculina.
 *
 * @param {string} nombre Parte del nombre de la voz, o vacío.
 * @param {string} personaje Personaje que habla.
 * @returns {{voz: SpeechSynthesisVoice | null, grave: boolean}} Voz elegida y si hay que bajarla.
 */
function elegirVoz(nombre, personaje) {
  try {
    const todas = window.speechSynthesis.getVoices();
    if (personaje === "don_gota") {
      const espanolas = todas.filter((voz) => voz.lang?.toLowerCase().startsWith("es"));
      return elegirVozDonGota(espanolas);
    }
    const buscado = normalizarNombreVoz(nombre);
    if (buscado) {
      const exacta = todas.find((voz) =>
        normalizarNombreVoz(voz.name).includes(buscado),
      );
      if (exacta) {
        return { voz: exacta, grave: false };
      }
    }
    const espanolas = todas.filter((voz) => voz.lang?.toLowerCase().startsWith("es"));
    if (espanolas.length === 0) {
      return { voz: null, grave: false };
    }
    if (personaje === "pana") {
      return {
        voz:
          espanolas.find((voz) => voz.lang.toLowerCase().startsWith("es-co")) ??
          espanolas[0],
        grave: false,
      };
    }
    const posicion = Math.max(0, PERSONAJES.indexOf(personaje));
    return { voz: espanolas[posicion % espanolas.length], grave: false };
  } catch {
    return { voz: null, grave: false };
  }
}

/**
 * Devuelve las voces que el navegador ya conoce.
 *
 * @returns {Array<SpeechSynthesisVoice>} Voces disponibles; vacía si todavía no hay.
 */
function vocesDelNavegador() {
  try {
    return window.speechSynthesis.getVoices() ?? [];
  } catch {
    return [];
  }
}

/**
 * Espera a que el navegador llene la lista de voces antes de elegir.
 *
 * Edge y Chrome pueden devolver `getVoices()` vacía justo al cargar y avisar
 * después con `voiceschanged`. Se espera como máximo `ESPERA_VOCES_MS` para no
 * dejar la escena en silencio si el navegador no avisa.
 *
 * @returns {Promise<void>} Se resuelve cuando hay voces o vence el plazo.
 */
function esperarVoces() {
  if (
    !hayVozDelNavegador() ||
    vocesSinAviso ||
    vocesDelNavegador().length > 0
  ) {
    return Promise.resolve();
  }
  return new Promise((resolver) => {
    let termino = false;
    let temporizador = null;
    const terminar = (sinAviso) => {
      if (termino) {
        return;
      }
      termino = true;
      if (sinAviso) {
        vocesSinAviso = true;
      }
      if (temporizador !== null) {
        clearTimeout(temporizador);
      }
      try {
        window.speechSynthesis.removeEventListener("voiceschanged", alCambiarVoces);
      } catch {
        // El navegador no permite quitar el aviso; ya quedó resuelto.
      }
      resolver();
    };
    const alCambiarVoces = () => terminar(false);
    temporizador = setTimeout(() => terminar(true), ESPERA_VOCES_MS);
    try {
      window.speechSynthesis.addEventListener("voiceschanged", alCambiarVoces);
      if (vocesDelNavegador().length > 0) {
        terminar(false);
      }
    } catch {
      terminar(true);
    }
  });
}

/**
 * Pide la lista de voces apenas carga la página.
 *
 * Edge y Chrome llenan `getVoices()` un momento después; si se pide al cargar,
 * la voz del primer turno (por ejemplo, Gonzalo para Pana) ya está lista y no
 * se cae al respaldo de Piper sin necesidad.
 *
 * @returns {void}
 */
function precargarVoces() {
  if (!hayVozDelNavegador()) {
    return;
  }
  try {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.addEventListener("voiceschanged", () => {
      window.speechSynthesis.getVoices();
    });
  } catch {
    // Sin voces del navegador: Piper sigue funcionando.
  }
}

precargarVoces();
