/**
 * Sucursal 1965 · rostros de los personajes de la escena.
 *
 * Cada rostro es un dibujo plano hecho solo con figuras SVG (círculos,
 * elipses, trazos y polígonos), sin archivos de imagen ni librerías, y se
 * crean con `createElementNS`. Todos viven en una caja de 100 × 100, de los hombros hacia
 * arriba, sobre un círculo del color del personaje.
 *
 * - Pana: el mismo dibujo de las tarjetas (`pana/personaje.py`): joven con
 *   buzo gris y copete peinado hacia arriba.
 * - Don Gota: prestamista con gorra, bigote, cadena dorada y diente de oro.
 * - Joven (voluntario): pelo crespo, chaqueta de jean y audífonos al cuello.
 * - Agente del joven: robot amable con gorra al revés.
 * - Agente del banco: robot formal con diadema de atención y corbatín.
 * - Auditor: persona mayor con gafas redondas y corbata.
 * - Invitado: el voluntario que escribe por WhatsApp, con el teléfono en la mano.
 *
 * La boca de cada rostro lleva la clase `escena__boca`: la hoja de estilos la
 * mueve mientras el personaje habla.
 *
 * La pantalla muestra primero el retrato en 3D de `escena/rostros/<personaje>.webp`
 * (imágenes generadas con IA, personajes inventados). Si un retrato no carga,
 * se usa el dibujo SVG de este módulo como respaldo.
 */

const SVG = "http://www.w3.org/2000/svg";

/** Colores compartidos. */
const C = Object.freeze({
  tinta: "#2b2a27",
  crema: "#f4ecd8",
  blanco: "#f6f5f0",
  mejilla: "#e89682",
  oro: "#f2c94c",
});

/**
 * Atajo para describir una figura: etiqueta, atributos e hijos.
 *
 * @param {string} etiqueta Etiqueta SVG (circle, ellipse, path, rect, polygon, polyline, g).
 * @param {Record<string, string|number>} atributos Atributos de la figura.
 * @param {Array<Array>} [hijos] Figuras hijas (solo para `g`).
 * @returns {Array} Descripción de la figura.
 */
function f(etiqueta, atributos, hijos = []) {
  return [etiqueta, atributos, hijos];
}

/**
 * Dos ojos redondos con brillo.
 *
 * @param {number} izq Centro horizontal del ojo izquierdo.
 * @param {number} der Centro horizontal del ojo derecho.
 * @param {number} cy Centro vertical.
 * @param {number} [r] Radio.
 * @returns {Array<Array>} Figuras de los ojos.
 */
function ojos(izq, der, cy, r = 3.2) {
  return [izq, der].flatMap((cx) => [
    f("ellipse", { cx, cy, rx: r, ry: r * 1.18, fill: C.tinta }),
    f("circle", { cx: cx + r * 0.35, cy: cy - r * 0.4, r: r * 0.34, fill: C.crema }),
  ]);
}

/**
 * Dos orejas iguales a los lados de la cara.
 *
 * @param {string} piel Color de la piel.
 * @param {string} sombra Color del borde.
 * @returns {Array<Array>} Figuras de las orejas.
 */
function orejas(piel, sombra) {
  return [30, 70].map((cx) =>
    f("ellipse", { cx, cy: 51, rx: 4, ry: 5.5, fill: piel, stroke: sombra, "stroke-width": 1 }),
  );
}

/**
 * Dos mejillas rosadas.
 *
 * @returns {Array<Array>} Figuras de las mejillas.
 */
function mejillas() {
  return [37, 63].map((cx) =>
    f("ellipse", { cx, cy: 58.5, rx: 3.6, ry: 2.4, fill: C.mejilla, opacity: 0.8 }),
  );
}

/**
 * Trazo sin relleno (cejas, sonrisas, cables).
 *
 * @param {string} d Camino SVG.
 * @param {string} color Color del trazo.
 * @param {number} [grosor] Grosor del trazo.
 * @returns {Array} Figura del trazo.
 */
function trazo(d, color, grosor = 1.8) {
  return f("path", {
    d,
    fill: "none",
    stroke: color,
    "stroke-width": grosor,
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  });
}

/**
 * Pana: el joven del buzo gris de las tarjetas, sonriendo.
 *
 * @returns {Array<Array>} Figuras del rostro.
 */
