/**
 * Captura del voluntario de la escena: fila y silla, tarjetas A–F, monto,
 * micrófono con aviso de servicio externo y confirmación de Pana.
 *
 * La transcripción la hace el navegador (`microfono.js`); aquí solo viaja el
 * texto a `POST /api/escena/interpretar` y se descarta al confirmar. Sin
 * micrófono, todo se puede hacer con teclado y tarjetas. Al confirmar se pide
 * `POST /api/escena` y se avisa a la pantalla con el evento `escena:lista`.
 *
 * No guarda nada: ni el perfil, ni el texto, ni la selección. Las pruebas de la
 * página viven en `test/test_web_escena.py`.
 */

import { detenerMicrofono, escuchar, hayMicrofono } from "./microfono.js";

/** Rutas de la API de la escena. */
const RUTA_OPCIONES = "/api/escena/opciones";
const RUTA_PERFILES = "/api/escena/perfiles";
const RUTA_VOLUNTARIO = "/api/escena/voluntario";
const RUTA_INTERPRETAR = "/api/escena/interpretar";
const RUTA_ESCENA = "/api/escena";

/** Espera máxima de cada petición de la captura. */
const ESPERA_MS = 8000;

/** Intentos por pregunta antes de ofrecer el perfil seguro. */
const INTENTOS_MAXIMOS = 2;

/** Estado de la captura en curso. */
const estado = {
  preguntas: [],
  respuestas: new Map(),
  seleccion: null,
  indice: 0,
  intentos: 0,
  monto: null,
  letra: null,
  montada: false,
  alTerminar: null,
};

/**
 * Atajo para buscar un elemento por id.
 *
 * @param {string} id Id del elemento.
 * @returns {HTMLElement} El elemento.
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
 * Escribe un aviso en la línea de estado de la captura.
 *
 * @param {string} texto Texto a mostrar.
 * @param {boolean} [error] Si el aviso es un error.
 * @returns {void}
 */
function avisar(texto, error = false) {
  const linea = porId("captura-estado");
  linea.textContent = texto;
  linea.dataset.error = error ? "si" : "";
}

/**
 * Pide una ruta y devuelve su JSON, o lanza un error con el detalle.
 *
 * @param {string} ruta Ruta de la API.
 * @param {object} [opciones] Opciones de `fetch`.
 * @returns {Promise<object>} El JSON de la respuesta.
 */
async function pedir(ruta, opciones = {}) {
  const respuesta = await fetch(ruta, {
    ...opciones,
    signal: AbortSignal.timeout(ESPERA_MS),
    headers: { "Content-Type": "application/json", ...(opciones.headers ?? {}) },
  });
  const datos = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) {
    throw new Error(datos.detail ?? datos.detalle ?? `Error ${respuesta.status}`);
  }
  return datos;
}

/**
 * Carga las cuatro preguntas con sus tarjetas A–F.
 *
 * @returns {Promise<void>} Se resuelve cuando el catálogo está listo.
 */
async function cargarOpciones() {
  if (estado.preguntas.length > 0) {
    return;
  }
  const datos = await pedir(RUTA_OPCIONES);
  estado.preguntas = Array.isArray(datos.preguntas) ? datos.preguntas : [];
}

/**
 * Elige una fila y una silla al azar y las muestra.
 *
 * @returns {Promise<void>} Se resuelve cuando hay selección.
 */
async function elegirVoluntario() {
  try {
    estado.seleccion = await pedir(RUTA_VOLUNTARIO, {
      method: "POST",
      body: JSON.stringify({}),
    });
    porId("captura-seleccion").textContent =
      `Fila ${estado.seleccion.fila}, silla ${estado.seleccion.silla}.`;
    avisar("Pásale el turno a esa silla. No se pide nombre.");
  } catch (error) {
    avisar(`No pude elegir al voluntario: ${error.message}`, true);
  }
}

/**
 * Pinta la pregunta actual con sus tarjetas y su campo de monto.
 *
 * @returns {void}
 */
