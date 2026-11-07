/**
 * Vista Bóveda · responsable: Yoldy (PR 14).
 *
 * Pinta `GET /api/boveda/mapa?pregunta=`: cada fragmento del corpus como un
 * punto en dos dimensiones, la posición de la pregunta y el top de fragmentos
 * recuperados con su título, sección, tipo y similitud.
 *
 * Reglas: la vista no calcula coordenadas ni similitudes (llegan normalizadas
 * de 0 a 100 desde el servidor), no hace peticiones distintas de
 * `/api/boveda/mapa` y, si el índice no está listo, lo explica en lugar de
 * dibujar un mapa vacío como si hubiera datos.
 */

import { crearEncabezadoVista, crearTexto } from "../comun.js";

/** Espacio de nombres de SVG para `createElementNS`. */
const SVG = "http://www.w3.org/2000/svg";

/** Preguntas rápidas que se ofrecen como botones. */
const SUGERENCIAS = [
  "¿Qué beneficios tiene la cuenta de nómina?",
  "Requisitos para un crédito de vivienda",
  "Horarios de atención en oficinas",
];

/** Nombre visible de cada sección del corpus. */
const SECCIONES = {
  oferta: "Oferta",
  identidad: "Identidad",
  atencion: "Atención",
  legal: "Legal",
  presencia: "Presencia",
  datos: "Datos",
  otros: "Otros",
};

/** Caracteres del fragmento que se muestran antes de «Ver fragmento completo». */
const LARGO_RESUMEN = 160;

/** Número de la última consulta, para descartar respuestas viejas. */
let ultimaConsulta = 0;

/**
 * Pinta la vista Bóveda dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-boveda` de `index.html`.
 * @param {{modo: string, pedir: Function, resumen: object | null}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  const encabezado = crearEncabezadoVista(
    "boveda",
    "Bóveda",
    "El corpus convertido en vectores. Cada punto es un fragmento; los cercanos hablan de temas parecidos. Escribe una pregunta para ver dónde cae y qué fragmentos recupera.",
  );

  if (estado.resumen?.indice_listo === false) {
    contenedor.replaceChildren(encabezado, crearIndiceNoListo());
    return;
  }

  const resultados = document.createElement("div");
  resultados.className = "boveda__resultados";
  resultados.setAttribute("aria-live", "polite");

  const vista = document.createElement("div");
  vista.className = "boveda";
  vista.append(crearBuscador((pregunta) => consultar(resultados, estado, pregunta)));
  if (estado.modo === "ejemplo") {
    vista.append(
      crearTexto(
        "p",
        "Datos de ejemplo: son los fragmentos reales del índice base, ubicados con una aproximación (TF-IDF en lugar de los embeddings del modelo). En la maqueta cualquier pregunta muestra el resultado de «¿Qué beneficios tiene la cuenta de nómina?».",
        "aviso boveda__aviso",
      ),
    );
  }
  vista.append(resultados);

  contenedor.replaceChildren(encabezado, vista);
  await consultar(resultados, estado, "");
}

/**
 * Crea el formulario de la pregunta con su botón y las preguntas sugeridas.
 * Solo consulta al enviar, porque cada consulta calcula un embedding.
 *
 * @param {(pregunta: string) => void} alConsultar Acción que ejecuta la consulta.
 * @returns {HTMLFormElement} El formulario.
 */
