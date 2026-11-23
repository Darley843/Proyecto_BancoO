/**
 * Sucursal 1965 · datos del panel de trazabilidad de la escena (tarea 6.5).
 *
 * El panel es para quien facilita, no para el público: por cada turno muestra
 * su `id`, su `origen`, el `escenario.codigo`, la fuente de cada cifra y los
 * hallazgos del auditor, y arriba un resumen con la usura, la tasa del banco,
 * la tasa del gota y el veredicto. Este módulo no toca la página: solo arma
 * los datos que `escena.js` pinta.
 */

import { TEXTO_VEREDICTO } from "./contrato.js";

/**
 * Clave con que se recuerda una cifra ya dicha: la misma fuente no se repite.
 *
 * @param {{etiqueta: string, fuente: {tipo: string, referencia: string}}} cifra Cifra del turno.
 * @returns {string} Clave única de la cifra.
 */
export function claveDeLaCifra(cifra) {
  return `${cifra.fuente?.tipo}|${cifra.fuente?.referencia}|${cifra.etiqueta}`;
}

/**
 * Busca la primera cifra que cumple una condición.
 *
 * @param {Iterable<object>} cifras Cifras dichas hasta ahora.
 * @param {(cifra: object) => boolean} condicion Qué cifra se busca.
 * @returns {object | null} La cifra, o `null`.
 */
function buscar(cifras, condicion) {
  for (const cifra of cifras) {
    if (condicion(cifra)) {
      return cifra;
    }
  }
  return null;
}

/**
 * Resumen del panel: las tres tasas que se comparan y el veredicto.
 *
 * Las tasas se reconocen por su fuente y su unidad, no por el texto de la
 * etiqueta: usura (`usura`), tasa del banco (`motor` o `gold` en E.A.) y tasa
 * del gota (`calculo_gota` en E.A.). Si una tasa aún no se ha dicho, su fila
 * queda «sin decir».
 *
 * @param {Iterable<object>} cifras Cifras dichas hasta ahora.
 * @param {string | null} veredicto `conforme`, `con_observaciones`, `objeta` o `null`.
 * @returns {Array<{nombre: string, valor: string, fuente: string}>} Filas del resumen.
 */
export function resumenDeTraza(cifras, veredicto) {
  const lista = [...cifras];
  const enEA = (cifra) => cifra.unidad === "porcentaje_ea";
  const filas = [
    ["Usura", buscar(lista, (c) => c.fuente?.tipo === "usura")],
    ["Tasa del banco", buscar(lista, (c) => enEA(c) && ["motor", "gold"].includes(c.fuente?.tipo))],
    ["Tasa del gota", buscar(lista, (c) => enEA(c) && c.fuente?.tipo === "calculo_gota")],
  ].map(([nombre, cifra]) => ({
    nombre,
    valor: cifra ? cifra.valor_legible : "sin decir",
    fuente: cifra ? `${cifra.fuente.tipo} · ${cifra.fuente.referencia}` : "",
  }));
  filas.push({
    nombre: "Veredicto del auditor",
    valor: veredicto ? TEXTO_VEREDICTO[veredicto] : "sin veredicto",
    fuente: veredicto ? "auditor (sin colores)" : "",
  });
  return filas;
}

/**
 * Datos de un turno para el panel: identidad, origen, escenario, fuentes y
 * hallazgos.
 *
 * @param {object} turno Turno ya validado por `contrato.js`.
 * @returns {{id: string, origen: string, escenario: string, fuentes: Array<{etiqueta: string, tipo: string, referencia: string, vigencia: string}>, hallazgos: string[]}}
 *   Lo que muestra el panel.
 */
export function trazaDelTurno(turno) {
  return {
    id: turno.id,
    origen: turno.origen,
    escenario: turno.escenario?.codigo ?? "—",
    fuentes: turno.cifras.map((cifra) => ({
      etiqueta: cifra.etiqueta,
      tipo: cifra.fuente.tipo,
      referencia: cifra.fuente.referencia,
      vigencia: cifra.fuente.vigencia ?? "",
    })),
    hallazgos: turno.hallazgos.map(
      (hallazgo) => `${hallazgo.gravedad} · ${hallazgo.codigo ?? "hallazgo"}: ${hallazgo.detalle}`,
    ),
  };
}

/**
 * Sellos de la escena (`sha256` de las configuraciones y de Gold), cortos.
 *
 * @param {Record<string, string> | undefined} sellos `Escena.sellos`.
 * @returns {string[]} Por ejemplo `config/tasas.toml 1a2b3c4d`.
 */
export function sellosCortos(sellos) {
  if (!sellos || typeof sellos !== "object") {
    return [];
  }
  return Object.entries(sellos)
    .filter(([, hash]) => typeof hash === "string" && hash.length > 0)
    .map(([ruta, hash]) => `${ruta} ${hash.slice(0, 8)}`);
}
