/**
 * Vista Arqueo · responsable: Anny (PR 18).
 *
 * Muestra `GET /api/arqueo` en modo de solo lectura: recuperación (hit@5,
 * MRR), evaluación v1/v2, McNemar entre versiones, comparación de pesos,
 * sensibilidad de la revisión humana, costo, uso y avisos. La vista pinta lo
 * que llega: no recalcula p, no compara p con alfa, no decide significancia y
 * no inventa cifras. La frase del McNemar v1/v2 y la del escenario de
 * sensibilidad se leen de `datos.mcnemar.lectura` y
 * `datos.sensibilidad.mcnemar.lectura`; si faltan, se muestra «—».
 */

import { crearEncabezadoVista, crearTexto } from "../comun.js";

/** Decimales de las métricas de recuperación y evaluación. */
const DECIMALES_METRICA = 4;

/** Decimales de los valores p, de alfa y de los costos. */
const DECIMALES_COSTO = 6;

/** Decimales del ahorro porcentual. */
const DECIMALES_AHORRO = 1;

/** Decimales del tiempo promedio de una corrida. */
const DECIMALES_TIEMPO = 2;

/** Títulos visibles de las columnas comunes de McNemar. */
const TITULOS_MCNEMAR = ["b", "c", "n", "p exacta", "p mínimo", "alfa", "excluidos"];

/**
 * Pinta la vista Arqueo dentro de su contenedor.
 *
 * @param {HTMLElement} contenedor Sección `#vista-arqueo` de `index.html`.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
export async function render(contenedor, estado) {
  const cuerpo = document.createElement("div");
  cuerpo.className = "arqueo";
  cuerpo.setAttribute("aria-live", "polite");

  contenedor.replaceChildren(
    crearEncabezadoVista(
      "arqueo",
      "Arqueo",
      "La evaluación del sistema: recuperación, respuestas de v1 y v2, McNemar, costo y uso. Son cifras publicadas por el reporte; esta vista no las recalcula.",
    ),
    cuerpo,
  );
  await pintar(cuerpo, estado);
}

/**
 * Pide el reporte del Arqueo y pinta sus bloques. Si la API falla, muestra el
 * error con reintento; si el reporte no existe, muestra el estado «sin arqueo».
 *
 * @param {HTMLElement} cuerpo Contenedor de la vista.
 * @param {{modo: string, pedir: Function}} estado Estado compartido que entrega `app.js`.
 * @returns {Promise<void>}
 */
async function pintar(cuerpo, estado) {
  cuerpo.replaceChildren(crearTexto("p", "Cargando el arqueo…", "cargando"));

  let respuesta;
  try {
    respuesta = await estado.pedir("arqueo");
  } catch (error) {
    cuerpo.replaceChildren(crearError(error, () => pintar(cuerpo, estado)));
    return;
  }

  if (!esObjeto(respuesta) || respuesta.disponible !== true || !esObjeto(respuesta.datos)) {
    cuerpo.replaceChildren(crearSinArqueo(respuesta));
    return;
  }

  const datos = respuesta.datos;
  const bloques = [];
  if (estado.modo === "ejemplo") {
    bloques.push(crearAvisoEjemplo());
  }
  bloques.push(crearResumen(datos));
  bloques.push(crearRecuperacion(datos));
  bloques.push(crearEvaluacion(datos));
  bloques.push(crearMcNemar(datos));
  bloques.push(crearComparacionPesos(datos));
  bloques.push(crearSensibilidad(datos));
  bloques.push(crearCosto(datos));
  bloques.push(crearUso(datos));
  bloques.push(crearReferencia(datos));
  const avisos = crearAvisos(datos);
  if (avisos) {
    bloques.push(avisos);
  }
  cuerpo.replaceChildren(...bloques);
}

/**
 * Crea el estado «sin arqueo»: no hay reporte y no se pintan métricas vacías.
 *
 * @param {{error?: string} | null | undefined} respuesta Respuesta de `/api/arqueo`.
 * @returns {HTMLElement} El bloque informativo.
 */