function crearBuscador(alConsultar) {
  const formulario = document.createElement("form");
  formulario.className = "boveda__buscador";
  formulario.setAttribute("role", "search");

  const etiqueta = crearTexto("label", "Pregunta a la Bóveda", "boveda__etiqueta");
  etiqueta.htmlFor = "boveda-pregunta";

  const campo = document.createElement("input");
  campo.id = "boveda-pregunta";
  campo.type = "search";
  campo.className = "boveda__campo";
  campo.placeholder = "Por ejemplo: beneficios de la cuenta de nómina";
  campo.autocomplete = "off";
  campo.maxLength = 300;

  const boton = crearTexto("button", "Buscar", "boveda__boton boveda__boton--primario");
  boton.type = "submit";

  formulario.addEventListener("submit", (evento) => {
    evento.preventDefault();
    alConsultar(campo.value);
  });

  const fila = document.createElement("div");
  fila.className = "boveda__fila-busqueda";
  fila.append(campo, boton);

  const sugerencias = document.createElement("div");
  sugerencias.className = "boveda__sugerencias";
  sugerencias.append(crearTexto("span", "Prueba con:", "boveda__sugerencias-titulo"));
  for (const texto of SUGERENCIAS) {
    const sugerencia = crearTexto("button", texto, "boveda__sugerencia");
    sugerencia.type = "button";
    sugerencia.addEventListener("click", () => {
      campo.value = texto;
      alConsultar(texto);
    });
    sugerencias.append(sugerencia);
  }

  formulario.append(etiqueta, fila, sugerencias);
  return formulario;
}

/**
 * Pide el mapa (con o sin pregunta) y pinta el mapa, el top o el error.
 * Si llega la respuesta de una consulta anterior, la descarta.
 *
 * @param {HTMLElement} resultados Contenedor de los resultados.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @param {string} texto Pregunta escrita por la persona (puede venir vacía).
 * @returns {Promise<void>}
 */
async function consultar(resultados, estado, texto) {
  const numero = ++ultimaConsulta;
  const pregunta = texto.trim();
  resultados.setAttribute("aria-busy", "true");
  if (pregunta) {
    resultados.prepend(crearTexto("p", "Buscando en la Bóveda…", "cargando boveda__cargando"));
  }

  let datos;
  try {
    datos = await estado.pedir("mapa", { consulta: { pregunta } });
  } catch (error) {
    if (numero !== ultimaConsulta) {
      return;
    }
    resultados.removeAttribute("aria-busy");
    resultados.replaceChildren(crearError(error, () => consultar(resultados, estado, texto)));
    return;
  }
  if (numero !== ultimaConsulta) {
    return;
  }
  resultados.removeAttribute("aria-busy");

  const puntos = puntosValidos(datos?.puntos);
  let marca = coordenadaValida(datos?.pregunta);
  let top = Array.isArray(datos?.top) ? datos.top : [];
  if (estado.modo === "ejemplo" && !pregunta) {
    // El contrato dice que sin pregunta no hay marca ni top; la maqueta los trae siempre.
    marca = null;
    top = [];
  }

  const avisoApi = typeof datos?.error === "string" ? datos.error.trim() : "";
  if (datos?.disponible === false) {
    resultados.replaceChildren(crearMapaNoCalculado(avisoApi));
    return;
  }
  if (puntos.length === 0) {
    resultados.replaceChildren(crearSinPuntos());
    return;
  }

  const contenido = document.createElement("div");
  contenido.className = "boveda__contenido";
  contenido.append(crearPanelMapa(puntos, marca), crearPanelTop(pregunta, top, avisoApi));
  resultados.replaceChildren(contenido);
}

/**
 * Se queda solo con los puntos que traen coordenadas válidas (números finitos
 * entre 0 y 100). Así un dato roto no se dibuja fuera del mapa.
 *
 * @param {unknown} puntos Lista `puntos` del contrato.
 * @returns {{x: number, y: number, seccion: string, titulo: string}[]} Puntos dibujables.
 */
function puntosValidos(puntos) {
  if (!Array.isArray(puntos)) {
    return [];
  }
  return puntos.filter((punto) => coordenadaValida(punto) !== null);
}

/**
 * Devuelve la coordenada si `x` e `y` son números finitos entre 0 y 100.
 *
 * @param {unknown} punto Objeto con `x` e `y`.
 * @returns {{x: number, y: number} | null} La coordenada o `null` si no sirve.
 */
function coordenadaValida(punto) {
  if (!punto || typeof punto !== "object") {
    return null;
  }
  const { x, y } = /** @type {{x: unknown, y: unknown}} */ (punto);
  const dentro = (valor) => typeof valor === "number" && Number.isFinite(valor) && valor >= 0 && valor <= 100;
  return dentro(x) && dentro(y) ? { x: Number(x), y: Number(y) } : null;
}

