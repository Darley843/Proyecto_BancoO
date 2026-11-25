/**
 * Sucursal 1965 · herramientas en vivo en la pantalla de la escena.
 *
 * Mientras los invitados escriben por WhatsApp, el público ve qué herramienta
 * usó Pana, si salió bien y cuánto tardó. Los datos salen de
 * `GET /api/herramientas/traza`, que lee la traza local del servidor MCP y
 * nunca devuelve argumentos ni huellas. El panel se abre y se cierra con la
 * tecla H (o su botón) y solo consulta la API mientras está abierto.
 */

/** Cada cuánto se pide la traza con el panel abierto, en milisegundos. */
export const INTERVALO_MS = 2000;
/** Espera máxima de cada petición antes de darla por perdida. */
const ESPERA_MS = 1500;
/** Cuántas llamadas se muestran. */
export const CANTIDAD = 6;
/** Prefijo con el que OpenClaw puede nombrar las herramientas del servidor. */
const PREFIJO_SERVIDOR = "sucursal__";

/**
 * Nombre para el público y dueña de cada una de las veinte herramientas.
 * El orden es el del catálogo (`herramientas/catalogo.py`).
 */
export const HERRAMIENTAS = Object.freeze({
  consultar_tasa: { texto: "Consultar la tasa publicada", duena: "Nayla" },
  simular_cuota: { texto: "Simular la cuota", duena: "Nayla" },
  verificar_usura: { texto: "Verificar la usura", duena: "Nayla" },
  diagnosticar_capacidad: { texto: "Diagnosticar la capacidad de pago", duena: "Nayla" },
  comparar_escenario: { texto: "Comparar «¿Y si…?»", duena: "Nayla" },
  convocar_comite: { texto: "Convocar al comité de crédito", duena: "Nayla" },
  calcular_prestamo_gota: { texto: "Calcular el préstamo gota a gota", duena: "Nayla" },
  comparar_gota_banco: { texto: "Comparar gota a gota y banco", duena: "Nayla" },
  negociar_opcion: { texto: "Negociar la opción", duena: "Nayla" },
  generar_ficha_opcion: { texto: "Generar la ficha de la opción", duena: "Nayla" },
  responder_sobre_proyecto: { texto: "Responder sobre el proyecto", duena: "Nayla" },
  registrar_consentimiento: { texto: "Registrar el consentimiento", duena: "Darley" },
  olvidar_mis_datos: { texto: "Olvidar mis datos", duena: "Darley" },
  solicitar_asesor: { texto: "Solicitar un asesor", duena: "Darley" },
  consultar_caso: { texto: "Consultar el caso", duena: "Darley" },
  generar_tarjeta_pana: { texto: "Generar la tarjeta de Pana", duena: "Darley" },
  buscar_en_documentos: { texto: "Buscar en los documentos del banco", duena: "Anny" },
  consultar_tarifas: { texto: "Consultar las tarifas", duena: "Anny" },
  clasificar_pregunta: { texto: "Clasificar la pregunta", duena: "Anny" },
  auditar_respuesta: { texto: "Auditar la respuesta", duena: "Anny" },
});

const estado = {
  montado: false,
  abierto: false,
  temporizador: null,
  ultimaId: null,
};

/**
 * Atajo para buscar un elemento por id.
 *
 * @param {string} id Id del elemento.
 * @returns {HTMLElement | null} El elemento, o `null`.
 */
function porId(id) {
  return document.getElementById(id);
}

/**
 * Crea un elemento con clase y texto.
 *
 * @param {string} etiqueta Etiqueta HTML.
 * @param {string} [clase] Clase CSS.
 * @param {string} [texto] Texto del elemento.
 * @returns {HTMLElement} El elemento creado.
 */
function crear(etiqueta, clase = "", texto = "") {
  const elemento = document.createElement(etiqueta);
  if (clase) {
    elemento.className = clase;
  }
  if (texto) {
    elemento.textContent = texto;
  }
  return elemento;
}

/**
 * Nombre del catálogo sin el prefijo del servidor que pone OpenClaw.
 *
 * @param {string} nombre Nombre como llega en la traza.
 * @returns {string} Nombre del catálogo.
 */
export function nombreDelCatalogo(nombre) {
  const texto = String(nombre ?? "");
  return texto.startsWith(PREFIJO_SERVIDOR) ? texto.slice(PREFIJO_SERVIDOR.length) : texto;
}

/**
 * Latencia legible: milisegundos por debajo de un segundo, si no segundos.
 *
 * @param {number} ms Duración en milisegundos.
 * @returns {string} Texto como «120 ms» o «1,4 s».
 */
export function latenciaLegible(ms) {
  const valor = Number(ms);
  if (!Number.isFinite(valor) || valor < 0) {
    return "—";
  }
  if (valor < 1000) {
    return `${Math.round(valor)} ms`;
  }
  return `${(valor / 1000).toFixed(1).replace(".", ",")} s`;
}

/**
 * Hora local de una llamada (la traza guarda UTC).
 *
 * @param {string} momento Fecha ISO 8601.
 * @returns {string} Hora como «08:15:02», o «—» si no se entiende.
 */
