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
 * Quita emojis, banderas y los selectores de variación o unión (U+FE0F,
 * U+200D) sin tocar los saltos de línea.
 *
 * @param {string} texto Texto original.
 * @returns {string} El texto sin pictogramas y sin espacios dobles.
 */
function sinEmojis(texto) {
  return texto
    .replace(
      /[\p{Extended_Pictographic}\p{Emoji_Modifier}\u{1F1E6}-\u{1F1FF}\u200D\uFE0F\u20E3]/gu,
      "",
    )
    .replace(/[^\S\n]{2,}/g, " ");
}

/** Marca de una opción: letra A–Z, punto, paréntesis o punto medio y espacio. */
const PATRON_OPCION = /(^|\s)([A-Z])\s*[.)·]\s+(?=\S)/gu;

/**
 * Recoge las marcas de una lista que empieza en «A» y sigue «B», «C»…
 *
 * Se ignoran las marcas que rompen la secuencia, como la «E» de «E. A.» o la
 * «M» de «M. V.»: no son opciones. Solo hay lista si llegan al menos «A» y
 * «B», así una letra suelta tampoco se confunde con una opción.
 *
 * @param {string} texto Texto original.
 * @returns {Array<{letra: string, inicio: number, fin: number}>} Marcas de la
 *   lista, en orden, o una lista vacía si no hay opciones.
 */
function marcasDeLista(texto) {
  const marcas = [];
  let esperada = "A";
  for (const coincidencia of texto.matchAll(PATRON_OPCION)) {
    const letra = coincidencia[2];
    if (letra !== esperada) {
      continue;
    }
    marcas.push({
      letra,
      inicio: coincidencia.index + coincidencia[1].length,
      fin: coincidencia.index + coincidencia[0].length,
    });
    esperada = String.fromCharCode(esperada.charCodeAt(0) + 1);
  }
  return marcas.length >= 2 ? marcas : [];
}

/**
 * Extrae el texto de una opción y le deja una sola frase terminada.
 *
 * @param {string} texto Texto original.
 * @param {{fin: number}} marca Marca que abre la opción.
 * @param {{inicio: number} | undefined} siguiente Marca que la cierra.
 * @returns {string} El texto de la opción, sin espacios de más y con su punto.
 */
function cuerpoDeOpcion(texto, marca, siguiente) {
  const hasta = siguiente ? siguiente.inicio : texto.length;
  const cuerpo = texto.slice(marca.fin, hasta).replace(/\s+/g, " ").trim();
  const limpio = cuerpo.replace(/[.;:]$/, "").trim();
  return /[.!?]$/.test(limpio) ? limpio : `${limpio}.`;
}

/**
 * Lee una lista de opciones antes de que la voz la pronuncie.
 *
 * En vez de omitir las opciones, la voz dice lo que va antes de la lista, cada
 * opción con su letra y una pausa de punto entre ellas, y cierra pidiendo la
 * letra elegida. Funciona con «A. …», «A) …» y «A · …», en la misma línea o en
 * líneas separadas.
 *
 * @param {string} texto Texto original.
 * @returns {string} El texto con las opciones una por una, o el mismo texto.
 */
function leerOpciones(texto) {
  const marcas = marcasDeLista(texto);
  if (marcas.length < 2) {
    return texto;
  }
  const prefijo = texto.slice(0, marcas[0].inicio).trim();
  const opciones = marcas
    .map((marca, indice) => `${marca.letra}: ${cuerpoDeOpcion(texto, marca, marcas[indice + 1])}`)
    .join(" ");
  return [prefijo, opciones, "Dime la letra de tu opción."].filter(Boolean).join(" ");
}

/**
 * Convierte los rangos de montos en «entre … y … pesos».
 *
 * Los rangos pueden venir con la escala al final («$20 a $50 millones»): la
 * escala vale para las dos puntas y se dice una sola vez, después del último
 * número.
 *
 * @param {string} texto Texto con rangos en formato colombiano.
 * @returns {string} El texto con los rangos en palabras.
 */