/**
 * Crea el panel del mapa: resumen, leyenda por sección (que también filtra),
 * el dibujo en SVG y la línea que describe el punto bajo el cursor.
 *
 * @param {{x: number, y: number, seccion: string, titulo: string}[]} puntos Puntos válidos.
 * @param {{x: number, y: number} | null} marca Posición de la pregunta, si la hay.
 * @returns {HTMLElement} El panel.
 */
function crearPanelMapa(puntos, marca) {
  const panel = document.createElement("section");
  panel.className = "tarjeta boveda__panel boveda__panel--mapa";
  panel.setAttribute("aria-label", "Mapa de fragmentos");

  const conteos = contarSecciones(puntos);
  const resumen = `${formatearEntero(puntos.length)} fragmentos en el mapa · ${conteos.length} ${conteos.length === 1 ? "sección" : "secciones"}`;
  panel.append(crearTexto("p", resumen, "boveda__resumen"));

  const info = crearTexto("p", "Pasa el cursor o toca un punto para ver su título.", "boveda__info");
  info.setAttribute("aria-live", "polite");

  const dibujo = crearDibujo(puntos, marca, info);
  panel.append(crearLeyenda(conteos, dibujo, marca !== null), dibujo, info);
  panel.append(
    crearTexto(
      "p",
      "Los ejes no tienen unidades: el mapa es una proyección (PCA) de los vectores a dos dimensiones, así que solo importa qué tan cerca están los puntos.",
      "boveda__nota",
    ),
  );
  return panel;
}

/**
 * Cuenta los puntos por sección, de la más grande a la más pequeña.
 *
 * @param {{seccion: string}[]} puntos Puntos válidos.
 * @returns {[string, number][]} Pares `[seccion, cantidad]`.
 */
function contarSecciones(puntos) {
  const conteo = new Map();
  for (const punto of puntos) {
    const seccion = textoSeccion(punto.seccion);
    conteo.set(seccion, (conteo.get(seccion) ?? 0) + 1);
  }
  return [...conteo.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "es"));
}

/**
 * Crea la leyenda: un botón por sección con su cantidad. Al pulsarlo, esa
 * sección se resalta en el mapa; «Todas» vuelve a la vista general.
 *
 * @param {[string, number][]} conteos Pares `[seccion, cantidad]`.
 * @param {SVGSVGElement} dibujo Mapa al que se aplica el resaltado.
 * @param {boolean} hayPregunta Si hay marca de la pregunta (para la leyenda).
 * @returns {HTMLElement} La leyenda.
 */
function crearLeyenda(conteos, dibujo, hayPregunta) {
  const leyenda = document.createElement("div");
  leyenda.className = "boveda__leyenda";
  leyenda.setAttribute("role", "group");
  leyenda.setAttribute("aria-label", "Resaltar una sección del mapa");

  const botones = [];
  const elegir = (seccion) => {
    resaltarSeccion(dibujo, seccion);
    for (const boton of botones) {
      boton.setAttribute("aria-pressed", String(boton.dataset.seccion === seccion));
    }
  };

  const todas = crearBotonSeccion("", "Todas", null);
  botones.push(todas);
  for (const [seccion, cantidad] of conteos) {
    botones.push(crearBotonSeccion(seccion, nombreSeccion(seccion), cantidad));
  }
  for (const boton of botones) {
    boton.addEventListener("click", () => elegir(boton.dataset.seccion ?? ""));
    leyenda.append(boton);
  }
  todas.setAttribute("aria-pressed", "true");

  if (hayPregunta) {
    const clave = document.createElement("span");
    clave.className = "boveda__clave-pregunta";
    clave.append(crearTexto("span", "", "boveda__clave-marca"), crearTexto("span", "Tu pregunta"));
    leyenda.append(clave);
  }
  return leyenda;
}

