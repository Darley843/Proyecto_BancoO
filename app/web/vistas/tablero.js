/**
 * Vista Tablero de tasas · responsable: Yoldy.
 *
 * Tarifas y coberturas extraídas de Gold a una tabla, cada fila con su fuente. Las cifras salen del CSV, nunca del modelo.
 * Por ahora es el armazón del PR 12: muestra el título y lo que falta.
 */

import { crearEncabezadoVista, crearPendiente } from "../comun.js";

/**
 * Pinta la vista Tablero de tasas dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-tablero` de `index.html`.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  contenedor.replaceChildren(
    crearEncabezadoVista("tablero", "Tablero de tasas", "Tarifas y coberturas extraídas de Gold a una tabla, cada fila con su fuente. Las cifras salen del CSV, nunca del modelo."),
    crearPendiente("Tabla con filtro de texto", "Se completa en el PR 15 con GET /api/tablero."),
  );
  void estado;
}