function crearSinArqueo(respuesta) {
  const caja = document.createElement("div");
  caja.className = "arqueo arqueo__sin-arqueo";
  const detalle =
    typeof respuesta?.error === "string" && respuesta.error.trim()
      ? ` Detalle: ${respuesta.error.trim()}.`
      : "";
  caja.append(
    crearTexto("h2", "Sin arqueo", "arqueo__titulo"),
    crearTexto(
      "p",
      `Todavía no hay un reporte de arqueo en este equipo.${detalle}`,
      "arqueo__pista",
    ),
    crearTexto(
      "p",
      "Ejecuta make arqueo y vuelve a abrir esta vista. Mientras tanto no se muestran métricas vacías como si fueran resultados.",
      "arqueo__pista",
    ),
  );
  return caja;
}

/**
 * Crea el aviso que recuerda que los datos vienen de la maqueta.
 *
 * @returns {HTMLElement} El aviso informativo.
 */
function crearAvisoEjemplo() {
  return crearTexto(
    "p",
    "Datos de ejemplo: es el reporte real envuelto como lo devuelve /api/arqueo, sin el detalle pregunta por pregunta. Se muestra tal cual y no se recalcula nada.",
    "aviso arqueo__aviso",
  );
}

/**
 * Crea la línea de resumen con los conteos del banco de preguntas.
 *
 * @param {Record<string, any>} datos Reporte del Arqueo.
 * @returns {HTMLElement} El párrafo de resumen.
 */
function crearResumen(datos) {
  const conteos = esObjeto(datos.conteos) ? datos.conteos : null;
  const porTipo = esObjeto(datos.preguntas_por_tipo) ? datos.preguntas_por_tipo : null;
  const partes = [];

  if (conteos) {
    partes.push(`${formatearEntero(conteos.preguntas)} preguntas`);
    partes.push(`${formatearEntero(conteos.con_fuente)} con fuente`);
    partes.push(`${formatearEntero(conteos.evaluables_b)} de ruta B`);
    partes.push(`${formatearEntero(conteos.evaluables_t)} de ruta T`);
  }
  if (porTipo) {
    const tipos = ["alcance", "tabla", "seguimiento", "fuera"].map(
      (tipo) => `${tipo} ${formatearEntero(porTipo[tipo])}`,
    );
    partes.push(`por tipo: ${tipos.join(", ")}`);
  }
  if (partes.length === 0) {
    return crearTexto("p", "El reporte no trae conteos de preguntas.", "arqueo__resumen");
  }

  const resumen = crearTexto("p", `${partes.join(" · ")}.`, "arqueo__resumen");
  if (Array.isArray(conteos?.no_indexadas) && conteos.no_indexadas.length > 0) {
    const ids = conteos.no_indexadas.join(", ");
    resumen.append(
      crearTexto("span", ` Fuentes no indexadas: ${ids}.`, "arqueo__resumen-nota"),
    );
  }
  return resumen;
}

/**
 * Crea la sección de recuperación con la tabla por configuración y el corte
 * de la Bóveda frente al Tablero.
 *
 * @param {Record<string, any>} datos Reporte del Arqueo.
 * @returns {HTMLElement} La sección.
 */
function crearRecuperacion(datos) {
  const configuraciones = Array.isArray(datos.recuperacion)
    ? datos.recuperacion.filter(esObjeto)
    : [];
  const contenido = [];

  if (configuraciones.length === 0) {
    contenido.push(crearPendiente("El reporte no trae configuraciones de recuperación."));
  } else {
    contenido.push(
      crearTabla(
        "Recuperación por configuración",
        ["Configuración", "Prefijos", "Evaluables", "Aciertos", "hit@5", "Wilson 95 %", "MRR"],
        configuraciones.map(crearFilaConfiguracion),
        true,
      ),
      crearTabla(
        "Bóveda frente a Tablero",
        ["Configuración", "hit@5 (todas)", "hit@5 (sin T)", "MRR (todas)", "MRR (sin T)"],
        configuraciones.map(crearFilaSinTablero),
        true,
      ),
    );
  }
  contenido.push(
    crearTexto(
      "p",
      "hit@5 mide si una URL esperada aparece entre los cinco primeros fragmentos; MRR, la posición de la primera. Wilson 95 % es el intervalo del hit@5. La ruta T responde desde el Tablero y se reporta aparte.",
      "arqueo__pista",
    ),
  );
  return crearSeccion("Recuperación", contenido);
}

