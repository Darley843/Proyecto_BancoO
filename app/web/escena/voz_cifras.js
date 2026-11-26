/**
 * Sucursal 1965 · cifras en palabras para la voz de la escena.
 *
 * Los subtítulos conservan el formato colombiano de las cifras («$28.000.000»,
 * «28,17 % E.A.»), pero el motor de voz del navegador lo lee como dólares y con
 * decimales. Este módulo traduce SOLO el texto que se manda a la voz: montos en
 * pesos, rangos, porcentajes con coma decimal y las siglas de las tasas. No
 * toca el DOM, no usa librerías y no modifica los subtítulos.
 */

const UNIDADES = Object.freeze([
  "cero",
  "uno",
  "dos",
  "tres",
  "cuatro",
  "cinco",
  "seis",
  "siete",
  "ocho",
  "nueve",
  "diez",
  "once",
  "doce",
  "trece",
  "catorce",
  "quince",
  "dieciséis",
  "diecisiete",
  "dieciocho",
  "diecinueve",
  "veinte",
  "veintiuno",
  "veintidós",
  "veintitrés",
  "veinticuatro",
  "veinticinco",
  "veintiséis",
  "veintisiete",
  "veintiocho",
  "veintinueve",
]);

const DECENAS = Object.freeze([
  "",
  "",
  "",
  "treinta",
  "cuarenta",
  "cincuenta",
  "sesenta",
  "setenta",
  "ochenta",
  "noventa",
]);

const CENTENAS = Object.freeze([
  "",
  "ciento",
  "doscientos",
  "trescientos",
  "cuatrocientos",
  "quinientos",
  "seiscientos",
  "setecientos",
  "ochocientos",
  "novecientos",
]);

/**
 * Convierte un número de 0 a 999 en palabras.
 *
 * @param {number} numero Entero entre 0 y 999.
 * @returns {string} El número escrito en español.
 */
function hastaNovecientosNoventaYNueve(numero) {
  if (numero < 30) {
    return UNIDADES[numero];
  }
  if (numero < 100) {
    const decena = Math.floor(numero / 10);
    const unidad = numero % 10;
    return unidad === 0 ? DECENAS[decena] : `${DECENAS[decena]} y ${UNIDADES[unidad]}`;
  }
  if (numero === 100) {
    return "cien";
  }
  const centena = Math.floor(numero / 100);
  const resto = numero % 100;
  return resto === 0 ? CENTENAS[centena] : `${CENTENAS[centena]} ${hastaNovecientosNoventaYNueve(resto)}`;
}

/**
 * Ajusta «uno» a «un» (y «veintiuno» a «veintiún») antes de mil o millón.
 *
 * @param {string} frase Número ya escrito en palabras.
 * @returns {string} La misma frase con la apócope que pide el español.
 */
function apocope(frase) {
  if (frase.endsWith("veintiuno")) {
    return `${frase.slice(0, -"veintiuno".length)}veintiún`;
  }
  if (frase.endsWith("uno")) {
    return `${frase.slice(0, -3)}un`;
  }
  return frase;
}

/**
 * Escribe en palabras un entero no negativo (hasta miles de millones).
 *
 * @param {number} numero Entero no negativo.
 * @returns {string} El número escrito en español.
 */
function palabrasEntero(numero) {
  if (!Number.isFinite(numero) || numero < 0) {
    return String(numero);
  }
  if (numero < 1000) {
    return hastaNovecientosNoventaYNueve(numero);
  }
  if (numero < 1_000_000) {
    const miles = Math.floor(numero / 1000);
    const resto = numero % 1000;
    const cabeza = miles === 1 ? "mil" : `${apocope(palabrasEntero(miles))} mil`;
    return resto === 0 ? cabeza : `${cabeza} ${hastaNovecientosNoventaYNueve(resto)}`;
  }
  if (numero < 1_000_000_000) {
    const millones = Math.floor(numero / 1_000_000);
    const resto = numero % 1_000_000;
    const cabeza = millones === 1 ? "un millón" : `${apocope(palabrasEntero(millones))} millones`;
    return resto === 0 ? cabeza : `${cabeza} ${palabrasEntero(resto)}`;
  }
  const milesDeMillones = Math.floor(numero / 1_000_000_000);
  const resto = numero % 1_000_000_000;
  const cabeza =
    milesDeMillones === 1
      ? "mil millones"
      : `${apocope(palabrasEntero(milesDeMillones))} mil millones`;
  return resto === 0 ? cabeza : `${cabeza} ${palabrasEntero(resto)}`;
}

/**
 * Escribe la parte decimal de un porcentaje tal como suena.
 *
 * Conserva los ceros iniciales («09» suena «cero nueve») y lee el resto como
 * número («17» suena «diecisiete»).
 *
 * @param {string} fraccion Dígitos después de la coma.
 * @returns {string} La fracción escrita en español.
 */
function palabrasFraccion(fraccion) {
  if (/^0\d*$/.test(fraccion)) {
    return fraccion
      .split("")
      .map((digito) => UNIDADES[Number(digito)])
      .join(" ");
  }
  return palabrasEntero(Number(fraccion));
}

