/**
 * Vista Tablero de tasas · responsable: Yoldy (PR 15).
 *
 * Muestra las filas de `GET /api/tablero?q=` (tarifas del tarifario en PDF y
 * tablas de la web del banco) con concepto, valor, moneda, recargos,
 * periodicidad, vigencia, origen y fuente, y un filtro de texto.
 *
 * Reglas: con la API, quien filtra es el servidor (la vista solo envía `q`);
 * la vista no recalcula valores, no compara filas y no inventa cifras: si un
 * campo viene vacío, muestra «—». Solo en la maqueta (`?ejemplo=1`) filtra en
 * el navegador las filas de ejemplo, porque no hay servidor que lo haga.
 */

import { crearEncabezadoVista, crearTexto } from "../comun.js";

/** Milisegundos de pausa entre la última tecla y la búsqueda. */
const PAUSA_MS = 300;

/** Búsquedas rápidas que se ofrecen como botones. */
const SUGERENCIAS = ["cuota de manejo", "retiro", "cheque", "Credencial", "USD"];

/** Columnas de la tabla: clave del contrato y título visible. */
const COLUMNAS = [
  ["concepto", "Concepto"],
  ["valor", "Valor"],
  ["recargos", "Recargos"],
  ["periodicidad", "Periodicidad"],
  ["vigente_desde", "Vigente desde"],
  ["origen", "Origen"],
  ["fuente", "Fuente"],
];

/** Nombre visible de cada origen del CSV. */
const ORIGENES = { tarifario: "Tarifario", tabla_web: "Tabla web" };

/**
 * Pinta la vista Tablero dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-tablero` de `index.html`.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  const resultados = document.createElement("div");
  resultados.className = "tablero__resultados";
  resultados.setAttribute("aria-live", "polite");

  const buscador = crearBuscador((consulta) => buscar(resultados, estado, consulta));

  const vista = document.createElement("div");
  vista.className = "tablero";
  vista.append(buscador.formulario);
  if (estado.modo === "ejemplo") {
    vista.append(
      crearTexto(
        "p",
        "Datos de ejemplo: filas reales del tarifario 2025 y de la tabla de asistencias. Aquí el filtro busca dentro de estas filas; con la API, el servidor filtra el CSV completo.",
        "aviso tablero__aviso",
      ),
    );
  }
  vista.append(resultados);

  contenedor.replaceChildren(
    crearEncabezadoVista(
      "tablero",
      "Tablero de tasas",
      "Las tarifas y coberturas tal como las publica el banco, cada una con su fuente. Estas cifras no las calcula ningún modelo.",
    ),
    vista,
  );
  await buscar(resultados, estado, "");
}

/**
 * Crea el formulario de búsqueda con su campo, el botón «Limpiar» y las
 * búsquedas sugeridas. Llama a `alBuscar` con una pausa mientras se escribe.
 *
 * @param {(consulta: string) => void} alBuscar Acción que ejecuta la búsqueda.
 * @returns {{formulario: HTMLFormElement, campo: HTMLInputElement}} Elementos creados.
 */
function crearBuscador(alBuscar) {
  const formulario = document.createElement("form");
  formulario.className = "tablero__buscador";
  formulario.setAttribute("role", "search");

  const etiqueta = crearTexto("label", "Buscar en el tablero", "tablero__etiqueta");
  etiqueta.htmlFor = "tablero-consulta";

  const campo = document.createElement("input");
  campo.id = "tablero-consulta";
  campo.type = "search";
  campo.className = "tablero__campo";
  campo.placeholder = "Por ejemplo: cuota de manejo";
  campo.autocomplete = "off";

  const limpiar = crearTexto("button", "Limpiar", "tablero__boton");
  limpiar.type = "button";

  let pausa = 0;
  campo.addEventListener("input", () => {
    window.clearTimeout(pausa);
    pausa = window.setTimeout(() => alBuscar(campo.value), PAUSA_MS);
  });
  formulario.addEventListener("submit", (evento) => {
    evento.preventDefault();
    window.clearTimeout(pausa);
    alBuscar(campo.value);
  });
  limpiar.addEventListener("click", () => {
    campo.value = "";
    alBuscar("");
    campo.focus();
  });

  const fila = document.createElement("div");
  fila.className = "tablero__fila-busqueda";
  fila.append(campo, limpiar);

  const sugerencias = document.createElement("div");
  sugerencias.className = "tablero__sugerencias";
  sugerencias.append(crearTexto("span", "Prueba con:", "tablero__sugerencias-titulo"));
  for (const texto of SUGERENCIAS) {
    const boton = crearTexto("button", texto, "tablero__sugerencia");
    boton.type = "button";
    boton.addEventListener("click", () => {
      campo.value = texto;
      alBuscar(texto);
    });
    sugerencias.append(boton);
  }

  formulario.append(etiqueta, fila, sugerencias);
  return { formulario, campo };
}

