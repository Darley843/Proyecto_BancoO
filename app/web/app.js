/**
 * Sucursal 1965 · armazón de la app web.
 *
 * Responsabilidades (OpenSpec sucursal-1965, decisión 15):
 * - enrutar entre las seis vistas de la sucursal con el hash de la URL;
 * - decidir si los datos salen de la API local o de `datos-ejemplo/`;
 * - pintar el encabezado común: saldo del día, sello de modo y tema.
 *
 * No contiene reglas de negocio: no decide rutas, costos ni validaciones.
 * Solo llama a la API y formatea lo que esta devuelve.
 */

import { crearTexto, formatearUsd } from "./comun.js";

/** Vistas de la sucursal, en el orden de la navegación. */
const VISTAS = ["vestibulo", "ventanilla", "boveda", "tablero", "camara", "arqueo"];

/** Vista que se abre cuando la URL no indica ninguna. */
const VISTA_INICIAL = "vestibulo";

/**
 * Endpoint de la API que corresponde a cada archivo de `datos-ejemplo/`.
 * El nombre del archivo es la clave; la forma del JSON es la del contrato.
 */
const ENDPOINTS = {
  estado: "/api/estado",
  preguntar: "/api/preguntar",
  tablero: "/api/tablero",
  mapa: "/api/boveda/mapa",
  pipeline: "/api/pipeline",
  arqueo: "/api/arqueo",
  vestibulo: "/api/vestibulo",
};

/**
 * Endpoints con streaming (eventos SSE). La clave es la del recurso normal en
 * `ENDPOINTS`; el evento `final` trae el mismo contrato que esa ruta.
 */
const ENDPOINTS_STREAM = {
  preguntar: "/api/preguntar/stream",
};

/** Milisegundos sin recibir nada del streaming antes de abandonar la petición. */
const ESPERA_STREAM_MS = 60000;

/** Mensaje cuando la conexión se corta antes del evento final. */
const MENSAJE_CORTE =
  "Se perdió la conexión con la sucursal antes de terminar el turno.";

/** Tiempo límite de una petición normal a la API (la Ventanilla puede tardar). */
const ESPERA_MS = 60000;

/** Tiempo límite para detectar si la API está encendida al abrir la app. */
const ESPERA_ESTADO_MS = 2500;

/** Clave de `localStorage` para la preferencia de tema (no guarda preguntas). */
const CLAVE_TEMA = "sucursal-tema";

/**
 * Estado compartido con las vistas. Cada vista recibe este objeto en
 * `render(contenedor, estado)` y usa `estado.pedir` para obtener datos, o
 * `estado.pedirEnVivo` para recibir el avance de un turno por streaming.
 */
const estado = {
  /** "api" cuando el servidor responde; "ejemplo" cuando se usa la maqueta. */
  modo: "ejemplo",
  /** Última respuesta de `/api/estado` (o de `estado.json`). */
  resumen: null,
  pedir,
  pedirEnVivo,
  refrescarEstado,
  formatearUsd,
};

/**
 * Pide datos a la API o, en modo de ejemplo, al archivo local equivalente.
 *
 * @param {keyof ENDPOINTS} nombre Nombre del recurso: `tablero`, `mapa`, `preguntar`…
 * @param {{consulta?: Record<string, string>, cuerpo?: object}} [opciones]
 *   `consulta` se envía como parámetros de la URL; `cuerpo` convierte la
 *   petición en un POST con JSON.
 * @returns {Promise<any>} El JSON de la respuesta.
 * @throws {Error} Con el mensaje del contrato `{"error": {"mensaje"}}` si la API falla.
 */
async function pedir(nombre, opciones = {}) {
  if (!(nombre in ENDPOINTS)) {
    throw new Error(`Recurso desconocido: ${nombre}`);
  }
  if (estado.modo === "ejemplo") {
    return leerJson(`datos-ejemplo/${nombre}.json`);
  }

  const url = new URL(ENDPOINTS[nombre], window.location.origin);
  for (const [clave, valor] of Object.entries(opciones.consulta ?? {})) {
    url.searchParams.set(clave, valor);
  }
  const init = opciones.cuerpo
    ? {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(opciones.cuerpo),
      }
    : {};
  return leerJson(url, init);
}