/**
 * Crea un botón de la leyenda.
 *
 * @param {string} seccion Clave de la sección (vacía para «Todas»).
 * @param {string} nombre Texto visible.
 * @param {number | null} cantidad Puntos de la sección, o `null` para «Todas».
 * @returns {HTMLButtonElement} El botón.
 */
function crearBotonSeccion(seccion, nombre, cantidad) {
  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "boveda__seccion";
  boton.dataset.seccion = seccion;
  boton.setAttribute("aria-pressed", "false");
  boton.append(crearTexto("span", nombre));
  if (cantidad !== null) {
    boton.append(crearTexto("span", formatearEntero(cantidad), "boveda__seccion-cantidad"));
  }
  return boton;
}

/**
 * Marca los puntos de una sección como resaltados y atenúa los demás.
 * Con la sección vacía, todos vuelven a su estado normal.
 *
 * @param {SVGSVGElement} dibujo Mapa.
 * @param {string} seccion Sección elegida o cadena vacía.
 * @returns {void}
 */
function resaltarSeccion(dibujo, seccion) {
  dibujo.classList.toggle("boveda__dibujo--filtrado", seccion !== "");
  for (const punto of dibujo.querySelectorAll(".boveda__punto")) {
    punto.classList.toggle("boveda__punto--resaltado", seccion !== "" && punto.dataset.seccion === seccion);
  }
}

/**
 * Dibuja el mapa en SVG: un círculo por fragmento y, si hay pregunta, su
 * marca encima. La `y` se invierte porque en SVG crece hacia abajo.
 *
 * @param {{x: number, y: number, seccion: string, titulo: string}[]} puntos Puntos válidos.
 * @param {{x: number, y: number} | null} marca Posición de la pregunta.
 * @param {HTMLElement} info Línea donde se describe el punto bajo el cursor.
 * @returns {SVGSVGElement} El dibujo.
 */
function crearDibujo(puntos, marca, info) {
  const dibujo = document.createElementNS(SVG, "svg");
  dibujo.setAttribute("class", "boveda__dibujo");
  dibujo.setAttribute("viewBox", "-3 -3 106 106");
  dibujo.setAttribute("role", "img");
  const descripcion = marca
    ? `Mapa con ${formatearEntero(puntos.length)} fragmentos y la posición de tu pregunta.`
    : `Mapa con ${formatearEntero(puntos.length)} fragmentos.`;
  dibujo.setAttribute("aria-label", descripcion);

  const marco = document.createElementNS(SVG, "rect");
  marco.setAttribute("class", "boveda__marco");
  marco.setAttribute("x", "-3");
  marco.setAttribute("y", "-3");
  marco.setAttribute("width", "106");
  marco.setAttribute("height", "106");
  dibujo.append(marco);

  const grupo = document.createElementNS(SVG, "g");
  for (const punto of puntos) {
    const circulo = document.createElementNS(SVG, "circle");
    circulo.setAttribute("class", "boveda__punto");
    circulo.setAttribute("cx", String(punto.x));
    circulo.setAttribute("cy", String(100 - punto.y));
    circulo.setAttribute("r", "1");
    circulo.dataset.seccion = textoSeccion(punto.seccion);
    const titulo = document.createElementNS(SVG, "title");
    titulo.textContent = describirPunto(punto);
    circulo.append(titulo);
    grupo.append(circulo);
  }
  dibujo.append(grupo);

  if (marca) {
    dibujo.append(crearMarcaPregunta(marca));
  }

  dibujo.addEventListener("pointerover", (evento) => {
    const objetivo = evento.target;
    if (objetivo instanceof SVGCircleElement && objetivo.classList.contains("boveda__punto")) {
      info.textContent = objetivo.querySelector("title")?.textContent ?? "";
    }
  });
  return dibujo;
}

/**
 * Crea la marca de la pregunta: un anillo y un punto, con su título.
 *
 * @param {{x: number, y: number}} marca Posición normalizada de la pregunta.
 * @returns {SVGGElement} El grupo de la marca.
 */
