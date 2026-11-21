/**
 * Sucursal 1965 · probador de voces de la escena (`/voces.html`).
 *
 * Muestra a cada personaje con su motor (Piper o voz del navegador), la lista
 * de voces en español de este computador, y deslizadores de tono y velocidad.
 * «Escuchar» prueba la elección y abajo se arman las líneas para
 * `config/voz.toml`. No guarda nada: lo elegido vive solo en la página.
 */

import {
  PERSONAJES,
  configuracionDe,
  decirConElNavegador,
  detenerVoz,
  hayVozDelNavegador,
  pedirConfiguracion,
  vocesEspanolas,
} from "./voz.js";

/** Nombre visible y frase de prueba de cada personaje (todo inventado). */
const DATOS = Object.freeze({
  pana: { nombre: "Pana", frase: "¡Hola! Soy Pana. Hoy la escena la hacemos los agentes." },
  don_gota: { nombre: "Don Gota", frase: "Tranquilo, parcero, yo le presto ya, sin papeles. Solo el veinte por ciento al mes." },
  joven: { nombre: "Joven (voluntario)", frase: "Necesito plata para un computador y no sé si me alcanza la cuota." },
  agente_joven: { nombre: "Agente del joven", frase: "Mi cliente puede pagar hasta doscientos mil al mes." },
  agente_banco: { nombre: "Agente del banco", frase: "A seis meses la cuota cabe en su capacidad, con tasa publicada." },
  auditor: { nombre: "Auditor", frase: "Revisé las cifras: la cuota coincide con el simulador. Semáforo verde." },
});

/** Elección actual de cada personaje. */
const eleccion = {};

/** Si cada personaje tiene Piper listo en este computador. */
const piperListo = {};

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
 * Crea un deslizador con su etiqueta y su valor visible.
 *
 * @param {string} id Id del control.
 * @param {string} rotulo Texto de la etiqueta.
 * @param {number} valor Valor inicial.
 * @param {number} minimo Valor mínimo.
 * @param {number} maximo Valor máximo.
 * @param {(valor: number) => void} alCambiar Se llama con el nuevo valor.
 * @returns {HTMLElement} El bloque con etiqueta y control.
 */
function deslizador(id, rotulo, valor, minimo, maximo, alCambiar) {
  const bloque = crear("label", "probador__campo");
  bloque.htmlFor = id;
  const titulo = crear("span", "", rotulo + ": ");
  const cifra = crear("strong", "", valor.toFixed(2));
  titulo.append(cifra);
  const control = crear("input");
  control.type = "range";
  control.id = id;
  control.min = String(minimo);
  control.max = String(maximo);
  control.step = "0.05";
  control.value = String(valor);
  control.addEventListener("input", () => {
    const numero = Number(control.value);
    cifra.textContent = numero.toFixed(2);
    alCambiar(numero);
  });
  bloque.append(titulo, control);
  return bloque;
}

/**
 * Llena un selector con las voces en español del navegador.
 *
 * @param {HTMLSelectElement} selector Selector a llenar.
 * @param {string} elegida Parte del nombre de la voz elegida.
 * @returns {void}
 */
function llenarVoces(selector, elegida) {
  const opciones = [crear("option", "", "Automática (la primera en español)")];
  opciones[0].value = "";
  for (const voz of vocesEspanolas()) {
    const opcion = crear("option", "", `${voz.nombre} (${voz.idioma})`);
    opcion.value = voz.nombre;
    opcion.selected = Boolean(elegida) && voz.nombre.toLowerCase().includes(elegida.toLowerCase());
    opciones.push(opcion);
  }
  selector.replaceChildren(...opciones);
}

/**
 * Arma la tarjeta de un personaje.
 *
 * @param {string} personaje Personaje de la escena.
 * @returns {HTMLElement} La tarjeta.
 */
function tarjeta(personaje) {
  const actual = eleccion[personaje];
  const caja = crear("article", "probador__tarjeta");
  caja.append(crear("h2", "", DATOS[personaje].nombre));

  const motor = crear("label", "probador__campo");
  motor.htmlFor = `motor-${personaje}`;
  motor.append(crear("span", "", "Motor"));
  const selectorMotor = crear("select");
  selectorMotor.id = `motor-${personaje}`;
  for (const [valor, texto] of [
    ["piper", piperListo[personaje] ? "Piper (listo)" : "Piper (falta make voz-modelo)"],
    ["navegador", "Voz del navegador"],
  ]) {
    const opcion = crear("option", "", texto);
    opcion.value = valor;
    opcion.selected = actual.motor === valor;
    selectorMotor.append(opcion);
  }
  selectorMotor.addEventListener("change", () => {
    actual.motor = selectorMotor.value;
    actualizarToml();
  });
  motor.append(selectorMotor);

  const voz = crear("label", "probador__campo");
  voz.htmlFor = `voz-${personaje}`;
  voz.append(crear("span", "", "Voz del navegador (también es el respaldo de Piper)"));
  const selectorVoz = crear("select", "probador__voces");
  selectorVoz.id = `voz-${personaje}`;
  selectorVoz.dataset.personaje = personaje;
  llenarVoces(selectorVoz, actual.navegador.voz);
  selectorVoz.addEventListener("change", () => {
    actual.navegador.voz = selectorVoz.value;
    actualizarToml();
  });
  voz.append(selectorVoz);

  const frase = crear("label", "probador__campo");
  frase.htmlFor = `frase-${personaje}`;
  frase.append(crear("span", "", "Frase de prueba"));
  const entrada = crear("input");
  entrada.id = `frase-${personaje}`;
  entrada.value = DATOS[personaje].frase;
  frase.append(entrada);

  const escuchar = crear("button", "", "Escuchar");
  escuchar.type = "button";
  escuchar.addEventListener("click", () => probar(personaje, entrada.value));

  caja.append(
    motor,
    voz,
    deslizador(`tono-${personaje}`, "Tono del navegador", actual.navegador.tono, 0, 2, (n) => {
      actual.navegador.tono = n;
      actualizarToml();
    }),
    deslizador(`velocidad-${personaje}`, "Velocidad del navegador", actual.navegador.velocidad, 0.5, 2, (n) => {
      actual.navegador.velocidad = n;
      actualizarToml();
    }),
    frase,
    escuchar,
  );
  return caja;
}

