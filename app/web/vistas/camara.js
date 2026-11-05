/**
 * Vista Cámara de compensación · responsable: Yoldy (PR 16).
 *
 * Muestra el pipeline de punta a punta con `GET /api/pipeline`: las cinco
 * etapas de `panel.pipeline_summary` (descubrir, Bronze, Silver, deduplicar,
 * Gold) y la etapa nueva de indexación, cada una con sus métricas, su nota y
 * su aviso. Abajo, el detalle de repeticiones y los archivos que se leyeron.
 *
 * Los avisos de una etapa (por ejemplo, «Bronze no está en este clon») se
 * muestran como avisos informativos, no como errores: el pipeline puede
 * estar bien aunque una capa no viaje en el repositorio. La vista solo pinta
 * lo que llega: no cuenta archivos ni recalcula métricas.
 */

import { crearEncabezadoVista, crearTexto } from "../comun.js";

/** Número de bloques repetidos que se muestran en el detalle. */
const BLOQUES_VISIBLES = 5;

/**
 * Pinta la vista Cámara dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-camara` de `index.html`.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  const cuerpo = document.createElement("div");
  cuerpo.className = "camara";
  cuerpo.setAttribute("aria-live", "polite");

  contenedor.replaceChildren(
    crearEncabezadoVista(
      "camara",
      "Cámara de compensación",
      "El camino de los datos, de la web del banco al índice: qué hace cada etapa, cuánto produjo y qué avisos dejó.",
    ),
    cuerpo,
  );
  await pintar(cuerpo, estado);
}

/**
 * Pide el resumen del pipeline y lo pinta; si falla, muestra el error con
 * un botón para reintentar.
 *
 * @param {HTMLElement} cuerpo Contenedor de la vista.
 * @param {{pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
async function pintar(cuerpo, estado) {
  cuerpo.replaceChildren(crearTexto("p", "Cargando el pipeline…", "cargando"));

  let datos;
  try {
    datos = await estado.pedir("pipeline");
  } catch (error) {
    cuerpo.replaceChildren(crearError(error, () => pintar(cuerpo, estado)));
    return;
  }

  const etapas = Array.isArray(datos?.etapas) ? datos.etapas : [];
  const lista = document.createElement("ol");
  lista.className = "camara__etapas";
  etapas.forEach((etapa, posicion) => lista.append(crearEtapa(etapa, posicion + 1)));
  lista.append(crearIndexacion(datos?.indexacion, etapas.length + 1));

  const avisos = etapas.filter((etapa) => textoODefecto(etapa?.warning, "")).length;
  cuerpo.replaceChildren(crearResumen(etapas.length + 1, avisos, datos?.indexacion), lista);

  const repeticiones = crearRepeticiones(datos?.repeticiones);
  if (repeticiones) {
    cuerpo.append(repeticiones);
  }
  cuerpo.append(crearFuentes(datos?.fuentes));
}

/**
 * Crea la línea de resumen: cuántas etapas, cuántas con aviso y si el índice
 * está listo.
 *
 * @param {number} total Etapas mostradas, con la indexación.
 * @param {number} avisos Etapas que traen aviso.
 * @param {{indice_listo?: boolean}} [indexacion] Etapa de indexación.
 * @returns {HTMLElement} El párrafo de resumen.
 */
function crearResumen(total, avisos, indexacion) {
  const partes = [`${total} etapas`];
  partes.push(avisos === 0 ? "ninguna con aviso" : `${avisos} con aviso`);
  partes.push(indexacion?.indice_listo ? "índice listo" : "índice pendiente");
  const resumen = crearTexto("p", `${partes.join(" · ")}.`, "camara__resumen");
  if (avisos > 0) {
    resumen.append(
      crearTexto(
        "span",
        " Un aviso no es un error: suele indicar una capa que no viaja en el repositorio.",
        "camara__resumen-nota",
      ),
    );
  }
  return resumen;
}

/**
 * Crea la tarjeta de una etapa del pipeline.
 *
 * @param {{key?: string, title?: string, hint?: string, metrics?: {label: string, value: string}[], note?: string, warning?: string}} etapa
 *   Etapa del contrato (`panel.Stage`).
 * @param {number} numero Posición de la etapa, desde 1.
 * @returns {HTMLLIElement} La etapa.
 */