function crearMarcaPregunta(marca) {
  const grupo = document.createElementNS(SVG, "g");
  grupo.setAttribute("class", "boveda__pregunta");
  const titulo = document.createElementNS(SVG, "title");
  titulo.textContent = "Tu pregunta";
  const anillo = document.createElementNS(SVG, "circle");
  anillo.setAttribute("class", "boveda__pregunta-anillo");
  anillo.setAttribute("r", "3");
  const centro = document.createElementNS(SVG, "circle");
  centro.setAttribute("class", "boveda__pregunta-centro");
  centro.setAttribute("r", "1.4");
  for (const circulo of [anillo, centro]) {
    circulo.setAttribute("cx", String(marca.x));
    circulo.setAttribute("cy", String(100 - marca.y));
  }
  grupo.append(titulo, anillo, centro);
  return grupo;
}

/**
 * Crea el panel del top: la lista de fragmentos recuperados o, si no hay
 * pregunta, una invitación a escribir una.
 *
 * Si la API trae un aviso (por ejemplo, Ollama no respondió y no se pudo
 * ubicar la pregunta), lo muestra en lugar de decir que no hubo fragmentos.
 *
 * @param {string} pregunta Pregunta consultada (vacía si no hay).
 * @param {object[]} top Lista `top` del contrato.
 * @param {string} [avisoApi] Campo `error` de la respuesta, si vino.
 * @returns {HTMLElement} El panel.
 */
function crearPanelTop(pregunta, top, avisoApi = "") {
  const panel = document.createElement("section");
  panel.className = "tarjeta boveda__panel boveda__panel--top";
  panel.setAttribute("aria-label", "Fragmentos recuperados");

  if (!pregunta) {
    panel.append(
      crearTexto("h2", "Fragmentos recuperados", "boveda__titulo-panel"),
      crearTexto("p", "Escribe una pregunta y aquí verás los fragmentos más cercanos, con su similitud.", "boveda__vacio"),
    );
    return panel;
  }
  if (avisoApi && top.length === 0) {
    panel.append(crearTexto("h2", `Búsqueda de «${pregunta}»`, "boveda__titulo-panel"));
    const aviso = document.createElement("div");
    aviso.className = "aviso aviso--error boveda__error";
    aviso.setAttribute("role", "alert");
    aviso.append(
      crearTexto("strong", "No se pudo buscar tu pregunta."),
      crearTexto("p", avisoApi),
      crearTexto("p", "El mapa sigue disponible. Si usas Ollama, revisa que esté abierto (ollama serve) y vuelve a buscar."),
    );
    panel.append(aviso);
    return panel;
  }
  panel.append(crearTexto("h2", `Top ${top.length} para «${pregunta}»`, "boveda__titulo-panel"));
  if (top.length === 0) {
    panel.append(crearTexto("p", "La Bóveda no encontró fragmentos para esta pregunta.", "boveda__vacio"));
    return panel;
  }

  const lista = document.createElement("ol");
  lista.className = "boveda__top";
  for (const fragmento of top) {
    lista.append(crearFragmento(fragmento));
  }
  panel.append(
    lista,
    crearTexto("p", "La similitud va de 0 a 1: más cerca de 1, más se parece el fragmento a tu pregunta.", "boveda__nota"),
  );
  return panel;
}

/**
 * Crea un elemento del top con título (enlazado a su fuente si la URL es
 * segura), sección, tipo, similitud, tokens y el texto del fragmento.
 *
 * @param {{titulo?: string, url?: string, seccion?: string, encabezado?: string, tipo?: string, tokens?: number, puntaje?: number, texto?: string}} fragmento Fragmento del contrato.
 * @returns {HTMLLIElement} El elemento de la lista.
 */
