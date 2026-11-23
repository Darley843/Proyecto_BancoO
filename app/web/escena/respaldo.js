/**
 * Sucursal 1965 · respaldo de la escena en el navegador (plan B).
 *
 * Guarda en `sessionStorage` la última escena que respondió el servidor, para
 * que una recarga de la página o una caída de la app no deje la pantalla en
 * blanco. Solo vive en esta pestaña: no se envía a ningún servicio y el botón
 * Reiniciar la borra. Si el navegador no deja guardar (modo privado, permisos),
 * la pantalla sigue igual, sin respaldo.
 *
 * También arma el **núcleo**: cuando la negociación falla o hay que acortar,
 * la escena sigue con Don Gota, Pana y el auditor sin repetir lo ya dicho.
 */

/** Claves de `sessionStorage`. */
export const CLAVE_COMPLETA = "sucursal.escena.completa";
export const CLAVE_NUCLEO = "sucursal.escena.nucleo";

/** Personajes que se quedan en el núcleo (sin negociación ni voluntario). */
const PERSONAJES_NUCLEO = Object.freeze(["don_gota", "pana", "auditor"]);

/**
 * Guarda una escena en `sessionStorage`.
 *
 * @param {string} clave `CLAVE_COMPLETA` o `CLAVE_NUCLEO`.
 * @param {{turnos: object[], veredicto?: object | null}} escena Escena a guardar.
 * @returns {boolean} `true` si se pudo guardar.
 */
export function guardarEscena(clave, escena) {
  try {
    globalThis.sessionStorage.setItem(clave, JSON.stringify(escena));
    return true;
  } catch {
    return false;
  }
}

/**
 * Lee una escena guardada.
 *
 * @param {string} clave `CLAVE_COMPLETA` o `CLAVE_NUCLEO`.
 * @returns {{turnos: object[], veredicto?: object | null} | null} La escena, o
 *   `null` si no hay o está dañada.
 */
export function leerEscena(clave) {
  try {
    const datos = JSON.parse(globalThis.sessionStorage.getItem(clave) ?? "null");
    return Array.isArray(datos?.turnos) ? datos : null;
  } catch {
    return null;
  }
}

/**
 * Borra las escenas guardadas (botón Reiniciar).
 *
 * @returns {void}
 */
export function borrarEscenas() {
  try {
    globalThis.sessionStorage.removeItem(CLAVE_COMPLETA);
    globalThis.sessionStorage.removeItem(CLAVE_NUCLEO);
  } catch {
    // Sin permiso para guardar tampoco hay nada que borrar.
  }
}

/**
 * Saca un núcleo de una escena completa cuando el servidor no lo da: los
 * turnos de Don Gota, Pana y el auditor, en el mismo orden.
 *
 * @param {object[]} turnos Turnos de la escena completa.
 * @returns {object[]} Turnos del núcleo.
 */
export function nucleoDeLaEscena(turnos) {
  return turnos.filter((turno) => PERSONAJES_NUCLEO.includes(turno?.personaje));
}

/**
 * Cambia al núcleo sin perder lo ya dicho: deja los turnos hasta el actual y
 * sigue con los del núcleo que aún no se han dicho (por `id`).
 *
 * @param {object[]} turnos Turnos que se venían reproduciendo.
 * @param {number} indice Posición del último turno dicho (-1 si ninguno).
 * @param {object[]} nucleo Turnos del núcleo.
 * @returns {object[]} La nueva lista de turnos.
 */
export function pasarAlNucleo(turnos, indice, nucleo) {
  const dichos = turnos.slice(0, indice + 1);
  const ids = new Set(dichos.map((turno) => turno?.id));
  const ultimoOrden = Math.max(-1, ...dichos.map((turno) => (Number.isInteger(turno?.orden) ? turno.orden : -1)));
  const pendientes = nucleo.filter((turno) => !ids.has(turno?.id));
  // Si el núcleo viene de la misma escena, solo siguen los turnos posteriores.
  const posteriores = pendientes.filter((turno) => !Number.isInteger(turno?.orden) || turno.orden > ultimoOrden);
  return [...dichos, ...(posteriores.length > 0 ? posteriores : pendientes)];
}
