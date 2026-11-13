/**
 * Vista Ventanilla · responsable: Nayla.
 *
 * Aquí se hace la pregunta. El Digiturno le asigna un turno y cada respuesta
 * sale con su comprobante: fuentes, tokens, costo y tiempo. La vista solo
 * formatea lo que devuelve la API: no decide rutas, costos ni validaciones.
 *
 * El `thread_id` vive en `sessionStorage`; las preguntas y respuestas quedan
 * solo en memoria y se pierden al recargar. Todo el texto se crea con
 * `crearTexto`, nunca como HTML.
 *
 * Streaming (responsable: Yoldy): con la API encendida, la pregunta va a
 * `POST /api/preguntar/stream` y la vista pinta el avance del grafo por
 * etapas (reformular, Digiturno, búsqueda y redacción) mientras espera. El
 * evento `final` trae el mismo cuerpo de `POST /api/preguntar`; si la conexión
 * se corta, se muestra el error de siempre y el hilo se conserva.
 */

import { crearEncabezadoVista, crearTexto, formatearUsd } from "../comun.js";

/** Clave de `sessionStorage` donde vive el hilo de la conversación. */
const CLAVE_HILO = "sucursal-ventanilla-hilo";

/** Identificador del campo de pregunta. */
const ID_PREGUNTA = "ventanilla-pregunta";

/** Identificador de la ayuda del campo de pregunta. */
const ID_AYUDA = "ventanilla-ayuda";

/** Identificador de la línea de estado. */
const ID_ESTADO = "ventanilla-estado";

/** Preguntas de ejemplo; la tercera encadena un seguimiento. */
const EJEMPLOS = [
  { pregunta: "¿En qué año se fundó el Banco de Occidente?" },
  { pregunta: "¿Cuánto cuesta la cuota de manejo de la tarjeta débito?" },
  {
    pregunta: "¿Qué tarjetas Credencial Mastercard ofrece?",
    seguimiento: "¿Y cuánto cuesta la Black?",
  },
  { pregunta: "¿En qué acciones me recomiendas invertir?" },
];

/** Nombres legibles de las rutas del contrato. */
const RUTAS = {
  boveda: "Bóveda",
  tablero: "Tablero",
  rechazo: "Rechazo",
  cortesia: "Cortesía",
  mixta: "Mixta (Tablero + Bóveda)",
};

/** Nombres legibles de los tipos de fuente. */
const TIPOS = {
  pagina: "Página",
  pdf: "PDF",
  video: "Video",
  "hecho verificado": "Hecho verificado",
};

/** Nombres visibles de las etapas que envía el streaming. */
const ETAPAS = {
  reformulando: "Memoria",
  router: "Digiturno",
  buscando: "Búsqueda",
  redactando: "Redacción",
};

/** Patrón de un UUID, para reutilizar solo hilos con forma válida. */
const PATRON_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Hilo activo de la pestaña. */
let hilo = null;

/** Hilo al que pertenecen los turnos en memoria. */
let hiloDeTurnos = null;

/** Indica si el hilo se creó en esta carga de la página. */
let hiloDeEstaPagina = false;

/** Indica si ya se intentó leer o crear el hilo inicial. */
let hiloInicializado = false;

/** Turnos de la sesión, solo en memoria. */
let turnos = [];

/** Evita dos peticiones simultáneas. */
let enCurso = false;

/** Referencias de la vista viva, para respuestas que llegan tarde. */
let vistaActual = null;

/** Botón de escucha que está leyendo ahora mismo. */
let botonEscuchando = null;

/** Instancia activa del reconocimiento de voz. */
let reconocimiento = null;

/** Botón de dictado que está escuchando ahora mismo. */
let botonDictadoActual = null;

/** Consecutivo local para los identificadores de los turnos. */
let contadorTurnos = 0;

/** Etapas del turno en curso, para repintarlas si se vuelve a la vista. */
let avance = [];

/**
 * Crea un hilo nuevo con `crypto.randomUUID` y un respaldo para navegadores
 * antiguos.
 *
 * @returns {string} Identificador del hilo.
 */
