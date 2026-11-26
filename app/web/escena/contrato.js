/**
 * Sucursal 1965 · espejo en el navegador de `TurnoEscena`
 * (`src/banco_occidente_corpus/escena/contratos.py`, cambio `demo-gota-a-gota`).
 *
 * Cada turno, venga del guion, del motor o del modelo, trae los mismos campos.
 * Así la voz, los subtítulos y el auditor se conectan sin depender de cómo se
 * generó el texto:
 *
 * - `id` y `orden`: identidad del turno en la escena.
 * - `personaje`: pana, don_gota, joven, agente_joven, agente_banco, auditor o
 *   invitado (el voluntario que escribe por WhatsApp y va solo en subtítulo).
 * - `texto`: lo que se dice en voz; `subtitulo` (opcional) lo que se lee.
 * - `cifras`: lista de `{etiqueta, valor, valor_legible, unidad, fuente}`;
 *   `fuente` es `{tipo, referencia, vigencia?, sha256?}`. `valor` llega como
 *   número o como texto decimal (así serializa Pydantic un `Decimal`).
 * - `escenario`: `EscenarioEscena` del motor o `null`.
 * - `origen`: guion_fijo, motor, llm, reglas, entrada_voz o canal (los turnos
 *   que publica el canal de WhatsApp).
 * - `hallazgos`: `{codigo, turno_id, detalle, gravedad}` del auditor.
 *
 * El veredicto del auditor (`conforme`, `con_observaciones`, `objeta`) viaja
 * aparte del semáforo del crédito (`verde`, `amarillo`, `rojo`) y nunca usa
 * colores. La pantalla no calcula cifras: muestra `valor_legible`.
 *
 * Este módulo no toca la página: solo valida y da formato.
 */

/** Personajes válidos, en el orden en que aparecen en la escena. */
export const PERSONAJES = Object.freeze([
  "pana",
  "don_gota",
  "joven",
  "agente_joven",
  "agente_banco",
  "auditor",
  "invitado",
]);

/** De dónde puede salir el texto de un turno. */
export const ORIGENES = Object.freeze([
  "guion_fijo",
  "motor",
  "llm",
  "reglas",
  "entrada_voz",
  "canal",
]);

/** Tipos de fuente verificable de una cifra. */
export const TIPOS_FUENTE = Object.freeze([
  "config",
  "gold",
  "motor",
  "calculo_gota",
  "usura",
  "guion",
  "documento",
]);

/** Unidades de una cifra. */
export const UNIDADES = Object.freeze(["pesos", "porcentaje_ea", "porcentaje", "meses", "dias", "veces"]);

/** Semáforo financiero del crédito (`null` = aún no calculado). */
export const SEMAFOROS = Object.freeze(["verde", "amarillo", "rojo"]);

/** Veredictos del auditor: sin colores, distintos del semáforo. */
export const VEREDICTOS = Object.freeze(["conforme", "con_observaciones", "objeta"]);

/** Texto visible de cada veredicto. */
export const TEXTO_VEREDICTO = Object.freeze({
  conforme: "conforme",
  con_observaciones: "con observaciones",
  objeta: "objeta",
});

/** Gravedades de un hallazgo. */
const GRAVEDADES = Object.freeze(["alta", "media"]);

/**
 * Pasos de la escena, en orden (plan de cierre, sección 5), con la
 * presentación de Pana al inicio y las preguntas del público al final.
 */
export const PASOS = Object.freeze([
  "Presentación",
  "Voluntario",
  "Personaje",
  "Oferta de Don Gota",
  "Pana compara",
  "Negociación",
  "Veredicto",
  "Preguntas",
]);

/** Posición del paso de la presentación y del de preguntas en `PASOS`. */
export const PASO_PRESENTACION = 0;
export const PASO_PREGUNTAS = PASOS.length - 1;

/**
 * Indica si un valor es un objeto simple (no `null` ni lista).
 *
 * @param {unknown} valor Valor a revisar.
 * @returns {boolean} `true` si es un objeto.
 */
function esObjeto(valor) {
  return valor !== null && typeof valor === "object" && !Array.isArray(valor);
}

