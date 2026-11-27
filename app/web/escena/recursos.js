/**
 * Sucursal 1965 · recursos de la pantalla (tecla G): repositorio y WhatsApp.
 *
 * El QR del repositorio y su URL salen del servidor: la URL no se escribe en el
 * HTML y el QR se dibuja en memoria con `segno`. El número de WhatsApp tampoco
 * está en el repositorio: el servidor lo lee de `PANA_WHATSAPP_NUMERO` y, si no
 * hay, el bloque queda oculto.
 *
 * Las consultas se hacen una sola vez por pestaña y no bloquean la escena.
 */

/** Ruta que devuelve la URL pública del repositorio. */
const RUTA_REPOSITORIO = "/api/escena/repositorio";
/** Ruta del PNG del QR del repositorio. */
const RUTA_REPOSITORIO_QR = "/api/escena/repositorio/qr.png";
/** Ruta que dice si hay número de WhatsApp configurado (nunca lo devuelve). */
const RUTA_WHATSAPP = "/api/escena/whatsapp";
/** Ruta del PNG del QR de WhatsApp. */
const RUTA_QR = "/api/escena/whatsapp/qr.png";

/** URL del repositorio ya pedida, o `null` mientras no se conozca. */
let urlRepositorio = null;
/** Resultado de la consulta de WhatsApp, para no repetirla. */
let disponible = null;

/**
 * Pide una sola vez la URL pública del repositorio.
 *
 * @returns {Promise<string | null>} URL, o `null` si el servidor no responde.
 */
async function pedirRepositorio() {
  if (urlRepositorio !== null) {
    return urlRepositorio;
  }
  try {
    const respuesta = await fetch(RUTA_REPOSITORIO, { signal: AbortSignal.timeout(3000) });
    const datos = respuesta.ok ? await respuesta.json() : null;
    urlRepositorio = typeof datos?.url === "string" ? datos.url : "";
  } catch {
    urlRepositorio = "";
  }
  return urlRepositorio;
}

/**
 * Consulta si el bloque de WhatsApp está configurado.
 *
 * @returns {Promise<boolean>} `true` si hay número en el servidor.
 */
export async function whatsappDisponible() {
  if (disponible !== null) {
    return disponible;
  }
  try {
    const respuesta = await fetch(RUTA_WHATSAPP, { signal: AbortSignal.timeout(3000) });
    const datos = respuesta.ok ? await respuesta.json() : null;
    disponible = datos?.disponible === true;
  } catch {
    disponible = false;
  }
  return disponible;
}

/**
 * Muestra u oculta el bloque de WhatsApp del panel de recursos.
 *
 * @returns {Promise<void>} Se resuelve cuando el bloque quedó actualizado.
 */
export async function mostrarWhatsapp() {
  const bloque = document.getElementById("escena-whatsapp");
  const imagen = document.getElementById("escena-whatsapp-qr");
  if (!bloque || !imagen) {
    return;
  }
  const hay = await whatsappDisponible();
  bloque.hidden = !hay;
  if (hay && !imagen.getAttribute("src")) {
    imagen.src = RUTA_QR;
  }
}

/**
 * Pone el QR de WhatsApp en una imagen cualquiera (la espera del voluntario).
 *
 * @param {HTMLImageElement | null} imagen Imagen donde va el QR.
 * @returns {Promise<boolean>} `true` si hay número y el QR quedó visible.
 */
export async function ponerQrWhatsapp(imagen) {
  if (!imagen) {
    return false;
  }
  const hay = await whatsappDisponible();
  imagen.hidden = !hay;
  if (hay && !imagen.getAttribute("src")) {
    imagen.src = RUTA_QR;
  }
  return hay;
}

/**
 * Prepara el panel de recursos (tecla G) al abrirlo.
 *
 * El enlace del repositorio se pone desde aquí para no escribir una URL externa
 * en el HTML. Si la ruta no responde, el enlace queda apuntando a la ruta local
 * que devuelve la URL y el QR se sigue mostrando.
 *
 * @returns {Promise<void>} Se resuelve cuando los recursos quedaron listos.
 */
export async function montarRecursos() {
  const enlace = document.getElementById("escena-repositorio-enlace");
  const imagen = document.getElementById("escena-repositorio-qr");
  if (imagen && !imagen.getAttribute("src")) {
    imagen.src = RUTA_REPOSITORIO_QR;
  }
  if (enlace) {
    enlace.href = (await pedirRepositorio()) || RUTA_REPOSITORIO;
  }
  await mostrarWhatsapp();
}
