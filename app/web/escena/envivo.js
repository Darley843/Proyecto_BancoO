/**
 * Sucursal 1965 · modo «En vivo» de la pantalla de la escena (tecla E).
 *
 * Mientras el voluntario escribe por WhatsApp, el canal y las herramientas de
 * Pana publican sus turnos en `data/escena/en_vivo.jsonl`, y la app los
 * entrega en `GET /api/escena/en-vivo?desde=<seq>` (contrato en
 * `docs/ESCENA_EN_VIVO.md`, §10 y §11). Este módulo hace el sondeo y las
 * cuentas puras de la cola; `escena.js` muestra y dice cada turno.
 *
 * Reglas del contrato que cumple aquí:
 *
 * - Sondeo cada 2 s con `setTimeout` después de cada respuesta (nunca un
 *   temporizador fijo que solape peticiones), `AbortController` con techo de
 *   1,5 s y `cache: "no-store"`.
 * - Se detiene con la pestaña oculta y vuelve con un sondeo inmediato.
 * - La cola se ordena y se deduplica por `seq`; `seq` es opaco (no se hace
 *   aritmética con él) y el cursor `desde` vive solo en memoria: nada se guarda
 *   en el almacenamiento del navegador.
 * - Al entrar con E se empieza desde el último turno de la lista: los turnos
 *   viejos solo mueven el cursor y no se reproducen. **R** sí vuelve a pedir
 *   desde `desde=0`.
 * - Un turno que no cumple el contrato no se dice: se cuenta como descartado.
 * - El invitado (el voluntario escribiendo por WhatsApp) nunca pide voz.
 */

import { erroresDelTurno } from "./contrato.js";

/** Ruta de la lista en vivo en la app local. */
export const RUTA_EN_VIVO = "/api/escena/en-vivo";
/** Espera entre un sondeo y el siguiente, en milisegundos. */
export const INTERVALO_MS = 2000;
/** Turnos máximos que devuelve la ruta en una respuesta (contrato §10). */
export const LIMITE_RUTA = 200;
/** Techo de cada petición antes de darla por perdida. */
export const ESPERA_MS = 1500;
/** Personajes que solo salen en subtítulo, sin voz. */
export const SIN_VOZ = Object.freeze(["invitado"]);
/** Lectura de un turno sin voz: 55 ms por letra, entre 2 y 6 segundos. */
export const MS_POR_LETRA = 55;
export const LECTURA_MINIMA_MS = 2000;
export const LECTURA_MAXIMA_MS = 6000;

/**
 * Dirección del sondeo a partir del cursor.
 *
 * @param {number | string} desde Último `seq` recibido (0 al empezar).
 * @returns {string} Ruta con el parámetro `desde`.
 */
export function urlEnVivo(desde) {
  return `${RUTA_EN_VIVO}?desde=${encodeURIComponent(String(desde ?? 0))}`;
}

/**
 * Indica si un turno debe decirse con voz.
 *
 * @param {string} personaje Personaje del turno.
 * @param {boolean} soloSubtitulos `true` si el modo solo subtítulos está activo.
 * @returns {boolean} `true` si se llama a la voz.
 */
export function pideVoz(personaje, soloSubtitulos) {
  return !soloSubtitulos && !SIN_VOZ.includes(personaje);
}

/**
 * Tiempo que un turno sin voz queda en pantalla antes de pasar al siguiente.
 *
 * @param {string} texto Texto que se subtitula.
 * @returns {number} Milisegundos, entre 2 y 6 segundos.
 */
export function tiempoDeLectura(texto) {
  const largo = String(texto ?? "").length;
  return Math.min(LECTURA_MAXIMA_MS, Math.max(LECTURA_MINIMA_MS, largo * MS_POR_LETRA));
}

/**
 * Compara dos `seq` sin hacer aritmética (pueden llegar como número o texto).
 *
 * @param {number | string} a Primer `seq`.
 * @param {number | string} b Segundo `seq`.
 * @returns {number} Negativo, cero o positivo, como `Array.prototype.sort`.
 */
export function compararSeq(a, b) {
  const x = BigInt(a);
  const y = BigInt(b);
  return x < y ? -1 : x > y ? 1 : 0;
}

/**
 * Indica si un registro de la lista tiene la forma `{seq, ts, origen, turno}`.
 *
 * @param {unknown} registro Registro recibido.
 * @returns {boolean} `true` si se puede ordenar y mostrar.
 */
function esRegistro(registro) {
  if (registro === null || typeof registro !== "object") {
    return false;
  }
  const { seq } = registro;
  const seqValido =
    (typeof seq === "number" && Number.isSafeInteger(seq) && seq >= 0) ||
    (typeof seq === "string" && /^\d+$/.test(seq));
  return seqValido && registro.turno !== null && typeof registro.turno === "object";
}

/**
 * Separa los registros nuevos que se pueden reproducir de los descartados.
 *
 * Solo entran los que tienen `seq` mayor que el último ya encolado (la cola
 * nunca se reordena por detrás de lo que ya sonó), sin repetir `seq`, en orden
 * ascendente y con el turno válido según `contrato.js`.
 *
 * @param {Array<{seq: number | string}>} cola Registros ya encolados, en orden.
 * @param {unknown} registros Registros que devolvió la ruta.
 * @returns {{nuevos: object[], descartados: string[]}} Registros que se añaden
 *   al final de la cola y el motivo de cada descarte.
 */
