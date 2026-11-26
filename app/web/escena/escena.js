/**
 * Sucursal 1965 · pantalla de la escena «Pana vs. el gota a gota» (`/escena.html`).
 *
 * Lee los turnos del contrato (`contrato.js`) y los reproduce uno por uno: el
 * personaje que habla se ilumina, su texto sale en subtítulos grandes y su voz
 * suena con `voz.js` (Piper o la del navegador). El panel de la derecha muestra
 * el escenario, el semáforo, las cifras con su fuente y los hallazgos del
 * auditor.
 *
 * Antes de la escena, Pana presenta a los agentes y la actividad
 * (`anfitrion.js`). Los turnos de la escena salen de `GET /api/escena/proyectado`
 * (la escena precalculada por `make escena-proyectada`); si no responde, de la
 * última escena guardada en esta pestaña (`respaldo.js`) y, si tampoco hay, de
 * `escena/turnos-ejemplo.json`. La pantalla dice cuál usa. Un turno que no
 * cumple el contrato no se dice: se muestra el error.
 *
 * Plan B: el botón **Núcleo** (o el evento `escena:nucleo`, que puede lanzar
 * el flujo en vivo cuando la negociación falla) sigue con Don Gota, Pana y el
 * auditor sin repetir lo ya dicho. El panel de **trazabilidad** (tecla T) es
 * solo para quien facilita y empieza oculto.
 *
 * Al final (o cuando quien presenta lo pida), el paso «Preguntas» abre el
 * micrófono: la persona del público pregunta y Pana responde con voz y
 * subtítulos, solo sobre el proyecto (`anfitrion.js`).
 *
 * Teclado: Espacio o → pasa al siguiente turno, P reproduce o pausa, S activa
 * el modo solo subtítulos, Q abre o cierra las preguntas, N pasa al núcleo,
 * T muestra la trazabilidad y R vuelve al inicio.
 */

import { decirComo, detenerVoz } from "../voz.js";
import {
  APERTURA_PREGUNTAS,
  LARGO_MAXIMO,
  cargarIntroduccion,
  responderPregunta,
} from "./anfitrion.js";
import { montarCaptura } from "./captura.js";
import { montarHerramientas } from "./herramientas.js";
import {
  PASOS,
  PASO_PREGUNTAS,
  PASO_PRESENTACION,
  PERSONAJES,
  TEXTO_VEREDICTO,
  erroresDelTurno,
  erroresDelVeredicto,
  formatearPesos,
  grupoDeLaCifra,
  pasoDelTurno,
  veredictoDeHallazgos,
} from "./contrato.js";
import { detenerMicrofono, escuchando, escuchar, hayMicrofono } from "./microfono.js";
import {
  CLAVE_COMPLETA,
  CLAVE_NUCLEO,
  borrarEscenas,
  guardarEscena,
  leerEscena,
  nucleoDeLaEscena,
  pasarAlNucleo,
} from "./respaldo.js";
import { retrato } from "./rostros.js";
import { claveDeLaCifra, resumenDeTraza, sellosCortos, trazaDelTurno } from "./traza.js";

/** Nombre visible de cada personaje (el color sale de la hoja de estilos). */
const FICHAS = Object.freeze({
  pana: { nombre: "Pana" },
  don_gota: { nombre: "Don Gota" },
  joven: { nombre: "Joven (voluntario)" },
  agente_joven: { nombre: "Agente del joven" },
  agente_banco: { nombre: "Agente del banco" },
  auditor: { nombre: "Auditor" },
  invitado: { nombre: "Invitado" },
});

/** Escena precalculada, su núcleo y los turnos de ejemplo. */
const RUTA_PROYECTADO = "/api/escena/proyectado";
const RUTA_NUCLEO = `${RUTA_PROYECTADO}?modo=nucleo`;
const RUTA_EJEMPLO = "escena/turnos-ejemplo.json";

/** Espera máxima por la escena (al cargar) y por el núcleo (en vivo). */
const ESPERA_ESCENA_MS = 8000;
const ESPERA_NUCLEO_MS = 4000;