/**
 * Pide un recurso con streaming (SSE) y avisa cada etapa mientras llega.
 *
 * Solo `preguntar` tiene streaming (`POST /api/preguntar/stream`). En modo de
 * ejemplo, o si el servidor no conoce la ruta (404 o 405, un backend
 * anterior), usa `pedir`, que devuelve el mismo contrato sin etapas. El tiempo
 * límite cuenta desde el último dato recibido, no desde el inicio: un turno
 * largo que sigue avanzando no se corta.
 *
 * @param {keyof ENDPOINTS_STREAM} nombre Recurso con streaming: `preguntar`.
 * @param {{cuerpo: object}} opciones Cuerpo JSON del POST.
 * @param {(etapa: object) => void} [alAvanzar] Recibe cada evento `etapa`.
 * @returns {Promise<any>} El cuerpo del evento `final`.
 * @throws {Error} Con el mensaje del contrato, de corte o de tiempo agotado.
 */
async function pedirEnVivo(nombre, opciones, alAvanzar = () => {}) {
  if (estado.modo === "ejemplo" || !(nombre in ENDPOINTS_STREAM)) {
    return pedir(nombre, opciones);
  }
  const controlador = new AbortController();
  let espera = 0;
  const reiniciarEspera = () => {
    window.clearTimeout(espera);
    espera = window.setTimeout(() => controlador.abort(), ESPERA_STREAM_MS);
  };
  reiniciarEspera();
  try {
    let respuesta;
    try {
      respuesta = await fetch(new URL(ENDPOINTS_STREAM[nombre], window.location.origin), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify(opciones.cuerpo),
        signal: controlador.signal,
      });
    } catch (error) {
      if (error?.name === "AbortError") {
        throw error;
      }
      throw new Error(MENSAJE_CORTE);
    }
    if (respuesta.status === 404 || respuesta.status === 405) {
      window.clearTimeout(espera);
      return pedir(nombre, opciones);
    }
    const tipo = respuesta.headers.get("Content-Type") ?? "";
    if (!respuesta.ok || !tipo.includes("text/event-stream")) {
      throw await errorDeRespuesta(respuesta);
    }
    return await leerEventos(respuesta, alAvanzar, reiniciarEspera);
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(
        `La sucursal dejó de responder durante ${ESPERA_STREAM_MS / 1000} s. Intenta de nuevo.`,
      );
    }
    throw error;
  } finally {
    window.clearTimeout(espera);
  }
}

/**
 * Lee los eventos SSE de la respuesta hasta el evento `final`.
 *
 * @param {Response} respuesta Respuesta `text/event-stream` de la API.
 * @param {(etapa: object) => void} alAvanzar Recibe cada evento `etapa`.
 * @param {() => void} alRecibir Se llama con cada trozo, para el tiempo límite.
 * @returns {Promise<object>} El cuerpo del evento `final`.
 * @throws {Error} Si llega un evento `error` o el flujo se corta antes del final.
 */
async function leerEventos(respuesta, alAvanzar, alRecibir) {
  if (!respuesta.body || typeof respuesta.body.getReader !== "function") {
    return procesarBloques(await respuesta.text(), alAvanzar).final;
  }
  const lector = respuesta.body.getReader();
  const decodificador = new TextDecoder("utf-8");
  let pendiente = "";
  for (;;) {
    let lectura;
    try {
      lectura = await lector.read();
    } catch (error) {
      if (error?.name === "AbortError") {
        throw error;
      }
      throw new Error(MENSAJE_CORTE);
    }
    if (lectura.done) {
      break;
    }
    alRecibir();
    pendiente += decodificador.decode(lectura.value, { stream: true });
    const corte = pendiente.lastIndexOf("\n\n");
    if (corte === -1) {
      continue;
    }
    const completos = pendiente.slice(0, corte + 2);
    pendiente = pendiente.slice(corte + 2);
    const { final } = procesarBloques(completos, alAvanzar);
    if (final) {
      lector.cancel().catch(() => {});
      return final;
    }
  }
  return procesarBloques(pendiente, alAvanzar).final;
}