export function registrosNuevos(cola, registros) {
  const descartados = [];
  if (!Array.isArray(registros)) {
    return { nuevos: [], descartados };
  }
  const ultimo = cola.length > 0 ? cola[cola.length - 1].seq : null;
  const vistos = new Set();
  const candidatos = [];
  for (const registro of registros) {
    if (!esRegistro(registro)) {
      descartados.push("registro sin seq o sin turno");
      continue;
    }
    const clave = String(registro.seq);
    if (vistos.has(clave) || (ultimo !== null && compararSeq(registro.seq, ultimo) <= 0)) {
      continue;
    }
    vistos.add(clave);
    const errores = erroresDelTurno(registro.turno);
    if (errores.length > 0) {
      descartados.push(errores.join(" · "));
      continue;
    }
    candidatos.push(registro);
  }
  candidatos.sort((a, b) => compararSeq(a.seq, b.seq));
  return { nuevos: candidatos, descartados };
}

/**
 * Cursor siguiente: el `ultimo` de la ruta si es válido y no retrocede.
 *
 * @param {number | string} desde Cursor actual.
 * @param {unknown} ultimo Valor `ultimo` de la respuesta.
 * @returns {number | string} Nuevo cursor.
 */
export function siguienteCursor(desde, ultimo) {
  const valido =
    (typeof ultimo === "number" && Number.isSafeInteger(ultimo) && ultimo >= 0) ||
    (typeof ultimo === "string" && /^\d+$/.test(ultimo));
  if (!valido) {
    return desde;
  }
  return compararSeq(ultimo, desde) > 0 ? ultimo : desde;
}

/**
 * Crea el sondeo de la lista en vivo.
 *
 * @param {{
 *   alRecibir: (registros: object[], ultimo: number | string) => void,
 *   alEstado: (estado: {conectado: boolean, desde: number | string}) => void,
 * }} avisos Funciones que reciben los registros y el estado de la conexión.
 * @returns {{iniciar: (opciones?: {desdeElFinal?: boolean, desde?: number | string}) => void,
 *   detener: () => void, reiniciar: () => void, activo: () => boolean}}
 *   Controles del sondeo. Con `desdeElFinal`, los turnos que ya existían no se
 *   entregan: solo los que lleguen después. Con `desde`, se sigue desde ese
 *   cursor (lo usa el paso de la espera al modo conversación).
 */
export function crearSondeo({ alRecibir, alEstado }) {
  const sondeo = {
    activo: false,
    desde: 0,
    temporizador: null,
    controlador: null,
    saltando: false,
  };

  /**
   * Agenda la siguiente vuelta si el modo sigue abierto y la pestaña visible.
   *
   * @returns {void}
   */
  function agendar() {
    window.clearTimeout(sondeo.temporizador);
    sondeo.temporizador = null;
    if (sondeo.activo && !document.hidden) {
      sondeo.temporizador = window.setTimeout(vuelta, INTERVALO_MS);
    }
  }

  /**
   * Una vuelta: pide los turnos después del cursor y avisa lo recibido.
   *
   * @returns {Promise<void>}
   */
  async function vuelta() {
    if (!sondeo.activo || document.hidden || sondeo.controlador) {
      return;
    }
    const controlador = new AbortController();
    sondeo.controlador = controlador;
    const techo = window.setTimeout(() => controlador.abort(), ESPERA_MS);
    let datos = null;
    try {
      const respuesta = await fetch(urlEnVivo(sondeo.desde), {
        cache: "no-store",
        signal: controlador.signal,
      });
      datos = respuesta.ok ? await respuesta.json() : null;
    } catch {
      datos = null;
    } finally {
      window.clearTimeout(techo);
      if (sondeo.controlador === controlador) {
        sondeo.controlador = null;
      }
    }
    if (!sondeo.activo || controlador.signal.reason === "detenido") {
      return;
    }
    const conectado = datos !== null && Array.isArray(datos.turnos);
    if (conectado) {
      sondeo.desde = siguienteCursor(sondeo.desde, datos.ultimo);
      if (sondeo.saltando) {
        // Lo que ya estaba en la lista solo mueve el cursor; con la página
        // llena (200) quedan más viejos y la próxima vuelta sigue saltando.
        sondeo.saltando = datos.turnos.length >= LIMITE_RUTA;
      } else {
        alRecibir(datos.turnos, sondeo.desde);
      }
    }
    alEstado({ conectado, desde: sondeo.desde });
    agendar();
  }

  /**
   * Con la pestaña oculta se para; al volver, sondea de inmediato.
   *
   * @returns {void}
   */
  function alCambiarVisibilidad() {
    if (!sondeo.activo) {
      return;
    }
    if (document.hidden) {
      window.clearTimeout(sondeo.temporizador);
      sondeo.temporizador = null;
    } else {
      vuelta();
    }
  }

  document.addEventListener("visibilitychange", alCambiarVisibilidad);

  /**
   * Corta la petición en curso y el temporizador.
   *
   * @returns {void}
   */
  function cortar() {
    window.clearTimeout(sondeo.temporizador);
    sondeo.temporizador = null;
    sondeo.controlador?.abort("detenido");
    sondeo.controlador = null;
  }

  return {
    iniciar({ desdeElFinal = false, desde = 0 } = {}) {
      cortar();
      sondeo.activo = true;
      sondeo.desde = siguienteCursor(0, desde);
      sondeo.saltando = desdeElFinal;
      vuelta();
    },
    detener() {
      sondeo.activo = false;
      cortar();
    },
    reiniciar() {
      cortar();
      sondeo.desde = 0;
      sondeo.saltando = false;
      if (sondeo.activo) {
        vuelta();
      }
    },
    activo() {
      return sondeo.activo;
    },
  };
}
