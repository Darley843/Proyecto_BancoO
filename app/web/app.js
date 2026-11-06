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

/** Tiempo límite de una petición normal a la API (la Ventanilla puede tardar). */
const ESPERA_MS = 60000;

/** Tiempo límite para detectar si la API está encendida al abrir la app. */
const ESPERA_ESTADO_MS = 2500;

/** Clave de `localStorage` para la preferencia de tema (no guarda preguntas). */
const CLAVE_TEMA = "sucursal-tema";

/**
 * Estado compartido con las vistas. Cada vista recibe este objeto en
 * `render(contenedor, estado)` y usa `estado.pedir` para obtener datos.
 */
const estado = {
  /** "api" cuando el servidor responde; "ejemplo" cuando se usa la maqueta. */
  modo: "ejemplo",
  /** Última respuesta de `/api/estado` (o de `estado.json`). */
  resumen: null,
  pedir,
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
