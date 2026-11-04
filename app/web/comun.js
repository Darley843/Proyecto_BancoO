/**
 * Sucursal 1965 · utilidades comunes de presentación.
 *
 * Las comparten `app.js` y las vistas. Solo crean elementos y formatean
 * cifras: no contienen reglas de negocio. Todo texto se inserta con
 * `textContent`, nunca como HTML, para no ejecutar nada que venga en los datos.
 */

/**
 * Crea un elemento con texto plano (nunca HTML), para no ejecutar nada que
 * venga en los datos.
 *
 * @param {string} etiqueta Etiqueta HTML, por ejemplo `p`.
 * @param {string} texto Texto visible.
 * @param {string} [clase] Clases CSS opcionales.
 * @returns {HTMLElement} El elemento creado.
 */
export function crearTexto(etiqueta, texto, clase = "") {
  const elemento = document.createElement(etiqueta);
  elemento.textContent = texto;
  if (clase) {
    elemento.className = clase;
  }
  return elemento;
}

/**
 * Crea el encabezado común de una vista (título y descripción).
 *
 * @param {string} nombre Nombre de la vista, para el id del título.
 * @param {string} titulo Título visible.
 * @param {string} descripcion Una o dos frases sobre qué es este espacio.
 * @returns {HTMLElement} El bloque de encabezado.
 */
export function crearEncabezadoVista(nombre, titulo, descripcion) {
  const bloque = document.createElement("header");
  bloque.className = "vista__encabezado";
  const h1 = crearTexto("h1", titulo);
  h1.id = `titulo-${nombre}`;
  bloque.append(h1, crearTexto("p", descripcion));
  return bloque;
}

/**
 * Crea el recuadro de "en construcción" que usan las vistas pendientes.
 *
 * @param {string} titulo Qué falta.
 * @param {string} detalle Qué PR lo completa.
 * @returns {HTMLElement} El recuadro.
 */
export function crearPendiente(titulo, detalle) {
  const caja = document.createElement("div");
  caja.className = "pendiente";
  caja.append(crearTexto("strong", titulo), crearTexto("span", detalle));
  return caja;
}

/**
 * Formatea una cifra en dólares con cuatro decimales, como el comprobante.
 *
 * @param {number} valor Monto en US$.
 * @returns {string} Texto como `US$ 0,0123`.
 */
export function formatearUsd(valor) {
  const numero = Number.isFinite(valor) ? valor : 0;
  return `US$ ${numero.toLocaleString("es-CO", {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  })}`;
}
