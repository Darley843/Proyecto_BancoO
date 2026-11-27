/**
 * Captura del voluntario de la escena: fila y silla, tarjetas A–F, monto,
 * micrófono con aviso de servicio externo y confirmación de Pana.
 *
 * La transcripción la hace el navegador (`microfono.js`); aquí el texto viaja a
 * `POST /api/escena/hablar`, que lo interpreta y devuelve la línea de Pana, y se
 * descarta al confirmar. Sin micrófono, todo se puede hacer con teclado y
 * tarjetas. Al confirmar se pide `POST /api/escena` y se avisa a la pantalla con
 * el evento `escena:lista`.
 *
 * Con el modo En vivo (tecla E) activo, el panel solo muestra la conversación
 * con Pana: un botón grande de micrófono que manda lo que oye a
 * `POST /api/escena/hablar`, el texto reconocido como confirmación y el aviso de
 * servicio externo. Las tarjetas, el monto y los botones del flujo guiado se
 * ocultan (siguen igual fuera de ese modo) y el panel se cierra solo después de
 * enviar, para no tapar los subtítulos.
 *
 * No guarda nada: ni el perfil, ni el texto, ni la selección. Las pruebas de la
 * página viven en `test/test_web_escena.py`.
 */

import { detenerMicrofono, escuchando, escuchar, hayMicrofono } from "./microfono.js";

/** Rutas de la API de la escena. */
const RUTA_OPCIONES = "/api/escena/opciones";
const RUTA_PERFILES = "/api/escena/perfiles";
const RUTA_VOLUNTARIO = "/api/escena/voluntario";
const RUTA_HABLAR = "/api/escena/hablar";
const RUTA_ESCENA = "/api/escena";

/** Espera máxima de cada petición de la captura. */
const ESPERA_MS = 8000;
/** Espera del turno libre: el canal puede tardar lo que tarda OpenClaw. */
const ESPERA_HABLAR_MS = 50000;

/** En vivo, tiempo que se ve «Escuché: …» antes de cerrar el panel solo. */
const CIERRE_EN_VIVO_MS = 1500;
/** Texto del botón de Pana fuera del modo En vivo. */
const TEXTO_HABLAR_CON_PANA = "Hablar con Pana";

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
 * @param {number} [espera] Tiempo máximo en milisegundos.
 * @returns {Promise<object>} El JSON de la respuesta.
 */
async function pedir(ruta, opciones = {}, espera = ESPERA_MS) {
  const respuesta = await fetch(ruta, {
    ...opciones,
    signal: AbortSignal.timeout(espera),
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
 * Envía la respuesta actual al servidor y avanza a la siguiente pregunta.
 *
 * El texto viene del campo o del micrófono. `POST /api/escena/hablar` devuelve
 * la interpretación y la línea con la que Pana confirma; si no entendió, la
 * línea se muestra y la pregunta no avanza.
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
    const datos = await pedir(RUTA_HABLAR, {
      method: "POST",
      body: JSON.stringify({ pregunta: pregunta.clave, texto }),
    });
    const linea = datos.turno?.texto ?? datos.mensaje ?? "";
    if (!datos.respuesta) {
      estado.intentos += 1;
      avisar(linea || "No entendí la respuesta. Dime una letra o un monto.", true);
      if (estado.intentos >= INTENTOS_MAXIMOS) {
        avisar(`${linea} Dos intentos: puedes seguir con el perfil seguro.`, true);
      }
      return;
    }
    estado.respuestas.set(pregunta.clave, datos.respuesta);
    estado.intentos = 0;
    avisar(linea || (datos.ajustado ? "Ajusté el monto." : "Respuesta registrada."));
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
 * Indica si la pantalla está en modo En vivo (lo marca `escena.js` en el body).
 *
 * @returns {boolean} `true` con el modo En vivo activo.
 */
function enVivo() {
  return document.body.classList.contains("escena--en-vivo");
}

/**
 * Abre el panel solo con la conversación con Pana (modo En vivo).
 *
 * No carga el catálogo de preguntas ni toca el flujo guiado: el voluntario no
 * declara monto ni elige tarjetas, solo habla.
 *
 * @param {string} [mensaje] Línea de estado que se muestra al abrir.
 * @returns {void}
 */
function abrirConversacion(mensaje = "") {
  porId("escena-captura").hidden = false;
  porId("escena-captura-abrir").setAttribute("aria-expanded", "true");
  const boton = porId("captura-pana");
  boton.textContent = boton.dataset.textoVivo || TEXTO_HABLAR_CON_PANA;
  porId("captura-pana-escuche").textContent = "";
  porId("captura-pana-estado").textContent = hayMicrofono()
    ? mensaje
    : "Este navegador no reconoce la voz: escríbele a Pana por WhatsApp.";
  // Al reabrir por un error no se roba el foco: E y V siguen funcionando.
  if (!boton.hidden && !mensaje) {
    boton.focus();
  }
}

/**
 * Abre o cierra la captura y carga el catálogo al abrir.
 *
 * En modo En vivo abre solo la conversación con Pana.
 *
 * @returns {Promise<void>} Se resuelve cuando el panel quedó visible.
 */
async function alternar() {
  const panel = porId("escena-captura");
  if (!panel.hidden) {
    cerrar();
    return;
  }
  if (enVivo()) {
    abrirConversacion();
    return;
  }
  porId("captura-pana").textContent = TEXTO_HABLAR_CON_PANA;
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
  // Un botón con foco se come los atajos (E, P, Espacio) de quien presenta.
  if (document.activeElement instanceof HTMLElement) {
    document.activeElement.blur();
  }
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
      avisar(`Escuché: «${texto}». Enviando a Pana…`);
      void enviar();
    },
    alError: () => avisar("No pude escuchar. Escribe la respuesta o usa una tarjeta.", true),
    alTerminar: () => boton.setAttribute("aria-pressed", "false"),
  });
}

