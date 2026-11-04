/**
 * Vista Arqueo · responsable: Anny.
 *
 * La evaluación del sistema: recuperación (hit@5, MRR), respuestas (exactitud y citas), costo y la prueba de McNemar entre v1 y v2.
 * Por ahora es el armazón del PR 12: muestra el título y lo que falta.
 */

import { crearEncabezadoVista, crearPendiente } from "../comun.js";

/**
 * Pinta la vista Arqueo dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-arqueo` de `index.html`.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  contenedor.replaceChildren(
    crearEncabezadoVista("arqueo", "Arqueo", "La evaluación del sistema: recuperación (hit@5, MRR), respuestas (exactitud y citas), costo y la prueba de McNemar entre v1 y v2."),
    crearPendiente("Métricas de la evaluación", "Se completa en el PR 18 con GET /api/arqueo."),
  );
  void estado;
}
