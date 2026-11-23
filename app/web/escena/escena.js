/**
 * Sucursal 1965 · pantalla de la escena «Pana vs. el gota a gota» (`/escena.html`).
 *
 * Lee los turnos del contrato (`contrato.js`) y los reproduce uno por uno: el
 * personaje que habla se ilumina, su texto sale en subtítulos grandes y su voz
 * suena con `voz.js` (Piper o la del navegador). El panel de la derecha muestra
 * el escenario, el semáforo, las cifras con su fuente y los hallazgos del
 * auditor.
 *
 * Los turnos salen de `GET /api/escena/turnos` cuando exista el orquestador; si
 * no responde, se usan los de `escena/turnos-ejemplo.json` y la pantalla lo
 * dice. Un turno que no cumple el contrato no se dice: se muestra el error.
 *
 * Teclado: Espacio o → pasa al siguiente turno, P reproduce o pausa, S activa
 * el modo solo subtítulos y R vuelve al inicio.
 */

import { decirComo, detenerVoz } from "../voz.js";
import {
  PASOS,
  PERSONAJES,
  erroresDelTurno,
  formatearCifra,
  pasoDelTurno,
} from "./contrato.js";
import { retrato } from "./rostros.js";

/** Nombre visible de cada personaje (el color sale de la hoja de estilos). */
const FICHAS = Object.freeze({
  pana: { nombre: "Pana" },
  don_gota: { nombre: "Don Gota" },
  joven: { nombre: "Joven (voluntario)" },
  agente_joven: { nombre: "Agente del joven" },
  agente_banco: { nombre: "Agente del banco" },
  auditor: { nombre: "Auditor" },
});

/** Ruta del orquestador (cuando exista) y de los turnos de ejemplo. */
const RUTA_TURNOS = "/api/escena/turnos";
const RUTA_EJEMPLO = "escena/turnos-ejemplo.json";

/** Pausa después de cada turno, y lectura mínima cuando no hay voz. */
const PAUSA_ENTRE_TURNOS_MS = 600;
const MS_POR_LETRA = 55;
const LECTURA_MINIMA_MS = 1800;