function crearEtapa(etapa, numero) {
  const aviso = textoODefecto(etapa?.warning, "");
  const item = crearTarjeta(
    numero,
    textoODefecto(etapa?.title, textoODefecto(etapa?.key)),
    aviso ? ["Con aviso", "aviso"] : ["Sin avisos", "ok"],
  );
  item.dataset.etapa = textoODefecto(etapa?.key, "");

  item.append(crearTexto("p", textoODefecto(etapa?.hint, ""), "camara__pista"));
  const metricas = crearMetricas(Array.isArray(etapa?.metrics) ? etapa.metrics : []);
  if (metricas) {
    item.append(metricas);
  }
  const nota = textoODefecto(etapa?.note, "");
  if (nota) {
    item.append(crearTexto("p", nota, "camara__nota"));
  }
  if (aviso) {
    const caja = crearTexto("p", aviso, "camara__aviso");
    caja.prepend(crearTexto("strong", "Aviso: "));
    item.append(caja);
  }
  return item;
}

/**
 * Crea la tarjeta de la etapa de indexación. Si el índice no existe, lo
 * explica como un paso pendiente, no como un fallo.
 *
 * @param {{indice_listo?: boolean, fragmentos_indexados?: number, modelo_embeddings?: string, alcance?: string} | null | undefined} indexacion
 *   Etapa de indexación del contrato.
 * @param {number} numero Posición de la etapa.
 * @returns {HTMLLIElement} La etapa.
 */
function crearIndexacion(indexacion, numero) {
  const listo = Boolean(indexacion?.indice_listo);
  const item = crearTarjeta(numero, "Indexar (Bóveda)", listo ? ["Índice listo", "ok"] : ["Pendiente", "pendiente"]);
  item.dataset.etapa = "indexacion";
  item.append(
    crearTexto(
      "p",
      "Convierte los fragmentos de Gold en vectores con Ollama y los guarda en Chroma para que la Bóveda los busque.",
      "camara__pista",
    ),
  );

  if (!listo) {
    const caja = crearTexto(
      "p",
      "El índice todavía no existe en este equipo. Se crea con make indice; mientras tanto, la Ventanilla y la Bóveda no pueden buscar fragmentos, pero el resto del pipeline sigue bien.",
      "camara__aviso camara__aviso--pendiente",
    );
    caja.prepend(crearTexto("strong", "Pendiente: "));
    item.append(caja);
    return item;
  }

  const fragmentos = Number.isInteger(indexacion?.fragmentos_indexados)
    ? indexacion.fragmentos_indexados.toLocaleString("es-CO")
    : "—";
  const metricas = crearMetricas([
    { label: "Fragmentos indexados", value: fragmentos },
    { label: "Modelo de embeddings", value: textoODefecto(indexacion?.modelo_embeddings) },
    { label: "Alcance", value: textoODefecto(indexacion?.alcance) },
  ]);
  if (metricas) {
    item.append(metricas);
  }
  return item;
}

/**
 * Crea la estructura común de una tarjeta de etapa: número, título y sello.
 *
 * @param {number} numero Posición de la etapa.
 * @param {string} titulo Título visible.
 * @param {[string, string]} sello Texto y tipo del sello (`ok`, `aviso` o `pendiente`).
 * @returns {HTMLLIElement} La tarjeta sin cuerpo.
 */
function crearTarjeta(numero, titulo, sello) {
  const item = document.createElement("li");
  item.className = "camara__etapa";

  const cabecera = document.createElement("div");
  cabecera.className = "camara__cabecera";
  const numeroEl = crearTexto("span", String(numero), "camara__numero");
  numeroEl.setAttribute("aria-hidden", "true");
  const [texto, tipo] = sello;
  cabecera.append(
    numeroEl,
    crearTexto("h2", titulo, "camara__titulo"),
    crearTexto("span", texto, `camara__sello camara__sello--${tipo}`),
  );
  item.append(cabecera);
  return item;
}

/**
 * Crea la lista de métricas de una etapa, con los valores tal como llegan.
 *
 * @param {{label?: string, value?: string}[]} metricas Métricas del contrato.
 * @returns {HTMLDListElement | null} La lista, o `null` si no hay métricas.
 */
function crearMetricas(metricas) {
  const validas = metricas.filter((metrica) => textoODefecto(metrica?.label, ""));
  if (validas.length === 0) {
    return null;
  }
  const lista = document.createElement("dl");
  lista.className = "camara__metricas";
  for (const metrica of validas) {
    const bloque = document.createElement("div");
    bloque.className = "camara__metrica";
    bloque.append(
      crearTexto("dt", textoODefecto(metrica.label)),
      crearTexto("dd", textoODefecto(String(metrica.value ?? "")), "camara__valor"),
    );
    lista.append(bloque);
  }
  return lista;
}

