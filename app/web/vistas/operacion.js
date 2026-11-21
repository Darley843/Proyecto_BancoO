/**
 * Vista Operación · responsable: Yoldy (OpenSpec corresponsal-whatsapp, 8.8).
 *
 * Tablero de solo lectura del canal de WhatsApp con `GET /api/operacion`:
 * estado y modo de envío, cola y deduplicación de mensajes, consentimientos,
 * casos del asesor (HITL), latencia p50/p95 por flujo con la caché aparte y
 * el resumen de Roba la Bóveda.
 *
 * Reglas de la vista (spec sucursal-frontend, «Tablero de operación»):
 * - nunca muestra números de teléfono, nombres ni conversaciones: el contrato
 *   no los trae y la vista no los pide;
 * - si el canal no está configurado o no hay datos, lo explica con un estado
 *   vacío claro y no inventa cifras;
 * - una latencia con menos de 30 corridas se marca como no concluyente.
 */

import { crearEncabezadoVista, crearTexto } from "../comun.js";

/** Corridas mínimas para que un percentil de latencia sea concluyente. */
const MINIMO_CORRIDAS = 30;

/** Nombre visible de cada flujo medido. */
const FLUJOS = {
  webhook: "Webhook (recibir y responder)",
  diagnostico: "Diagnóstico financiero",
  hitl: "Asesor (HITL)",
  mcp: "Servidor MCP",
  ventanilla: "Ventanilla web (preguntar)",
};

/** Nombre visible del modo de envío del canal. */
const MODOS = {
  real: "Envío real",
  falso: "Envío falso (simulado)",
  deshabilitado: "Deshabilitado",
};

/** Texto de cada motivo por el que se abre un caso de asesor. */
const MOTIVOS = {
  semaforo_rojo: "Semáforo rojo",
  solicitud_usuario: "Pidió hablar con un asesor",
};

/** Nombre visible de cada categoría de Roba la Bóveda. */
const CATEGORIAS = {
  inyeccion: "Inyección",
  extraccion_prompt: "Extracción del prompt",
  dato_personal: "Dato personal",
  fuera_dominio: "Fuera del dominio",
  legitimo: "Pregunta legítima",
};

/**
 * Pinta la vista Operación dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-operacion` de `index.html`.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  const cuerpo = document.createElement("div");
  cuerpo.className = "operacion";
  cuerpo.setAttribute("aria-live", "polite");

  contenedor.replaceChildren(
    crearEncabezadoVista(
      "operacion",
      "Operación del corresponsal",
      "Cómo va el canal de WhatsApp: mensajes, consentimientos, casos para el asesor, tiempos de respuesta y el juego Roba la Bóveda. Solo cifras, sin teléfonos, nombres ni conversaciones.",
    ),
    cuerpo,
  );
  await pintar(cuerpo, estado);
}

/**
 * Pide el resumen de operación y lo pinta; si falla, muestra el error con
 * un botón para reintentar.
 *
 * @param {HTMLElement} cuerpo Contenedor de la vista.
 * @param {{pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
async function pintar(cuerpo, estado) {
  cuerpo.replaceChildren(crearTexto("p", "Cargando la operación…", "cargando"));

  let datos;
  try {
    datos = await estado.pedir("operacion");
  } catch (error) {
    cuerpo.replaceChildren(crearError(error, () => pintar(cuerpo, estado)));
    return;
  }

  const rejilla = document.createElement("div");
  rejilla.className = "operacion__rejilla";
  rejilla.append(
    crearCanal(datos?.canal),
    crearMensajes(datos?.mensajes, datos?.canal),
    crearConsentimientos(datos?.consentimientos),
    crearRoba(datos?.roba),
  );

  cuerpo.replaceChildren(
    crearResumen(datos, () => pintar(cuerpo, estado)),
    rejilla,
    crearCasos(datos?.casos),
    crearLatencias(datos?.latencia, datos?.latencia_cache),
  );
}

/**
 * Crea la línea de resumen con la hora del corte y el botón «Actualizar».
 *
 * @param {{generado?: string}} datos Respuesta de `/api/operacion`.
 * @param {() => void} actualizar Vuelve a pedir el resumen.
 * @returns {HTMLElement} El bloque de resumen.
 */