/**
 * Envía una frase libre al voluntario activo y muestra lo que respondió Pana.
 *
 * La ruta del canal aplica los filtros, busca al voluntario en memoria y envía
 * la respuesta (y la ficha, si la hay) por WhatsApp. Aquí solo se pinta el
 * texto que la pantalla puede mostrar.
 *
 * @param {string} texto Frase dictada por el voluntario.
 * @returns {Promise<void>} Se resuelve cuando la respuesta quedó pintada.
 */
async function enviarAPana(texto) {
  const linea = porId("captura-pana-estado");
  try {
    const datos = await pedir(
      RUTA_HABLAR,
      { method: "POST", body: JSON.stringify({ texto }) },
      ESPERA_HABLAR_MS,
    );
    const respuesta = String(datos?.turno?.texto ?? datos?.mensaje ?? "").trim();
    const ficha = datos?.ficha ? " También te envié la ficha por WhatsApp." : "";
    linea.textContent = `${respuesta}${ficha}` || "Pana no respondió.";
  } catch (error) {
    if (enVivo() && porId("escena-captura").hidden) {
      // El panel ya se cerró solo: se vuelve a abrir para que se vea el error.
      abrirConversacion(error.message);
      return;
    }
    linea.textContent = error.message;
  }
}

/**
 * Escucha una pregunta libre y la manda al canal del voluntario activo.
 *
 * @returns {void}
 */
function preguntarAPana() {
  const boton = porId("captura-pana");
  const linea = porId("captura-pana-estado");
  if (!hayMicrofono()) {
    linea.textContent = "Este navegador no tiene micrófono: escribe en WhatsApp.";
    return;
  }
  if (escuchando()) {
    detenerMicrofono();
    return;
  }
  boton.setAttribute("aria-pressed", "true");
  escuchar({
    alResultado: (texto) => {
      porId("captura-pana-escuche").textContent = `Escuché: «${texto}»`;
      linea.textContent = "Enviando a Pana…";
      void enviarAPana(texto);
      if (enVivo()) {
        // En vivo la respuesta sale en la escena: el panel no tapa los subtítulos.
        window.setTimeout(cerrar, CIERRE_EN_VIVO_MS);
      }
    },
    alError: (mensaje) => {
      linea.textContent = mensaje;
    },
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
  const pana = porId("captura-pana");
  pana.hidden = !hayMicrofono();
  pana.addEventListener("click", preguntarAPana);
  document.addEventListener("escena:captura", alternar);
}
