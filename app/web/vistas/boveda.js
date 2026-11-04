/**
 * Vista Bóveda · responsable: Yoldy.
 *
 * El corpus convertido en vectores. El mapa muestra cada fragmento en dos dimensiones y resalta los cinco más cercanos a la pregunta.
 * Por ahora es el armazón del PR 12: muestra el título y lo que falta.
 */

import { crearEncabezadoVista, crearPendiente } from "../comun.js";

/**
 * Pinta la vista Bóveda dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-boveda` de `index.html`.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  contenedor.replaceChildren(
    crearEncabezadoVista("boveda", "Bóveda", "El corpus convertido en vectores. El mapa muestra cada fragmento en dos dimensiones y resalta los cinco más cercanos a la pregunta."),
    crearPendiente("Mapa de fragmentos y top 5", "Se completa en el PR 14 con GET /api/boveda/mapa."),
  );
  void estado;
}