/**
 * Crea una fila de la tabla de recuperación.
 *
 * @param {Record<string, any>} configuracion Configuración del contrato.
 * @returns {string[]} Celdas de la fila.
 */
function crearFilaConfiguracion(configuracion) {
  const etiqueta = textoODefecto(configuracion.etiqueta);
  const nombre = configuracion.por_defecto ? `${etiqueta} (por defecto)` : etiqueta;
  return [
    nombre,
    siNo(configuracion.prefijos),
    formatearEntero(configuracion.evaluables),
    formatearEntero(configuracion.aciertos),
    formatearNumero(configuracion.hit_at_5),
    formatearIntervalo(configuracion.intervalo95),
    formatearNumero(configuracion.mrr),
  ];
}

/**
 * Crea una fila del corte Bóveda frente a Tablero.
 *
 * @param {Record<string, any>} configuracion Configuración del contrato.
 * @returns {string[]} Celdas de la fila.
 */
function crearFilaSinTablero(configuracion) {
  const sinTablero = esObjeto(configuracion.sin_tablero) ? configuracion.sin_tablero : {};
  return [
    textoODefecto(configuracion.etiqueta),
    formatearNumero(configuracion.hit_at_5),
    formatearNumero(sinTablero.hit_at_5),
    formatearNumero(configuracion.mrr),
    formatearNumero(sinTablero.mrr),
  ];
}

/**
 * Crea la sección de evaluación v1 y v2.
 *
 * @param {Record<string, any>} datos Reporte del Arqueo.
 * @returns {HTMLElement} La sección.
 */
function crearEvaluacion(datos) {
  const evaluacion = esObjeto(datos.evaluacion) ? datos.evaluacion : {};
  const contenido = [
    crearTabla(
      "Exactitud y citas de v1 y v2",
      ["Versión", "Aciertos", "Total", "Exactitud", "Citas correctas", "Revisadas"],
      [crearFilaEvaluacion("v1", evaluacion.v1), crearFilaEvaluacion("v2", evaluacion.v2)],
      true,
    ),
  ];
  if (!esObjeto(evaluacion.v2)) {
    contenido.push(
      crearPendiente(
        "La evaluación v2 todavía no existe. Cuando estén los resultados y la revisión humana v2, make arqueo la incorpora sin tocar la vista.",
      ),
    );
  }
  return crearSeccion("Evaluación v1 y v2", contenido);
}

/**
 * Crea una fila de la tabla de evaluación. Un bloque nulo se marca pendiente.
 *
 * @param {string} nombre Versión visible.
 * @param {Record<string, any> | null | undefined} bloque Evaluación de la versión.
 * @returns {string[]} Celdas de la fila.
 */
function crearFilaEvaluacion(nombre, bloque) {
  if (!esObjeto(bloque)) {
    return [nombre, "pendiente", "pendiente", "pendiente", "pendiente", "pendiente"];
  }
  return [
    nombre,
    formatearEntero(bloque.aciertos),
    formatearEntero(bloque.total),
    formatearNumero(bloque.exactitud),
    formatearNumero(bloque.citas_correctas),
    formatearEntero(bloque.revisadas),
  ];
}

/**
 * Crea la sección del McNemar v1 frente a v2 con la lectura del JSON.
 *
 * @param {Record<string, any>} datos Reporte del Arqueo.
 * @returns {HTMLElement} La sección.
 */