function pintarPregunta() {
  const contenedor = porId("captura-pregunta");
  const pregunta = estado.preguntas[estado.indice];
  if (!pregunta) {
    return;
  }
  const titulo = crear(
    "p",
    "escena__captura-pregunta",
    `${estado.indice + 1} de ${estado.preguntas.length} · ${pregunta.pregunta}`,
  );
  const tarjetas = crear("div", "escena__tarjetas");
  for (const opcion of pregunta.opciones) {
    const boton = crear("button", "escena__tarjeta", `${opcion.letra} · ${opcion.texto}`);
    boton.type = "button";
    boton.dataset.letra = opcion.letra;
    boton.addEventListener("click", () => elegirTarjeta(opcion.letra));
    tarjetas.append(boton);
  }
  const campo = crear("div", "escena__captura-campo");
  const etiqueta = crear("label", "", "Monto declarado (opcional)");
  etiqueta.htmlFor = "captura-texto";
  const entrada = crear("input");
  entrada.id = "captura-texto";
  entrada.type = "text";
  entrada.autocomplete = "off";
  entrada.placeholder = "1.500.000 o una letra A–F";
  entrada.addEventListener("keydown", (evento) => {
    if (evento.key === "Enter") {
      evento.preventDefault();
      enviar();
    }
  });
  campo.append(etiqueta, entrada);
  contenedor.replaceChildren(titulo, tarjetas, campo);
  estado.letra = null;
  estado.monto = null;
  porId("captura-texto").focus();
}

/**
 * Marca la tarjeta elegida y la recuerda para el envío.
 *
 * @param {string} letra Letra A–F de la tarjeta.
 * @returns {void}
 */
function elegirTarjeta(letra) {
  estado.letra = letra;
  for (const boton of document.querySelectorAll("#captura-pregunta [data-letra]")) {
    boton.classList.toggle("escena__tarjeta--elegida", boton.dataset.letra === letra);
  }
  avisar(`Tarjeta ${letra} elegida. Pulsa «Enviar» o di el monto.`);
}

/**
 * Envía la respuesta actual al parser y avanza a la siguiente pregunta.
 *
 * @returns {Promise<void>} Se resuelve cuando la respuesta quedó registrada.
 */
async function enviar() {
  const pregunta = estado.preguntas[estado.indice];
  if (!pregunta) {
    return;
  }
  const escrito = porId("captura-texto").value.trim();
  const partes = [];
  if (estado.letra) {
    partes.push(`letra ${estado.letra}`);
  }
  if (escrito) {
    partes.push(escrito);
  }
  const texto = partes.join(" ");
  if (!texto) {
    avisar("Elige una tarjeta o escribe un monto.", true);
    return;
  }
  try {
    const datos = await pedir(RUTA_INTERPRETAR, {
      method: "POST",
      body: JSON.stringify({ pregunta: pregunta.clave, texto }),
    });
    estado.respuestas.set(pregunta.clave, datos.respuesta);
    estado.intentos = 0;
    avisar(datos.ajustado ? (datos.mensaje ?? "Ajusté el monto.") : "Respuesta registrada.");
    estado.indice += 1;
    if (estado.indice < estado.preguntas.length) {
      pintarPregunta();
    } else {
      mostrarConfirmacion();
    }
  } catch (error) {
    estado.intentos += 1;
    avisar(error.message, true);
    if (estado.intentos >= INTENTOS_MAXIMOS) {
      avisar("Dos intentos: puedes seguir con el perfil seguro.", true);
    }
  }
}

/**
 * Muestra el resumen que Pana repite antes de pedir la confirmación.
 *
 * @returns {void}
 */
function mostrarConfirmacion() {
  const partes = estado.preguntas.map((pregunta) => {
    const respuesta = estado.respuestas.get(pregunta.clave);
    return `${pregunta.clave}: ${respuesta?.texto ?? "sin respuesta"}`;
  });
  porId("captura-resumen").textContent =
    `Confirmo tus respuestas. ${partes.join(" · ")}. ¿Está bien?`;
  porId("captura-confirmacion").hidden = false;
  porId("captura-pregunta").replaceChildren();
  avisar("Pana repite las cuatro respuestas: confirma o cambia.");
}

/**
 * Confirma y pide la escena de fase 1 para que la pantalla la reproduzca.
 *
 * @returns {Promise<void>} Se resuelve cuando la escena quedó pedida.
 */
async function confirmar() {
  if (estado.respuestas.size < estado.preguntas.length) {
    avisar("Faltan respuestas: vuelve a empezar.", true);
    return;
  }
  const respuestas = estado.preguntas.map((pregunta) => ({
    pregunta: pregunta.clave,
    letra: estado.respuestas.get(pregunta.clave)?.letra ?? null,
  }));
  const cuerpo = { respuestas, seleccion: estado.seleccion, confirmado: true };
  try {
    const escena = await pedir(RUTA_ESCENA, { method: "POST", body: JSON.stringify(cuerpo) });
    cerrar();
    if (typeof estado.alTerminar === "function") {
      estado.alTerminar(escena);
    }
    document.dispatchEvent(new CustomEvent("escena:lista", { detail: escena }));
  } catch (error) {
    avisar(`No pude pedir la escena: ${error.message}`, true);
  }
}