function pana() {
  const piel = "#eec4a0";
  const sombra = "#daa880";
  const pelo = "#6b462c";
  const buzo = "#7a7c82";
  const buzoOscuro = "#5c5e64";
  return [
    f("rect", { x: 13, y: 80, width: 74, height: 40, rx: 14, fill: buzo }),
    f("ellipse", { cx: 50, cy: 82, rx: 17, ry: 5, fill: buzoOscuro }),
    f("polygon", { points: "39,81 61,81 55,100 45,100", fill: C.blanco }),
    f("rect", { x: 43.5, y: 69, width: 13, height: 12, rx: 3, fill: sombra }),
    f("polygon", { points: "43.5,79 56.5,79 50,87", fill: sombra }),
    f("polygon", { points: "32,83 41,81 47,100 36,100", fill: buzoOscuro }),
    f("polygon", { points: "68,83 59,81 53,100 64,100", fill: buzoOscuro }),
    trazo("M42 84 L43 95", C.blanco, 1.2),
    trazo("M58 84 L57 95", C.blanco, 1.2),
    ...orejas(piel, sombra),
    f("ellipse", { cx: 50, cy: 49, rx: 20, ry: 22, fill: piel }),
    f("path", { d: "M29 43 A21 17 0 0 1 71 43 Z", fill: pelo }),
    f("polygon", {
      points: "30,43 31,34 35,28 40,25 41,19 46,23 49,15 54,21 59,13 62,21 68,17 67,25 71,32 70,43",
      fill: pelo,
    }),
    trazo("M47 24 L52 19 L57 17", "#8c603e", 1.6),
    f("polygon", { points: "30,43 32,37 52,36 70,41 70,45 60,41 46,40 34,42", fill: pelo }),
    f("polygon", { points: "30,42 33,42 32.5,50 30.5,48", fill: pelo }),
    f("polygon", { points: "67,42 70,42 69.5,50 67.5,48", fill: pelo }),
    trazo("M37 44.5 Q41 42.5 45 44", pelo),
    trazo("M55 44 Q59 42.5 63 44.5", pelo),
    ...ojos(41, 59, 50.5),
    trazo("M47.8 56.3 Q50 58 52.2 56.3", sombra),
    ...mejillas(),
    f("g", { class: "escena__boca" }, [
      f("path", { d: "M42 60.5 A8 6.5 0 0 0 58 60.5 Z", fill: C.tinta }),
      f("path", { d: "M45.6 63.7 A4.4 2.8 0 0 0 54.4 63.7 Z", fill: C.mejilla }),
    ]),
  ];
}

/**
 * Don Gota: prestamista con gorra, bigote, cadena y diente de oro.
 *
 * @returns {Array<Array>} Figuras del rostro.
 */
function donGota() {
  const piel = "#c98d64";
  const sombra = "#a86f4c";
  const pelo = "#3a2e27";
  return [
    f("rect", { x: 12, y: 80, width: 76, height: 40, rx: 14, fill: "#2b2f3a" }),
    f("polygon", { points: "40,80 60,80 50,99", fill: "#8a2620" }),
    f("polygon", { points: "30,83 40,80 47,100 34,100", fill: "#1f222b" }),
    f("polygon", { points: "70,83 60,80 53,100 66,100", fill: "#1f222b" }),
    f("rect", { x: 44, y: 68, width: 12, height: 14, rx: 3, fill: sombra }),
    trazo("M41 83 Q50 96 59 83", C.oro, 2),
    f("circle", { cx: 50, cy: 91.5, r: 2.4, fill: C.oro }),
    ...orejas(piel, sombra),
    f("ellipse", { cx: 50, cy: 50, rx: 19, ry: 21, fill: piel }),
    f("rect", { x: 30, y: 39, width: 3.2, height: 11, rx: 1.5, fill: "#6f6a66" }),
    f("rect", { x: 66.8, y: 39, width: 3.2, height: 11, rx: 1.5, fill: "#6f6a66" }),
    f("path", { d: "M29 40 Q30 22 50 21 Q70 22 71 40 Z", fill: "#55443a" }),
    f("path", { d: "M26 41 Q50 32 78 37 L79 41.5 Q50 37.5 25 44.5 Z", fill: "#3f3229" }),
    f("circle", { cx: 50, cy: 22.5, r: 1.6, fill: "#3f3229" }),
    trazo("M36 45 L45 46.2", pelo, 2.6),
    trazo("M55 44.5 L64 40.5", pelo, 2.6),
    f("ellipse", { cx: 41, cy: 50.5, rx: 2.6, ry: 2.4, fill: C.tinta }),
    f("ellipse", { cx: 59, cy: 50, rx: 2.6, ry: 2.8, fill: C.tinta }),
    trazo("M37.5 49 Q41 47.6 44.5 49", pelo, 1.6),
    trazo("M48.5 52 Q46.5 57.5 50 58.2 Q53 58.4 52.3 56.4", sombra),
    f("path", {
      d: "M39.5 61.5 Q45 57 50 60 Q55 57 60.5 61.5 Q55 63.2 50 61.6 Q45 63.2 39.5 61.5 Z",
      fill: pelo,
    }),
    f("g", { class: "escena__boca" }, [
      f("path", { d: "M43 64.4 Q50 70 57.5 63.4 Q50 66.8 43 64.4 Z", fill: C.tinta }),
      f("rect", { x: 51.6, y: 64.9, width: 2.2, height: 2, rx: 0.4, fill: C.oro }),
    ]),
  ];
}