/**
 * Indica si un valor es un texto no vacío.
 *
 * @param {unknown} valor Valor a revisar.
 * @returns {boolean} `true` si es texto con contenido.
 */
function esTexto(valor) {
  return typeof valor === "string" && valor.trim().length > 0;
}

/**
 * Convierte un decimal del contrato (número o texto) en número.
 *
 * @param {unknown} valor Valor de la cifra.
 * @returns {number} El número, o `NaN` si no es un decimal válido.
 */
export function aNumero(valor) {
  if (typeof valor === "number") {
    return valor;
  }
  if (typeof valor === "string" && /^-?\d+(\.\d+)?$/.test(valor.trim())) {
    return Number(valor);
  }
  return Number.NaN;
}

/**
 * Revisa una cifra del turno.
 *
 * @param {unknown} cifra Cifra recibida.
 * @param {number} posicion Posición en la lista (para el mensaje).
 * @returns {string[]} Errores encontrados.
 */
function erroresDeLaCifra(cifra, posicion) {
  const prefijo = `cifra ${posicion}`;
  if (!esObjeto(cifra)) {
    return [`${prefijo}: no es un objeto`];
  }
  const errores = [];
  if (!esTexto(cifra.etiqueta)) {
    errores.push(`${prefijo}: falta la etiqueta`);
  }
  if (!Number.isFinite(aNumero(cifra.valor))) {
    errores.push(`${prefijo}: el valor no es un número`);
  }
  if (!esTexto(cifra.valor_legible)) {
    errores.push(`${prefijo}: falta valor_legible`);
  }
  if (!UNIDADES.includes(cifra.unidad)) {
    errores.push(`${prefijo}: unidad desconocida ${cifra.unidad}`);
  }
  if (!esObjeto(cifra.fuente) || !TIPOS_FUENTE.includes(cifra.fuente.tipo) || !esTexto(cifra.fuente.referencia)) {
    errores.push(`${prefijo}: la fuente necesita tipo y referencia`);
  }
  return errores;
}

/**
 * Revisa el escenario del turno (puede ser `null`).
 *
 * @param {unknown} escenario Escenario recibido.
 * @returns {string[]} Errores encontrados.
 */
function erroresDelEscenario(escenario) {
  if (escenario === null || escenario === undefined) {
    return [];
  }
  if (!esObjeto(escenario)) {
    return ["el escenario no es un objeto"];
  }
  const errores = [];
  if (!esTexto(escenario.codigo)) {
    errores.push("escenario: falta el código");
  }
  if (!Number.isFinite(aNumero(escenario.monto))) {
    errores.push("escenario: el monto no es un número");
  }
  if (escenario.semaforo != null && !SEMAFOROS.includes(escenario.semaforo)) {
    errores.push(`semáforo desconocido: ${escenario.semaforo}`);
  }
  if (typeof escenario.aceptable !== "boolean" || typeof escenario.ofertable !== "boolean") {
    errores.push("escenario: aceptable y ofertable deben ser sí o no");
  }
  return errores;
}

/**
 * Revisa que un turno cumpla el contrato `TurnoEscena`.
 *
 * @param {unknown} turno Turno recibido (del guion, el motor o el modelo).
 * @returns {string[]} Errores encontrados; vacía si el turno es válido.
 */
export function erroresDelTurno(turno) {
  if (!esObjeto(turno)) {
    return ["el turno no es un objeto"];
  }
  const errores = [];
  if (!esTexto(turno.id)) {
    errores.push("falta el id");
  }
  if (!Number.isInteger(turno.orden) || turno.orden < 0) {
    errores.push("el orden debe ser un entero desde 0");
  }
  if (!PERSONAJES.includes(turno.personaje)) {
    errores.push(`personaje desconocido: ${turno.personaje}`);
  }
  if (!esTexto(turno.texto)) {
    errores.push("falta el texto");
  }
  if (turno.subtitulo != null && typeof turno.subtitulo !== "string") {
    errores.push("el subtítulo debe ser texto");
  }
  if (!ORIGENES.includes(turno.origen)) {
    errores.push(`origen desconocido: ${turno.origen}`);
  }
  if (!Array.isArray(turno.cifras)) {
    errores.push("cifras debe ser una lista");
  } else {
    turno.cifras.forEach((cifra, posicion) => errores.push(...erroresDeLaCifra(cifra, posicion)));
  }
  errores.push(...erroresDelEscenario(turno.escenario));
  if (!Array.isArray(turno.hallazgos)) {
    errores.push("hallazgos debe ser una lista");
  } else if (!turno.hallazgos.every((h) => esObjeto(h) && esTexto(h.detalle) && GRAVEDADES.includes(h.gravedad))) {
    errores.push("cada hallazgo necesita detalle y gravedad alta o media");
  }
  return errores;
}