function crearMcNemar(datos) {
  const mcnemar = esObjeto(datos.mcnemar) ? datos.mcnemar : null;
  const contenido = [];

  if (!mcnemar) {
    contenido.push(crearPendiente("El reporte no trae la comparación McNemar v1 frente a v2."));
  } else {
    contenido.push(
      crearTabla(
        "McNemar v1 frente a v2 (20 preguntas de alcance)",
        ["Comparación", ...TITULOS_MCNEMAR],
        [["v1 frente a v2", ...valoresMcNemar(mcnemar)]],
        true,
      ),
      crearLectura(mcnemar),
    );
  }
  return crearSeccion("McNemar v1 frente a v2", contenido);
}

/**
 * Crea la sección del McNemar de pesos. Solo lleva la tabla y la explicación
 * fija de qué significan b y c en esta comparación; no calcula una frase.
 *
 * @param {Record<string, any>} datos Reporte del Arqueo.
 * @returns {HTMLElement} La sección.
 */
function crearComparacionPesos(datos) {
  const pesos = esObjeto(datos.mcnemar_pesos) ? datos.mcnemar_pesos : null;
  const contenido = [];

  if (!pesos) {
    contenido.push(crearPendiente("El reporte no trae la comparación principal de pesos."));
  } else {
    contenido.push(
      crearTexto(
        "p",
        "En esta comparación, b cuenta los pares donde acierta la configuración por defecto y falla 1/0; c, lo contrario. Las demás configuraciones son exploratorias: no se declara un ganador por significancia.",
        "arqueo__pista",
      ),
      crearTabla(
        "Comparación principal de pesos (preguntas de ruta B)",
        ["Comparación", ...TITULOS_MCNEMAR],
        [["Por defecto frente a 1/0", ...valoresMcNemar(pesos)]],
        true,
      ),
    );
  }
  return crearSeccion("McNemar de pesos", contenido);
}

/**
 * Crea la sección de sensibilidad de la revisión humana.
 *
 * @param {Record<string, any>} datos Reporte del Arqueo.
 * @returns {HTMLElement} La sección.
 */
function crearSensibilidad(datos) {
  const sensibilidad = esObjeto(datos.sensibilidad) ? datos.sensibilidad : null;
  const contenido = [];

  if (!sensibilidad) {
    contenido.push(
      crearPendiente(
        "La revisión humana v2 todavía no declara un escenario de sensibilidad.",
      ),
    );
    return crearSeccion("Sensibilidad de la revisión humana", contenido);
  }

  contenido.push(
    crearTexto(
      "p",
      `Escenario alterno con la nota de ${textoODefecto(sensibilidad.revisor)}. No cambia el veredicto principal ni la segunda firma.`,
      "arqueo__pista",
    ),
  );

  const cambios = Array.isArray(sensibilidad.cambios)
    ? sensibilidad.cambios.filter(esObjeto)
    : [];
  if (cambios.length > 0) {
    contenido.push(
      crearTabla(
        "Cambios del escenario de sensibilidad",
        ["#", "Veredicto principal", "Veredicto de sensibilidad", "Nota"],
        cambios.map((cambio) => [
          formatearEntero(cambio.id),
          textoODefecto(cambio.de),
          textoODefecto(cambio.a),
          textoODefecto(cambio.nota, ""),
        ]),
      ),
    );
  }

  const evaluacion = esObjeto(sensibilidad.evaluacion) ? sensibilidad.evaluacion : null;
  const alterno = esObjeto(sensibilidad.mcnemar) ? sensibilidad.mcnemar : null;
  const principal = esObjeto(datos.evaluacion?.v2) ? datos.evaluacion.v2 : null;
  const principalMcNemar = esObjeto(datos.mcnemar) ? datos.mcnemar : null;

  contenido.push(
    crearTabla(
      "Evaluación y McNemar del escenario principal y del alterno",
      [
        "Escenario",
        "Aciertos v2",
        "Exactitud v2",
        ...TITULOS_MCNEMAR,
      ],
      [
        [
          "Principal",
          ...valoresEvaluacion(principal),
          ...valoresMcNemar(principalMcNemar),
        ],
        ["Sensibilidad", ...valoresEvaluacion(evaluacion), ...valoresMcNemar(alterno)],
      ],
      true,
    ),
  );
  if (alterno) {
    contenido.push(crearLectura(alterno));
  }
  return crearSeccion("Sensibilidad de la revisión humana", contenido);
}