export function horaLocal(momento) {
  const fecha = new Date(momento);
  if (Number.isNaN(fecha.getTime())) {
    return "—";
  }
  return fecha.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

/**
 * Convierte una llamada de la API en la fila que se pinta.
 *
 * Una herramienta que no está en el catálogo se muestra con su nombre tal cual,
 * sin dueña: la pantalla nunca inventa a quién pertenece.
 *
 * @param {{herramienta: string, ok: boolean, codigo: string | null,
 *   latencia_ms: number, momento: string}} llamada Llamada de la traza pública.
 * @returns {{texto: string, nombre: string, duena: string, ok: boolean,
 *   resultado: string, latencia: string, hora: string}} Fila lista para pintar.
 */
export function filaDeLlamada(llamada) {
  const nombre = nombreDelCatalogo(llamada.herramienta);
  const ficha = Object.hasOwn(HERRAMIENTAS, nombre) ? HERRAMIENTAS[nombre] : null;
  return {
    texto: ficha ? ficha.texto : nombre,
    nombre,
    duena: ficha ? ficha.duena : "",
    ok: Boolean(llamada.ok),
    resultado: llamada.ok ? "bien" : `error: ${llamada.codigo ?? "sin código"}`,
    latencia: latenciaLegible(llamada.latencia_ms),
    hora: horaLocal(llamada.momento),
  };
}

/**
 * Pinta la lista de llamadas, o el aviso que corresponda.
 *
 * @param {Array<object> | null} llamadas Llamadas de la API, o `null` si falló.
 * @returns {void}
 */
function pintar(llamadas) {
  const lista = porId("escena-herramientas-lista");
  const aviso = porId("escena-herramientas-aviso");
  if (llamadas === null) {
    aviso.textContent = "Sin conexión con la traza: revisar que la app siga encendida.";
    aviso.hidden = false;
    return;
  }
  if (llamadas.length === 0) {
    lista.replaceChildren();
    aviso.textContent = "Todavía no hay llamadas. Aparecen cuando Pana usa una herramienta.";
    aviso.hidden = false;
    return;
  }
  aviso.hidden = true;
  const nueva = llamadas[0].id !== estado.ultimaId;
  estado.ultimaId = llamadas[0].id;
  lista.replaceChildren(
    ...llamadas.map((llamada, posicion) => {
      const fila = filaDeLlamada(llamada);
      const item = crear(
        "li",
        `escena__herramienta${fila.ok ? "" : " escena__herramienta--error"}${posicion === 0 ? " escena__herramienta--ultima" : ""}${posicion === 0 && nueva ? " escena__herramienta--nueva" : ""}`,
      );
      item.title = fila.nombre;
      const marca = crear("span", "escena__herramienta-marca", fila.ok ? "✓" : "✕");
      marca.setAttribute("aria-label", fila.ok ? "salió bien" : "falló");
      const texto = crear("span", "escena__herramienta-texto", fila.texto);
      const detalle = crear(
        "span",
        "escena__herramienta-detalle",
        [fila.duena, fila.ok ? fila.latencia : fila.resultado, fila.hora].filter(Boolean).join(" · "),
      );
      item.append(marca, texto, detalle);
      return item;
    }),
  );
}

/**
 * Pide las últimas llamadas a la API.
 *
 * @returns {Promise<Array<object> | null>} Llamadas, o `null` si no respondió.
 */
async function pedirLlamadas() {
  try {
    const respuesta = await fetch(`/api/herramientas/traza?n=${CANTIDAD}`, {
      signal: AbortSignal.timeout(ESPERA_MS),
    });
    if (!respuesta.ok) {
      return null;
    }
    const datos = await respuesta.json();
    return Array.isArray(datos?.llamadas) ? datos.llamadas : null;
  } catch {
    return null;
  }
}

/**
 * Una vuelta del sondeo: pide, pinta y agenda la siguiente si sigue abierto.
 *
 * @returns {Promise<void>}
 */
async function actualizar() {
  const llamadas = await pedirLlamadas();
  if (!estado.abierto) {
    return;
  }
  pintar(llamadas);
  estado.temporizador = setTimeout(actualizar, INTERVALO_MS);
}

/**
 * Abre o cierra el panel. Solo se consulta la API con el panel abierto.
 *
 * @returns {void}
 */
function alternar() {
  estado.abierto = !estado.abierto;
  porId("escena-herramientas").hidden = !estado.abierto;
  porId("escena-ver-herramientas")?.setAttribute("aria-expanded", String(estado.abierto));
  clearTimeout(estado.temporizador);
  estado.temporizador = null;
  if (estado.abierto) {
    actualizar();
  }
}

/**
 * Conecta el botón y la tecla H (que `escena.js` avisa con `escena:herramientas`).
 *
 * @returns {void}
 */
export function montarHerramientas() {
  if (estado.montado || !porId("escena-herramientas")) {
    return;
  }
  estado.montado = true;
  porId("escena-ver-herramientas")?.addEventListener("click", alternar);
  document.addEventListener("escena:herramientas", alternar);
}
