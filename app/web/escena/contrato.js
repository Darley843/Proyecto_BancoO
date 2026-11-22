/**
 * Sucursal 1965 · contrato del turno de la escena «Pana vs. el gota a gota».
 *
 * Cada turno, venga del guion, del motor o del modelo, trae los mismos campos
 * (plan de cierre, sección 6). Así la voz, los subtítulos y el auditor se
 * conectan sin depender de cómo se generó el texto:
 *
 * - `personaje`: joven, don_gota, pana, agente_joven, agente_banco o auditor.
 * - `texto`: lo que se dice en voz y se muestra en subtítulos.
 * - `cifras`: lista de `{nombre, valor, fuente}`; `fuente` es motor, simulador
 *   o Tablero. Las tasas van como fracción (0,24 = 24 %).
 * - `escenario`: `{monto, plazo, semaforo}`; `semaforo` puede venir vacío.
 * - `origen`: guion, motor, modelo o reglas.
 * - `hallazgos`: objeciones del auditor (lista vacía si está conforme).
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
]);

/** De dónde puede salir el texto de un turno. */
export const ORIGENES = Object.freeze(["guion", "motor", "modelo", "reglas"]);

/** De dónde puede salir una cifra. */
export const FUENTES = Object.freeze(["motor", "simulador", "Tablero"]);

/** Colores válidos del semáforo (vacío = aún no calculado). */
export const SEMAFOROS = Object.freeze(["", "verde", "amarillo", "rojo"]);

/** Pasos de la escena, en orden (plan de cierre, sección 5). */
export const PASOS = Object.freeze([
  "Voluntario",
  "Personaje",
  "Oferta de Don Gota",
  "Pana compara",
  "Negociación",
  "Veredicto",
]);

/** Nombres visibles de algunas cifras conocidas. */
const ETIQUETAS = Object.freeze({
  monto: "Monto",
  plazo_meses: "Plazo",
  tasa_mensual_don_gota: "Tasa mensual de Don Gota",
  tea_don_gota: "TEA de Don Gota",
  cuota_don_gota: "Cuota de Don Gota",
  total_don_gota: "Total con Don Gota",
  tea_banco: "TEA del banco",
  cuota_banco: "Cuota del banco",
  total_banco: "Total con el banco",
  usura: "Usura (referencia)",
});

/**
 * Revisa que un turno cumpla el contrato.
 *
 * @param {unknown} turno Turno recibido (del guion, el motor o el modelo).
 * @returns {string[]} Errores encontrados; vacía si el turno es válido.
 */
export function erroresDelTurno(turno) {
  const errores = [];
  if (!turno || typeof turno !== "object") {
    return ["el turno no es un objeto"];
  }
  if (!PERSONAJES.includes(turno.personaje)) {
    errores.push(`personaje desconocido: ${turno.personaje}`);
  }
  if (typeof turno.texto !== "string" || !turno.texto.trim()) {
    errores.push("falta el texto");
  }
  if (!ORIGENES.includes(turno.origen)) {
    errores.push(`origen desconocido: ${turno.origen}`);
  }
  if (!Array.isArray(turno.cifras)) {
    errores.push("cifras debe ser una lista");
  } else {
    turno.cifras.forEach((cifra, posicion) => {
      if (typeof cifra?.nombre !== "string" || !cifra.nombre) {
        errores.push(`cifra ${posicion}: falta el nombre`);
      }
      if (typeof cifra?.valor !== "number" || !Number.isFinite(cifra.valor)) {
        errores.push(`cifra ${posicion}: el valor no es un número`);
      }
      if (!FUENTES.includes(cifra?.fuente)) {
        errores.push(`cifra ${posicion}: fuente desconocida ${cifra?.fuente}`);
      }
    });
  }
  const escenario = turno.escenario;
  if (!escenario || typeof escenario !== "object") {
    errores.push("falta el escenario");
  } else if (!SEMAFOROS.includes(escenario.semaforo ?? "")) {
    errores.push(`semáforo desconocido: ${escenario.semaforo}`);
  }
  if (!Array.isArray(turno.hallazgos)) {
    errores.push("hallazgos debe ser una lista");
  }
  return errores;
}

/**
 * Deduce en qué paso de la escena va un turno.
 *
 * El contrato no trae el paso: se deduce de quién habla y de lo que ya pasó,
 * y nunca retrocede.
 *
 * @param {{personaje: string, cifras: Array<{nombre: string}>}} turno Turno actual.
 * @param {number} anterior Paso del turno anterior (0 a 5; -1 al empezar).
 * @returns {number} Paso del turno, de 0 a 5.
 */
export function pasoDelTurno(turno, anterior) {
  const nombres = (turno.cifras ?? []).map((cifra) => cifra.nombre);
  let paso = 0;
  if (turno.personaje === "auditor") {
    paso = 5;
  } else if (turno.personaje === "agente_joven" || turno.personaje === "agente_banco") {
    paso = 4;
  } else if (turno.personaje === "don_gota") {
    paso = 2;
  } else if (turno.personaje === "pana" && nombres.some((n) => n.startsWith("tea_"))) {
    paso = 3;
  } else if (turno.personaje === "joven" || anterior >= 1) {
    paso = 1;
  }
  return Math.max(paso, anterior);
}

/**
 * Da formato a una cifra según su nombre.
 *
 * Tasas, TEA y usura van como porcentaje; plazos en meses; montos, cuotas y
 * totales en pesos. Cualquier otra cifra sale como número.
 *
 * @param {{nombre: string, valor: number}} cifra Cifra del turno.
 * @returns {{etiqueta: string, texto: string}} Nombre visible y valor con formato.
 */
export function formatearCifra(cifra) {
  const nombre = cifra.nombre;
  const etiqueta = ETIQUETAS[nombre] ?? nombre.split("_").join(" ");
  let texto;
  if (/^(tasa|tea)|usura/.test(nombre)) {
    const porcentaje = (cifra.valor * 100).toLocaleString("es-CO", {
      maximumFractionDigits: 1,
    });
    texto = `${porcentaje} %`;
  } else if (/plazo/.test(nombre)) {
    texto = `${cifra.valor} meses`;
  } else if (/monto|cuota|total/.test(nombre)) {
    texto = `$${Math.round(cifra.valor).toLocaleString("es-CO")}`;
  } else {
    texto = cifra.valor.toLocaleString("es-CO");
  }
  return { etiqueta, texto };
}