/**
 * Crea el detalle de repeticiones de Gold: barras por umbral y los bloques
 * más repetidos. Si el contrato trae `null`, no se muestra nada.
 *
 * @param {{thresholds?: {threshold: number, percentage: number}[], blocks?: {pages: number, text: string}[], unique_global?: number, unique_average?: number} | null | undefined} repeticiones
 *   Detalle de `panel.Repetitions`.
 * @returns {HTMLElement | null} La sección, o `null` si no hay detalle.
 */
function crearRepeticiones(repeticiones) {
  if (!repeticiones || typeof repeticiones !== "object") {
    return null;
  }
  const seccion = document.createElement("section");
  seccion.className = "camara__repeticiones";
  seccion.append(crearTexto("h2", "Repeticiones en Gold", "camara__subtitulo"));
  seccion.append(
    crearTexto(
      "p",
      "Líneas que aparecen en muchas páginas (menús, pies, banners). Solo se miden: Gold no se borra (CONSTITUTION §7.6).",
      "camara__pista",
    ),
  );

  const umbrales = Array.isArray(repeticiones.thresholds) ? repeticiones.thresholds : [];
  for (const fila of umbrales) {
    if (!Number.isFinite(fila?.percentage)) {
      continue;
    }
    const barra = document.createElement("div");
    barra.className = "camara__barra";
    const relleno = document.createElement("span");
    relleno.className = "camara__relleno";
    relleno.style.width = `${Math.min(Math.max(fila.percentage, 0), 100)}%`;
    barra.append(relleno);

    const filaUmbral = document.createElement("div");
    filaUmbral.className = "camara__umbral";
    filaUmbral.append(
      crearTexto("span", `En ${fila.threshold} o más páginas`, "camara__umbral-etiqueta"),
      barra,
      crearTexto("span", `${fila.percentage.toLocaleString("es-CO")} %`, "camara__valor"),
    );
    seccion.append(filaUmbral);
  }

  const bloques = Array.isArray(repeticiones.blocks) ? repeticiones.blocks.slice(0, BLOQUES_VISIBLES) : [];
  if (bloques.length > 0) {
    seccion.append(crearTexto("h3", "Bloques más repetidos", "camara__subtitulo-menor"));
    const lista = document.createElement("ol");
    lista.className = "camara__bloques";
    for (const bloque of bloques) {
      const item = document.createElement("li");
      item.append(
        crearTexto("span", `${bloque?.pages ?? "—"} páginas`, "camara__bloque-paginas"),
        crearTexto("q", textoODefecto(bloque?.text), "camara__bloque-texto"),
      );
      lista.append(item);
    }
    seccion.append(lista);
  }
  return seccion;
}

/**
 * Crea la lista plegable de archivos que leyó el resumen.
 *
 * @param {unknown} fuentes Rutas del contrato.
 * @returns {HTMLDetailsElement} El bloque plegable.
 */
function crearFuentes(fuentes) {
  const rutas = Array.isArray(fuentes) ? fuentes.filter((ruta) => typeof ruta === "string" && ruta) : [];
  const bloque = document.createElement("details");
  bloque.className = "camara__fuentes";
  bloque.append(crearTexto("summary", `Archivos que se leyeron (${rutas.length})`));
  const lista = document.createElement("ul");
  for (const ruta of rutas) {
    const item = document.createElement("li");
    item.append(crearTexto("code", ruta));
    lista.append(item);
  }
  bloque.append(lista);
  return bloque;
}

/**
 * Crea el aviso de error con su botón de reintento.
 *
 * @param {Error} error Error recibido al pedir el pipeline.
 * @param {() => void} reintentar Acción del botón «Reintentar».
 * @returns {HTMLElement} El aviso.
 */
function crearError(error, reintentar) {
  const aviso = document.createElement("div");
  aviso.className = "aviso aviso--error camara__error";
  aviso.setAttribute("role", "alert");

  const boton = crearTexto("button", "Reintentar", "camara__reintentar");
  boton.type = "button";
  boton.addEventListener("click", reintentar);

  aviso.append(
    crearTexto("strong", "No se pudo cargar el pipeline."),
    crearTexto("span", ` ${error?.message ?? "Error desconocido"}`),
    boton,
  );
  return aviso;
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