/**
 * Crea el párrafo con la lectura que trae el JSON. Si la clave falta, muestra
 * «—» y no calcula ninguna frase.
 *
 * @param {Record<string, any>} mcnemar Bloque de McNemar con `lectura`.
 * @returns {HTMLElement} El párrafo de lectura.
 */
function crearLectura(mcnemar) {
  const parrafo = document.createElement("p");
  parrafo.className = "arqueo__lectura";
  parrafo.append(
    crearTexto("strong", "Lectura: "),
    document.createTextNode(textoODefecto(mcnemar.lectura)),
  );
  return parrafo;
}

/**
 * Devuelve los valores comunes de un bloque de McNemar en el orden de la tabla.
 *
 * @param {Record<string, any> | null | undefined} mcnemar Bloque de McNemar.
 * @returns {string[]} Valores b, c, n, p, p mínimo, alfa y excluidos.
 */
function valoresMcNemar(mcnemar) {
  if (!esObjeto(mcnemar)) {
    return ["—", "—", "—", "—", "—", "—", "—"];
  }
  return [
    formatearEntero(mcnemar.b),
    formatearEntero(mcnemar.c),
    formatearEntero(mcnemar.n),
    formatearNumero(mcnemar.p, DECIMALES_COSTO),
    formatearNumero(mcnemar.p_minimo, DECIMALES_COSTO),
    formatearNumero(mcnemar.alfa, DECIMALES_COSTO),
    formatearEntero(mcnemar.excluidos),
  ];
}

/**
 * Devuelve los aciertos y la exactitud de un bloque de evaluación.
 *
 * @param {Record<string, any> | null | undefined} evaluacion Bloque de evaluación.
 * @returns {[string, string]} Aciertos y exactitud formateados.
 */
function valoresEvaluacion(evaluacion) {
  if (!esObjeto(evaluacion)) {
    return ["—", "—"];
  }
  return [formatearEntero(evaluacion.aciertos), formatearNumero(evaluacion.exactitud)];
}

/**
 * Crea la sección de costo con la lectura del reporte.
 *
 * @param {Record<string, any>} datos Reporte del Arqueo.
 * @returns {HTMLElement} La sección.
 */
function crearCosto(datos) {
  const costo = esObjeto(datos.costo) ? datos.costo : null;
  const contenido = [];

  if (!costo) {
    contenido.push(crearPendiente("El reporte no trae el bloque de costo."));
  } else {
    contenido.push(
      crearTabla(
        "Costo y uso histórico del Arqueo",
        ["Concepto", "Valor"],
        [
          ["Costo del Arqueo (DeepSeek)", formatearCosto(costo.arqueo_usd)],
          [
            "Costo histórico de v1 (20 de alcance)",
            formatearCosto(costo.v1_alcance_usd),
          ],
          [
            "Costo histórico de v2 (44 preguntas, cota inferior)",
            valorOPendiente(costo.v2_usd, formatearCosto),
          ],
          [
            "Costo de v2 en las 20 de alcance (cota inferior)",
            valorOPendiente(costo.v2_alcance_usd, formatearCosto),
          ],
          [
            "Ahorro máximo en las 20 de alcance",
            valorOPendiente(
              costo.ahorro_alcance_pct,
              (valor) => `${formatearNumero(valor, DECIMALES_AHORRO)} % menos`,
            ),
          ],
          [
            "Preguntas de alcance con clasificador en v2",
            textoClasificador(costo),
          ],
          ["Preguntas del banco", formatearEntero(costo.preguntas)],
        ],
        true,
      ),
      crearTexto(
        "p",
        "El Arqueo no llama a DeepSeek: su costo es cero. Las cifras de v2 son una cota inferior histórica: se midieron antes del arreglo del #93 y no incluían el clasificador de dudas ni la reformulación. Una corrida nueva ya suma las tres llamadas del turno.",
        "arqueo__pista",
      ),
    );
  }
  return crearSeccion("Costo", contenido);
}