function crearResumen(datos, actualizar) {
  const fila = document.createElement("div");
  fila.className = "operacion__resumen";
  const hora = formatearFecha(datos?.generado);
  fila.append(
    crearTexto("p", hora ? `Corte de las cifras: ${hora}` : "Cifras sin hora de corte", "operacion__corte"),
  );
  const boton = crearTexto("button", "Actualizar", "operacion__boton");
  boton.type = "button";
  boton.addEventListener("click", actualizar);
  fila.append(boton);
  return fila;
}

/**
 * Crea la tarjeta del canal: si está configurado, en qué modo envía y
 * cuántos números de prueba están autorizados.
 *
 * @param {{configurado?: boolean, modo?: string, numeros_autorizados?: number}} [canal]
 *   Bloque `canal` del contrato.
 * @returns {HTMLElement} La tarjeta.
 */
function crearCanal(canal) {
  const configurado = canal?.configurado === true;
  const modo = configurado ? textoODefecto(canal?.modo, "deshabilitado") : "deshabilitado";
  const tarjeta = crearTarjeta(
    "Canal de WhatsApp",
    configurado ? [MODOS[modo] ?? modo, modo === "real" ? "ok" : "aviso"] : ["Sin configurar", "pendiente"],
  );
  tarjeta.dataset.bloque = "canal";
  if (!configurado) {
    tarjeta.append(
      crearTexto(
        "p",
        "El canal todavía no está configurado: faltan las variables de entorno de Meta. La Ventanilla web sigue funcionando.",
        "operacion__vacio",
      ),
    );
    return tarjeta;
  }
  tarjeta.append(
    crearCifras([
      ["Números autorizados", canal?.numeros_autorizados],
    ]),
  );
  if (modo === "falso") {
    tarjeta.append(
      crearTexto("p", "Las respuestas se registran, pero no salen hacia WhatsApp.", "operacion__nota"),
    );
  }
  return tarjeta;
}

/**
 * Crea la tarjeta de mensajes: recibidos, respondidos, errores, cola y
 * duplicados descartados.
 *
 * @param {{recibidos?: number, respondidos?: number, errores?: number, pendientes?: number, duplicados?: number}} [mensajes]
 *   Bloque `mensajes` del contrato.
 * @param {{configurado?: boolean}} [canal] Bloque `canal`, para el estado vacío.
 * @returns {HTMLElement} La tarjeta.
 */
function crearMensajes(mensajes, canal) {
  const errores = entero(mensajes?.errores);
  const tarjeta = crearTarjeta(
    "Mensajes y cola",
    errores > 0 ? [`${formatearEntero(errores)} con error`, "aviso"] : ["Sin errores", "ok"],
  );
  tarjeta.dataset.bloque = "mensajes";
  if (entero(mensajes?.recibidos) === 0) {
    tarjeta.append(
      crearTexto(
        "p",
        canal?.configurado ? "Aún no ha llegado ningún mensaje." : "Sin canal no llegan mensajes.",
        "operacion__vacio",
      ),
    );
    return tarjeta;
  }
  tarjeta.append(
    crearCifras([
      ["Recibidos", mensajes?.recibidos],
      ["Respondidos", mensajes?.respondidos],
      ["Con error", mensajes?.errores],
      ["En cola", mensajes?.pendientes],
      ["Duplicados descartados", mensajes?.duplicados],
    ]),
  );
  return tarjeta;
}

/**
 * Crea la tarjeta de consentimientos de la Ley 1581 de 2012.
 *
 * @param {{aceptados?: number, pendientes?: number, revocados?: number}} [consentimientos]
 *   Bloque `consentimientos` del contrato.
 * @returns {HTMLElement} La tarjeta.
 */
function crearConsentimientos(consentimientos) {
  const pendientes = entero(consentimientos?.pendientes);
  const tarjeta = crearTarjeta(
    "Consentimientos",
    pendientes > 0 ? [`${formatearEntero(pendientes)} por aceptar`, "aviso"] : ["Al día", "ok"],
  );
  tarjeta.dataset.bloque = "consentimientos";
  tarjeta.append(
    crearCifras([
      ["Aceptados", consentimientos?.aceptados],
      ["Por aceptar", consentimientos?.pendientes],
      ["Revocados", consentimientos?.revocados],
    ]),
    crearTexto("p", "Nadie recibe respuestas del asistente sin aceptar antes el aviso de datos.", "operacion__nota"),
  );
  return tarjeta;
}

/**
 * Crea la tarjeta resumen de Roba la Bóveda, con enlace a la terminal.
 *
 * @param {{intentos?: number, exitos?: number, puntos?: number, por_categoria?: Record<string, number>}} [roba]
 *   Bloque `roba` del contrato.
 * @returns {HTMLElement} La tarjeta.
 */
