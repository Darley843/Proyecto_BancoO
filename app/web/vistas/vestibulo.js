/**
 * Vista Vestíbulo · responsable: Yoldy (PR 17).
 *
 * Es la pantalla de bienvenida de la sucursal. Tiene tres partes:
 * 1. una portada con una entrada clara a la Ventanilla;
 * 2. un mapa corto de los espacios de la sucursal;
 * 3. la línea de tiempo del banco desde 1965, con los hitos de
 *    `config/vestibulo.toml` (GET /api/vestibulo), cada uno con su fuente.
 *
 * No llama al modelo ni necesita el índice: solo lee hitos con año, texto y
 * enlace. Todo texto se pinta con `textContent` (vía `crearTexto`).
 */

import { crearEncabezadoVista, crearTexto } from "../comun.js";

/** Espacios de la sucursal que se presentan en el Vestíbulo. */
const ESPACIOS = [
  {
    vista: "ventanilla",
    titulo: "Ventanilla",
    texto: "Haz tu pregunta y recibe un comprobante con fuentes, tokens y costo.",
  },
  {
    vista: "boveda",
    titulo: "Bóveda",
    texto: "Mira en un mapa de qué fragmentos sale cada respuesta.",
  },
  {
    vista: "tablero",
    titulo: "Tablero de tasas",
    texto: "Consulta tarifas y cuotas tal como las publica el banco.",
  },
  {
    vista: "camara",
    titulo: "Cámara",
    texto: "Sigue el camino de los datos, de la web del banco al índice.",
  },
  {
    vista: "arqueo",
    titulo: "Arqueo",
    texto: "Revisa qué tan bien responde el asistente, con cifras.",
  },
];

/**
 * Pinta la vista Vestíbulo dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-vestibulo` de `index.html`.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  const linea = document.createElement("section");
  linea.className = "vestibulo__linea";
  linea.setAttribute("aria-labelledby", "titulo-linea-vestibulo");

  const vista = document.createElement("div");
  vista.className = "vestibulo";
  vista.append(crearPortada(), crearEspacios(), linea);

  contenedor.replaceChildren(
    crearEncabezadoVista(
      "vestibulo",
      "Vestíbulo",
      "Te damos la bienvenida a la Sucursal 1965, un asistente que responde sobre el Banco de Occidente con fuentes públicas.",
    ),
    vista,
  );
  await pintarHitos(linea, estado);
}

/**
 * Crea la portada: sello de 1965, lema y entrada a la Ventanilla.
 *
 * @returns {HTMLElement} El bloque de portada.
 */
function crearPortada() {
  const portada = document.createElement("div");
  portada.className = "vestibulo__portada";

  const sello = crearTexto("span", "1965", "vestibulo__sello");
  sello.setAttribute("aria-hidden", "true");

  const texto = document.createElement("div");
  texto.className = "vestibulo__portada-texto";
  const entrada = crearTexto("a", "Tomar turno en la Ventanilla", "boton-primario vestibulo__entrada");
  entrada.href = "#ventanilla";
  texto.append(
    crearTexto("p", "Desde Cali, desde 1965", "vestibulo__antetitulo"),
    crearTexto("h2", "El banco que lo conoce a usted, ahora con un asistente", "vestibulo__lema"),
    crearTexto(
      "p",
      "Pregunta por productos, tarifas o historia del banco. Cada respuesta cita su fuente y muestra cuánto costó.",
      "vestibulo__bajada",
    ),
    entrada,
  );

  portada.append(sello, texto);
  return portada;
}

/**
 * Crea la lista de espacios de la sucursal, cada uno como enlace a su vista.
 *
 * @returns {HTMLElement} La navegación de espacios.
 */
function crearEspacios() {
  const bloque = document.createElement("nav");
  bloque.className = "vestibulo__espacios";
  bloque.setAttribute("aria-label", "Qué hay en cada espacio");

  const lista = document.createElement("ul");
  lista.className = "vestibulo__espacios-lista";
  for (const espacio of ESPACIOS) {
    const enlace = document.createElement("a");
    enlace.className = "vestibulo__espacio";
    enlace.href = `#${espacio.vista}`;
    enlace.append(
      crearTexto("strong", espacio.titulo, "vestibulo__espacio-titulo"),
      crearTexto("span", espacio.texto, "vestibulo__espacio-texto"),
    );
    const item = document.createElement("li");
    item.append(enlace);
    lista.append(item);
  }

  bloque.append(crearTexto("h2", "Qué hay en cada espacio", "vestibulo__subtitulo"), lista);
  return bloque;
}