/**
 * Joven (voluntario): pelo crespo, chaqueta de jean y audífonos al cuello.
 *
 * @returns {Array<Array>} Figuras del rostro.
 */
function joven() {
  const piel = "#9a6443";
  const sombra = "#7c4d31";
  const pelo = "#2a1d17";
  const rizos = [
    [32, 41, 6],
    [35, 32, 7],
    [43, 26.5, 7.5],
    [52.5, 25, 7.5],
    [61, 28, 7],
    [67, 35, 6.5],
    [69, 42.5, 5],
    [31, 47, 3.8],
  ];
  return [
    f("rect", { x: 14, y: 80, width: 72, height: 40, rx: 14, fill: "#3d5a80" }),
    f("polygon", { points: "40,80 60,80 56,100 44,100", fill: "#fff3d6" }),
    f("polygon", { points: "30,83 41,80 46,100 34,100", fill: "#2f4766" }),
    f("polygon", { points: "70,83 59,80 54,100 66,100", fill: "#2f4766" }),
    f("rect", { x: 44, y: 68, width: 12, height: 14, rx: 3, fill: sombra }),
    trazo("M36 79 Q50 92 64 79", "#1f2430", 2.6),
    f("rect", { x: 31.5, y: 75, width: 7, height: 9, rx: 3, fill: "#1f2430" }),
    f("rect", { x: 61.5, y: 75, width: 7, height: 9, rx: 3, fill: "#1f2430" }),
    ...orejas(piel, sombra),
    f("ellipse", { cx: 50, cy: 50, rx: 19, ry: 21, fill: piel }),
    ...rizos.map(([cx, cy, r]) => f("circle", { cx, cy, r, fill: pelo })),
    f("path", { d: "M31 44 Q36 34 50 34 Q64 34 69 44 Q62 38 50 38.5 Q38 38 31 44 Z", fill: pelo }),
    trazo("M37 44.5 Q41 42.5 45 44", pelo),
    trazo("M55 44 Q59 42.5 63 44.5", pelo),
    ...ojos(41, 59, 50.5),
    trazo("M47.8 56.3 Q50 58 52.2 56.3", sombra),
    ...mejillas(),
    f("g", { class: "escena__boca" }, [
      f("path", { d: "M43.5 61 Q50 67.5 56.5 61 Z", fill: C.tinta }),
      f("path", { d: "M44.5 61 L55.5 61 L55 62.3 L45 62.3 Z", fill: C.blanco }),
    ]),
  ];
}

/**
 * Agente del joven: robot amable, de pantalla azul y gorra al revés.
 *
 * @returns {Array<Array>} Figuras del rostro.
 */
function agenteJoven() {
  const metal = "#e6ecf5";
  const gris = "#8a95a8";
  const luz = "#7ff0ff";
  return [
    f("rect", { x: 16, y: 82, width: 68, height: 38, rx: 12, fill: "#2d4a8a" }),
    f("circle", { cx: 50, cy: 92, r: 3.2, fill: luz }),
    f("rect", { x: 45, y: 68, width: 10, height: 15, rx: 2, fill: gris }),
    f("rect", { x: 24, y: 40, width: 6, height: 16, rx: 2.5, fill: gris }),
    f("rect", { x: 70, y: 40, width: 6, height: 16, rx: 2.5, fill: gris }),
    trazo("M50 17 L50 26", "#c9d3e3", 2),
    f("circle", { cx: 50, cy: 15.5, r: 3.2, fill: "#ffd166" }),
    f("rect", { x: 28, y: 26, width: 44, height: 44, rx: 12, fill: metal }),
    f("path", { d: "M29 34 Q30 21 50 21 Q70 21 71 34 Z", fill: "#ff7a59" }),
    f("path", { d: "M29 32 L19 30.5 Q18 33.5 20 35 L30 35 Z", fill: "#e2603f" }),
    f("rect", { x: 33, y: 37, width: 34, height: 25, rx: 7, fill: "#142240" }),
    f("rect", { x: 39.5, y: 42, width: 7, height: 8, rx: 3.5, fill: luz }),
    f("rect", { x: 53.5, y: 42, width: 7, height: 8, rx: 3.5, fill: luz }),
    f("g", { class: "escena__boca" }, [trazo("M42.5 54.5 Q50 59.5 57.5 54.5", luz, 2.4)]),
  ];
}