/**
 * Escribe un porcentaje en palabras, con coma decimal si la tiene.
 *
 * @param {string} crudo Número tal como aparece antes del «%».
 * @returns {string} El número escrito en palabras.
 */
function palabrasPorcentaje(crudo) {
  const [entero, fraccion] = crudo.split(",");
  const base = palabrasEntero(Number(entero.replace(/\./g, "")));
  if (!fraccion) {
    return base;
  }
  return `${base} coma ${palabrasFraccion(fraccion)}`;
}

/**
 * Devuelve las palabras de un monto y si lleva «de» antes de «pesos».
 *
 * «$1.000.000» pide «un millón de pesos», pero «$1.500.000» pide «un millón
 * quinientos mil pesos».
 *
 * @param {string} crudo Dígitos del monto, con puntos de miles.
 * @returns {{palabras: string, conDe: boolean} | null} Monto en palabras, o `null` si no es válido.
 */
function montoEnPalabras(crudo) {
  const digitos = crudo.replace(/\./g, "");
  const valor = Number(digitos);
  if (!Number.isFinite(valor)) {
    return null;
  }
  return {
    palabras: palabrasEntero(valor),
    conDe: valor >= 1_000_000 && valor % 1_000_000 === 0,
  };
}

/**
 * Escribe un monto completo con su moneda.
 *
 * @param {string} crudo Dígitos del monto, con puntos de miles.
 * @returns {string} El monto en palabras con «pesos» (o el original si no se entiende).
 */
function montoConPesos(crudo) {
  const monto = montoEnPalabras(crudo);
  if (!monto) {
    return `$${crudo}`;
  }
  return `${monto.palabras} ${monto.conDe ? "de pesos" : "pesos"}`;
}

/**
 * Quita las URL del texto: no se leen en voz alta.
 *
 * @param {string} texto Texto original.
 * @returns {string} El texto sin enlaces.
 */
function sinUrls(texto) {
  return texto.replace(/\bhttps?:\/\/[^\s]+/gi, " ").replace(/\bwww\.[^\s]+/gi, " ");
}

/**
 * Quita las marcas de formato de WhatsApp (*negrita* y _cursiva_).
 *
 * @param {string} texto Texto original.
 * @returns {string} El texto sin las marcas.
 */
function sinMarcas(texto) {
  return texto.replace(/[*_]/g, "");
}

/**
 * Convierte los rangos de montos en «entre … y … pesos».
 *
 * @param {string} texto Texto con rangos en formato colombiano.
 * @returns {string} El texto con los rangos en palabras.
 */
function cambiarRangos(texto) {
  return texto.replace(
    /\$\s*(\d[\d.]*)\s*[–—−-]\s*\$\s*(\d[\d.]*)/g,
    (coincidencia, desde, hasta) => {
      const inicio = montoEnPalabras(desde);
      const fin = montoEnPalabras(hasta);
      if (!inicio || !fin) {
        return coincidencia;
      }
      return `entre ${inicio.palabras} y ${fin.palabras} ${fin.conDe ? "de pesos" : "pesos"}`;
    },
  );
}

/**
 * Convierte cada monto suelto en palabras con «pesos».
 *
 * @param {string} texto Texto con montos en formato colombiano.
 * @returns {string} El texto con los montos en palabras.
 */
function cambiarMontos(texto) {
  return texto.replace(/\$\s*(\d[\d.]*)/g, (coincidencia, crudo) => montoConPesos(crudo));
}

/**
 * Convierte los porcentajes y sus siglas en palabras.
 *
 * @param {string} texto Texto con porcentajes.
 * @returns {string} El texto con porcentajes y tasas en palabras.
 */
function cambiarPorcentajes(texto) {
  const conPorcentaje = texto.replace(
    /(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?)\s*%\s*(E\.?\s*A\.?|M\.?\s*V\.?)?/gi,
    (coincidencia, crudo, sigla) => {
      const base = `${palabrasPorcentaje(crudo)} por ciento`;
      const limpia = String(sigla ?? "")
        .toUpperCase()
        .replace(/[.\s]/g, "");
      if (limpia === "EA") {
        return `${base} efectivo anual`;
      }
      if (limpia === "MV") {
        return `${base} mes vencido`;
      }
      return base;
    },
  );
  return conPorcentaje
    .replace(/\bE\.?\s*A\.?\b/gi, "efectivo anual")
    .replace(/\bM\.?\s*V\.?\b/gi, "mes vencido");
}

/**
 * Prepara un texto para que la voz lo lea en español claro.
 *
 * Los subtítulos no pasan por aquí: esta función se llama únicamente justo
 * antes de entregar el texto a `decirComo`.
 *
 * @param {string} texto Texto del turno tal como aparece en pantalla.
 * @returns {string} El texto solo para la voz, con cifras y siglas en palabras.
 */
export function paraVoz(texto) {
  let limpio = String(texto ?? "");
  limpio = sinUrls(limpio);
  limpio = sinMarcas(limpio);
  limpio = cambiarRangos(limpio);
  limpio = cambiarMontos(limpio);
  limpio = cambiarPorcentajes(limpio);
  return limpio.replace(/\s+/g, " ").trim();
}
