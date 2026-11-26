/**
 * Sucursal 1965 · cifras completas para los subtítulos de la escena.
 *
 * Las etiquetas de la entrevista se mantienen cortas porque en WhatsApp las
 * opciones de lista tienen un máximo de 24 caracteres («$20 a $50 millones»).
 * En la pantalla de la escena conviene leer la cifra completa: este módulo
 * expande las abreviaturas («$20 a $50 millones» → «$20.000.000 a
 * $50.000.000») sin tocar la configuración ni los textos de WhatsApp.
 *
 * No toca el DOM, no usa librerías y no cambia el texto que va a la voz.
 */

/**
 * Escribe un entero con puntos de miles al estilo colombiano.
 *
 * @param {number} valor Entero no negativo.
 * @returns {string} El valor con puntos cada tres cifras.
 */
function conPuntos(valor) {
  return String(valor).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

/**
 * Convierte los dígitos de un monto en su valor numérico.
 *
 * @param {string} crudo Dígitos del monto, con puntos de miles.
 * @returns {number | null} El valor, o `null` si no se entiende.
 */
function valorDelMonto(crudo) {
  const valor = Number(crudo.replace(/\./g, ""));
  return Number.isFinite(valor) ? valor : null;
}

/**
 * Expande un monto abreviado a su cifra completa con puntos de miles.
 *
 * @param {string} crudo Dígitos del monto.
 * @param {number} factor Escala: 1.000 para «mil», 1.000.000 para «millones».
 * @returns {string} La cifra completa con el signo «$».
 */
function montoCompleto(crudo, factor) {
  const valor = valorDelMonto(crudo);
  return valor === null ? `$${crudo}` : `$${conPuntos(valor * factor)}`;
}

/**
 * Expande las cifras abreviadas de un texto para mostrarlo en la escena.
 *
 * Los rangos con la escala al final («$20 a $50 millones») aplican la escala a
 * las dos puntas; las etiquetas sueltas («$500 mil», «$1 millón») se expanden
 * cada una por su lado. Los montos abreviados con coma decimal («$7,5
 * millones») se resuelven antes que sus equivalentes enteros y se muestran con
 * la cifra completa («$7.500.000»).
 *
 * @param {string} texto Texto con montos abreviados.
 * @returns {string} El mismo texto con las cifras completas.
 */
export function paraPantalla(texto) {
  let limpio = String(texto ?? "");
  limpio = limpio.replace(
    /\$\s*(\d+(?:\.\d{3})*)\s+a\s+\$\s*(\d+(?:\.\d{3})*)\s*(millones|millón)\b/gi,
    (coincidencia, desde, hasta) =>
      `${montoCompleto(desde, 1_000_000)} a ${montoCompleto(hasta, 1_000_000)}`,
  );
  limpio = limpio.replace(
    /\$\s*(\d+),(\d+)\s*millones\b/gi,
    (coincidencia, entero, fraccion) =>
      `$${conPuntos(Math.round(Number(`${entero}.${fraccion}`) * 1_000_000))}`,
  );
  limpio = limpio.replace(
    /\$\s*(\d+),(\d+)\s*mil\b/gi,
    (coincidencia, entero, fraccion) =>
      `$${conPuntos(Math.round(Number(`${entero}.${fraccion}`) * 1_000))}`,
  );
  limpio = limpio.replace(
    /\$\s*(\d+(?:\.\d{3})*)\s*millones\b/gi,
    (coincidencia, crudo) => montoCompleto(crudo, 1_000_000),
  );
  limpio = limpio.replace(
    /\$\s*(\d+(?:\.\d{3})*)\s*(millón|millon)\b/gi,
    (coincidencia, crudo) => montoCompleto(crudo, 1_000_000),
  );
  limpio = limpio.replace(
    /\$\s*(\d+(?:\.\d{3})*)\s*mil\b/gi,
    (coincidencia, crudo) => montoCompleto(crudo, 1_000),
  );
  return limpio.replace(/\$\s*(\d+(?:\.\d{3})*)/g, (coincidencia, crudo) =>
    montoCompleto(crudo, 1),
  );
}