/**
 * Pide los hitos y pinta la línea de tiempo; si falla, muestra el error con
 * un botón para reintentar.
 *
 * @param {HTMLElement} seccion Sección de la línea de tiempo.
 * @param {{pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
async function pintarHitos(seccion, estado) {
  const titulo = crearTexto("h2", "Línea de tiempo", "vestibulo__subtitulo");
  titulo.id = "titulo-linea-vestibulo";
  seccion.replaceChildren(titulo, crearTexto("p", "Cargando la historia…", "cargando"));

  let datos;
  try {
    datos = await estado.pedir("vestibulo");
  } catch (error) {
    seccion.replaceChildren(titulo, crearErrorHitos(error, () => pintarHitos(seccion, estado)));
    return;
  }

  const hitos = normalizarHitos(datos?.hitos);
  if (hitos.length === 0) {
    seccion.replaceChildren(
      titulo,
      crearTexto("p", "Aún no hay hitos configurados en config/vestibulo.toml.", "aviso"),
    );
    return;
  }

  seccion.replaceChildren(
    titulo,
    crearTexto(
      "p",
      `${hitos.length} momentos del banco, de ${hitos[0].anio} a ${hitos.at(-1).anio}. Cada uno enlaza a su fuente pública.`,
      "vestibulo__resumen",
    ),
    ...agruparPorDecada(hitos).map(([decada, grupo]) => crearDecada(decada, grupo)),
  );
}

/**
 * Crea el aviso de error de la línea de tiempo con su botón de reintento.
 *
 * @param {Error} error Error recibido al pedir los hitos.
 * @param {() => void} reintentar Acción del botón «Reintentar».
 * @returns {HTMLElement} El aviso.
 */
function crearErrorHitos(error, reintentar) {
  const aviso = document.createElement("div");
  aviso.className = "aviso aviso--error vestibulo__error";
  aviso.setAttribute("role", "alert");

  const boton = crearTexto("button", "Reintentar", "vestibulo__reintentar");
  boton.type = "button";
  boton.addEventListener("click", reintentar);

  aviso.append(
    crearTexto("strong", "No se pudo cargar la línea de tiempo."),
    crearTexto("span", ` ${error?.message ?? "Error desconocido"}`),
    boton,
  );
  return aviso;
}

/**
 * Deja solo los hitos válidos (año entero y texto) y los ordena por año.
 *
 * @param {unknown} hitos Lista recibida del contrato.
 * @returns {{anio: number, texto: string, url: string}[]} Hitos listos para pintar.
 */
function normalizarHitos(hitos) {
  if (!Array.isArray(hitos)) {
    return [];
  }
  return hitos
    .filter((hito) => Number.isInteger(hito?.anio) && typeof hito?.texto === "string" && hito.texto.trim())
    .map((hito) => ({ anio: hito.anio, texto: hito.texto.trim(), url: typeof hito.url === "string" ? hito.url : "" }))
    .sort((a, b) => a.anio - b.anio);
}

/**
 * Agrupa los hitos por década, conservando el orden.
 *
 * @param {{anio: number}[]} hitos Hitos ya ordenados.
 * @returns {[number, object[]][]} Pares `[década, hitos]`, por ejemplo `[1970, [...]]`.
 */
function agruparPorDecada(hitos) {
  const grupos = new Map();
  for (const hito of hitos) {
    const decada = Math.floor(hito.anio / 10) * 10;
    if (!grupos.has(decada)) {
      grupos.set(decada, []);
    }
    grupos.get(decada).push(hito);
  }
  return [...grupos.entries()];
}

/**
 * Crea el bloque de una década con su lista de hitos.
 *
 * @param {number} decada Año inicial de la década, por ejemplo 1970.
 * @param {{anio: number, texto: string, url: string}[]} hitos Hitos de esa década.
 * @returns {HTMLElement} El bloque de la década.
 */
function crearDecada(decada, hitos) {
  const bloque = document.createElement("div");
  bloque.className = "vestibulo__decada";

  const lista = document.createElement("ol");
  lista.className = "vestibulo__hitos";
  for (const hito of hitos) {
    lista.append(crearHito(hito));
  }

  bloque.append(crearTexto("h3", `Década de ${decada}`, "vestibulo__decada-titulo"), lista);
  return bloque;
}

/**
 * Crea un hito: año, texto y enlace a la fuente (solo si es http o https).
 *
 * @param {{anio: number, texto: string, url: string}} hito Hito del contrato.
 * @returns {HTMLElement} El elemento de la lista.
 */
function crearHito(hito) {
  const item = document.createElement("li");
  item.className = "vestibulo__hito";

  const anio = crearTexto("time", String(hito.anio), "vestibulo__anio");
  anio.dateTime = String(hito.anio);
  item.append(anio, crearTexto("p", hito.texto, "vestibulo__texto"));

  if (esUrlSegura(hito.url)) {
    const enlace = crearTexto("a", "Ver fuente", "vestibulo__fuente");
    enlace.href = hito.url;
    enlace.target = "_blank";
    enlace.rel = "noopener noreferrer";
    enlace.setAttribute("aria-label", `Ver la fuente del hito de ${hito.anio} en otra pestaña`);
    item.append(enlace);
  }
  return item;
}

/**
 * Comprueba que una URL sea http o https antes de usarla como enlace.
 *
 * @param {string} url URL de la fuente.
 * @returns {boolean} `true` si es segura.
 */
function esUrlSegura(url) {
  if (typeof url !== "string" || !url.trim()) {
    return false;
  }
  try {
    const destino = new URL(url);
    return destino.protocol === "http:" || destino.protocol === "https:";
  } catch {
    return false;
  }
}