function crearRoba(roba) {
  const intentos = entero(roba?.intentos);
  const exitos = entero(roba?.exitos);
  const tarjeta = crearTarjeta(
    "Roba la Bóveda",
    intentos === 0 ? ["Sin intentos", "pendiente"] : [`${formatearEntero(exitos)} defensas vulneradas`, exitos > 0 ? "aviso" : "ok"],
  );
  tarjeta.dataset.bloque = "roba";
  if (intentos === 0) {
    tarjeta.append(crearTexto("p", "Nadie ha intentado robar la Bóveda todavía.", "operacion__vacio"));
  } else {
    tarjeta.append(
      crearCifras([
        ["Intentos", roba?.intentos],
        ["Éxitos del atacante", roba?.exitos],
        ["Puntos", roba?.puntos],
      ]),
    );
    const categorias = Object.entries(roba?.por_categoria ?? {}).filter(([, valor]) => entero(valor) > 0);
    if (categorias.length > 0) {
      const lista = document.createElement("ul");
      lista.className = "operacion__categorias";
      for (const [clave, valor] of categorias) {
        lista.append(crearTexto("li", `${CATEGORIAS[clave] ?? clave}: ${formatearEntero(entero(valor))}`));
      }
      tarjeta.append(lista);
    }
  }
  const enlace = crearTexto("a", "Abrir la terminal", "operacion__enlace");
  enlace.href = "#roba";
  tarjeta.append(enlace);
  return tarjeta;
}

/**
 * Crea el bloque de casos para el asesor: totales y la lista de pendientes
 * con motivo, semáforo y fecha (sin datos de la persona).
 *
 * @param {{pendientes?: number, contactados?: number, descartados?: number, lista?: {id?: string, motivo?: string, semaforo?: string, estado?: string, creado?: string}[]}} [casos]
 *   Bloque `casos` del contrato.
 * @returns {HTMLElement} El bloque.
 */
function crearCasos(casos) {
  const bloque = crearSeccion("Casos para el asesor (HITL)");
  bloque.dataset.bloque = "casos";
  bloque.append(
    crearCifras([
      ["Pendientes", casos?.pendientes],
      ["Contactados", casos?.contactados],
      ["Descartados", casos?.descartados],
    ]),
  );

  const pendientes = (Array.isArray(casos?.lista) ? casos.lista : []).filter(
    (caso) => caso?.estado === "pendiente",
  );
  if (pendientes.length === 0) {
    bloque.append(crearTexto("p", "No hay casos esperando a un asesor.", "operacion__vacio"));
    return bloque;
  }

  const tabla = crearTabla(["Caso", "Motivo", "Semáforo", "Abierto"]);
  const cuerpo = tabla.querySelector("tbody");
  for (const caso of pendientes) {
    const fila = document.createElement("tr");
    const semaforo = textoODefecto(caso?.semaforo, "sin_dato");
    const sello = crearTexto("span", nombreSemaforo(semaforo), `operacion__semaforo operacion__semaforo--${claseSemaforo(semaforo)}`);
    const celdaSemaforo = document.createElement("td");
    celdaSemaforo.append(sello);
    fila.append(
      crearTexto("td", textoODefecto(caso?.id), "cifra"),
      crearTexto("td", MOTIVOS[caso?.motivo] ?? textoODefecto(caso?.motivo)),
      celdaSemaforo,
      crearTexto("td", formatearFecha(caso?.creado) || "—"),
    );
    cuerpo.append(fila);
  }
  bloque.append(envolverTabla(tabla));
  return bloque;
}

/**
 * Crea el bloque de latencias: una tabla para las corridas normales y otra
 * para las que respondió la caché, que nunca se mezclan.
 *
 * @param {Record<string, {p50_ms?: number, p95_ms?: number, n?: number, suficiente?: boolean}>} [latencia]
 *   Percentiles por flujo sin caché.
 * @param {Record<string, {p50_ms?: number, p95_ms?: number, n?: number, suficiente?: boolean}>} [latenciaCache]
 *   Percentiles por flujo de las corridas con caché.
 * @returns {HTMLElement} El bloque.
 */