/** Estado de la reproducción. */
const estado = {
  turnos: [],
  indice: -1,
  paso: -1,
  reproduciendo: false,
  cifras: new Map(),
  vistos: new Set(),
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
 * Arma el escenario (seis personajes) y la barra de pasos.
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
 * Pide los turnos al orquestador o, si no responde, usa los de ejemplo.
 *
 * @returns {Promise<{turnos: object[], ejemplo: boolean}>} Turnos y si son de ejemplo.
 */
async function cargarTurnos() {
  for (const [ruta, ejemplo] of [
    [RUTA_TURNOS, false],
    [RUTA_EJEMPLO, true],
  ]) {
    try {
      const respuesta = await fetch(ruta, { signal: AbortSignal.timeout(8000) });
      if (respuesta.ok) {
        const datos = await respuesta.json();
        if (Array.isArray(datos?.turnos)) {
          return { turnos: datos.turnos, ejemplo };
        }
      }
    } catch {
      // Sigue con la siguiente fuente.
    }
  }
  return { turnos: [], ejemplo: true };
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
  estado.paso = pasoDelTurno(turno, estado.paso);
  estado.vistos.add(turno.personaje);
  for (const cifra of turno.cifras) {
    estado.cifras.set(cifra.nombre, cifra);
  }
  for (const personaje of PERSONAJES) {
    const caja = porId(`personaje-${personaje}`);
    caja.classList.toggle("escena__personaje--habla", personaje === turno.personaje);
    caja.classList.toggle("escena__personaje--visto", estado.vistos.has(personaje));
  }
  PASOS.forEach((_, posicion) => {
    const paso = porId(`paso-${posicion}`);
    paso.classList.toggle("escena__paso--activo", posicion === estado.paso);
    paso.classList.toggle("escena__paso--hecho", posicion < estado.paso);
  });
  quien.replaceChildren(
    crear("span", `escena__quien escena__quien--${turno.personaje}`, FICHAS[turno.personaje].nombre),
    crear("span", "escena__origen", turno.origen),
  );
  subtitulo.textContent = turno.texto;
  pintarPanel(turno);
  porId("escena-contador").textContent = `Turno ${indice + 1} de ${estado.turnos.length}`;
  return true;
}

/**
 * Pinta el panel de cifras: escenario, semáforo, cifras y hallazgos.
 *
 * @param {object} turno Turno actual (ya validado).
 * @returns {void}
 */
function pintarPanel(turno) {
  const { monto, plazo, semaforo } = turno.escenario;
  const chips = [];
  if (monto) {
    chips.push(formatearCifra({ nombre: "monto", valor: monto }).texto);
  }
  if (plazo) {
    chips.push(`${plazo} meses`);
  }
  porId("escena-escenario").replaceChildren(
    ...(chips.length ? chips : ["Esperando al voluntario"]).map((texto) =>
      crear("span", "escena__chip", texto),
    ),
  );
  const luz = porId("escena-semaforo");
  luz.dataset.color = semaforo || "";
  porId("escena-semaforo-texto").textContent = semaforo
    ? `Semáforo ${semaforo}`
    : "Semáforo sin calcular";

  const filas = [...estado.cifras.values()].map((cifra) => {
    const { etiqueta, texto } = formatearCifra(cifra);
    const fila = crear("tr", `escena__cifra escena__cifra--${grupoDe(cifra.nombre)}`);
    fila.append(crear("th", "", etiqueta), crear("td", "", texto), crear("td", "escena__fuente", cifra.fuente));
    return fila;
  });
  porId("escena-cifras").replaceChildren(...filas);
  porId("escena-sin-cifras").hidden = filas.length > 0;

  const hallazgos = porId("escena-hallazgos");
  hallazgos.replaceChildren(...turno.hallazgos.map((texto) => crear("li", "", texto)));
  porId("escena-caja-hallazgos").hidden = turno.personaje !== "auditor";
  porId("escena-conforme").hidden = turno.hallazgos.length > 0;
}

/**
 * Agrupa una cifra para colorearla: Don Gota, banco o referencia.
 *
 * @param {string} nombre Nombre de la cifra.
 * @returns {"gota" | "banco" | "otra"} Grupo de la cifra.
 */
function grupoDe(nombre) {
  if (nombre.endsWith("_don_gota")) {
    return "gota";
  }
  if (nombre.endsWith("_banco")) {
    return "banco";
  }
  return "otra";
}

/**
 * Dice el turno con la voz de su personaje, o espera lo que tarda leerlo.
 *
 * El joven es la persona voluntaria: habla en persona, así que su turno solo
 * se muestra en subtítulos.
 *
 * @param {object} turno Turno ya mostrado.
 * @returns {Promise<void>} Se resuelve cuando termina de sonar.
 */
function decir(turno) {
  const soloSubtitulos = porId("escena-solo-subtitulos").checked || turno.personaje === "joven";
  const caja = porId(`personaje-${turno.personaje}`);
  caja.classList.toggle("escena__personaje--mudo", soloSubtitulos);
  return new Promise((listo) => {
    if (soloSubtitulos) {
      window.setTimeout(listo, Math.max(LECTURA_MINIMA_MS, turno.texto.length * MS_POR_LETRA));
      return;
    }
    decirComo(turno.personaje, turno.texto, { alTerminar: listo }).then((voz) => {
      porId("escena-voz").textContent = voz === "piper" ? "Voz: Piper" : voz === "navegador" ? "Voz: navegador" : "";
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
 * Vuelve al principio de la escena.
 *
 * @returns {void}
 */
function reiniciar() {
  pausar();
  estado.indice = -1;
  estado.paso = -1;
  estado.cifras.clear();
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
  const tecla = evento.key.toLowerCase();
  if (tecla === " " || tecla === "arrowright") {
    evento.preventDefault();
    siguiente();
  } else if (tecla === "p") {
    estado.reproduciendo ? pausar() : reproducir();
  } else if (tecla === "s") {
    const casilla = porId("escena-solo-subtitulos");
    casilla.checked = !casilla.checked;
  } else if (tecla === "r") {
    reiniciar();
  }
}

/**
 * Arranca la pantalla: carga los turnos y conecta los controles.
 *
 * @returns {Promise<void>} Se resuelve al quedar lista.
 */
async function iniciar() {
  montar();
  const { turnos, ejemplo } = await cargarTurnos();
  estado.turnos = turnos;
  porId("escena-sello").hidden = !ejemplo;
  reiniciar();
  if (turnos.length === 0) {
    porId("escena-texto").textContent = "No hay turnos para mostrar.";
  }
  porId("escena-reproducir").addEventListener("click", () =>
    estado.reproduciendo ? pausar() : reproducir(),
  );
  porId("escena-siguiente").addEventListener("click", siguiente);
  porId("escena-reiniciar").addEventListener("click", reiniciar);
  document.addEventListener("keydown", teclado);
}

iniciar();