/**
 * Resume cuántas preguntas de alcance usaron el clasificador en v2.
 *
 * @param {Record<string, any>} costo Bloque de costo.
 * @returns {string} Texto como `15 de 20`.
 */
function textoClasificador(costo) {
  if (!esNumero(costo.v2_alcance_con_clasificador)) {
    return "pendiente";
  }
  let texto = `${formatearEntero(costo.v2_alcance_con_clasificador)} de ${formatearEntero(costo.v2_alcance_preguntas)}`;
  if (esNumero(costo.v2_alcance_sin_motivo) && costo.v2_alcance_sin_motivo > 0) {
    texto += ` (${formatearEntero(costo.v2_alcance_sin_motivo)} sin motivo)`;
  }
  return texto;
}

/**
 * Crea la sección de uso de tokens y tiempos de v1 y v2.
 *
 * @param {Record<string, any>} datos Reporte del Arqueo.
 * @returns {HTMLElement} La sección.
 */
function crearUso(datos) {
  const uso = esObjeto(datos.uso) ? datos.uso : null;
  const contenido = [];

  if (!uso) {
    contenido.push(crearPendiente("El reporte no trae el bloque de uso."));
  } else {
    contenido.push(
      crearTabla(
        "Uso y tiempos por versión",
        [
          "Versión",
          "Registros",
          "Entrada",
          "Salida",
          "Caché",
          "Costo promedio (US$)",
          "Tiempo promedio (s)",
        ],
        [crearFilaUso("v1", uso.v1), crearFilaUso("v2", uso.v2)],
        true,
      ),
    );
    if (!esObjeto(uso.v2)) {
      contenido.push(
        crearPendiente("El uso de v2 todavía no existe; se completa con make evaluar VERSION=v2."),
      );
    }
  }
  return crearSeccion("Uso", contenido);
}

/**
 * Crea una fila de la tabla de uso. Un bloque nulo se marca pendiente.
 *
 * @param {string} nombre Versión visible.
 * @param {Record<string, any> | null | undefined} bloque Resumen de uso.
 * @returns {string[]} Celdas de la fila.
 */
function crearFilaUso(nombre, bloque) {
  if (!esObjeto(bloque)) {
    return [nombre, "pendiente", "pendiente", "pendiente", "pendiente", "pendiente", "pendiente"];
  }
  return [
    nombre,
    formatearEntero(bloque.registros),
    formatearEntero(bloque.entrada_total),
    formatearEntero(bloque.salida_total),
    formatearEntero(bloque.cache_total),
    formatearCosto(bloque.costo_usd_promedio),
    formatearNumero(bloque.tiempo_promedio, DECIMALES_TIEMPO),
  ];
}

/**
 * Crea la sección de verificación local contra el anexo A.
 *
 * @param {Record<string, any>} datos Reporte del Arqueo.
 * @returns {HTMLElement} La sección.
 */