/**
 * Pide a la API el audio de Piper de un personaje.
 *
 * @param {string} personaje Personaje que habla.
 * @param {string} texto Texto a leer.
 * @returns {Promise<Blob | null>} El audio, o `null` si no hay Piper.
 */
async function audioDePiper(personaje, texto) {
  try {
    const respuesta = await fetch("/api/voz", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto, personaje }),
    });
    return respuesta.ok ? await respuesta.blob() : null;
  } catch {
    return null;
  }
}

/** Audio de Piper que suena ahora en el probador. */
let reproductor = null;

/**
 * Prueba la voz elegida de un personaje.
 *
 * @param {string} personaje Personaje que habla.
 * @param {string} texto Texto a leer.
 * @returns {Promise<void>} Se resuelve al terminar de sonar.
 */
async function probar(personaje, texto) {
  detener();
  const actual = eleccion[personaje];
  const aviso = porId("aviso-voces");
  if (actual.motor === "piper") {
    const audio = await audioDePiper(personaje, texto);
    if (audio) {
      const url = URL.createObjectURL(audio);
      reproductor = new window.Audio(url);
      await new Promise((listo) => {
        reproductor.onended = listo;
        reproductor.onerror = listo;
        reproductor.play().catch(listo);
      });
      URL.revokeObjectURL(url);
      return;
    }
    aviso.textContent = `${DATOS[personaje].nombre}: Piper no respondió (¿falta make voz-modelo o config/voz.toml dice motor "navegador"?). Sonó la voz del navegador.`;
  }
  await new Promise((listo) => {
    if (!decirConElNavegador(texto, actual.navegador, personaje, listo)) {
      listo();
    }
  });
}

/**
 * Detiene lo que esté sonando.
 *
 * @returns {void}
 */
function detener() {
  if (reproductor) {
    reproductor.pause();
    reproductor = null;
  }
  detenerVoz();
}

/**
 * Escribe las líneas de `config/voz.toml` con la elección actual.
 *
 * @returns {void}
 */
function actualizarToml() {
  const bloques = PERSONAJES.map((personaje) => {
    const actual = eleccion[personaje];
    return [
      `[personajes.${personaje}]`,
      `motor = "${actual.motor}"`,
      `navegador = "${actual.navegador.voz.replaceAll('"', "")}"`,
      `tono_navegador = ${actual.navegador.tono.toFixed(2)}`,
      `velocidad_navegador = ${actual.navegador.velocidad.toFixed(2)}`,
    ].join("\n");
  });
  porId("toml").value = bloques.join("\n\n");
}

/**
 * Copia las líneas del TOML al portapapeles, o las selecciona si no se puede.
 *
 * @returns {Promise<void>} Se resuelve al terminar.
 */
async function copiar() {
  const area = porId("toml");
  try {
    await navigator.clipboard.writeText(area.value);
    porId("copiado").textContent = "Copiadas.";
  } catch {
    area.select();
    porId("copiado").textContent = "Selecciona y copia con Ctrl + C.";
  }
}

/**
 * Vuelve a llenar los selectores cuando el navegador termina de cargar voces.
 *
 * @returns {void}
 */
function refrescarVoces() {
  for (const selector of document.querySelectorAll(".probador__voces")) {
    llenarVoces(selector, eleccion[selector.dataset.personaje].navegador.voz);
  }
  const cuantas = vocesEspanolas().length;
  porId("aviso-voces").textContent = hayVozDelNavegador()
    ? `Este navegador tiene ${cuantas} voces en español.`
    : "Este navegador no tiene voces: solo sirve Piper.";
}

/**
 * Arranca el probador: lee la configuración y arma las tarjetas.
 *
 * @returns {Promise<void>} Se resuelve al terminar.
 */
async function iniciar() {
  const desdeApi = await pedirConfiguracion();
  for (const personaje of PERSONAJES) {
    const ajuste = await configuracionDe(personaje);
    piperListo[personaje] = Boolean(desdeApi?.[personaje]?.piper);
    eleccion[personaje] = {
      motor: ajuste.motor,
      navegador: { voz: "", tono: 1, velocidad: 1, ...ajuste.navegador },
    };
  }
  porId("lista").replaceChildren(...PERSONAJES.map(tarjeta));
  actualizarToml();
  refrescarVoces();
  if (hayVozDelNavegador()) {
    window.speechSynthesis.addEventListener("voiceschanged", refrescarVoces);
  }
  porId("detener").addEventListener("click", detener);
  porId("copiar").addEventListener("click", copiar);
  porId("escuchar-todos").addEventListener("click", async () => {
    for (const personaje of PERSONAJES) {
      await probar(personaje, porId(`frase-${personaje}`).value);
    }
  });
}

iniciar();
