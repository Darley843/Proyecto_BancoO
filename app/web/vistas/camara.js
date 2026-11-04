/**
 * Vista Cámara de compensación · responsable: Yoldy.
 *
 * El pipeline de captura de punta a punta: descubrir, descargar, extraer, deduplicar, publicar en Gold e indexar.
 * Por ahora es el armazón del PR 12: muestra el título y lo que falta.
 */

import { crearEncabezadoVista, crearPendiente } from "../comun.js";

/**
 * Pinta la vista Cámara de compensación dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-camara` de `index.html`.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  contenedor.replaceChildren(
    crearEncabezadoVista("camara", "Cámara de compensación", "El pipeline de captura de punta a punta: descubrir, descargar, extraer, deduplicar, publicar en Gold e indexar."),
    crearPendiente("Etapas del pipeline con sus métricas", "Se completa en el PR 16 con GET /api/pipeline."),
  );
  void estado;
}