function crearReferencia(datos) {
  const referencia = esObjeto(datos.referencia_anexo_a) ? datos.referencia_anexo_a : null;
  const contenido = [];

  if (!referencia) {
    contenido.push(crearPendiente("El reporte no trae la referencia del anexo A."));
  } else {
    const esperado = esObjeto(referencia.esperado) ? referencia.esperado : {};
    const medido = esObjeto(referencia.medido) ? referencia.medido : {};
    contenido.push(
      crearTabla(
        "Verificación local contra el anexo A",
        ["Configuración", "hit@5 esperado", "hit@5 medido", "MRR esperado", "MRR medido"],
        ["1/0", "por_defecto"].map((nombre) => {
          const bloqueEsperado = esObjeto(esperado[nombre]) ? esperado[nombre] : {};
          const bloqueMedido = esObjeto(medido[nombre]) ? medido[nombre] : {};
          return [
            nombre,
            formatearNumero(bloqueEsperado.hit_at_5),
            formatearNumero(bloqueMedido.hit_at_5),
            formatearNumero(bloqueEsperado.mrr),
            formatearNumero(bloqueMedido.mrr),
          ];
        }),
        true,
      ),
      crearTexto(
        "p",
        "No es un umbral: sirve para comprobar que el barrido reproduce el orden del recuperador.",
        "arqueo__pista",
      ),
    );
  }
  return crearSeccion("Referencia del anexo A", contenido);
}

/**
 * Crea la sección de avisos del reporte, si hay alguno.
 *
 * @param {Record<string, any>} datos Reporte del Arqueo.
 * @returns {HTMLElement | null} La sección, o `null` si no hay avisos.
 */
function crearAvisos(datos) {
  const avisos = Array.isArray(datos.avisos)
    ? datos.avisos.filter((aviso) => typeof aviso === "string" && aviso.trim())
    : [];
  if (avisos.length === 0) {
    return null;
  }
  const lista = document.createElement("ul");
  lista.className = "arqueo__avisos";
  for (const aviso of avisos) {
    const item = document.createElement("li");
    item.textContent = aviso;
    lista.append(item);
  }
  return crearSeccion("Avisos", [lista]);
}

/**
 * Crea una sección con su título y los nodos que recibe.
 *
 * @param {string} titulo Título visible de la sección.
 * @param {Node[]} contenido Nodos del cuerpo.
 * @returns {HTMLElement} La sección.
 */
function crearSeccion(titulo, contenido) {
  const seccion = document.createElement("section");
  seccion.className = "arqueo__seccion";
  seccion.append(crearTexto("h2", titulo, "arqueo__titulo"), ...contenido);
  return seccion;
}

/**
 * Crea una tabla accesible con título, encabezados de columna y de fila.
 *
 * @param {string} titulo Texto del `caption`.
 * @param {string[]} columnas Títulos de las columnas.
 * @param {string[][]} filas Filas; la primera celda es el encabezado de fila.
 * @param {boolean} [numerica] Alinea a la derecha las columnas de cifras.
 * @returns {HTMLElement} La tabla dentro de su envoltorio desplazable.
 */
function crearTabla(titulo, columnas, filas, numerica = false) {
  const tabla = document.createElement("table");
  tabla.className = numerica ? "arqueo__tabla arqueo__tabla--numerica" : "arqueo__tabla";

  const caption = crearTexto("caption", titulo, "arqueo__caption");
  const thead = document.createElement("thead");
  const filaCabecera = document.createElement("tr");
  for (const columna of columnas) {
    const th = crearTexto("th", columna);
    th.scope = "col";
    filaCabecera.append(th);
  }
  thead.append(filaCabecera);

  const tbody = document.createElement("tbody");
  for (const celdas of filas) {
    const tr = document.createElement("tr");
    celdas.forEach((contenido, indice) => {
      if (indice === 0) {
        const th = crearTexto("th", String(contenido));
        th.scope = "row";
        tr.append(th);
      } else {
        tr.append(crearTexto("td", String(contenido)));
      }
    });
    tbody.append(tr);
  }

  tabla.append(caption, thead, tbody);
  const envoltorio = document.createElement("div");
  envoltorio.className = "arqueo__tabla-envoltura";
  envoltorio.append(tabla);
  return envoltorio;
}

/**
 * Crea un bloque «Pendiente» para un bloque nulo del reporte.
 *
 * @param {string} texto Explicación de qué falta.
 * @returns {HTMLElement} El aviso de pendiente.
 */