/** Número de la última búsqueda, para descartar respuestas viejas. */
let ultimaBusqueda = 0;

/**
 * Pide las filas para una consulta y pinta la tabla, el estado vacío o el error.
 * Si llega una respuesta de una búsqueda anterior, la descarta.
 *
 * @param {HTMLElement} resultados Contenedor de los resultados.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @param {string} consulta Texto escrito por la persona.
 * @returns {Promise<void>}
 */
async function buscar(resultados, estado, consulta) {
  const numero = ++ultimaBusqueda;
  const q = consulta.trim();
  resultados.setAttribute("aria-busy", "true");

  let datos;
  try {
    datos = await estado.pedir("tablero", { consulta: { q } });
  } catch (error) {
    if (numero !== ultimaBusqueda) {
      return;
    }
    resultados.removeAttribute("aria-busy");
    resultados.replaceChildren(crearError(error, () => buscar(resultados, estado, consulta)));
    return;
  }
  if (numero !== ultimaBusqueda) {
    return;
  }
  resultados.removeAttribute("aria-busy");

  let filas = Array.isArray(datos?.filas) ? datos.filas : [];
  let total = Number.isInteger(datos?.total) ? datos.total : filas.length;
  if (estado.modo === "ejemplo") {
    filas = filtrarEnMaqueta(filas, q);
    total = filas.length;
  }

  if (filas.length === 0) {
    resultados.replaceChildren(crearVacio(q));
    return;
  }
  resultados.replaceChildren(crearResumen(filas.length, total, q), crearTabla(filas));
}

/**
 * Filtra las filas de ejemplo en el navegador. Solo se usa en la maqueta:
 * con la API, el filtro lo hace el servidor. Cada palabra de la consulta debe
 * aparecer en el concepto, la categoría, el valor o la moneda, sin importar
 * tildes ni mayúsculas.
 *
 * @param {object[]} filas Filas de `datos-ejemplo/tablero.json`.
 * @param {string} q Consulta ya recortada.
 * @returns {object[]} Filas coincidentes, en el mismo orden.
 */
function filtrarEnMaqueta(filas, q) {
  const palabras = normalizar(q).split(/\s+/).filter(Boolean);
  if (palabras.length === 0) {
    return filas;
  }
  return filas.filter((fila) => {
    const texto = normalizar([fila.concepto, fila.categoria, fila.valor, fila.moneda].join(" "));
    return palabras.every((palabra) => texto.includes(palabra));
  });
}

/**
 * Pasa un texto a minúsculas y le quita las tildes, para comparar búsquedas.
 *
 * @param {unknown} texto Texto de entrada.
 * @returns {string} Texto normalizado.
 */