/**
 * Agente del banco: robot formal con diadema de atención y corbatín.
 *
 * @returns {Array<Array>} Figuras del rostro.
 */
function agenteBanco() {
  const metal = "#ece6f7";
  const oscuro = "#2a2140";
  const luz = "#e6d6ff";
  return [
    f("rect", { x: 14, y: 82, width: 72, height: 38, rx: 12, fill: "#3b2d5c" }),
    f("polygon", { points: "42,82 58,82 50,97", fill: "#f4f1fb" }),
    f("polygon", { points: "44.5,84.5 50,87 55.5,84.5 55.5,90 50,87.5 44.5,90", fill: "#c39bff" }),
    f("rect", { x: 45, y: 68, width: 10, height: 15, rx: 2, fill: "#8a7fa3" }),
    f("rect", { x: 28, y: 24, width: 44, height: 46, rx: 14, fill: metal }),
    trazo("M26 46 Q26 17 50 17 Q74 17 74 46", oscuro, 3),
    f("rect", { x: 22.5, y: 39, width: 7.5, height: 14, rx: 3, fill: oscuro }),
    f("rect", { x: 70, y: 39, width: 7.5, height: 14, rx: 3, fill: oscuro }),
    trazo("M26.5 52 Q28.5 64.5 40 64.5", oscuro, 2),
    f("circle", { cx: 41.5, cy: 64.5, r: 2.3, fill: oscuro }),
    f("rect", { x: 33, y: 33, width: 34, height: 25, rx: 7, fill: "#241a3d" }),
    trazo("M39 45 Q43 40.5 47 45", luz, 2.4),
    trazo("M53 45 Q57 40.5 61 45", luz, 2.4),
    f("g", { class: "escena__boca" }, [f("ellipse", { cx: 50, cy: 51.5, rx: 4, ry: 2.4, fill: luz })]),
  ];
}

/**
 * Auditor: persona mayor con gafas redondas, pelo canoso y corbata.
 *
 * @returns {Array<Array>} Figuras del rostro.
 */
function auditor() {
  const piel = "#f0c8a8";
  const sombra = "#d4a584";
  const canas = "#b8bec8";
  return [
    f("rect", { x: 13, y: 80, width: 74, height: 40, rx: 14, fill: "#4a5468" }),
    f("polygon", { points: "40,80 60,80 55,100 45,100", fill: C.blanco }),
    f("polygon", { points: "48,82 52,82 53.5,96 50,99 46.5,96", fill: "#2b3446" }),
    f("polygon", { points: "31,83 41,80 46,100 35,100", fill: "#3a4356" }),
    f("polygon", { points: "69,83 59,80 54,100 65,100", fill: "#3a4356" }),
    f("rect", { x: 44, y: 68, width: 12, height: 13, rx: 3, fill: sombra }),
    ...orejas(piel, sombra),
    f("ellipse", { cx: 50, cy: 50, rx: 19, ry: 21, fill: piel }),
    f("path", { d: "M30 46 Q29 30 40 27 Q50 25 60 27 Q71 30 70 46 Q67 36 60 33 Q50 31 40 33 Q33 36 30 46 Z", fill: canas }),
    trazo("M36 43 L45 43.5", "#8f96a3", 2.6),
    trazo("M55 43.5 L64 43", "#8f96a3", 2.6),
    f("circle", { cx: 41, cy: 50, r: 2, fill: C.tinta }),
    f("circle", { cx: 59, cy: 50, r: 2, fill: C.tinta }),
    f("circle", { cx: 41, cy: 50, r: 6, fill: "#ffffff", "fill-opacity": 0.22, stroke: C.tinta, "stroke-width": 1.8 }),
    f("circle", { cx: 59, cy: 50, r: 6, fill: "#ffffff", "fill-opacity": 0.22, stroke: C.tinta, "stroke-width": 1.8 }),
    trazo("M47 49.5 Q50 48 53 49.5", C.tinta, 1.6),
    trazo("M35 49 L31 47.5", C.tinta, 1.4),
    trazo("M65 49 L69 47.5", C.tinta, 1.4),
    trazo("M48.5 53 Q47.5 57.5 50 58 Q52.5 57.5 51.5 53", sombra),
    f("g", { class: "escena__boca" }, [trazo("M44.5 63 Q50 65.2 55.5 63", C.tinta, 2)]),
  ];
}