/**
 * Interpreta bloques SSE completos y reparte las etapas.
 *
 * @param {string} texto Uno o varios bloques separados por línea en blanco.
 * @param {(etapa: object) => void} alAvanzar Recibe cada evento `etapa`.
 * @returns {{final: object | null}} El cuerpo del evento `final`, si llegó.
 * @throws {Error} Si llega un evento `error` o si el texto termina sin `final`
 *   cuando ya no quedan datos por leer.
 */
function procesarBloques(texto, alAvanzar) {
  const bloques = texto.replace(/\r\n/g, "\n").split("\n\n");
  for (const bloque of bloques) {
    const evento = interpretarEvento(bloque);
    if (!evento) {
      continue;
    }
    if (evento.tipo === "etapa") {
      alAvanzar(evento.datos);
    } else if (evento.tipo === "final") {
      return { final: evento.datos };
    } else if (evento.tipo === "error") {
      throw new Error(
        evento.datos?.error?.mensaje ?? "La sucursal informó un error.",
      );
    }
  }
  return { final: null };
}

/**
 * Convierte un bloque SSE (`event:` y `data:`) en un objeto.
 *
 * @param {string} bloque Texto de un evento, sin la línea en blanco final.
 * @returns {{tipo: string, datos: any} | null} El evento, o `null` si está
 *   vacío o su JSON no es válido.
 */
function interpretarEvento(bloque) {
  let tipo = "message";
  const datos = [];
  for (const linea of bloque.split("\n")) {
    if (linea.startsWith("event:")) {
      tipo = linea.slice(6).trim();
    } else if (linea.startsWith("data:")) {
      datos.push(linea.slice(5).trimStart());
    }
  }
  if (datos.length === 0) {
    return null;
  }
  try {
    return { tipo, datos: JSON.parse(datos.join("\n")) };
  } catch {
    return null;
  }
}

/**
 * Convierte una respuesta HTTP fallida en un error con el mensaje del contrato.
 *
 * @param {Response} respuesta Respuesta que no es un streaming válido.
 * @returns {Promise<Error>} El error listo para lanzar.
 */
async function errorDeRespuesta(respuesta) {
  try {
    const datos = await respuesta.json();
    return new Error(datos?.error?.mensaje ?? `HTTP ${respuesta.status}`);
  } catch {
    return new Error(`HTTP ${respuesta.status}`);
  }
}

/**
 * Descarga un JSON con tiempo límite y traduce los errores HTTP al mensaje
 * del contrato.
 *
 * @param {string | URL} url Dirección del recurso.
 * @param {RequestInit} [init] Opciones de `fetch`.
 * @param {number} [esperaMs] Milisegundos antes de abandonar la petición.
 * @returns {Promise<any>} El JSON ya interpretado.
 * @throws {Error} Si la respuesta no es 2xx, no es JSON o se agota el tiempo.
 */
async function leerJson(url, init = {}, esperaMs = ESPERA_MS) {
  const controlador = new AbortController();
  const espera = setTimeout(() => controlador.abort(), esperaMs);
  let respuesta;
  try {
    respuesta = await fetch(url, { ...init, signal: controlador.signal });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error(`La sucursal no respondió en ${esperaMs / 1000} s. Intenta de nuevo.`);
    }
    throw error;
  } finally {
    clearTimeout(espera);
  }
  let datos = null;
  try {
    datos = await respuesta.json();
  } catch {
    throw new Error(`La respuesta de ${url} no es JSON (HTTP ${respuesta.status}).`);
  }
  if (!respuesta.ok) {
    const mensaje = datos?.error?.mensaje ?? `HTTP ${respuesta.status}`;
    throw new Error(mensaje);
  }
  return datos;
}

/**
 * Decide el modo de datos. Con `?ejemplo=1` en la URL se fuerza la maqueta;
 * si no, se prueba `/api/estado` y, si no responde, se usa la maqueta.
 *
 * @returns {Promise<"api" | "ejemplo">} El modo elegido.
 */
async function decidirModo() {
  const parametros = new URLSearchParams(window.location.search);
  if (parametros.get("ejemplo") === "1") {
    return "ejemplo";
  }
  try {
    estado.resumen = await leerJson(ENDPOINTS.estado, {}, ESPERA_ESTADO_MS);
    return "api";
  } catch {
    return "ejemplo";
  }
}

