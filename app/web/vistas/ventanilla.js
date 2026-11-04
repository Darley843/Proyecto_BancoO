/**
 * Vista Ventanilla · responsable: Nayla.
 *
 * Aquí se hace la pregunta. El Digiturno le asigna un turno y cada respuesta sale con su comprobante: fuentes, tokens, costo y tiempo.
 * Por ahora es el armazón del PR 12: muestra el título y lo que falta.
 */

import { crearEncabezadoVista, crearPendiente } from "../comun.js";

/**
 * Pinta la vista Ventanilla dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-ventanilla` de `index.html`.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  contenedor.replaceChildren(
    crearEncabezadoVista("ventanilla", "Ventanilla", "Aquí se hace la pregunta. El Digiturno le asigna un turno y cada respuesta sale con su comprobante: fuentes, tokens, costo y tiempo."),
    crearPendiente("Conversación con memoria y comprobante", "Se completa en el PR 13 con POST /api/preguntar."),
  );
  void estado;
}