function normalizar(texto) {
  return String(texto ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

/**
 * Crea la línea que dice cuántas filas se muestran.
 *
 * @param {number} mostradas Filas en pantalla.
 * @param {number} total Total filtrado que informa la API.
 * @param {string} q Consulta actual.
 * @returns {HTMLElement} El párrafo de resumen.
 */
function crearResumen(mostradas, total, q) {
  const palabra = total === 1 ? "fila" : "filas";
  const cuantas = mostradas === total ? `${total} ${palabra}` : `${mostradas} de ${total} ${palabra}`;
  const texto = q ? `${cuantas} para «${q}».` : `${cuantas} en el tablero.`;
  return crearTexto("p", texto, "tablero__resumen");
}

/**
 * Crea el estado vacío: explica que no hubo coincidencias y que el tablero
 * no inventa valores.
 *
 * @param {string} q Consulta sin resultados.
 * @returns {HTMLElement} El aviso.
 */
function crearVacio(q) {
  const caja = document.createElement("div");
  caja.className = "tablero__vacio";
  caja.append(
    crearTexto("strong", q ? `No hay filas para «${q}».` : "El tablero todavía no tiene filas."),
    crearTexto(
      "span",
      "El tablero solo muestra valores publicados por el banco y no inventa cifras. Prueba con otra palabra o pregunta en la Ventanilla.",
    ),
  );
  return caja;
}

/**
 * Crea el aviso de error con su botón de reintento.
 *
 * @param {Error} error Error recibido al pedir las filas.
 * @param {() => void} reintentar Acción del botón «Reintentar».
 * @returns {HTMLElement} El aviso.
 */
function crearError(error, reintentar) {
  const aviso = document.createElement("div");
  aviso.className = "aviso aviso--error tablero__error";
  aviso.setAttribute("role", "alert");

  const boton = crearTexto("button", "Reintentar", "tablero__boton");
  boton.type = "button";
  boton.addEventListener("click", reintentar);

  aviso.append(
    crearTexto("strong", "No se pudo cargar el tablero."),
    crearTexto("span", ` ${error?.message ?? "Error desconocido"}`),
    boton,
  );
  return aviso;
}

/**
 * Crea la tabla con una fila por tarifa. En celular, cada fila se ve como
 * una tarjeta gracias a `data-columna` y al CSS.
 *
 * @param {object[]} filas Filas del contrato.
 * @returns {HTMLElement} La tabla dentro de su envoltorio.
 */
function crearTabla(filas) {
  const tabla = document.createElement("table");
  tabla.className = "tablero__tabla";

  const encabezado = document.createElement("tr");
  for (const [, titulo] of COLUMNAS) {
    const celda = crearTexto("th", titulo);
    celda.scope = "col";
    encabezado.append(celda);
  }
  const thead = document.createElement("thead");
  thead.append(encabezado);

  const tbody = document.createElement("tbody");
  for (const fila of filas) {
    tbody.append(crearFila(fila));
  }

  tabla.append(thead, tbody);
  const envoltorio = document.createElement("div");
  envoltorio.className = "tablero__envoltorio";
  envoltorio.append(tabla);
  return envoltorio;
}

/**
 * Crea una fila de la tabla, sin cambiar ningún valor del contrato.
 *
 * @param {Record<string, string>} fila Fila del contrato.
 * @returns {HTMLTableRowElement} La fila.
 */
function crearFila(fila) {
  const tr = document.createElement("tr");
  for (const [clave, titulo] of COLUMNAS) {
    const td = document.createElement("td");
    td.dataset.columna = titulo;
    td.className = `tablero__celda tablero__celda--${clave.replace("_", "-")}`;
    td.append(...contenidoDeCelda(clave, fila));
    tr.append(td);
  }
  return tr;
}

/**
 * Decide qué se pinta en cada celda. Los campos vacíos se muestran como «—».
 *
 * @param {string} clave Columna del contrato.
 * @param {Record<string, string>} fila Fila del contrato.
 * @returns {Node[]} Nodos para la celda.
 */
function contenidoDeCelda(clave, fila) {
  switch (clave) {
    case "concepto": {
      const bloque = document.createElement("div");
      bloque.append(
        crearTexto("strong", textoODefecto(fila.concepto), "tablero__concepto"),
        crearTexto("span", textoODefecto(fila.categoria, ""), "tablero__categoria"),
      );
      return [bloque];
    }
    case "valor":
      return [crearTexto("span", valorConMoneda(fila), "tablero__valor")];
    case "origen":
      return [crearTexto("span", ORIGENES[fila.origen] ?? textoODefecto(fila.origen), "etiqueta")];
    case "fuente":
      return [crearEnlaceFuente(fila)];
    default:
      return [document.createTextNode(textoODefecto(fila[clave]))];
  }
}

/**
 * Une moneda y valor tal como vienen, por ejemplo `COP 16.700`. Si la
 * «moneda» es `%` (descuentos y comisiones del CSV), va después: `17 %`.
 *
 * @param {Record<string, string>} fila Fila del contrato.
 * @returns {string} Texto del valor, o «—» si falta.
 */
function valorConMoneda(fila) {
  const valor = textoODefecto(fila.valor, "");
  if (!valor) {
    return "—";
  }
  const moneda = textoODefecto(fila.moneda, "");
  if (moneda === "%") {
    return `${valor} %`;
  }
  return moneda ? `${moneda} ${valor}` : valor;
}

/**
 * Devuelve el texto recortado, o un valor por defecto si viene vacío.
 *
 * @param {unknown} valor Valor del contrato.
 * @param {string} [defecto] Texto si falta, «—» por defecto.
 * @returns {string} Texto para mostrar.
 */
function textoODefecto(valor, defecto = "—") {
  return typeof valor === "string" && valor.trim() ? valor.trim() : defecto;
}

/**
 * Crea el enlace a la fuente, solo si la URL es http o https.
 *
 * @param {Record<string, string>} fila Fila del contrato.
 * @returns {HTMLElement} Enlace o texto de respaldo.
 */
function crearEnlaceFuente(fila) {
  const url = typeof fila.fuente === "string" ? fila.fuente : "";
  if (!esUrlSegura(url)) {
    return crearTexto("span", "Sin enlace", "tablero__sin-enlace");
  }
  const enlace = crearTexto("a", "Abrir", "tablero__fuente");
  enlace.href = url;
  enlace.target = "_blank";
  enlace.rel = "noopener noreferrer";
  enlace.setAttribute("aria-label", `Abrir la fuente de «${textoODefecto(fila.concepto)}» en otra pestaña`);
  return enlace;
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