function crearHilo() {
  try {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
      return globalThis.crypto.randomUUID();
    }
    if (
      globalThis.crypto &&
      typeof globalThis.crypto.getRandomValues === "function"
    ) {
      const bytes = new Uint8Array(16);
      globalThis.crypto.getRandomValues(bytes);
      const hex = Array.from(bytes, (byte) =>
        byte.toString(16).padStart(2, "0"),
      );
      return [
        hex.slice(0, 4).join(""),
        hex.slice(4, 6).join(""),
        hex.slice(6, 8).join(""),
        hex.slice(8, 10).join(""),
        hex.slice(10, 16).join(""),
      ].join("-");
    }
  } catch {
    // Sin criptografía disponible: se usa una marca de tiempo.
  }
  return `hilo-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Lee el hilo guardado en la pestaña, si tiene forma de UUID.
 *
 * @returns {string | null} El hilo guardado o `null`.
 */
function leerHiloGuardado() {
  try {
    const guardado = window.sessionStorage.getItem(CLAVE_HILO);
    if (typeof guardado === "string" && PATRON_UUID.test(guardado)) {
      return guardado;
    }
  } catch {
    // Sin almacenamiento: el hilo vive solo en memoria.
  }
  return null;
}

/**
 * Guarda el hilo en la pestaña. Es el único dato que se persiste.
 *
 * @param {string} valor Hilo que se quiere conservar.
 * @returns {void}
 */
function guardarHilo(valor) {
  try {
    window.sessionStorage.setItem(CLAVE_HILO, valor);
  } catch {
    // Si no se puede guardar, el hilo dura solo esta visita.
  }
}

/**
 * Renueva el hilo y limpia la conversación visible. No llama a la API.
 *
 * @returns {void}
 */
function nuevaConversacion() {
  detenerVoz();
  detenerDictado();
  hilo = crearHilo();
  hiloDeTurnos = hilo;
  hiloDeEstaPagina = true;
  hiloInicializado = true;
  turnos = [];
  guardarHilo(hilo);
  if (!vistaActual) {
    return;
  }
  limpiarError(vistaActual);
  limpiarEstado(vistaActual);
  pintarTurnos(vistaActual);
  actualizarComprobante(vistaActual, null);
  if (vistaActual.avisoContinuacion) {
    vistaActual.avisoContinuacion.hidden = true;
  }
  vistaActual.entrada.value = "";
  vistaActual.entrada.focus();
  anunciar(vistaActual, "Nueva conversación iniciada.");
}

/**
 * Crea los avisos de modo ejemplo, modo demo, índice ausente y conversación
 * continuada.
 *
 * @param {{modo?: string, resumen?: object}} app Estado compartido de `app.js`.
 * @param {boolean} continuaba Si hay un hilo anterior sin turnos visibles.
 * @returns {HTMLElement} Contenedor de avisos.
 */
function crearAvisos(app, continuaba) {
  const contenedor = document.createElement("div");
  contenedor.className = "ventanilla__avisos";

  if (app?.modo === "ejemplo") {
    const aviso = crearTexto(
      "p",
      "Datos de ejemplo: la respuesta es una maqueta y siempre es la misma; no se consulta la API.",
      "aviso",
    );
    aviso.setAttribute("role", "note");
    contenedor.append(aviso);
  } else if (app?.resumen?.modo_demo) {
    const aviso = crearTexto(
      "p",
      "Modo demo: el servidor responde con plantillas y no llama al modelo.",
      "aviso",
    );
    aviso.setAttribute("role", "note");
    contenedor.append(aviso);
  }

  if (app?.modo === "api" && app?.resumen?.indice_listo === false) {
    const aviso = crearTexto(
      "p",
      "La Bóveda no tiene índice todavía. Ejecuta «make indice» para que la Ventanilla pueda citar fuentes.",
      "aviso",
    );
    aviso.setAttribute("role", "note");
    contenedor.append(aviso);
  }

  if (continuaba) {
    const aviso = crearTexto(
      "p",
      'Esta conversación continúa una anterior. Usa "Nueva conversación" para empezar de cero.',
      "ventanilla__continuacion",
    );
    aviso.setAttribute("role", "status");
    contenedor.append(aviso);
  }

  return contenedor;
}

/**
 * Crea el formulario, sus botones, el estado y el recuadro de error.
 *
 * @returns {{
 *   elemento: HTMLFormElement,
 *   entrada: HTMLInputElement,
 *   botonEnviar: HTMLButtonElement,
 *   botonNueva: HTMLButtonElement,
 *   botonesEjemplo: HTMLButtonElement[],
 *   estado: HTMLElement,
 *   error: HTMLElement,
 * }} Referencias del formulario.
 */
function crearFormulario() {
  const formulario = document.createElement("form");
  formulario.className = "ventanilla__formulario tarjeta";
  formulario.noValidate = true;

  const etiqueta = crearTexto("label", "Tu pregunta", "ventanilla__etiqueta");
  etiqueta.htmlFor = ID_PREGUNTA;

  const entrada = document.createElement("input");
  entrada.type = "text";
  entrada.id = ID_PREGUNTA;
  entrada.name = "pregunta";
  entrada.className = "ventanilla__entrada";
  entrada.autocomplete = "off";
  entrada.required = true;
  entrada.setAttribute("aria-describedby", ID_AYUDA);

  const ayuda = crearTexto(
    "p",
    "Pregunta por productos, tarifas o historia del Banco de Occidente.",
    "ventanilla__ayuda",
  );
  ayuda.id = ID_AYUDA;

  const acciones = document.createElement("div");
  acciones.className = "ventanilla__acciones";

  const botonEnviar = crearBoton(
    "Tomar turno",
    "ventanilla__boton",
    "submit",
  );
  const botonNueva = crearBoton(
    "Nueva conversación",
    "ventanilla__boton ventanilla__boton--secundario",
    "button",
  );
  const botonDictado = crearBotonDictado(entrada);
  acciones.append(botonEnviar, botonNueva);
  if (botonDictado) {
    acciones.append(botonDictado);
  }

  const ejemplos = document.createElement("fieldset");
  ejemplos.className = "ventanilla__ejemplos";
  ejemplos.append(
    crearTexto("legend", "Preguntas de ejemplo", "ventanilla__legend"),
  );
  const listaEjemplos = document.createElement("div");
  listaEjemplos.className = "ventanilla__ejemplos-lista";
  const botonesEjemplo = [];
  for (const ejemplo of EJEMPLOS) {
    const boton = crearBotonEjemplo(ejemplo);
    botonesEjemplo.push(boton);
    listaEjemplos.append(boton);
  }
  ejemplos.append(listaEjemplos);

  const estado = crearTexto("p", "", "ventanilla__estado");
  estado.id = ID_ESTADO;
  estado.setAttribute("role", "status");
  estado.setAttribute("aria-live", "polite");
  estado.hidden = true;

  const error = document.createElement("div");
  error.className = "ventanilla__error";
  error.setAttribute("role", "alert");
  error.hidden = true;

  formulario.append(etiqueta, entrada, ayuda, acciones, ejemplos);
  return {
    elemento: formulario,
    entrada,
    botonEnviar,
    botonNueva,
    botonesEjemplo,
    estado,
    error,
  };
}

/**
 * Crea un botón nativo con texto plano.
 *
 * @param {string} texto Texto visible.
 * @param {string} clase Clases CSS.
 * @param {"button" | "submit"} [tipo] Tipo del botón.
 * @returns {HTMLButtonElement} El botón creado.
 */
function crearBoton(texto, clase, tipo = "button") {
  const boton = crearTexto("button", texto, clase);
  boton.type = tipo;
  return boton;
}

/**
 * Crea un botón de ejemplo. Si el ejemplo trae seguimiento, el mismo botón
 * envía las dos preguntas en orden.
 *
 * @param {{pregunta: string, seguimiento?: string}} ejemplo Ejemplo.
 * @returns {HTMLButtonElement} El botón creado.
 */
function crearBotonEjemplo(ejemplo) {
  const boton = crearBoton("", "ventanilla__ejemplo", "button");
  boton.append(
    crearTexto("span", ejemplo.pregunta, "ventanilla__ejemplo-texto"),
  );
  if (ejemplo.seguimiento) {
    boton.append(
      crearTexto(
        "span",
        `y luego: ${ejemplo.seguimiento}`,
        "ventanilla__ejemplo-seguimiento",
      ),
    );
    boton.setAttribute(
      "aria-label",
      `Preguntar: ${ejemplo.pregunta} y luego: ${ejemplo.seguimiento}`,
    );
  }
  boton.addEventListener("click", () => {
    if (enCurso) {
      return;
    }
    const preguntas = [ejemplo.pregunta, ejemplo.seguimiento].filter(
      (pregunta) => typeof pregunta === "string" && pregunta.trim(),
    );
    void enviarSecuencia(preguntas);
  });
  return boton;
}

/**
 * Conecta el envío del formulario y el botón de nueva conversación.
 *
 * @param {object} vista Referencias de la vista.
 * @returns {void}
 */
function conectarEventos(vista) {
  vista.formulario.addEventListener("submit", (evento) => {
    evento.preventDefault();
    const pregunta = vista.entrada.value.trim();
    if (!pregunta) {
      mostrarError(vista, "Escribe una pregunta antes de tomar turno.", null);
      vista.entrada.focus();
      return;
    }
    limpiarError(vista);
    void enviarSecuencia([pregunta]);
  });

  vista.botonNueva.addEventListener("click", () => {
    if (!enCurso) {
      nuevaConversacion();
    }
  });
}

/**
 * Activa o desactiva los controles mientras se espera una respuesta.
 *
 * @param {object | null} vista Referencias de la vista.
 * @param {boolean} ocupado Si hay una petición en curso.
 * @returns {void}
 */
function actualizarControles(vista, ocupado) {
  if (!vista) {
    return;
  }
  vista.botonEnviar.disabled = ocupado;
  vista.botonNueva.disabled = ocupado;
  for (const boton of vista.botonesEjemplo) {
    boton.disabled = ocupado;
  }
  vista.botonEnviar.textContent = ocupado ? "Atendiendo…" : "Tomar turno";
  vista.lista.setAttribute("aria-busy", ocupado ? "true" : "false");
  if (ocupado) {
    vista.estado.hidden = false;
  } else if (!vista.estado.textContent) {
    vista.estado.hidden = true;
  }
}

/**
 * Muestra una línea de estado, por ejemplo «Atendiendo…».
 *
 * @param {object | null} vista Referencias de la vista.
 * @param {string} texto Texto a mostrar.
 * @returns {void}
 */
function mostrarEstado(vista, texto) {
  if (!vista) {
    return;
  }
  vista.estado.textContent = texto;
  vista.estado.hidden = false;
}

/**
 * Oculta y vacía la línea de estado.
 *
 * @param {object | null} vista Referencias de la vista.
 * @returns {void}
 */
function limpiarEstado(vista) {
  if (!vista) {
    return;
  }
  vista.estado.textContent = "";
  vista.estado.hidden = true;
}

/**
 * Anuncia un mensaje breve en la línea de estado y lo retira después.
 *
 * @param {object | null} vista Referencias de la vista.
 * @param {string} texto Texto a anunciar.
 * @returns {void}
 */
function anunciar(vista, texto) {
  if (!vista) {
    return;
  }
  vista.estado.textContent = texto;
  vista.estado.hidden = false;
  window.setTimeout(() => {
    if (vista.estado.textContent === texto) {
      vista.estado.textContent = "";
      vista.estado.hidden = true;
    }
  }, 4000);
}

/**
 * Muestra el error de la API con su texto y, si hay pregunta, un reintento.
 *
 * @param {object | null} vista Referencias de la vista.
 * @param {string} mensaje Texto del error.
 * @param {string | null} pregunta Pregunta que se puede reintentar.
 * @returns {void}
 */
function mostrarError(vista, mensaje, pregunta) {
  if (!vista) {
    return;
  }
  vista.preguntaParaReintentar = pregunta;
  const texto = crearTexto("p", mensaje, "ventanilla__error-texto");
  const detalle = crearTexto(
    "p",
    "El hilo se conserva; puedes reintentar o cambiar la pregunta.",
    "ventanilla__error-detalle",
  );
  vista.error.replaceChildren(texto, detalle);
  if (pregunta) {
    const acciones = document.createElement("div");
    acciones.className = "ventanilla__error-acciones";
    const boton = crearBoton(
      "Reintentar",
      "ventanilla__boton ventanilla__boton--secundario",
      "button",
    );
    boton.addEventListener("click", () => {
      if (vista.preguntaParaReintentar) {
        void enviarSecuencia([vista.preguntaParaReintentar]);
      }
    });
    acciones.append(boton);
    vista.error.append(acciones);
  }
  vista.error.hidden = false;
}

/**
 * Oculta y vacía el recuadro de error.
 *
 * @param {object | null} vista Referencias de la vista.
 * @returns {void}
 */
function limpiarError(vista) {
  if (!vista) {
    return;
  }
  vista.error.replaceChildren();
  vista.error.hidden = true;
  vista.preguntaParaReintentar = null;
}

/**
 * Envía una o varias preguntas en el mismo hilo y pinta cada respuesta.
 *
 * @param {string[]} preguntas Preguntas en orden.
 * @returns {Promise<void>}
 */
async function enviarSecuencia(preguntas) {
  if (enCurso) {
    return;
  }
  const vista = vistaActual;
  if (!vista) {
    return;
  }
  const hiloPeticion = hilo;
  enCurso = true;
  actualizarControles(vista, true);
  limpiarError(vista);
  let preguntaActual = "";

  try {
    for (const pregunta of preguntas) {
      preguntaActual = String(pregunta ?? "").trim();
      if (!preguntaActual) {
        continue;
      }
      if (vistaActual) {
        vistaActual.entrada.value = preguntaActual;
        mostrarEstado(vistaActual, `Atendiendo: «${preguntaActual}»…`);
      }
      reiniciarAvance(vistaActual);
      const datos = await pedirTurno(preguntaActual, hiloPeticion, (etapa) => {
        if (hilo === hiloPeticion) {
          registrarEtapa(etapa);
          pintarAvance(vistaActual);
        }
      });
      if (hilo !== hiloPeticion) {
        return;
      }
      const turno = {
        pregunta: preguntaActual,
        datos,
        fecha: new Date(),
        etapas: avance.filter((etapa) => etapa.estado === "hecho"),
      };
      reiniciarAvance(vistaActual);
      turnos.push(turno);
      if (vistaActual) {
        agregarTurno(vistaActual, turno);
        actualizarComprobante(vistaActual, turno);
        vistaActual.entrada.value = "";
      }
    }
  } catch (error) {
    if (hilo === hiloPeticion && vistaActual) {
      mostrarError(
        vistaActual,
        mensajeDeError(error),
        preguntaActual || null,
      );
    }
  } finally {
    enCurso = false;
    reiniciarAvance(vistaActual);
    if (vistaActual) {
      if (vistaActual.estado.textContent.startsWith("Atendiendo")) {
        limpiarEstado(vistaActual);
      }
      actualizarControles(vistaActual, false);
    }
  }
}

/**
 * Pide un turno a la API y comprueba que la respuesta tenga la forma mínima.
 *
 * Usa `app.pedirEnVivo` (streaming por etapas); en la maqueta
 * (`datos-ejemplo/`) ese mismo método devuelve el JSON de ejemplo sin etapas.
 *
 * @param {string} pregunta Pregunta saneada por el formulario.
 * @param {string} hiloPeticion Hilo al que pertenece la pregunta.
 * @param {(etapa: object) => void} [alAvanzar] Recibe cada etapa del grafo.
 * @returns {Promise<object>} Respuesta del contrato.
 * @throws {Error} Si la API no está disponible o la respuesta está incompleta.
 */
async function pedirTurno(pregunta, hiloPeticion, alAvanzar = () => {}) {
  const app = vistaActual?.app;
  if (!app || typeof app.pedir !== "function") {
    throw new Error("La sucursal no está disponible en este momento.");
  }
  const cuerpo = { pregunta, thread_id: hiloPeticion };
  const datos =
    typeof app.pedirEnVivo === "function"
      ? await app.pedirEnVivo("preguntar", { cuerpo }, alAvanzar)
      : await app.pedir("preguntar", { cuerpo });
  if (
    !datos ||
    typeof datos.respuesta !== "string" ||
    typeof datos.turno !== "string"
  ) {
    throw new Error("La sucursal devolvió una respuesta incompleta.");
  }
  await refrescarSaldo(app);
  return datos;
}

/**
 * Guarda una etapa del turno en curso: la abre o la marca como terminada.
 *
 * @param {{nodo?: string, etapa?: string, estado?: string, texto?: string}} etapa
 *   Evento `etapa` del streaming.
 * @returns {void}
 */
function registrarEtapa(etapa) {
  if (!etapa || typeof etapa !== "object") {
    return;
  }
  const paso = {
    nodo: String(etapa.nodo ?? ""),
    etapa: String(etapa.etapa ?? ""),
    estado: etapa.estado === "hecho" ? "hecho" : "en_curso",
    texto: textoODefecto(etapa.texto, "Atendiendo…"),
  };
  if (paso.estado === "hecho") {
    const abierta = avance.findLastIndex(
      (previa) => previa.nodo === paso.nodo && previa.estado === "en_curso",
    );
    if (abierta !== -1) {
      avance[abierta] = paso;
      return;
    }
  }
  avance.push(paso);
}

/**
 * Vacía el avance del turno y lo oculta.
 *
 * @param {object | null} vista Referencias de la vista.
 * @returns {void}
 */
function reiniciarAvance(vista) {
  avance = [];
  pintarAvance(vista);
}

/**
 * Pinta la lista de etapas del turno en curso.
 *
 * @param {object | null} vista Referencias de la vista.
 * @returns {void}
 */
function pintarAvance(vista) {
  if (!vista?.avance) {
    return;
  }
  vista.avance.replaceChildren(...avance.map(crearPaso));
  vista.avance.hidden = avance.length === 0;
}

/**
 * Crea un paso del avance: nombre de la etapa y lo que pasó en ella.
 *
 * @param {{etapa: string, estado: string, texto: string}} paso Etapa guardada.
 * @returns {HTMLLIElement} El elemento de la lista.
 */
function crearPaso(paso) {
  const elemento = document.createElement("li");
  elemento.className = `ventanilla__paso ventanilla__paso--${paso.estado === "hecho" ? "hecho" : "en-curso"}`;
  elemento.append(
    crearTexto(
      "span",
      ETAPAS[paso.etapa] ?? textoODefecto(paso.etapa, "Etapa"),
      "ventanilla__paso-etapa",
    ),
    crearTexto("span", paso.texto, "ventanilla__paso-texto"),
  );
  return elemento;
}

/**
 * Vuelve a pedir el estado de la sucursal para actualizar el saldo del día.
 *
 * Es el punto único de toda respuesta: el formulario, los ejemplos, las
 * secuencias y el reintento terminan en `pedirTurno`.
 *
 * @param {object | null} app Estado compartido de `app.js`.
 * @returns {Promise<void>}
 */
async function refrescarSaldo(app) {
  if (!app || typeof app.refrescarEstado !== "function") {
    return;
  }
  try {
    await app.refrescarEstado();
  } catch {
    // El saldo es informativo: un fallo aquí no invalida el turno.
  }
}

/**
 * Convierte un error en un mensaje claro para la vista.
 *
 * @param {unknown} error Error capturado.
 * @returns {string} Mensaje visible.
 */
function mensajeDeError(error) {
  const mensaje =
    error instanceof Error && error.message
      ? error.message
      : "Error desconocido";
  return `No se pudo completar la consulta: ${mensaje}`;
}

/**
 * Reconstruye todos los turnos en memoria, sin anunciarlos otra vez.
 *
 * @param {object | null} vista Referencias de la vista.
 * @returns {void}
 */
function pintarTurnos(vista) {
  if (!vista) {
    return;
  }
  vista.lista.setAttribute("aria-live", "off");
  vista.lista.replaceChildren();
  if (turnos.length === 0) {
    vista.lista.append(
      crearTexto(
        "p",
        "Todavía no hay turnos. Escribe una pregunta o usa un ejemplo.",
        "ventanilla__vacio",
      ),
    );
  } else {
    for (const turno of turnos) {
      vista.lista.append(crearTurno(turno));
    }
  }
  vista.lista.setAttribute("aria-live", "polite");
}

/**
 * Agrega un turno nuevo al final del hilo y lo hace visible.
 *
 * @param {object | null} vista Referencias de la vista.
 * @param {{pregunta: string, datos: object, fecha: Date}} turno Turno nuevo.
 * @returns {void}
 */
function agregarTurno(vista, turno) {
  if (!vista) {
    return;
  }
  const vacio = vista.lista.querySelector(".ventanilla__vacio");
  if (vacio) {
    vacio.remove();
  }
  const elemento = crearTurno(turno);
  vista.lista.append(elemento);
  if (vista.avisoContinuacion) {
    vista.avisoContinuacion.hidden = true;
  }
  if (typeof elemento.scrollIntoView === "function") {
    elemento.scrollIntoView({ block: "nearest" });
  }
}

/**
 * Crea el artículo de un turno: pregunta, ticket, meta, memoria y respuesta.
 *
 * @param {{pregunta: string, datos: object, fecha: Date}} turno Turno.
 * @returns {HTMLElement} El artículo creado.
 */
function crearTurno(turno) {
  const datos = turno?.datos ?? {};
  contadorTurnos += 1;
  const idPregunta = `ventanilla-turno-${contadorTurnos}`;

  const articulo = document.createElement("article");
  articulo.className = "ventanilla__turno";
  articulo.setAttribute("aria-labelledby", idPregunta);

  const cabecera = document.createElement("header");
  cabecera.className = "ventanilla__turno-cabecera";
  const pregunta = crearTexto(
    "h3",
    textoODefecto(turno?.pregunta, "Pregunta sin texto"),
    "ventanilla__pregunta",
  );
  pregunta.id = idPregunta;
  cabecera.append(crearTicket(datos), pregunta);

  const meta = document.createElement("p");
  meta.className = "ventanilla__meta";
  meta.append(
    crearTexto(
      "span",
      `Ruta: ${rotuloRuta(datos.ruta)}`,
      "ventanilla__meta-dato",
    ),
    crearTexto(
      "span",
      `Motivo: ${textoODefecto(datos.motivo)}`,
      "ventanilla__meta-dato",
    ),
  );

  articulo.append(cabecera, meta);

  if (typeof datos.reformulada === "string" && datos.reformulada.trim()) {
    articulo.append(
      crearTexto(
        "p",
        `Memoria: reformulada como «${datos.reformulada.trim()}»`,
        "ventanilla__memoria",
      ),
    );
  }

  const textoRespuesta = textoODefecto(
    datos.respuesta,
    "La sucursal no devolvió texto.",
  );
  articulo.append(crearTexto("p", textoRespuesta, "ventanilla__respuesta"));

  const escuchar = crearBotonEscuchar(textoRespuesta, etiquetaTurno(datos));
  if (escuchar) {
    const pie = document.createElement("div");
    pie.className = "ventanilla__turno-pie";
    pie.append(escuchar);
    articulo.append(pie);
  }

  return articulo;
}

/**
 * Crea el ticket de un turno con la letra y el número.
 *
 * @param {object} datos Respuesta del contrato.
 * @returns {HTMLElement} El ticket creado.
 */
function crearTicket(datos) {
  const letra = ["B", "T", "X"].includes(datos?.turno) ? datos.turno : "X";
  const etiqueta = etiquetaTurno(datos);
  const ticket = document.createElement("span");
  ticket.className = `ventanilla__ticket ventanilla__ticket--${letra.toLowerCase()}`;
  ticket.setAttribute("role", "img");
  ticket.setAttribute("aria-label", `Turno ${etiqueta}`);
  const visual = crearTexto("span", etiqueta, "ventanilla__ticket-texto");
  visual.setAttribute("aria-hidden", "true");
  ticket.append(visual);
  return ticket;
}

/**
 * Devuelve el texto del ticket, por ejemplo `T-12`.
 *
 * @param {object} datos Respuesta del contrato.
 * @returns {string} Letra y número, o solo la letra.
 */
function etiquetaTurno(datos) {
  const letra = ["B", "T", "X"].includes(datos?.turno) ? datos.turno : "X";
  const numero = datos?.turno_numero;
  if (
    numero === null ||
    numero === undefined ||
    !Number.isFinite(Number(numero))
  ) {
    return letra;
  }
  return `${letra}-${Number(numero)}`;
}

/**
 * Traduce el código de ruta a una etiqueta visible.
 *
 * @param {string} ruta Código del contrato.
 * @returns {string} Etiqueta legible.
 */
function rotuloRuta(ruta) {
  return RUTAS[ruta] ?? textoODefecto(ruta, "—");
}

/**
 * Traduce el tipo de fuente a una etiqueta visible.
 *
 * @param {string} tipo Código del contrato.
 * @returns {string} Etiqueta legible.
 */
function rotuloTipo(tipo) {
  return TIPOS[tipo] ?? textoODefecto(tipo, "—");
}

/**
 * Devuelve un texto no vacío o el valor por defecto.
 *
 * @param {unknown} valor Valor que llega de la API.
 * @param {string} [defecto] Texto de respaldo.
 * @returns {string} Texto visible.
 */
function textoODefecto(valor, defecto = "—") {
  return typeof valor === "string" && valor.trim() ? valor : defecto;
}

/**
 * Pinta el comprobante del turno más reciente, o su estado vacío.
 *
 * @param {HTMLElement} contenedor Aside del comprobante.
 * @param {{datos: object, fecha: Date} | null} turno Turno o `null`.
 * @returns {void}
 */
function pintarComprobante(contenedor, turno) {
  const titulo = crearTexto(
    "h2",
    "Comprobante",
    "ventanilla__titulo-seccion",
  );
  titulo.id = "ventanilla-comprobante-titulo";

  if (!turno) {
    contenedor.replaceChildren(
      titulo,
      crearTexto(
        "p",
        "El comprobante del turno más reciente aparecerá aquí.",
        "ventanilla__vacio",
      ),
    );
    return;
  }

  const datos = turno.datos ?? {};
  const tirilla = document.createElement("div");
  tirilla.className = "ventanilla__tirilla";
  tirilla.append(
    crearTexto("p", "Sucursal 1965", "ventanilla__tirilla-cabecera"),
    crearTexto(
      "p",
      "Comprobante de turno",
      "ventanilla__tirilla-subtitulo",
    ),
  );

  if (datos.cache === true) {
    tirilla.append(crearTexto("p", "Desde caché", "ventanilla__cache"));
  }

  const listaDatos = document.createElement("dl");
  listaDatos.className = "ventanilla__datos";
  agregarDato(listaDatos, "Turno", etiquetaTurno(datos));
  agregarDato(listaDatos, "Fecha y hora", formatearFecha(turno.fecha));
  agregarDato(listaDatos, "Ruta", rotuloRuta(datos.ruta));
  agregarDato(
    listaDatos,
    "Usó el modelo",
    datos.uso_modelo === true ? "Sí" : "No",
  );
  agregarDato(
    listaDatos,
    "Tokens de entrada",
    formatearEntero(datos.tokens_entrada),
  );
  agregarDato(
    listaDatos,
    "Tokens de salida",
    formatearEntero(datos.tokens_salida),
  );
  agregarDato(
    listaDatos,
    "Tokens de caché",
    formatearEntero(datos.tokens_cache),
  );
  agregarDato(listaDatos, "Tiempo", formatearTiempo(datos.tiempo_s));
  agregarDato(
    listaDatos,
    "Costo",
    formatearUsd(Number(datos.costo_usd ?? 0)),
  );
  agregarDato(listaDatos, "Caché", datos.cache === true ? "Sí" : "No");
  tirilla.append(listaDatos);

  const etapas = Array.isArray(turno.etapas) ? turno.etapas : [];
  if (etapas.length > 0) {
    tirilla.append(
      crearTexto("h3", "Recorrido del turno", "ventanilla__fuentes-titulo"),
    );
    const recorrido = document.createElement("ol");
    recorrido.className = "ventanilla__recorrido";
    recorrido.append(...etapas.map(crearPaso));
    tirilla.append(recorrido);
  }

  const fuentes = Array.isArray(datos.fuentes) ? datos.fuentes : [];
  tirilla.append(
    crearTexto("h3", "Fuentes", "ventanilla__fuentes-titulo"),
  );
  if (fuentes.length === 0) {
    tirilla.append(
      crearTexto(
        "p",
        "Sin fuentes en este turno.",
        "ventanilla__sin-fuentes",
      ),
    );
  } else {
    const listaFuentes = document.createElement("ol");
    listaFuentes.className = "ventanilla__fuentes";
    fuentes.forEach((fuente, indice) => {
      listaFuentes.append(crearFuente(fuente, indice));
    });
    tirilla.append(listaFuentes);
  }

  tirilla.append(
    crearTexto(
      "p",
      "Sucursal 1965 · Proyecto académico TAAML",
      "ventanilla__tirilla-pie",
    ),
  );
  contenedor.replaceChildren(titulo, tirilla);
}

/**
 * Agrega un par de etiqueta y valor a la lista del comprobante.
 *
 * @param {HTMLDListElement} lista Lista de datos.
 * @param {string} etiqueta Texto de la etiqueta.
 * @param {string} valor Texto del valor.
 * @returns {void}
 */
function agregarDato(lista, etiqueta, valor) {
  lista.append(
    crearTexto("dt", etiqueta, "ventanilla__dato-etiqueta"),
    crearTexto("dd", valor, "ventanilla__dato-valor"),
  );
}

/**
 * Crea una fuente numerada con título, tipo, enlace y similitud.
 *
 * @param {object} fuente Fuente del contrato.
 * @param {number} indice Posición en la lista, para el respaldo del número.
 * @returns {HTMLElement} El elemento de la fuente.
 */
function crearFuente(fuente, indice) {
  const elemento = document.createElement("li");
  elemento.className = "ventanilla__fuente";

  const numero = Number(fuente?.n);
  const etiquetaNumero =
    fuente?.n !== null &&
    fuente?.n !== undefined &&
    Number.isFinite(numero)
      ? String(numero)
      : String(indice + 1);

  const cabecera = document.createElement("p");
  cabecera.className = "ventanilla__fuente-cabecera";
  cabecera.append(
    crearTexto("span", etiquetaNumero, "ventanilla__fuente-n"),
    crearTexto(
      "span",
      textoODefecto(fuente?.titulo, "Fuente sin título"),
      "ventanilla__fuente-titulo",
    ),
  );

  elemento.append(cabecera);
  elemento.append(
    crearTexto("span", rotuloTipo(fuente?.tipo), "ventanilla__fuente-tipo"),
  );
  elemento.append(crearEnlaceFuente(fuente));

  const barra = crearBarraSimilitud(fuente?.similitud);
  if (barra) {
    elemento.append(barra);
  }

  return elemento;
}

/**
 * Crea el enlace a la fuente, solo si la URL es http o https.
 *
 * @param {object} fuente Fuente del contrato.
 * @returns {HTMLElement} Enlace o texto de respaldo.
 */
function crearEnlaceFuente(fuente) {
  const url = typeof fuente?.url === "string" ? fuente.url : "";
  if (!esUrlSegura(url)) {
    return crearTexto(
      "span",
      "Enlace no disponible",
      "ventanilla__fuente-sin-enlace",
    );
  }
  const enlace = crearTexto("a", "Abrir fuente", "ventanilla__fuente-enlace");
  enlace.href = url;
  enlace.target = "_blank";
  enlace.rel = "noopener noreferrer";
  enlace.setAttribute(
    "aria-label",
    `Abrir ${textoODefecto(fuente?.titulo, "la fuente")} en otra pestaña`,
  );
  return enlace;
}

/**
 * Crea la barra de similitud y su porcentaje. Si el valor falta, no hay barra.
 *
 * @param {unknown} valor Similitud entre 0 y 1.
 * @returns {HTMLElement | null} Barra creada o `null`.
 */
function crearBarraSimilitud(valor) {
  if (valor === null || valor === undefined || valor === "") {
    return null;
  }
  const numero = Number(valor);
  if (!Number.isFinite(numero)) {
    return null;
  }
  const proporcion = Math.min(Math.max(numero, 0), 1);
  const bloque = document.createElement("div");
  bloque.className = "ventanilla__similitud";

  const pista = document.createElement("span");
  pista.className = "ventanilla__similitud-pista";
  pista.setAttribute("aria-hidden", "true");
  const relleno = document.createElement("span");
  relleno.className = "ventanilla__similitud-relleno";
  relleno.style.width = `${Math.round(proporcion * 100)}%`;
  pista.append(relleno);

  bloque.append(
    pista,
    crearTexto(
      "span",
      `Similitud: ${Math.round(proporcion * 100)} %`,
      "ventanilla__similitud-texto",
    ),
  );
  return bloque;
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

/**
 * Formatea la fecha y hora local del envío.
 *
 * @param {Date} fecha Fecha del turno.
 * @returns {string} Texto como `4/11/2026, 10:32`.
 */
function formatearFecha(fecha) {
  if (!(fecha instanceof Date) || Number.isNaN(fecha.getTime())) {
    return "—";
  }
  try {
    return fecha.toLocaleString("es-CO", {
      dateStyle: "short",
      timeStyle: "short",
      hour12: false,
    });
  } catch {
    return fecha.toLocaleString("es-CO");
  }
}

/**
 * Formatea el tiempo de respuesta con dos decimales.
 *
 * @param {unknown} valor Segundos.
 * @returns {string} Texto como `0,04 s`.
 */
function formatearTiempo(valor) {
  const numero = Number(valor);
  if (!Number.isFinite(numero)) {
    return "0,00 s";
  }
  return `${numero.toLocaleString("es-CO", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })} s`;
}

/**
 * Formatea un entero con separador de miles.
 *
 * @param {unknown} valor Número de tokens.
 * @returns {string} Texto como `1.520`.
 */
function formatearEntero(valor) {
  const numero = Number(valor);
  return Number.isFinite(numero) ? numero.toLocaleString("es-CO") : "0";
}

/**
 * Crea el botón de escucha si el navegador soporta síntesis de voz.
 *
 * @param {string} texto Respuesta que se leerá.
 * @param {string} etiqueta Ticket del turno, para el nombre accesible.
 * @returns {HTMLButtonElement | null} Botón o `null`.
 */
function crearBotonEscuchar(texto, etiqueta) {
  if (!texto.trim()) {
    return null;
  }
  if (
    !("speechSynthesis" in window) ||
    typeof window.SpeechSynthesisUtterance !== "function"
  ) {
    return null;
  }
  const boton = crearBoton("Escuchar", "ventanilla__escuchar", "button");
  boton.setAttribute(
    "aria-label",
    `Escuchar la respuesta del turno ${etiqueta}`,
  );
  boton.setAttribute("aria-pressed", "false");
  boton.addEventListener("click", () => {
    if (botonEscuchando === boton) {
      detenerVoz();
      return;
    }
    hablar(texto, boton);
  });
  return boton;
}

/**
 * Elige la primera voz en español disponible, prefiriendo `es-CO`.
 *
 * @returns {SpeechSynthesisVoice | null} Voz elegida o `null`.
 */
function elegirVozEspanola() {
  try {
    const voces = window.speechSynthesis.getVoices();
    const espanolas = voces.filter((voz) =>
      voz.lang?.toLowerCase().startsWith("es"),
    );
    return (
      espanolas.find((voz) =>
        voz.lang.toLowerCase().startsWith("es-co"),
      ) ??
      espanolas[0] ??
      null
    );
  } catch {
    return null;
  }
}

/**
 * Lee una respuesta en voz alta y cambia el botón a «Detener».
 *
 * @param {string} texto Texto que se leerá.
 * @param {HTMLButtonElement} boton Botón que inició la lectura.
 * @returns {void}
 */
function hablar(texto, boton) {
  detenerVoz();
  try {
    const locucion = new window.SpeechSynthesisUtterance(texto);
    const voz = elegirVozEspanola();
    if (voz) {
      locucion.voice = voz;
    }
    locucion.lang = voz?.lang ?? "es-CO";
    locucion.rate = 1;
    botonEscuchando = boton;
    boton.textContent = "Detener";
    boton.setAttribute("aria-pressed", "true");
    locucion.onend = () => restaurarBotonEscucha(boton);
    locucion.onerror = () => restaurarBotonEscucha(boton);
    window.speechSynthesis.speak(locucion);
  } catch {
    restaurarBotonEscucha(boton);
    if (vistaActual) {
      anunciar(vistaActual, "No se pudo leer la respuesta en voz alta.");
    }
  }
}

/**
 * Devuelve el botón de escucha a su estado inicial.
 *
 * @param {HTMLButtonElement | null} boton Botón que terminó de leer.
 * @returns {void}
 */
function restaurarBotonEscucha(boton) {
  if (!boton) {
    return;
  }
  boton.textContent = "Escuchar";
  boton.setAttribute("aria-pressed", "false");
  if (botonEscuchando === boton) {
    botonEscuchando = null;
  }
}

/**
 * Detiene cualquier lectura en curso.
 *
 * @returns {void}
 */
function detenerVoz() {
  try {
    window.speechSynthesis?.cancel();
  } catch {
    // Sin voz disponible: no hay nada que detener.
  }
  if (botonEscuchando) {
    restaurarBotonEscucha(botonEscuchando);
  }
}

/**
 * Crea el botón de dictado si el navegador expone reconocimiento de voz.
 *
 * @param {HTMLInputElement} entrada Campo donde se escribe la transcripción.
 * @returns {HTMLButtonElement | null} Botón o `null`.
 */
function crearBotonDictado(entrada) {
  const Reconocimiento =
    window.SpeechRecognition ?? window.webkitSpeechRecognition;
  if (typeof Reconocimiento !== "function") {
    return null;
  }
  const boton = crearBoton(
    "Dictar",
    "ventanilla__boton ventanilla__boton--secundario",
    "button",
  );
  boton.setAttribute("aria-label", "Dictar la pregunta");
  boton.setAttribute("aria-pressed", "false");
  boton.addEventListener("click", () => {
    if (reconocimiento) {
      detenerDictado();
      return;
    }
    iniciarDictado(Reconocimiento, entrada, boton);
  });
  return boton;
}

/**
 * Inicia el dictado, escribe la transcripción y lo cierra en cuanto llega el
 * resultado final.
 *
 * Antes de empezar detiene cualquier reconocimiento anterior: nunca hay dos
 * micrófonos activos a la vez. El botón vuelve a «Dictar» al terminar, al
 * fallar y al cancelar.
 *
 * @param {Function} Reconocimiento Constructor del reconocimiento.
 * @param {HTMLInputElement} entrada Campo de pregunta.
 * @param {HTMLButtonElement} boton Botón que inició el dictado.
 * @returns {void}
 */
function iniciarDictado(Reconocimiento, entrada, boton) {
  detenerDictado();
  try {
    const instancia = new Reconocimiento();
    instancia.lang = "es-CO";
    instancia.interimResults = false;
    instancia.continuous = false;
    instancia.maxAlternatives = 1;
    reconocimiento = instancia;
    botonDictadoActual = boton;
    boton.textContent = "Dictando…";
    boton.setAttribute("aria-pressed", "true");

    instancia.onresult = (evento) => {
      const resultado = evento.results?.[0];
      const texto = String(resultado?.[0]?.transcript ?? "").trim();
      if (texto) {
        entrada.value = entrada.value.trim()
          ? `${entrada.value.trim()} ${texto}`
          : texto;
        entrada.focus();
      }
      if (reconocimiento === instancia && instancia.continuous !== true) {
        detenerDictado();
      }
    };
    instancia.onerror = (evento) => {
      if (reconocimiento !== instancia) {
        return;
      }
      if (evento?.error === "aborted") {
        detenerDictado();
        return;
      }
      const permisoNegado =
        evento?.error === "not-allowed" ||
        evento?.error === "service-not-allowed";
      detenerDictado();
      if (vistaActual) {
        anunciar(
          vistaActual,
          permisoNegado
            ? "Para dictar, permite el micrófono en el navegador."
            : "No se pudo usar el micrófono. Revisa el permiso del navegador.",
        );
      }
    };
    instancia.onend = () => {
      if (reconocimiento === instancia) {
        detenerDictado();
      }
    };
    instancia.start();
  } catch {
    detenerDictado();
    if (vistaActual) {
      anunciar(
        vistaActual,
        "No se pudo usar el micrófono. Revisa el permiso del navegador.",
      );
    }
  }
}

/**
 * Detiene el dictado en curso y devuelve el botón a «Dictar».
 *
 * @returns {void}
 */
function detenerDictado() {
  const instancia = reconocimiento;
  reconocimiento = null;
  if (instancia) {
    try {
      instancia.abort();
    } catch {
      // Si no se puede abortar, el reconocimiento termina solo.
    }
  }
  if (botonDictadoActual) {
    botonDictadoActual.textContent = "Dictar";
    botonDictadoActual.setAttribute("aria-pressed", "false");
    botonDictadoActual = null;
  }
}

/**
 * Detiene el dictado y la lectura cuando la página se oculta o se cierra, y
 * también cuando el hash cambia de vista.
 *
 * @param {Event} evento Evento `visibilitychange`, `pagehide` o `hashchange`.
 * @returns {void}
 */
function alSalirDeLaVista(evento) {
  if (
    evento?.type === "visibilitychange" &&
    document.visibilityState === "visible"
  ) {
    return;
  }
  detenerDictado();
  detenerVoz();
}

window.addEventListener("pagehide", alSalirDeLaVista);
window.addEventListener("visibilitychange", alSalirDeLaVista);
window.addEventListener("hashchange", alSalirDeLaVista);

/**
 * Pinta la vista Ventanilla dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-ventanilla` de `index.html`.
 * @param {{modo: string, resumen?: object, pedir: Function}} estado Estado
 *   compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  const app = estado;
  detenerVoz();
  detenerDictado();

  if (!hiloInicializado) {
    const guardado = leerHiloGuardado();
    if (guardado) {
      hilo = guardado;
      hiloDeEstaPagina = false;
    } else {
      hilo = crearHilo();
      guardarHilo(hilo);
      hiloDeEstaPagina = true;
    }
    hiloInicializado = true;
  }
  if (hiloDeTurnos !== hilo) {
    hiloDeTurnos = hilo;
    turnos = [];
  }

  const continuaba =
    Boolean(hilo) &&
    turnos.length === 0 &&
    !hiloDeEstaPagina &&
    !enCurso;

  const raiz = document.createElement("div");
  raiz.className = "ventanilla";

  const avisos = crearAvisos(app, continuaba);
  const formulario = crearFormulario();

  const listaAvance = document.createElement("ol");
  listaAvance.className = "ventanilla__avance";
  listaAvance.setAttribute("aria-label", "Avance del turno");
  listaAvance.hidden = true;

  const cuerpo = document.createElement("div");
  cuerpo.className = "ventanilla__cuerpo";

  const conversacion = document.createElement("section");
  conversacion.className = "ventanilla__conversacion";
  conversacion.setAttribute(
    "aria-labelledby",
    "ventanilla-conversacion-titulo",
  );
  const tituloConversacion = crearTexto(
    "h2",
    "Conversación",
    "ventanilla__titulo-seccion",
  );
  tituloConversacion.id = "ventanilla-conversacion-titulo";

  const lista = document.createElement("div");
  lista.className = "ventanilla__turnos";
  lista.setAttribute("role", "log");
  lista.setAttribute("aria-live", "polite");
  lista.setAttribute("aria-relevant", "additions");
  conversacion.append(tituloConversacion, lista);

  const comprobante = document.createElement("aside");
  comprobante.className = "ventanilla__comprobante";
  comprobante.setAttribute(
    "aria-labelledby",
    "ventanilla-comprobante-titulo",
  );

  cuerpo.append(conversacion, comprobante);
  raiz.append(
    avisos,
    formulario.elemento,
    formulario.estado,
    listaAvance,
    formulario.error,
    cuerpo,
  );
  contenedor.replaceChildren(
    crearEncabezadoVista(
      "ventanilla",
      "Ventanilla",
      "Aquí se hace la pregunta. El Digiturno le asigna un turno y cada respuesta sale con su comprobante: fuentes, tokens, costo y tiempo.",
    ),
    raiz,
  );

  vistaActual = {
    app,
    formulario: formulario.elemento,
    entrada: formulario.entrada,
    botonEnviar: formulario.botonEnviar,
    botonNueva: formulario.botonNueva,
    botonesEjemplo: formulario.botonesEjemplo,
    estado: formulario.estado,
    error: formulario.error,
    avance: listaAvance,
    avisoContinuacion: avisos.querySelector(".ventanilla__continuacion"),
    lista,
    comprobante,
  };

  conectarEventos(vistaActual);
  pintarTurnos(vistaActual);
  actualizarComprobante(
    vistaActual,
    turnos.length > 0 ? turnos[turnos.length - 1] : null,
  );
  if (enCurso) {
    mostrarEstado(vistaActual, "Atendiendo una pregunta…");
  }
  pintarAvance(vistaActual);
  actualizarControles(vistaActual, enCurso);
}

/**
 * Pinta el comprobante del turno indicado.
 *
 * @param {object | null} vista Referencias de la vista.
 * @param {{datos: object, fecha: Date} | null} turno Turno o `null`.
 * @returns {void}
 */
function actualizarComprobante(vista, turno) {
  if (!vista) {
    return;
  }
  pintarComprobante(vista.comprobante, turno);
}
