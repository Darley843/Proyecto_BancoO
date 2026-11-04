/**
 * Vista Vestíbulo · responsable: Yoldy.
 *
 * La historia del banco desde 1965, contada con hitos tomados de Gold y enlazados a su fuente pública.
 * Por ahora es el armazón del PR 12: muestra el título y lo que falta.
 */

import { crearEncabezadoVista, crearPendiente, crearTexto } from "../comun.js";

/**
 * Pinta la vista Vestíbulo dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-vestibulo` de `index.html`.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  contenedor.replaceChildren(
    crearEncabezadoVista("vestibulo", "Vestíbulo", "La historia del banco desde 1965, contada con hitos tomados de Gold y enlazados a su fuente pública."),
    crearPendiente("Línea de tiempo con los hitos", "Se completa en el PR 17 con GET /api/vestibulo."),
  );
  const entrada = crearTexto("a", "Pasar a la Ventanilla", "boton-primario");
  entrada.href = "#ventanilla";
  contenedor.append(entrada);
  void estado;
}