function crearPendiente(texto) {
  const caja = crearTexto("p", texto, "arqueo__pendiente");
  caja.prepend(crearTexto("strong", "Pendiente: "));
  return caja;
}

/**
 * Crea el aviso de error con su botón de reintento.
 *
 * @param {Error} error Error recibido al pedir el arqueo.
 * @param {() => void} reintentar Acción del botón «Reintentar».
 * @returns {HTMLElement} El aviso.
 */
function crearError(error, reintentar) {
  const aviso = document.createElement("div");
  aviso.className = "aviso aviso--error arqueo__error";
  aviso.setAttribute("role", "alert");

  const boton = crearTexto("button", "Reintentar", "arqueo__reintentar");
  boton.type = "button";
  boton.addEventListener("click", reintentar);

  aviso.append(
    crearTexto("strong", "No se pudo cargar el arqueo."),
    crearTexto("span", ` ${error?.message ?? "Error desconocido"}`),
    boton,
  );
  return aviso;
}

/**
 * Formatea una cifra con los decimales pedidos y separadores de es-CO.
 *
 * @param {unknown} valor Valor del contrato.
 * @param {number} [decimales] Decimales visibles.
 * @returns {string} La cifra formateada o «—».
 */
function formatearNumero(valor, decimales = DECIMALES_METRICA) {
  if (!esNumero(valor)) {
    return "—";
  }
  return valor.toLocaleString("es-CO", {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

/**
 * Formatea un entero con separadores de es-CO.
 *
 * @param {unknown} valor Valor del contrato.
 * @returns {string} El entero formateado o «—».
 */
function formatearEntero(valor) {
  if (!esNumero(valor)) {
    return "—";
  }
  return valor.toLocaleString("es-CO", { maximumFractionDigits: 0 });
}

/**
 * Formatea un costo en dólares con los decimales del reporte.
 *
 * @param {unknown} valor Costo en US$.
 * @returns {string} El costo formateado o «—».
 */
function formatearCosto(valor) {
  return formatearNumero(valor, DECIMALES_COSTO);
}

/**
 * Formatea un intervalo de Wilson como «inferior a superior».
 *
 * @param {unknown} intervalo Par inferior y superior.
 * @returns {string} El intervalo formateado o «—».
 */
function formatearIntervalo(intervalo) {
  if (!Array.isArray(intervalo) || intervalo.length < 2) {
    return "—";
  }
  const [inferior, superior] = intervalo;
  if (!esNumero(inferior) || !esNumero(superior)) {
    return "—";
  }
  return `${formatearNumero(inferior)} a ${formatearNumero(superior)}`;
}

/**
 * Aplica un formateador a un valor si es numérico; si no, devuelve pendiente.
 *
 * @param {unknown} valor Valor del contrato.
 * @param {(valor: number) => string} formateador Formateador numérico.
 * @returns {string} El valor formateado o «pendiente».
 */
function valorOPendiente(valor, formateador) {
  return esNumero(valor) ? formateador(valor) : "pendiente";
}

/**
 * Indica si un valor es un número finito.
 *
 * @param {unknown} valor Valor del contrato.
 * @returns {boolean} `true` si se puede formatear como cifra.
 */
function esNumero(valor) {
  return typeof valor === "number" && Number.isFinite(valor);
}

/**
 * Indica si un valor es un objeto no nulo ni arreglo.
 *
 * @param {unknown} valor Valor del contrato.
 * @returns {boolean} `true` si es un objeto del reporte.
 */
function esObjeto(valor) {
  return typeof valor === "object" && valor !== null && !Array.isArray(valor);
}

/**
 * Convierte un booleano opcional en «sí», «no» o «—».
 *
 * @param {unknown} valor Bandera del contrato.
 * @returns {string} Texto visible.
 */
function siNo(valor) {
  if (valor === true) {
    return "sí";
  }
  if (valor === false) {
    return "no";
  }
  return "—";
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