function crearLatencias(latencia, latenciaCache) {
  const bloque = crearSeccion("Tiempos de respuesta (p50 y p95)");
  bloque.dataset.bloque = "latencia";
  bloque.append(
    crearTexto(
      "p",
      `p50 es el tiempo típico y p95 el de los turnos más lentos. Con menos de ${MINIMO_CORRIDAS} corridas el percentil no es concluyente.`,
      "operacion__nota",
    ),
  );

  const normales = Object.entries(latencia ?? {});
  if (normales.length === 0) {
    bloque.append(
      crearTexto("p", "Aún no hay mediciones. Se generan con make arqueo.", "operacion__vacio"),
    );
  } else {
    bloque.append(crearTablaLatencia("Sin caché", normales));
  }

  const conCache = Object.entries(latenciaCache ?? {});
  if (conCache.length > 0) {
    bloque.append(crearTablaLatencia("Con caché (aparte)", conCache));
  }
  return bloque;
}

/**
 * Crea una tabla de latencia con flujo, p50, p95, corridas y si es concluyente.
 *
 * @param {string} titulo Leyenda de la tabla.
 * @param {[string, {p50_ms?: number, p95_ms?: number, n?: number, suficiente?: boolean}][]} filas
 *   Pares flujo-percentiles.
 * @returns {HTMLElement} La tabla envuelta.
 */
function crearTablaLatencia(titulo, filas) {
  const tabla = crearTabla(["Flujo", "p50", "p95", "Corridas", "Lectura"]);
  tabla.prepend(crearTexto("caption", titulo));
  const cuerpo = tabla.querySelector("tbody");
  for (const [flujo, medida] of filas) {
    const n = entero(medida?.n);
    const concluyente = medida?.suficiente === true && n >= MINIMO_CORRIDAS;
    const fila = document.createElement("tr");
    fila.dataset.flujo = flujo;
    const lectura = crearTexto(
      "span",
      concluyente ? "Concluyente" : "Muestra insuficiente",
      `operacion__lectura operacion__lectura--${concluyente ? "ok" : "insuficiente"}`,
    );
    const celdaLectura = document.createElement("td");
    celdaLectura.append(lectura);
    fila.append(
      crearTexto("td", FLUJOS[flujo] ?? flujo),
      crearTexto("td", formatearMs(medida?.p50_ms), "cifra"),
      crearTexto("td", formatearMs(medida?.p95_ms), "cifra"),
      crearTexto("td", formatearEntero(n), "cifra"),
      celdaLectura,
    );
    cuerpo.append(fila);
  }
  return envolverTabla(tabla);
}

/**
 * Crea una tarjeta con título y sello de estado.
 *
 * @param {string} titulo Título de la tarjeta.
 * @param {[string, string]} sello Texto del sello y su tono (`ok`, `aviso`, `pendiente`).
 * @returns {HTMLElement} La tarjeta.
 */
function crearTarjeta(titulo, [textoSello, tono]) {
  const tarjeta = document.createElement("article");
  tarjeta.className = "operacion__tarjeta";
  const cabecera = document.createElement("div");
  cabecera.className = "operacion__cabecera";
  cabecera.append(
    crearTexto("h2", titulo, "operacion__titulo"),
    crearTexto("span", textoSello, `operacion__sello operacion__sello--${tono}`),
  );
  tarjeta.append(cabecera);
  return tarjeta;
}

/**
 * Crea una sección de ancho completo con su título.
 *
 * @param {string} titulo Título de la sección.
 * @returns {HTMLElement} La sección.
 */
function crearSeccion(titulo) {
  const seccion = document.createElement("section");
  seccion.className = "operacion__seccion";
  seccion.append(crearTexto("h2", titulo, "operacion__titulo"));
  return seccion;
}

/**
 * Crea una lista de cifras etiquetadas. Un valor ausente se muestra como «—»,
 * nunca como cero, para no inventar datos.
 *
 * @param {[string, unknown][]} pares Etiqueta y valor de cada cifra.
 * @returns {HTMLDListElement} La lista.
 */
function crearCifras(pares) {
  const lista = document.createElement("dl");
  lista.className = "operacion__cifras";
  for (const [etiqueta, valor] of pares) {
    const grupo = document.createElement("div");
    const numero = Number.isFinite(valor) ? formatearEntero(valor) : "—";
    grupo.append(crearTexto("dt", etiqueta), crearTexto("dd", numero, "cifra"));
    lista.append(grupo);
  }
  return lista;
}

/**
 * Crea una tabla vacía con su encabezado.
 *
 * @param {string[]} columnas Nombres de las columnas.
 * @returns {HTMLTableElement} La tabla, con `thead` y `tbody`.
 */