/**
 * Revisa el veredicto del auditor: nunca un color del semáforo.
 *
 * @param {unknown} veredicto Objeto `VeredictoAuditor` recibido.
 * @returns {string[]} Errores encontrados; vacía si es válido.
 */
export function erroresDelVeredicto(veredicto) {
  if (!esObjeto(veredicto)) {
    return ["el veredicto no es un objeto"];
  }
  if (!VEREDICTOS.includes(veredicto.veredicto)) {
    return [`veredicto desconocido: ${veredicto.veredicto}`];
  }
  if (!Array.isArray(veredicto.hallazgos)) {
    return ["el veredicto necesita su lista de hallazgos"];
  }
  return [];
}

/**
 * Deduce el veredicto de los hallazgos de un turno, como el auditor
 * (alta → objeta, media → con_observaciones, ninguno → conforme).
 *
 * @param {Array<{gravedad: string}>} hallazgos Hallazgos del turno.
 * @returns {"conforme" | "con_observaciones" | "objeta"} Veredicto.
 */
export function veredictoDeHallazgos(hallazgos) {
  if (hallazgos.some((h) => h.gravedad === "alta")) {
    return "objeta";
  }
  return hallazgos.length > 0 ? "con_observaciones" : "conforme";
}

/**
 * Deduce en qué paso de la escena va un turno.
 *
 * El contrato no trae el paso: se deduce de quién habla y de lo que ya pasó,
 * y nunca retrocede. La presentación (paso 0) y las preguntas (paso 7) las
 * marca la pantalla; aquí solo se deducen los pasos 1 (Voluntario) a 6
 * (Veredicto). Pana compara cuando dice cifras del cálculo de Don Gota y el
 * invitado cae en Voluntario sin hacer retroceder la escena.
 *
 * @param {{personaje: string, cifras: Array<{fuente: {tipo: string}}>}} turno Turno actual.
 * @param {number} anterior Paso del turno anterior (-1 o 0 al empezar).
 * @returns {number} Paso del turno, de 1 a 6.
 */
export function pasoDelTurno(turno, anterior) {
  const tipos = (turno.cifras ?? []).map((cifra) => cifra.fuente?.tipo);
  let paso = 1;
  if (turno.personaje === "invitado") {
    paso = 1;
  } else if (turno.personaje === "auditor") {
    paso = 6;
  } else if (turno.personaje === "agente_joven" || turno.personaje === "agente_banco") {
    paso = 5;
  } else if (turno.personaje === "don_gota") {
    paso = 3;
  } else if (turno.personaje === "pana" && tipos.includes("calculo_gota")) {
    paso = 4;
  } else if (turno.personaje === "joven" || anterior >= 2) {
    paso = 2;
  }
  return Math.max(paso, anterior);
}

/**
 * Agrupa una cifra por su fuente para colorearla en el panel.
 *
 * @param {{fuente: {tipo: string}}} cifra Cifra del turno.
 * @returns {"gota" | "banco" | "otra"} Grupo de la cifra.
 */
export function grupoDeLaCifra(cifra) {
  const tipo = cifra.fuente?.tipo;
  if (tipo === "calculo_gota") {
    return "gota";
  }
  if (tipo === "motor" || tipo === "gold") {
    return "banco";
  }
  return "otra";
}

/**
 * Escribe un monto en pesos colombianos sin decimales.
 *
 * @param {unknown} valor Monto (número o texto decimal).
 * @returns {string} Por ejemplo `$1.000.000`.
 */
export function formatearPesos(valor) {
  return `$${Math.round(aNumero(valor)).toLocaleString("es-CO")}`;
}