function crearFragmento(fragmento) {
  const item = document.createElement("li");
  item.className = "boveda__fragmento";

  const cabeza = document.createElement("div");
  cabeza.className = "boveda__fragmento-cabeza";
  const titulo = textoODefecto(fragmento.titulo, "Sin título");
  if (esUrlSegura(fragmento.url)) {
    const enlace = crearTexto("a", titulo, "boveda__fragmento-titulo");
    enlace.href = /** @type {string} */ (fragmento.url);
    enlace.target = "_blank";
    enlace.rel = "noopener noreferrer";
    enlace.setAttribute("aria-label", `${titulo} (abre la fuente en otra pestaña)`);
    cabeza.append(enlace);
  } else {
    cabeza.append(crearTexto("strong", titulo, "boveda__fragmento-titulo"));
  }
  cabeza.append(crearSimilitud(fragmento.puntaje));
  item.append(cabeza);

  const datos = document.createElement("div");
  datos.className = "boveda__fragmento-datos";
  datos.append(crearTexto("span", nombreSeccion(textoSeccion(fragmento.seccion)), "etiqueta"));
  datos.append(crearTexto("span", textoODefecto(fragmento.tipo, "—"), "boveda__dato"));
  if (Number.isInteger(fragmento.tokens)) {
    datos.append(crearTexto("span", `${formatearEntero(/** @type {number} */ (fragmento.tokens))} tokens`, "boveda__dato"));
  }
  item.append(datos);

  if (textoODefecto(fragmento.encabezado, "")) {
    item.append(crearTexto("p", String(fragmento.encabezado), "boveda__fragmento-encabezado"));
  }
  item.append(crearTextoFragmento(textoODefecto(fragmento.texto, "")));
  return item;
}

/**
 * Crea la similitud del fragmento como número con coma decimal y una barra.
 * Si el puntaje no es un número entre 0 y 1, muestra «—» sin barra.
 *
 * @param {unknown} puntaje Similitud coseno del contrato.
 * @returns {HTMLElement} El bloque de similitud.
 */