/**
 * Pinta en el encabezado el gasto del día frente al tope y el sello de modo.
 *
 * @param {{gasto_hoy_usd: number, tope_usd: number, modo_demo: boolean}} resumen
 *   Respuesta de `/api/estado`.
 * @returns {void}
 */
function pintarEncabezado(resumen) {
  const cifra = document.getElementById("saldo-cifra");
  const relleno = document.getElementById("saldo-relleno");
  const saldo = document.getElementById("saldo");
  const sello = document.getElementById("sello-modo");

  const gasto = Number(resumen?.gasto_hoy_usd ?? 0);
  const tope = Number(resumen?.tope_usd ?? 0);
  const proporcion = tope > 0 ? Math.min(gasto / tope, 1) : 0;

  cifra.textContent = `${formatearUsd(gasto)} de ${formatearUsd(tope)}`;
  relleno.style.width = `${Math.round(proporcion * 100)}%`;
  saldo.dataset.alerta = String(proporcion >= 0.8);
  saldo.title = `Gasto en DeepSeek hoy: ${Math.round(proporcion * 100)} % del tope diario`;

  const enMaqueta = estado.modo === "ejemplo";
  sello.hidden = !(enMaqueta || resumen?.modo_demo);
  sello.textContent = enMaqueta ? "Datos de ejemplo" : "Modo demo";
}

/**
 * Vuelve a leer `/api/estado` y repinta el saldo del día en el encabezado.
 *
 * La Ventanilla la llama después de cada turno respondido. Si la petición
 * falla, conserva el último resumen y no interrumpe la conversación.
 *
 * @returns {Promise<object | null>} El resumen actualizado o el último válido.
 */
async function refrescarEstado() {
  try {
    estado.resumen =
      estado.modo === "ejemplo"
        ? await pedir("estado")
        : await leerJson(ENDPOINTS.estado, { cache: "no-store" });
    pintarEncabezado(estado.resumen);
  } catch {
    // El saldo es informativo: se conserva el último resumen disponible.
  }
  return estado.resumen;
}

/**
 * Dibuja el guilloché del encabezado: curvas de espirógrafo en SVG, como las
 * de los billetes y cheques. Es solo decoración y no depende de datos.
 *
 * @param {HTMLElement} contenedor Elemento donde se inserta el SVG.
 * @returns {void}
 */
function dibujarGuilloche(contenedor) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 1200 160");
  svg.setAttribute("preserveAspectRatio", "xMidYMid slice");

  const curvas = [
    { R: 70, r: 23, d: 48, cx: 140, color: "#e0bd5c" },
    { R: 90, r: 31, d: 60, cx: 1060, color: "#e0bd5c" },
    { R: 60, r: 17, d: 40, cx: 600, color: "#ffffff" },
  ];
  for (const { R, r, d, cx, color } of curvas) {
    const camino = document.createElementNS(ns, "path");
    camino.setAttribute("d", trazarEspirografo(R, r, d, cx, 80));
    camino.setAttribute("fill", "none");
    camino.setAttribute("stroke", color);
    camino.setAttribute("stroke-width", "0.6");
    svg.appendChild(camino);
  }
  contenedor.replaceChildren(svg);
}

/**
 * Calcula el trazo de un hipotrocoide (la curva de un espirógrafo).
 *
 * @param {number} R Radio del círculo fijo.
 * @param {number} r Radio del círculo que gira por dentro.
 * @param {number} d Distancia del lápiz al centro del círculo que gira.
 * @param {number} cx Centro horizontal.
 * @param {number} cy Centro vertical.
 * @returns {string} Atributo `d` de un `<path>` SVG.
 */
function trazarEspirografo(R, r, d, cx, cy) {
  const vueltas = r / mcd(R, r);
  const pasos = 720 * vueltas;
  const puntos = [];
  for (let i = 0; i <= pasos; i += 1) {
    const t = (i / 720) * 2 * Math.PI;
    const x = (R - r) * Math.cos(t) + d * Math.cos(((R - r) / r) * t);
    const y = (R - r) * Math.sin(t) - d * Math.sin(((R - r) / r) * t);
    puntos.push(`${(cx + x).toFixed(1)},${(cy + y).toFixed(1)}`);
  }
  return `M${puntos.join("L")}`;
}