/** Texto del sello de la barra según de dónde salió la escena. */
const SELLOS = Object.freeze({
  servidor: "",
  guardada: "Escena guardada (sin servidor)",
  ejemplo: "Turnos de ejemplo",
});

/** Pausa después de cada turno, y lectura mínima cuando no hay voz. */
const PAUSA_ENTRE_TURNOS_MS = 600;
const MS_POR_LETRA = 55;
const LECTURA_MINIMA_MS = 1800;

/** Estado de la reproducción. */
const estado = {
  turnos: [],
  largoIntroduccion: 0,
  preguntas: false,
  aperturaDicha: false,
  pensando: false,
  indice: -1,
  paso: -1,
  reproduciendo: false,
  cifras: new Map(),
  vistos: new Set(),
  escenario: null,
  veredicto: null,
  introduccion: [],
  original: [],
  veredictoOriginal: null,
  modo: "completa",
  todas: new Map(),
  sellos: {},
  traza: false,
  auditorHablo: false,
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
 * Arma el escenario con los personajes del contrato y la barra de pasos.
 *
 * @returns {void}
 */
function montar() {
  const escenario = porId("escena-personajes");
  escenario.replaceChildren(
    ...PERSONAJES.map((personaje) => {
      const caja = crear("div", `escena__personaje escena__personaje--${personaje}`);
      caja.id = `personaje-${personaje}`;
      const ondas = crear("div", "escena__ondas");
      ondas.setAttribute("aria-hidden", "true");
      for (let barra = 0; barra < 4; barra += 1) {
        ondas.append(crear("i"));
      }
      caja.append(retrato(personaje), ondas, crear("div", "escena__nombre", FICHAS[personaje].nombre));
      return caja;
    }),
  );
  porId("escena-pasos").replaceChildren(
    ...PASOS.map((texto, posicion) => {
      const paso = crear("span", "escena__paso", `${posicion + 1} ${texto}`);
      paso.id = `paso-${posicion}`;
      return paso;
    }),
  );
}

/**
 * Pide una escena a una ruta y la devuelve solo si trae lista de turnos.
 *
 * @param {string} ruta Ruta de la API o del archivo.
 * @param {number} espera Milisegundos antes de rendirse.
 * @returns {Promise<{turnos: object[], veredicto?: object, sellos?: object} | null>}
 *   La escena, o `null` si no respondió bien.
 */
async function pedirEscena(ruta, espera) {
  try {
    const respuesta = await fetch(ruta, { signal: AbortSignal.timeout(espera) });
    if (!respuesta.ok) {
      return null;
    }
    const datos = await respuesta.json();
    return Array.isArray(datos?.turnos) ? datos : null;
  } catch {
    return null;
  }
}

/**
 * Deja de una escena solo lo que usa la pantalla, con el veredicto validado.
 *
 * @param {{turnos: object[], veredicto?: object, sellos?: object}} datos Escena recibida.
 * @returns {{turnos: object[], veredicto: object | null, sellos: object}} Escena lista.
 */
function normalizarEscena(datos) {
  const veredicto = erroresDelVeredicto(datos.veredicto).length === 0 ? datos.veredicto : null;
  return { turnos: datos.turnos, veredicto, sellos: datos.sellos ?? {} };
}

/**
 * Carga la escena: primero el servidor, luego la guardada en esta pestaña y
 * por último los turnos de ejemplo.
 *
 * Lo que responde el servidor se guarda en la pestaña (`respaldo.js`) para sobrevivir a
 * una recarga si la app se cae.
 *
 * @returns {Promise<{turnos: object[], veredicto: object | null, sellos: object, fuente: "servidor" | "guardada" | "ejemplo"}>}
 *   La escena y de dónde salió.
 */
async function cargarTurnos() {
  const delServidor = await pedirEscena(RUTA_PROYECTADO, ESPERA_ESCENA_MS);
  if (delServidor) {
    const escena = normalizarEscena(delServidor);
    guardarEscena(CLAVE_COMPLETA, escena);
    return { ...escena, fuente: "servidor" };
  }
  const guardada = leerEscena(CLAVE_COMPLETA);
  if (guardada) {
    return { ...normalizarEscena(guardada), fuente: "guardada" };
  }
  const ejemplo = await pedirEscena(RUTA_EJEMPLO, ESPERA_ESCENA_MS);
  return ejemplo
    ? { ...normalizarEscena(ejemplo), fuente: "ejemplo" }
    : { turnos: [], veredicto: null, sellos: {}, fuente: "ejemplo" };
}

/**
 * Busca el núcleo: el del servidor, el guardado o, si no hay ninguno, el que
 * sale de la escena completa (Don Gota, Pana y el auditor).
 *
 * @returns {Promise<{turnos: object[], veredicto: object | null, de: string}>}
 *   Turnos del núcleo, su veredicto y de dónde salieron.
 */
async function buscarNucleo() {
  const delServidor = await pedirEscena(RUTA_NUCLEO, ESPERA_NUCLEO_MS);
  if (delServidor) {
    const nucleo = normalizarEscena(delServidor);
    guardarEscena(CLAVE_NUCLEO, nucleo);
    return { ...nucleo, de: "servidor" };
  }
  const guardado = leerEscena(CLAVE_NUCLEO);
  if (guardado) {
    return { ...normalizarEscena(guardado), de: "guardado" };
  }
  return { turnos: nucleoDeLaEscena(estado.original), veredicto: estado.veredictoOriginal, de: "escena" };
}

/**
 * Muestra un turno: quién habla, subtítulo, pasos, escenario y cifras.
 *
 * @param {number} indice Posición del turno.
 * @returns {boolean} `true` si el turno cumple el contrato y se mostró.
 */
function mostrar(indice) {
  const turno = estado.turnos[indice];
  const errores = erroresDelTurno(turno);
  const subtitulo = porId("escena-texto");
  const quien = porId("escena-quien");
  if (errores.length > 0) {
    quien.replaceChildren(crear("span", "escena__error", "Turno inválido"));
    subtitulo.textContent = errores.join(" · ");
    return false;
  }
  estado.paso =
    indice < estado.largoIntroduccion
      ? PASO_PRESENTACION
      : pasoDelTurno(turno, Math.min(estado.paso, PASO_PREGUNTAS - 1));
  estado.vistos.add(turno.personaje);
  if (turno.cifras.length > 0) {
    // El panel muestra las cifras del turno que se está diciendo; si el turno
    // no trae cifras, quedan las anteriores (así el auditor ve la comparación).
    estado.cifras = new Map(turno.cifras.map((cifra) => [cifra.etiqueta, cifra]));
  }
  if (turno.escenario) {
    estado.escenario = turno.escenario;
  }
  for (const cifra of turno.cifras) {
    estado.todas.set(claveDeLaCifra(cifra), cifra);
  }
  // En la presentación el auditor solo se presenta: aún no hay veredicto.
  if (turno.personaje === "auditor" && indice >= estado.largoIntroduccion) {
    estado.auditorHablo = true;
  }
  iluminar(turno.personaje);
  marcarPasos();
  porId("escena-pregunta").hidden = true;
  quien.replaceChildren(
    crear("span", `escena__quien escena__quien--${turno.personaje}`, FICHAS[turno.personaje].nombre),
    crear("span", "escena__origen", turno.origen),
  );
  subtitulo.textContent = turno.subtitulo || turno.texto;
  pintarPanel(turno);
  pintarTraza(turno);
  porId("escena-contador").textContent = `Turno ${indice + 1} de ${estado.turnos.length}`;
  return true;
}

/**
 * Ilumina al personaje que habla y atenúa a los que aún no han hablado.
 *
 * @param {string} quienHabla Personaje del turno.
 * @returns {void}
 */
function iluminar(quienHabla) {
  for (const personaje of PERSONAJES) {
    const caja = porId(`personaje-${personaje}`);
    caja.classList.toggle("escena__personaje--habla", personaje === quienHabla);
    caja.classList.toggle("escena__personaje--visto", estado.vistos.has(personaje));
  }
}

/**
 * Marca en la barra el paso actual y los ya hechos.
 *
 * @returns {void}
 */
function marcarPasos() {
  PASOS.forEach((_, posicion) => {
    const paso = porId(`paso-${posicion}`);
    paso.classList.toggle("escena__paso--activo", posicion === estado.paso);
    paso.classList.toggle("escena__paso--hecho", posicion < estado.paso);
  });
}

/**
 * Pinta el panel de cifras: escenario, semáforo del crédito, cifras con su
 * fuente y, en el turno del auditor, su veredicto (sin colores).
 *
 * @param {object} turno Turno actual (ya validado).
 * @returns {void}
 */
function pintarPanel(turno) {
  const escenario = estado.escenario;
  const chips = [];
  if (escenario && Number(escenario.monto) > 0) {
    chips.push(formatearPesos(escenario.monto));
  }
  if (escenario?.plazo_meses) {
    chips.push(`${escenario.plazo_meses} meses`);
  }
  porId("escena-escenario").replaceChildren(
    ...(chips.length ? chips : ["Esperando al voluntario"]).map((texto) =>
      crear("span", "escena__chip", texto),
    ),
  );
  const semaforo = escenario?.semaforo ?? "";
  porId("escena-semaforo").dataset.color = semaforo;
  porId("escena-semaforo-texto").textContent = semaforo
    ? `Semáforo del crédito: ${semaforo}`
    : "Semáforo sin calcular";

  const filas = [...estado.cifras.values()].map((cifra) => {
    const fila = crear("tr", `escena__cifra escena__cifra--${grupoDeLaCifra(cifra)}`);
    const fuente = crear("td", "escena__fuente", cifra.fuente.tipo);
    fuente.title = cifra.fuente.referencia;
    fila.append(crear("th", "", cifra.etiqueta), crear("td", "", cifra.valor_legible), fuente);
    return fila;
  });
  porId("escena-cifras").replaceChildren(...filas);
  porId("escena-sin-cifras").hidden = filas.length > 0;

  const delAuditor = turno.personaje === "auditor";
  porId("escena-caja-hallazgos").hidden = !delAuditor;
  if (!delAuditor) {
    return;
  }
  const hallazgos = estado.veredicto?.hallazgos ?? turno.hallazgos;
  const veredicto = estado.veredicto?.veredicto ?? veredictoDeHallazgos(turno.hallazgos);
  const etiqueta = porId("escena-veredicto");
  etiqueta.textContent = `Auditor: ${TEXTO_VEREDICTO[veredicto]}`;
  etiqueta.dataset.veredicto = veredicto;
  porId("escena-hallazgos").replaceChildren(...hallazgos.map((h) => crear("li", "", h.detalle)));
  porId("escena-conforme").hidden = hallazgos.length > 0;
}

/**
 * Llena una tabla de dos o tres columnas con filas de texto.
 *
 * @param {string} id Id del `tbody`.
 * @param {string[][]} filas Celdas de cada fila (la primera es el encabezado).
 * @returns {void}
 */
function llenarTabla(id, filas) {
  porId(id).replaceChildren(
    ...filas.map(([encabezado, ...celdas]) => {
      const fila = crear("tr");
      fila.append(crear("th", "", encabezado), ...celdas.map((celda) => crear("td", "", celda)));
      return fila;
    }),
  );
}

/**
 * Pinta el panel de trazabilidad (aunque esté oculto, para que al abrirlo ya
 * tenga el turno actual).
 *
 * @param {object | null} turno Turno actual ya validado, o `null` al reiniciar.
 * @returns {void}
 */
function pintarTraza(turno) {
  // El veredicto aparece cuando el auditor ya habló, no antes.
  const veredicto = estado.auditorHablo ? (estado.veredicto?.veredicto ?? null) : null;
  llenarTabla(
    "escena-traza-resumen",
    resumenDeTraza(estado.todas.values(), veredicto).map((fila) => [fila.nombre, fila.valor, fila.fuente]),
  );
  const datos = turno ? trazaDelTurno(turno) : null;
  porId("escena-traza-id").textContent = datos?.id ?? "—";
  porId("escena-traza-origen").textContent = datos?.origen ?? "—";
  porId("escena-traza-escenario").textContent = datos?.escenario ?? "—";
  porId("escena-traza-modo").textContent = estado.modo;
  llenarTabla(
    "escena-traza-fuentes",
    datos?.fuentes.length
      ? datos.fuentes.map((f) => [f.etiqueta, f.tipo, [f.referencia, f.vigencia].filter(Boolean).join(" · ")])
      : [["Este turno no dice cifras."]],
  );
  porId("escena-traza-hallazgos").replaceChildren(
    ...(datos?.hallazgos ?? []).map((texto) => crear("li", "", texto)),
  );
  const sellos = sellosCortos(estado.sellos);
  porId("escena-traza-sellos").textContent = sellos.length ? `Sellos: ${sellos.join(" · ")}` : "";
}

/**
 * Muestra u oculta el panel de trazabilidad (solo para quien facilita).
 *
 * @returns {void}
 */
function alternarTraza() {
  estado.traza = !estado.traza;
  porId("escena-traza").hidden = !estado.traza;
  porId("escena-ver-traza").setAttribute("aria-expanded", String(estado.traza));
}

/**
 * Pasa al núcleo (Don Gota, Pana y el auditor) sin perder los turnos ya
 * dichos. Se usa con el botón Núcleo, la tecla N o el evento `escena:nucleo`.
 * Deja la escena en pausa: quien presenta sigue con «Seguir» o Espacio.
 *
 * @returns {Promise<void>} Se resuelve al quedar el núcleo listo.
 */
async function cambiarANucleo() {
  if (estado.modo === "nucleo") {
    return;
  }
  pausar();
  const boton = porId("escena-nucleo");
  boton.disabled = true;
  porId("escena-modo").textContent = "Buscando el núcleo…";
  const nucleo = await buscarNucleo();
  const largo = estado.largoIntroduccion;
  const escena = estado.turnos.slice(largo);
  const indiceEnEscena = Math.max(-1, estado.indice - largo);
  estado.turnos = [...estado.introduccion, ...pasarAlNucleo(escena, indiceEnEscena, nucleo.turnos)];
  if (nucleo.veredicto) {
    estado.veredicto = nucleo.veredicto;
  }
  estado.modo = "nucleo";
  porId("escena-modo").textContent = `Núcleo (${nucleo.de})`;
  porId("escena-traza-modo").textContent = estado.modo;
  porId("escena-contador").textContent = `Turno ${estado.indice + 1} de ${estado.turnos.length}`;
  actualizarBotones();
}

/**
 * Dice el turno con la voz de su personaje, o espera lo que tarda leerlo.
 *
 * El joven y el invitado son la persona voluntaria: hablan en persona o
 * escriben por WhatsApp, así que su turno solo se muestra en subtítulos.
 *
 * @param {object} turno Turno ya mostrado.
 * @returns {Promise<void>} Se resuelve cuando termina de sonar.
 */
function decir(turno) {
  const soloSubtitulos =
    porId("escena-solo-subtitulos").checked ||
    turno.personaje === "joven" ||
    turno.personaje === "invitado";
  const caja = porId(`personaje-${turno.personaje}`);
  caja.classList.toggle("escena__personaje--mudo", soloSubtitulos);
  return new Promise((listo) => {
    if (soloSubtitulos) {
      window.setTimeout(listo, Math.max(LECTURA_MINIMA_MS, turno.texto.length * MS_POR_LETRA));
      return;
    }
    decirComo(turno.personaje, turno.texto, { alTerminar: listo })
      .then((voz) => {
        porId("escena-voz").textContent = voz === "piper" ? "Voz: Piper" : voz === "navegador" ? "Voz: navegador" : "";
      })
      .catch(() => {
        // Si la voz falla, el turno ya está en subtítulos: se sigue sin esperar.
        porId("escena-voz").textContent = "Voz: falló";
        listo();
      });
  });
}

/**
 * Espera unos milisegundos.
 *
 * @param {number} ms Milisegundos.
 * @returns {Promise<void>} Se resuelve al pasar el tiempo.
 */
function esperar(ms) {
  return new Promise((listo) => window.setTimeout(listo, ms));
}

/**
 * Reproduce desde el turno actual hasta el final o hasta que se pause.
 *
 * En modo solo subtítulos avanza de a un turno por clic, para que quien
 * presenta lleve el ritmo.
 *
 * @returns {Promise<void>} Se resuelve al terminar o al pausar.
 */
async function reproducir() {
  if (estado.reproduciendo) {
    return;
  }
  estado.reproduciendo = true;
  actualizarBotones();
  while (estado.reproduciendo && estado.indice < estado.turnos.length - 1) {
    estado.indice += 1;
    if (mostrar(estado.indice)) {
      await decir(estado.turnos[estado.indice]);
    }
    if (porId("escena-solo-subtitulos").checked) {
      break;
    }
    await esperar(PAUSA_ENTRE_TURNOS_MS);
  }
  estado.reproduciendo = false;
  actualizarBotones();
}

/**
 * Pausa la reproducción y corta la voz.
 *
 * @returns {void}
 */
function pausar() {
  estado.reproduciendo = false;
  detenerVoz();
  actualizarBotones();
}

/**
 * Muestra el siguiente turno sin esperar a la voz anterior.
 *
 * @returns {void}
 */
function siguiente() {
  pausar();
  if (estado.indice < estado.turnos.length - 1) {
    estado.indice += 1;
    if (mostrar(estado.indice)) {
      decir(estado.turnos[estado.indice]);
    }
  }
  actualizarBotones();
}

/**
 * Botón Reiniciar: vuelve a la escena completa desde el principio y borra la
 * escena guardada en esta pestaña.
 *
 * @returns {void}
 */
function reiniciar() {
  borrarEscenas();
  estado.turnos = [...estado.introduccion, ...estado.original];
  estado.veredicto = estado.veredictoOriginal;
  estado.modo = "completa";
  porId("escena-modo").textContent = "";
  prepararInicio();
}

/**
 * Deja la pantalla lista para empezar, sin cambiar los turnos cargados.
 *
 * @returns {void}
 */
function prepararInicio() {
  pausar();
  cerrarPreguntas();
  estado.aperturaDicha = false;
  estado.indice = -1;
  estado.paso = -1;
  estado.cifras.clear();
  estado.todas.clear();
  estado.auditorHablo = false;
  estado.escenario = null;
  estado.vistos.clear();
  montar();
  porId("escena-quien").replaceChildren();
  porId("escena-texto").textContent = "Pulsa «Empezar» o la barra espaciadora.";
  porId("escena-escenario").replaceChildren(crear("span", "escena__chip", "Esperando al voluntario"));
  porId("escena-cifras").replaceChildren();
  porId("escena-sin-cifras").hidden = false;
  porId("escena-caja-hallazgos").hidden = true;
  porId("escena-semaforo").dataset.color = "";
  porId("escena-semaforo-texto").textContent = "Semáforo sin calcular";
  porId("escena-contador").textContent = `${estado.turnos.length} turnos`;
  pintarTraza(null);
  actualizarBotones();
}

/**
 * Ajusta el texto y el estado de los botones.
 *
 * @returns {void}
 */
function actualizarBotones() {
  const alFinal = estado.indice >= estado.turnos.length - 1;
  const reproducirBoton = porId("escena-reproducir");
  reproducirBoton.textContent = estado.reproduciendo
    ? "Pausar"
    : estado.indice < 0
      ? "Empezar"
      : alFinal
        ? "Terminó"
        : "Seguir";
  reproducirBoton.disabled = !estado.reproduciendo && alFinal;
  porId("escena-siguiente").disabled = alFinal;
  porId("escena-nucleo").disabled = estado.modo === "nucleo" || estado.original.length === 0;
}

/**
 * Abre el paso «Preguntas»: muestra el cuadro de la pregunta y, la primera vez,
 * Pana invita al público a preguntar.
 *
 * @returns {void}
 */
function abrirPreguntas() {
  pausar();
  estado.preguntas = true;
  estado.paso = PASO_PREGUNTAS;
  marcarPasos();
  porId("escena-preguntas").hidden = false;
  porId("escena-preguntar").textContent = "Cerrar preguntas";
  avisar(hayMicrofono() ? "Pulsa «Hablar» y haz la pregunta, o escríbela." : "Escribe la pregunta.");
  if (!estado.aperturaDicha) {
    estado.aperturaDicha = true;
    hablarPana(APERTURA_PREGUNTAS, "");
  }
  porId("escena-pregunta-texto").focus();
}

/**
 * Cierra el paso «Preguntas» y el micrófono.
 *
 * @returns {void}
 */
function cerrarPreguntas() {
  detenerMicrofono();
  estado.preguntas = false;
  estado.pensando = false;
  porId("escena-preguntas").hidden = true;
  porId("escena-preguntar").textContent = "Preguntas (Q)";
  porId("escena-microfono").textContent = "Hablar";
  porId("escena-microfono").setAttribute("aria-pressed", "false");
}

/**
 * Muestra un aviso corto para quien presenta junto al cuadro de la pregunta.
 *
 * @param {string} texto Aviso.
 * @returns {void}
 */
function avisar(texto) {
  porId("escena-pregunta-estado").textContent = texto;
}

/**
 * Abre o cierra el micrófono; al oír la frase, la responde de una vez.
 *
 * @returns {void}
 */
function alternarMicrofono() {
  const boton = porId("escena-microfono");
  if (escuchando()) {
    detenerMicrofono();
    return;
  }
  detenerVoz();
  const empezo = escuchar({
    alResultado: (texto) => {
      porId("escena-pregunta-texto").value = texto;
      contestar(texto);
    },
    alError: avisar,
    alTerminar: () => {
      boton.textContent = "Hablar";
      boton.setAttribute("aria-pressed", "false");
    },
  });
  if (empezo) {
    boton.textContent = "Escuchando… (parar)";
    boton.setAttribute("aria-pressed", "true");
    avisar("Escuchando…");
  }
}

/**
 * Muestra un turno de Pana fuera del guion (apertura o respuesta) y lo dice.
 *
 * @param {object} turno Turno de Pana (ya validado).
 * @param {string} pregunta Pregunta del público que se muestra arriba, o "".
 * @returns {Promise<void>} Se resuelve cuando Pana termina de hablar.
 */
function hablarPana(turno, pregunta) {
  estado.vistos.add("pana");
  iluminar("pana");
  const caja = porId("escena-pregunta");
  caja.hidden = !pregunta;
  caja.textContent = pregunta ? `Pregunta del público: «${pregunta}»` : "";
  porId("escena-quien").replaceChildren(
    crear("span", "escena__quien escena__quien--pana", FICHAS.pana.nombre),
    crear("span", "escena__origen", turno.origen),
  );
  porId("escena-texto").textContent = turno.texto;
  return decir(turno);
}

/**
 * Responde una pregunta del público con la voz de Pana.
 *
 * Mientras espera la respuesta no acepta otra pregunta; mientras Pana habla,
 * una pregunta nueva corta la voz y se responde.
 *
 * @param {string} pregunta Lo que se dijo o escribió.
 * @returns {Promise<void>} Se resuelve cuando Pana termina de responder.
 */
async function contestar(pregunta) {
  const texto = String(pregunta ?? "").trim();
  if (estado.pensando || !texto) {
    return;
  }
  detenerMicrofono();
  detenerVoz();
  estado.pensando = true;
  porId("escena-responder").disabled = true;
  avisar("Pana está pensando…");
  porId("escena-pregunta").hidden = false;
  porId("escena-pregunta").textContent = `Pregunta del público: «${texto}»`;
  porId("escena-texto").textContent = "Pana está pensando…";
  let respuesta;
  try {
    respuesta = await responderPregunta(texto);
  } finally {
    estado.pensando = false;
    porId("escena-responder").disabled = false;
  }
  if (!estado.preguntas) {
    return;
  }
  avisar(respuesta.respaldo ? "El servidor de preguntas no respondió: contestó la ficha de respaldo." : "");
  porId("escena-pregunta-texto").value = "";
  await hablarPana(respuesta.turno, texto);
}

/**
 * Atiende los atajos de teclado de quien presenta.
 *
 * @param {KeyboardEvent} evento Tecla pulsada.
 * @returns {void}
 */
function teclado(evento) {
  if (evento.target instanceof HTMLInputElement || evento.target instanceof HTMLButtonElement) {
    return;
  }
  if (evento.ctrlKey || evento.metaKey || evento.altKey) {
    return;
  }
  const tecla = evento.key.toLowerCase();
  if (tecla === " " || tecla === "arrowright") {
    evento.preventDefault();
    siguiente();
  } else if (tecla === "p") {
    estado.reproduciendo ? pausar() : reproducir();
  } else if (tecla === "s") {
    const casilla = porId("escena-solo-subtitulos");
    casilla.checked = !casilla.checked;
  } else if (tecla === "q") {
    estado.preguntas ? cerrarPreguntas() : abrirPreguntas();
  } else if (tecla === "v") {
    document.dispatchEvent(new CustomEvent("escena:captura"));
  } else if (tecla === "n") {
    cambiarANucleo();
  } else if (tecla === "t") {
    alternarTraza();
  } else if (tecla === "h") {
    document.dispatchEvent(new CustomEvent("escena:herramientas"));
  } else if (tecla === "r") {
    reiniciar();
  }
}

/**
 * Carga la escena que acaba de confirmar el voluntario y la reproduce.
 *
 * La captura (`captura.js`) pide `POST /api/escena` y avisa con
 * `escena:lista`; aquí se reemplazan los turnos, se guarda la escena en la
 * pestaña y se empieza desde la presentación.
 *
 * @param {object} datos Escena de fase 1 que devolvió el servidor.
 * @returns {void}
 */
function cargarEscenaViva(datos) {
  if (!datos || !Array.isArray(datos.turnos) || datos.turnos.length === 0) {
    return;
  }
  const escena = normalizarEscena(datos);
  estado.original = escena.turnos;
  estado.veredictoOriginal = escena.veredicto;
  estado.veredicto = escena.veredicto;
  estado.sellos = escena.sellos;
  estado.modo = "completa";
  estado.turnos = [...estado.introduccion, ...escena.turnos];
  guardarEscena(CLAVE_COMPLETA, escena);
  porId("escena-sello").hidden = true;
  prepararInicio();
  reproducir();
}

/**
 * Arranca la pantalla: carga los turnos y conecta los controles.
 *
 * @returns {Promise<void>} Se resuelve al quedar lista.
 */
async function iniciar() {
  montar();
  const [introduccion, { turnos, veredicto, sellos, fuente }] = await Promise.all([
    cargarIntroduccion(),
    cargarTurnos(),
  ]);
  estado.introduccion = introduccion;
  estado.largoIntroduccion = introduccion.length;
  estado.original = turnos;
  estado.veredictoOriginal = veredicto;
  estado.veredicto = veredicto;
  estado.sellos = sellos;
  estado.turnos = [...introduccion, ...turnos];
  const sello = porId("escena-sello");
  sello.textContent = SELLOS[fuente];
  sello.hidden = !SELLOS[fuente];
  prepararInicio();
  if (turnos.length === 0) {
    porId("escena-texto").textContent = "No hay turnos de la escena: solo la presentación.";
  }
  porId("escena-reproducir").addEventListener("click", () =>
    estado.reproduciendo ? pausar() : reproducir(),
  );
  porId("escena-siguiente").addEventListener("click", siguiente);
  porId("escena-reiniciar").addEventListener("click", reiniciar);
  porId("escena-nucleo").addEventListener("click", cambiarANucleo);
  porId("escena-ver-traza").addEventListener("click", alternarTraza);
  document.addEventListener("escena:nucleo", cambiarANucleo);
  porId("escena-preguntar").addEventListener("click", () =>
    estado.preguntas ? cerrarPreguntas() : abrirPreguntas(),
  );
  porId("escena-form-pregunta").addEventListener("submit", (evento) => {
    evento.preventDefault();
    contestar(porId("escena-pregunta-texto").value);
  });
  porId("escena-pregunta-texto").maxLength = LARGO_MAXIMO;
  const microfono = porId("escena-microfono");
  microfono.hidden = !hayMicrofono();
  microfono.addEventListener("click", alternarMicrofono);
  montarCaptura();
  montarHerramientas();
  document.addEventListener("escena:lista", (evento) => cargarEscenaViva(evento.detail));
  document.addEventListener("keydown", teclado);
}

iniciar();