function crearSimilitud(puntaje) {
  const bloque = document.createElement("span");
  bloque.className = "boveda__similitud";
  const valido = typeof puntaje === "number" && Number.isFinite(puntaje) && puntaje >= 0 && puntaje <= 1;
  const texto = valido
    ? puntaje.toLocaleString("es-CO", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "—";
  bloque.append(crearTexto("span", "Similitud", "boveda__similitud-etiqueta"), crearTexto("span", texto, "cifra"));
  if (valido) {
    const barra = document.createElement("span");
    barra.className = "boveda__barra";
    const relleno = document.createElement("span");
    relleno.className = "boveda__barra-relleno";
    relleno.style.width = `${Math.round(puntaje * 100)}%`;
    barra.append(relleno);
    bloque.append(barra);
  }
  return bloque;
}

/**
 * Muestra el inicio del texto del fragmento y, si es largo, el resto dentro
 * de un desplegable.
 *
 * @param {string} texto Texto del fragmento.
 * @returns {HTMLElement} Párrafo o desplegable.
 */
function crearTextoFragmento(texto) {
  const plano = texto.replace(/\s+/g, " ").trim();
  if (plano.length <= LARGO_RESUMEN) {
    return crearTexto("p", plano, "boveda__fragmento-texto");
  }
  const desplegable = document.createElement("details");
  desplegable.className = "boveda__fragmento-texto";
  const resumen = crearTexto("summary", `${plano.slice(0, LARGO_RESUMEN).trimEnd()}…`);
  desplegable.append(resumen, crearTexto("p", texto));
  return desplegable;
}

/**
 * Explica que el índice no está listo y cómo crearlo. No dibuja ningún mapa.
 *
 * @returns {HTMLElement} El aviso.
 */
function crearIndiceNoListo() {
  const aviso = document.createElement("div");
  aviso.className = "aviso boveda__no-listo";
  aviso.setAttribute("role", "status");
  aviso.append(
    crearTexto("strong", "El índice de la Bóveda todavía no está listo."),
    crearTexto(
      "p",
      "Sin índice no hay vectores que dibujar, así que no se muestra un mapa vacío. Para crearlo, con Ollama encendido, ejecuta en la terminal:",
    ),
    crearTexto("code", "make indice", "boveda__comando"),
    crearTexto("p", "Cuando termine, vuelve a abrir la Bóveda."),
  );
  return aviso;
}

/**
 * Explica que el mapa todavía no se calculó (`disponible: false`) con el
 * mensaje que manda la API. No dibuja ningún mapa.
 *
 * @param {string} mensaje Campo `error` de la respuesta (puede venir vacío).
 * @returns {HTMLElement} El aviso.
 */
function crearMapaNoCalculado(mensaje) {
  const aviso = document.createElement("div");
  aviso.className = "aviso boveda__no-listo";
  aviso.setAttribute("role", "status");
  aviso.append(
    crearTexto("strong", "El mapa no está calculado todavía."),
    crearTexto("p", mensaje || "Ejecuta make indice para crear el índice y el mapa."),
  );
  return aviso;
}

/**
 * Explica que la respuesta llegó sin puntos válidos. No dibuja ningún mapa.
 *
 * @returns {HTMLElement} El aviso.
 */
function crearSinPuntos() {
  const aviso = document.createElement("div");
  aviso.className = "aviso boveda__no-listo";
  aviso.setAttribute("role", "status");
  aviso.append(
    crearTexto("strong", "El mapa todavía no tiene puntos."),
    crearTexto("p", "La Bóveda respondió sin fragmentos ubicados. Revisa que el índice esté creado con make indice."),
  );
  return aviso;
}

/**
 * Crea el aviso de error con el mensaje de la API y un botón para reintentar.
 *
 * @param {Error} error Error recibido al pedir los datos.
 * @param {() => void} reintentar Acción del botón «Reintentar».
 * @returns {HTMLElement} El aviso.
 */
function crearError(error, reintentar) {
  const aviso = document.createElement("div");
  aviso.className = "aviso aviso--error boveda__error";
  aviso.setAttribute("role", "alert");

  const boton = crearTexto("button", "Reintentar", "boveda__boton");
  boton.type = "button";
  boton.addEventListener("click", reintentar);

  aviso.append(
    crearTexto("strong", "No se pudo cargar la Bóveda."),
    crearTexto("span", ` ${error?.message ?? "Error desconocido"}`),
    boton,
  );
  return aviso;
}

/**
 * Describe un punto para su título emergente: título y sección.
 *
 * @param {{titulo?: string, seccion?: string}} punto Punto del contrato.
 * @returns {string} Texto como «Cuenta de Ahorros · Oferta».
 */
function describirPunto(punto) {
  return `${textoODefecto(punto.titulo, "Sin título")} · ${nombreSeccion(textoSeccion(punto.seccion))}`;
}

/**
 * Normaliza la clave de sección; si viene vacía, usa «otros».
 *
 * @param {unknown} seccion Sección del contrato.
 * @returns {string} Clave de la sección.
 */
function textoSeccion(seccion) {
  return typeof seccion === "string" && seccion.trim() ? seccion.trim() : "otros";
}

/**
 * Devuelve el nombre visible de una sección, o la clave tal cual si es nueva.
 *
 * @param {string} seccion Clave de la sección.
 * @returns {string} Nombre visible.
 */
function nombreSeccion(seccion) {
  return SECCIONES[seccion] ?? seccion;
}

/**
 * Formatea un entero con punto de miles, como se escribe en Colombia.
 *
 * @param {number} numero Entero a formatear.
 * @returns {string} Por ejemplo «1.520».
 */
function formatearEntero(numero) {
  return numero.toLocaleString("es-CO", { maximumFractionDigits: 0 });
}

/**
 * Devuelve el texto si no está vacío; si no, el texto por defecto.
 *
 * @param {unknown} valor Valor del contrato.
 * @param {string} defecto Texto a usar si el valor viene vacío.
 * @returns {string} Texto para mostrar.
 */
function textoODefecto(valor, defecto) {
  if (valor === null || valor === undefined) {
    return defecto;
  }
  const texto = String(valor).trim();
  return texto ? texto : defecto;
}

/**
 * Comprueba que una URL sea http o https antes de usarla como enlace.
 *
 * @param {unknown} url Dirección del contrato.
 * @returns {boolean} `true` si es segura para un enlace.
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