/**
 * Máximo común divisor, para saber cuántas vueltas cierran la curva.
 *
 * @param {number} a Primer entero positivo.
 * @param {number} b Segundo entero positivo.
 * @returns {number} El máximo común divisor.
 */
function mcd(a, b) {
  return b === 0 ? a : mcd(b, a % b);
}

/**
 * Aplica el tema guardado (claro u oscuro) o deja el del sistema.
 *
 * @returns {void}
 */
function aplicarTemaGuardado() {
  try {
    const tema = window.localStorage.getItem(CLAVE_TEMA);
    if (tema === "claro" || tema === "oscuro") {
      document.documentElement.dataset.tema = tema;
    }
  } catch {
    // Sin almacenamiento disponible: se usa el tema del sistema.
  }
}

/**
 * Alterna entre tema claro y oscuro y recuerda la elección.
 *
 * @returns {void}
 */
function alternarTema() {
  const actual =
    document.documentElement.dataset.tema ??
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro");
  const nuevo = actual === "oscuro" ? "claro" : "oscuro";
  document.documentElement.dataset.tema = nuevo;
  try {
    window.localStorage.setItem(CLAVE_TEMA, nuevo);
  } catch {
    // Si no se puede guardar, el cambio dura solo esta visita.
  }
}

/**
 * Lee la vista pedida en el hash de la URL (`#boveda`).
 *
 * @returns {string} Nombre de una vista válida.
 */
function vistaDesdeHash() {
  const nombre = window.location.hash.replace("#", "");
  return VISTAS.includes(nombre) ? nombre : VISTA_INICIAL;
}

/**
 * Muestra una vista: oculta las demás, marca el enlace activo y carga el
 * módulo `vistas/<nombre>.js`, que pinta su contenido con `render`.
 *
 * @param {string} nombre Nombre de la vista.
 * @returns {Promise<void>}
 */
async function mostrarVista(nombre) {
  for (const seccion of document.querySelectorAll(".vista")) {
    seccion.hidden = seccion.dataset.vista !== nombre;
  }
  for (const enlace of document.querySelectorAll(".navegacion a")) {
    if (enlace.dataset.vista === nombre) {
      enlace.setAttribute("aria-current", "page");
    } else {
      enlace.removeAttribute("aria-current");
    }
  }

  const contenedor = document.getElementById(`vista-${nombre}`);
  contenedor.replaceChildren(crearTexto("p", "Cargando…", "cargando"));
  try {
    const modulo = await import(`./vistas/${nombre}.js`);
    await modulo.render(contenedor, estado);
  } catch (error) {
    const aviso = crearTexto("p", `No se pudo abrir esta vista: ${error.message}`, "aviso aviso--error");
    contenedor.replaceChildren(aviso);
  }
}

/**
 * Arranca la app: tema, guilloché, modo de datos, encabezado y primera vista.
 *
 * @returns {Promise<void>}
 */
async function iniciar() {
  aplicarTemaGuardado();
  dibujarGuilloche(document.getElementById("guilloche"));
  document.getElementById("boton-tema").addEventListener("click", alternarTema);

  estado.modo = await decidirModo();
  if (estado.modo === "ejemplo") {
    estado.resumen = await pedir("estado").catch(() => null);
  }
  pintarEncabezado(estado.resumen);

  window.addEventListener("hashchange", () => mostrarVista(vistaDesdeHash()));
  await mostrarVista(vistaDesdeHash());
}

/**
 * Muestra en la página un error que impidió arrancar la sucursal, para que no
 * quede solo en la consola del navegador.
 *
 * @param {Error} error Error recibido al arrancar.
 * @returns {void}
 */
function avisarErrorDeArranque(error) {
  const aviso = crearTexto("p", `La sucursal no pudo arrancar: ${error?.message ?? error}`, "aviso aviso--error");
  aviso.setAttribute("role", "alert");
  document.getElementById("contenido")?.replaceChildren(aviso);
}

iniciar().catch(avisarErrorDeArranque);