function cambiarRangos(texto) {
  const conEscala = texto.replace(
    /\$\s*(\d+(?:\.\d{3})*)\s+a\s+\$\s*(\d+(?:\.\d{3})*)\s*(millones|millón)\b/gi,
    (coincidencia, desde, hasta, escala) => {
      const inicio = montoEnPalabras(desde);
      const fin = montoEnPalabras(hasta);
      if (!inicio || !fin) {
        return coincidencia;
      }
      const unidad = /^millones$/i.test(escala) ? "millones" : "millón";
      return `de ${inicio.palabras} a ${fin.palabras} ${unidad} de pesos`;
    },
  );
  return conEscala.replace(
    /\$\s*(\d+(?:\.\d{3})*)\s*[–—−-]\s*\$\s*(\d+(?:\.\d{3})*)/g,
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
 * Convierte los montos abreviados con «mil», «millón» o «millones».
 *
 * «$20 millones» se lee «veinte millones de pesos» y «Menos de $500 mil» se
 * lee «menos de quinientos mil pesos». Los montos abreviados con coma decimal
 * («$7,5 millones») se leen con «coma» («siete coma cinco millones de pesos»)
 * y se resuelven antes que sus equivalentes enteros.
 *
 * @param {string} texto Texto con montos abreviados.
 * @returns {string} El texto con esos montos en palabras.
 */
function cambiarMontosConEscala(texto) {
  return texto
    .replace(
      /\$\s*(\d+),(\d+)\s*millones\b/gi,
      (coincidencia, entero, fraccion) =>
        `${palabrasEntero(Number(entero))} coma ${palabrasFraccion(fraccion)} millones de pesos`,
    )
    .replace(
      /\$\s*(\d+),(\d+)\s*mil\b/gi,
      (coincidencia, entero, fraccion) =>
        `${palabrasEntero(Number(entero))} coma ${palabrasFraccion(fraccion)} mil pesos`,
    )
    .replace(/\$\s*(\d+(?:\.\d{3})*)\s*millones\b/gi, (coincidencia, crudo) => {
      const monto = montoEnPalabras(crudo);
      return monto ? `${monto.palabras} millones de pesos` : coincidencia;
    })
    .replace(/\$\s*(\d+(?:\.\d{3})*)\s*(millón|millon)\b/gi, (coincidencia, crudo) => {
      const monto = montoEnPalabras(crudo);
      return monto ? `${apocope(monto.palabras)} millón de pesos` : coincidencia;
    })
    .replace(/\$\s*(\d+(?:\.\d{3})*)\s*mil\b/gi, (coincidencia, crudo) => {
      const monto = montoEnPalabras(crudo);
      return monto ? `${monto.palabras} mil pesos` : coincidencia;
    });
}

/**
 * Convierte cada monto suelto en palabras con «pesos».
 *
 * @param {string} texto Texto con montos en formato colombiano.
 * @returns {string} El texto con los montos en palabras.
 */
function cambiarMontos(texto) {
  return texto.replace(/\$\s*(\d+(?:\.\d{3})*)/g, (coincidencia, crudo) =>
    montoConPesos(crudo),
  );
}

/**
 * Convierte los porcentajes y sus siglas en palabras.
 *
 * El espacio que sigue al «%» solo se consume cuando viene la sigla; sin ella
 * se conserva para no pegar la frase siguiente («20 % al mes»).
 *
 * @param {string} texto Texto con porcentajes.
 * @returns {string} El texto con porcentajes y tasas en palabras.
 */
function cambiarPorcentajes(texto) {
  const conPorcentaje = texto.replace(
    /(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:,\d+)?)\s*%(?:\s*(E\.?\s*A\.?|M\.?\s*V\.?))?/gi,
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
 * Deja el texto sin «$» ni la palabra «dólar».
 *
 * Es la red de seguridad: si algún monto no encajó en los patrones anteriores,
 * se quita el símbolo y se dice «pesos» en su lugar. Así la voz nunca lee
 * dólares.
 *
 * @param {string} texto Texto ya convertido.
 * @returns {string} El texto sin símbolos de dólar.
 */
function sinDolares(texto) {
  return texto
    .replace(/\$\s*([^\s.,;:!?)]*)/g, (coincidencia, resto) =>
      resto ? `${resto} pesos` : "pesos",
    )
    .replace(/\bd[oó]lares\b/gi, "pesos")
    .replace(/\bd[oó]lar\b/gi, "peso");
}

/**
 * Prepara un texto para que la voz lo lea en español claro.
 *
 * Los subtítulos no pasan por aquí: esta función se llama únicamente justo
 * antes de entregar el texto a la voz. También lee las listas de opciones una
 * por una, con su letra y una pausa entre ellas.
 *
 * @param {string} texto Texto del turno tal como aparece en pantalla.
 * @returns {string} El texto solo para la voz, con cifras, siglas y opciones
 *   listas para el oído.
 */
export function paraVoz(texto) {
  let limpio = String(texto ?? "");
  limpio = sinUrls(limpio);
  limpio = sinMarcas(limpio);
  limpio = sinEmojis(limpio);
  limpio = leerOpciones(limpio);
  limpio = cambiarRangos(limpio);
  limpio = cambiarMontosConEscala(limpio);
  limpio = cambiarMontos(limpio);
  limpio = cambiarPorcentajes(limpio);
  limpio = sinDolares(limpio);
  return limpio.replace(/\s+/g, " ").trim();
}