/**
 * Usa el perfil seguro del TOML, sin voluntario ni micrófono.
 *
 * @returns {Promise<void>} Se resuelve cuando la escena quedó pedida.
 */
async function usarPerfilSeguro() {
  try {
    const datos = await pedir(RUTA_PERFILES);
    const valido = (datos.perfiles ?? []).find((perfil) => perfil.valido);
    if (!valido) {
      avisar("No hay perfiles seguros válidos en config/escena.toml.", true);
      return;
    }
    const escena = await pedir(RUTA_ESCENA, {
      method: "POST",
      body: JSON.stringify({ perfil_id: valido.id, seleccion: estado.seleccion }),
    });
    cerrar();
    if (typeof estado.alTerminar === "function") {
      estado.alTerminar(escena);
    }
    document.dispatchEvent(new CustomEvent("escena:lista", { detail: escena }));
  } catch (error) {
    avisar(`No pude usar el perfil seguro: ${error.message}`, true);
  }
}

/**
 * Pide cambiar una respuesta: vuelve a la primera pregunta.
 *
 * @returns {void}
 */
function cambiar() {
  estado.respuestas.clear();
  estado.indice = 0;
  estado.intentos = 0;
  porId("captura-confirmacion").hidden = true;
  pintarPregunta();
  avisar("Volvamos a las preguntas.");
}

/**
 * Abre o cierra la captura y carga el catálogo al abrir.
 *
 * @returns {Promise<void>} Se resuelve cuando el panel quedó visible.
 */
async function alternar() {
  const panel = porId("escena-captura");
  if (!panel.hidden) {
    cerrar();
    return;
  }
  panel.hidden = false;
  porId("escena-captura-abrir").setAttribute("aria-expanded", "true");
  try {
    await cargarOpciones();
    if (estado.preguntas.length > 0 && estado.indice < estado.preguntas.length) {
      pintarPregunta();
    }
  } catch (error) {
    avisar(`No pude cargar las preguntas: ${error.message}`, true);
  }
  porId("captura-aviso").textContent =
    "El reconocimiento de voz del navegador puede usar un servicio externo. " +
    "Puedes escribir o usar las tarjetas A–F.";
}

/**
 * Cierra la captura y detiene el micrófono.
 *
 * @returns {void}
 */
function cerrar() {
  detenerMicrofono();
  porId("escena-captura").hidden = true;
  porId("escena-captura-abrir").setAttribute("aria-expanded", "false");
}

/**
 * Escucha una respuesta con el micrófono y la deja en el campo de texto.
 *
 * @returns {void}
 */
function dictar() {
  const boton = porId("captura-microfono");
  if (!hayMicrofono()) {
    avisar("Este navegador no tiene reconocimiento de voz: escribe o usa las tarjetas.", true);
    return;
  }
  boton.setAttribute("aria-pressed", "true");
  escuchar({
    alResultado: (texto) => {
      porId("captura-texto").value = texto;
      avisar(`Escuché: «${texto}». Revisa y pulsa «Enviar».`);
    },
    alError: () => avisar("No pude escuchar. Escribe la respuesta o usa una tarjeta.", true),
    alTerminar: () => boton.setAttribute("aria-pressed", "false"),
  });
}

/**
 * Conecta los botones de la captura; se ejecuta una sola vez.
 *
 * @param {{alTerminar?: (escena: object) => void}} [opciones] Callback de fin.
 * @returns {void}
 */
export function montarCaptura(opciones = {}) {
  if (estado.montada) {
    return;
  }
  estado.montada = true;
  estado.alTerminar = opciones.alTerminar ?? null;
  const abrir = porId("escena-captura-abrir");
  if (abrir) {
    abrir.addEventListener("click", alternar);
    abrir.setAttribute("aria-expanded", "false");
  }
  porId("captura-voluntario").addEventListener("click", elegirVoluntario);
  porId("captura-enviar").addEventListener("click", enviar);
  porId("captura-si").addEventListener("click", confirmar);
  porId("captura-no").addEventListener("click", cambiar);
  porId("captura-seguro").addEventListener("click", usarPerfilSeguro);
  const microfono = porId("captura-microfono");
  microfono.hidden = !hayMicrofono();
  microfono.addEventListener("click", dictar);
  document.addEventListener("escena:captura", alternar);
}