/**
 * Invitado: el voluntario que escribe por WhatsApp, con el teléfono en la mano.
 *
 * @returns {Array<Array>} Figuras del rostro.
 */
function invitado() {
  const piel = "#b9825f";
  const sombra = "#966548";
  const pelo = "#241b16";
  return [
    f("rect", { x: 14, y: 82, width: 72, height: 38, rx: 12, fill: "#4f6b57" }),
    f("polygon", { points: "41,82 59,82 55,100 45,100", fill: C.crema }),
    f("rect", { x: 45, y: 68, width: 10, height: 15, rx: 2, fill: sombra }),
    ...orejas(piel, sombra),
    f("ellipse", { cx: 50, cy: 50, rx: 19, ry: 21, fill: piel }),
    f("path", { d: "M31 45 Q33 31 50 30 Q67 31 69 45 Q62 39 50 39.5 Q38 39 31 45 Z", fill: pelo }),
    ...ojos(41, 59, 50.5),
    trazo("M47.8 56.3 Q50 58 52.2 56.3", sombra),
    ...mejillas(),
    f("g", { class: "escena__boca" }, [trazo("M44 62 Q50 66 56 62", C.tinta, 2)]),
    f("rect", { x: 76, y: 72, width: 9, height: 16, rx: 2, fill: "#1f222b" }),
    f("rect", { x: 77.5, y: 74, width: 6, height: 11, rx: 1, fill: "#9fd8ff" }),
    trazo("M76 88 Q68 93 60 92", piel, 2.6),
  ];
}

/** Dibujo de cada personaje del contrato. */
const DIBUJOS = Object.freeze({
  pana,
  don_gota: donGota,
  joven,
  agente_joven: agenteJoven,
  agente_banco: agenteBanco,
  auditor,
  invitado,
});

/**
 * Convierte una descripción de figura en un elemento SVG.
 *
 * @param {Array} figura Descripción `[etiqueta, atributos, hijos]`.
 * @returns {SVGElement} El elemento creado.
 */
function construir([etiqueta, atributos, hijos]) {
  const elemento = document.createElementNS(SVG, etiqueta);
  for (const [nombre, valor] of Object.entries(atributos)) {
    elemento.setAttribute(nombre, String(valor));
  }
  elemento.append(...hijos.map(construir));
  return elemento;
}

/**
 * Arma el rostro SVG de un personaje sobre un círculo de su color.
 *
 * El círculo usa `currentColor`, así el color sale de la hoja de estilos. El
 * dibujo se recorta al círculo para que los hombros no se salgan.
 *
 * @param {string} personaje Personaje del contrato (pana, don_gota, …).
 * @returns {SVGSVGElement} El rostro, listo para insertar en la página.
 */
export function rostro(personaje) {
  const dibujo = DIBUJOS[personaje] ?? DIBUJOS.pana;
  const recorte = `escena-recorte-${personaje}`;
  const lienzo = construir(
    f("svg", { viewBox: "0 0 100 100", class: "escena__avatar", "aria-hidden": "true" }, [
      f("defs", {}, [f("clipPath", { id: recorte }, [f("circle", { cx: 50, cy: 50, r: 47 })])]),
      f("circle", { cx: 50, cy: 50, r: 47, class: "escena__figura" }),
      f("g", { "clip-path": `url(#${recorte})` }, dibujo()),
    ]),
  );
  return lienzo;
}

/** Carpeta de los retratos en 3D, relativa a `escena.html`. */
const CARPETA_RETRATOS = "escena/rostros";

/**
 * Arma el retrato en 3D de un personaje, con el dibujo SVG como respaldo.
 *
 * Si la imagen no existe o no carga, se reemplaza por `rostro(personaje)` sin
 * avisar: la escena sigue igual, solo cambia el estilo de esa cara.
 *
 * @param {string} personaje Personaje del contrato (pana, don_gota, …).
 * @returns {HTMLImageElement} La imagen, lista para insertar en la página.
 */
export function retrato(personaje) {
  const imagen = document.createElement("img");
  imagen.className = "escena__avatar escena__foto";
  imagen.alt = "";
  imagen.decoding = "async";
  imagen.addEventListener("error", () => imagen.replaceWith(rostro(personaje)), { once: true });
  imagen.src = `${CARPETA_RETRATOS}/${personaje}.webp`;
  return imagen;
}

/** Personajes que tienen rostro dibujado. */
export const CON_ROSTRO = Object.freeze(Object.keys(DIBUJOS));