function crearTabla(columnas) {
  const tabla = document.createElement("table");
  tabla.className = "operacion__tabla";
  const cabeza = document.createElement("thead");
  const fila = document.createElement("tr");
  for (const columna of columnas) {
    const celda = crearTexto("th", columna);
    celda.scope = "col";
    fila.append(celda);
  }
  cabeza.append(fila);
  tabla.append(cabeza, document.createElement("tbody"));
  return tabla;
}

/**
 * Envuelve una tabla para que se desplace de lado en pantallas angostas.
 *
 * @param {HTMLTableElement} tabla Tabla a envolver.
 * @returns {HTMLElement} El envoltorio.
 */
function envolverTabla(tabla) {
  const caja = document.createElement("div");
  caja.className = "operacion__desplazable";
  caja.append(tabla);
  return caja;
}

/**
 * Crea el aviso de error con un botón para reintentar.
 *
 * @param {Error} error Error recibido.
 * @param {() => void} reintentar Vuelve a pedir el resumen.
 * @returns {HTMLElement} El aviso.
 */
function crearError(error, reintentar) {
  const aviso = document.createElement("div");
  aviso.className = "aviso aviso--error operacion__error";
  aviso.setAttribute("role", "alert");
  const boton = crearTexto("button", "Reintentar", "operacion__boton");
  boton.type = "button";
  boton.addEventListener("click", reintentar);
  aviso.append(
    crearTexto("strong", "No se pudo cargar la operación."),
    crearTexto("span", ` ${error?.message ?? "Error desconocido"}`),
    boton,
  );
  return aviso;
}

/**
 * Devuelve el nombre visible de un semáforo.
 *
 * @param {string} semaforo `verde`, `amarillo` o `rojo`.
 * @returns {string} Nombre con mayúscula inicial, o «Sin dato».
 */
function nombreSemaforo(semaforo) {
  return { verde: "Verde", amarillo: "Amarillo", rojo: "Rojo" }[semaforo] ?? "Sin dato";
}

/**
 * Devuelve la clase CSS de un semáforo, limitada a los valores conocidos.
 *
 * @param {string} semaforo Valor del contrato.
 * @returns {string} `verde`, `amarillo`, `rojo` o `sin-dato`.
 */
function claseSemaforo(semaforo) {
  return ["verde", "amarillo", "rojo"].includes(semaforo) ? semaforo : "sin-dato";
}

/**
 * Convierte un valor del contrato en entero no negativo.
 *
 * @param {unknown} valor Valor numérico o ausente.
 * @returns {number} El entero, o 0 si no es un número válido.
 */
function entero(valor) {
  return Number.isFinite(valor) && valor > 0 ? Math.trunc(valor) : 0;
}

/**
 * Formatea un entero con separador de miles colombiano.
 *
 * @param {number} valor Cifra.
 * @returns {string} Texto como `1.234`.
 */
function formatearEntero(valor) {
  return Number(valor).toLocaleString("es-CO", { maximumFractionDigits: 0 });
}

/**
 * Formatea milisegundos: hasta 999 ms en milisegundos y desde 1 s en segundos.
 *
 * @param {unknown} ms Milisegundos.
 * @returns {string} Texto como `420 ms` o `1,8 s`, o «—» si falta.
 */
function formatearMs(ms) {
  if (!Number.isFinite(ms)) {
    return "—";
  }
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  return `${(ms / 1000).toLocaleString("es-CO", { maximumFractionDigits: 1 })} s`;
}

/**
 * Formatea una fecha ISO en hora de Colombia (Bogotá), sin importar la zona
 * horaria del computador que abre la vista.
 *
 * @param {unknown} iso Fecha ISO 8601.
 * @returns {string} Fecha legible, o cadena vacía si no es válida.
 */
function formatearFecha(iso) {
  if (typeof iso !== "string" || !iso) {
    return "";
  }
  const fecha = new Date(iso);
  if (Number.isNaN(fecha.getTime())) {
    return "";
  }
  return fecha.toLocaleString("es-CO", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "America/Bogota",
  });
}

/**
 * Devuelve el texto recortado, o un valor por defecto si viene vacío.
 *
 * @param {unknown} valor Valor del contrato.
 * @param {string} [defecto] Texto si falta, «—» por defecto.
 * @returns {string} Texto para mostrar.
 */
function textoODefecto(valor, defecto = "—") {
  return typeof valor === "string" && valor.trim() ? valor.trim() : defecto;
}
