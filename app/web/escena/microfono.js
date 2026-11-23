/**
 * Sucursal 1965 · micrófono para las preguntas del público en la escena.
 *
 * Usa el reconocimiento de voz del navegador (`SpeechRecognition`, en Edge lo
 * procesa Microsoft) en español de Colombia, con un solo resultado final, igual
 * que el botón «Dictar» de la Ventanilla. Nunca hay dos micrófonos abiertos.
 */

/** Reconocimiento activo, o `null`. */
let activo = null;

/**
 * Devuelve el constructor del reconocimiento de voz, si el navegador lo tiene.
 *
 * @returns {Function | null} Constructor o `null`.
 */
function constructor() {
  const Reconocimiento = globalThis.SpeechRecognition ?? globalThis.webkitSpeechRecognition;
  return typeof Reconocimiento === "function" ? Reconocimiento : null;
}

/**
 * Indica si este navegador puede escuchar por micrófono.
 *
 * @returns {boolean} `true` si hay reconocimiento de voz.
 */
export function hayMicrofono() {
  return constructor() !== null;
}

/**
 * Indica si el micrófono está escuchando ahora.
 *
 * @returns {boolean} `true` mientras escucha.
 */
export function escuchando() {
  return activo !== null;
}

/**
 * Escucha una frase y la entrega al terminar.
 *
 * @param {object} avisos Funciones que se llaman al pasar cada cosa.
 * @param {(texto: string) => void} avisos.alResultado Recibe la frase reconocida.
 * @param {(mensaje: string) => void} avisos.alError Recibe un mensaje para quien presenta.
 * @param {() => void} avisos.alTerminar Se llama siempre al cerrar el micrófono.
 * @returns {boolean} `true` si empezó a escuchar.
 */
export function escuchar({ alResultado, alError, alTerminar }) {
  detenerMicrofono();
  const Reconocimiento = constructor();
  if (!Reconocimiento) {
    alError("Este navegador no tiene micrófono para dictar: escribe la pregunta.");
    return false;
  }
  try {
    const instancia = new Reconocimiento();
    instancia.lang = "es-CO";
    instancia.interimResults = false;
    instancia.continuous = false;
    instancia.maxAlternatives = 1;
    activo = instancia;
    instancia.onresult = (evento) => {
      const texto = String(evento.results?.[0]?.[0]?.transcript ?? "").trim();
      if (texto && activo === instancia) {
        alResultado(texto);
      }
    };
    instancia.onerror = (evento) => {
      if (activo !== instancia || evento?.error === "aborted") {
        return;
      }
      const sinPermiso = evento?.error === "not-allowed" || evento?.error === "service-not-allowed";
      alError(
        sinPermiso
          ? "Permite el micrófono en el navegador, o escribe la pregunta."
          : evento?.error === "no-speech"
            ? "No se oyó nada. Intenta otra vez, más cerca del micrófono."
            : "No se pudo usar el micrófono (¿hay internet?). Escribe la pregunta.",
      );
    };
    instancia.onend = () => {
      if (activo === instancia) {
        activo = null;
      }
      alTerminar();
    };
    instancia.start();
    return true;
  } catch {
    activo = null;
    alError("No se pudo usar el micrófono. Escribe la pregunta.");
    alTerminar();
    return false;
  }
}

/**
 * Cierra el micrófono si está abierto.
 *
 * @returns {void}
 */
export function detenerMicrofono() {
  const instancia = activo;
  activo = null;
  if (instancia) {
    try {
      instancia.abort();
    } catch {
      // Si no se puede abortar, el reconocimiento termina solo.
    }
  }
}
