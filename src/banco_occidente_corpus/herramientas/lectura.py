"""Herramientas de lectura y cálculo del agente `pana` (1–11 y 17–20).

Todas son deterministas sobre artefactos ya construidos —Tablero, Gold, Bóveda,
configuración y documentos del proyecto— y ninguna escribe en el corpus. Las que
podrían necesitar un modelo devuelven un error explicable cuando no hay clave,
en lugar de abrir la red por su cuenta.
"""

from __future__ import annotations

import os
from decimal import Decimal

from ..config import load_config
from ..diagnostico.comite import auditar_texto, construir_escenarios
from ..diagnostico.escenarios import CambioEscenario, comparar_resultado
from ..escena.comparacion import alertas_comparacion
from ..escena.comparacion import comparar_gota_banco as _comparar_gota_banco
from ..escena.gota import calcular_prestamo_gota as _calcular_gota
from ..escena.gota import formatear_pesos
from ..escena.negociacion import negociar
from ..escena.proyecto import crear_recuperador_proyecto, es_pregunta_del_proyecto
from ..mcp_servidor.servidor import buscar_en_boveda
from ..mcp_servidor.servidor import consultar_tasa as _consultar_tasa
from ..mcp_servidor.servidor import simular_cuota as _simular_cuota
from ..pana.desde_diagnostico import tarjeta_y_texto
from ..sucursal.digiturno import clasificar
from ..tablero.herramienta import filas_de_consulta
from ..tablero.tasas import cargar_config_tasas, clave_producto
from ..tablero.tipos import leer_filas, ruta_tablero
from .comun import como_json, diagnostico_de, error, ok
from .esquemas import (
    AuditarRespuestaEntrada,
    BuscarEnDocumentosEntrada,
    CalcularPrestamoGotaEntrada,
    CampoEscenarioHerramienta,
    ClasificarPreguntaEntrada,
    CompararEscenarioEntrada,
    CompararGotaBancoEntrada,
    ConsultarTarifasEntrada,
    ConsultarTasaEntrada,
    ConvocarComiteEntrada,
    DiagnosticarCapacidadEntrada,
    GenerarFichaOpcionEntrada,
    NegociarOpcionEntrada,
    ResponderSobreProyectoEntrada,
    SalidaHerramienta,
    SimularCuotaEntrada,
    VerificarUsuraEntrada,
)

#: Preguntas máximas de palabras que se muestran de un fragmento del proyecto.
MAXIMO_PALABRAS_PROYECTO: int = 40
#: Tope de cifras permitidas que acepta el auditor.
MAXIMO_CIFRAS_AUDITOR: int = 40


def consultar_tasa(
    producto: str,
    plazo_dias: int | None = None,
    monto: int | None = None,
) -> SalidaHerramienta:
    """Consulta la tasa vigente de un producto del Tablero del banco.

    Args:
        producto: clave o nombre del producto, por ejemplo «libre inversión».
        plazo_dias: para el CDT, plazo publicado en días.
        monto: para el CDT, monto en pesos.

    Returns:
        El rango E.A./M.V. con vigencia, fuente y alertas, o un error estable.
    """
    entrada = ConsultarTasaEntrada(producto=producto, plazo_dias=plazo_dias, monto=monto)
    resultado = _consultar_tasa(entrada.producto, entrada.plazo_dias, entrada.monto)
    fallo = resultado.get("error")
    if isinstance(fallo, dict):
        return error(
            "consultar_tasa",
            str(fallo.get("codigo", "tasa_no_disponible")),
            str(fallo.get("mensaje", "No hay tasa disponible.")),
        )
    return ok("consultar_tasa", resultado)


def simular_cuota(producto: str, monto: float, plazo_meses: int) -> SalidaHerramienta:
    """Simula la cuota mensual de un crédito con la tasa vigente del Tablero.

    Args:
        producto: producto de crédito con cuota fija.
        monto: capital en pesos.
        plazo_meses: número de cuotas mensuales.

    Returns:
        La cuota en rango, las tasas, los totales y el aviso orientativo.
    """
    entrada = SimularCuotaEntrada(producto=producto, monto=monto, plazo_meses=plazo_meses)
    resultado = _simular_cuota(entrada.producto, entrada.monto, entrada.plazo_meses)
    fallo = resultado.get("error")
    if isinstance(fallo, dict):
        return error(
            "simular_cuota",
            str(fallo.get("codigo", "producto_no_simulable")),
            str(fallo.get("mensaje", "No se pudo simular la cuota.")),
        )
    return ok("simular_cuota", resultado)


def verificar_usura(tasa_ea: float, producto: str | None = None) -> SalidaHerramienta:
    """Compara una tasa E.A. con la usura certificada en `config/tasas.toml`.

    Args:
        tasa_ea: tasa efectiva anual como fracción (0,2834 = 28,34 %).
        producto: producto al que se aplicaría; vivienda, ahorro y CDT están
            exceptuados de la usura de consumo y ordinario.

    Returns:
        Si la tasa excede la usura, el exceso en puntos y la fuente certificada.
    """
    entrada = VerificarUsuraEntrada(tasa_ea=tasa_ea, producto=producto)
    ajustes = cargar_config_tasas()
    usura = ajustes.usura
    if not usura.certificada:
        return error(
            "verificar_usura",
            "usura_sin_certificar",
            "La usura no está certificada en config/tasas.toml.",
        )
    limite = float(usura.tasa_ea)
    exceso = max(0.0, entrada.tasa_ea - limite)
    clave = clave_producto(entrada.producto) if entrada.producto else ""
    aplica = not clave or clave not in usura.exceptuados
    return ok(
        "verificar_usura",
        {
            "tasa_ea": round(entrada.tasa_ea, 6),
            "tasa_ea_pct": round(entrada.tasa_ea * 100, 4),
            "usura_ea": limite,
            "usura_ea_pct": round(limite * 100, 4),
            "excede": exceso > 0,
            "exceso_puntos": round(exceso * 100, 4),
            "aplica": aplica,
            "producto": clave or None,
            "exceptuados": sorted(usura.exceptuados),
            "vigencia": f"{usura.vigencia_desde.isoformat()}/{usura.vigencia_hasta.isoformat()}",
            "fuente": usura.fuente,
            "resolucion": usura.resolucion,
            "nota": (
                "La usura se mide en tasa efectiva anual. Un spread sobre IPC o IBR "
                "no es una tasa y no se compara con este límite."
            ),
        },
    )


def diagnosticar_capacidad(respuestas: list[str]) -> SalidaHerramienta:
    """Calcula el diagnóstico completo a partir de las respuestas de la entrevista.

    Args:
        respuestas: ids canónicos de la entrevista.

    Returns:
        El resultado determinista con cuota, semáforo, alertas y trazabilidad.
    """
    entrada = DiagnosticarCapacidadEntrada(respuestas=respuestas)
    resultado = diagnostico_de(entrada.respuestas)
    return ok("diagnosticar_capacidad", {"resultado": como_json(resultado)})


def comparar_escenario(
    respuestas: list[str],
    campo: CampoEscenarioHerramienta,
    valor: float,
) -> SalidaHerramienta:
    """Compara un «¿Y si…?» contra el diagnóstico original, sin el grafo.

    Args:
        respuestas: ids de la entrevista original.
        campo: insumo que cambia (`monto_credito`, `plazo_meses`, `ingreso_mensual`,
            `gastos_mensuales` o `cuotas_deudas`).
        valor: valor nuevo del insumo.

    Returns:
        El escenario calculado y la comparación con su tendencia.
    """
    entrada = CompararEscenarioEntrada(respuestas=respuestas, campo=campo, valor=valor)
    resultado = diagnostico_de(entrada.respuestas)
    cambio = CambioEscenario(campo=entrada.campo, valor=Decimal(str(entrada.valor)))
    nuevo, comparacion = comparar_resultado(resultado, cambio, origen="herramienta")
    return ok(
        "comparar_escenario",
        {
            "escenario": como_json(nuevo),
            "comparacion": como_json(comparacion),
        },
    )


def convocar_comite(respuestas: list[str]) -> SalidaHerramienta:
    """Convoca el comité de crédito cuando el diagnóstico es amarillo o rojo.

    El comité usa el modelo de DeepSeek del proyecto. Sin `DEEPSEEK_API_KEY` la
    herramienta no inventa una deliberación: devuelve los escenarios
    precalculados y un error explicable para que el agente ofrezca el respaldo.

    Args:
        respuestas: ids canónicos de la entrevista.

    Returns:
        La deliberación con posturas, recomendación y hallazgos, o el motivo por
        el que no se convocó.
    """
    entrada = ConvocarComiteEntrada(respuestas=respuestas)
    resultado = diagnostico_de(entrada.respuestas)
    if resultado.semaforo not in {"amarillo", "rojo"} or resultado.cuota_mensual is None:
        return ok(
            "convocar_comite",
            {
                "convocado": False,
                "motivo": "El comité solo se convoca en amarillo o rojo con cuota.",
                "semaforo": resultado.semaforo,
            },
        )
    escenarios = construir_escenarios(resultado.entrada, resultado)
    if not os.environ.get("DEEPSEEK_API_KEY"):
        salida = error(
            "convocar_comite",
            "modelo_no_disponible",
            "El comité necesita DEEPSEEK_API_KEY; mientras tanto se ofrecen los escenarios.",
        )
        salida.datos["escenarios"] = como_json(escenarios)
        return salida
    from ..diagnostico.comite import deliberar  # import local: el módulo es pesado

    deliberacion = deliberar(resultado.entrada, resultado)
    return ok("convocar_comite", {"deliberacion": como_json(deliberacion)})


def calcular_prestamo_gota(monto: int) -> SalidaHerramienta:
    """Calcula el préstamo de Don Gota con la aritmética de la escena.

    Args:
        monto: capital en pesos.

    Returns:
        Interés, cuota diaria, totales y tasa E.A. equivalente, con su fuente.
    """
    entrada = CalcularPrestamoGotaEntrada(monto=monto)
    prestamo = _calcular_gota(entrada.monto)
    datos = como_json(prestamo)
    datos["resumen"] = (
        f"{formatear_pesos(prestamo.monto)} al {prestamo.tasa_mensual * 100:.0f} % mensual: "
        f"interés de {formatear_pesos(prestamo.interes_mensual)} y cuota diaria de "
        f"{formatear_pesos(prestamo.cuota_diaria)}."
    )
    return ok("calcular_prestamo_gota", datos)


def comparar_gota_banco(monto: int, respuestas: list[str]) -> SalidaHerramienta:
    """Compara el gota a gota con el banco y con la usura vigente.

    Args:
        monto: mismo monto para los dos lados.
        respuestas: ids de la entrevista con ingresos, gastos, deudas y plazo.

    Returns:
        La comparación con los totales, la usura y los supuestos.
    """
    entrada = CompararGotaBancoEntrada(monto=monto, respuestas=respuestas)
    prestamo = _calcular_gota(entrada.monto)
    diagnostico = diagnostico_de(entrada.respuestas)
    comparacion = _comparar_gota_banco(prestamo, diagnostico.entrada)
    return ok(
        "comparar_gota_banco",
        {
            "comparacion": como_json(comparacion),
            "alertas": list(alertas_comparacion(comparacion)),
        },
    )


def negociar_opcion(respuestas: list[str], modo_demo: bool = False) -> SalidaHerramienta:
    """Negocia la opción del joven y del banco sobre la mesa precalculada.

    Con `modo_demo` la política es determinista de principio a fin, sin modelo.
    Sin `DEEPSEEK_API_KEY` la lógica ya cae a reglas por su cuenta.

    Args:
        respuestas: ids de la entrevista que arman la mesa.
        modo_demo: fuerza la política determinista.

    Returns:
        Los turnos, el acuerdo o `None`, el veredicto y el registro de validaciones.
    """
    entrada = NegociarOpcionEntrada(respuestas=respuestas, modo_demo=modo_demo)
    diagnostico = diagnostico_de(entrada.respuestas)
    entorno = {"SUCURSAL_DEMO": "1"} if entrada.modo_demo else None
    resultado = negociar(diagnostico.entrada, entorno=entorno)
    return ok(
        "negociar_opcion",
        {
            "turnos": como_json(resultado.negociacion.turnos),
            "acuerdo": como_json(resultado.acuerdo),
            "decisiones": como_json(resultado.decisiones),
            "veredicto": como_json(resultado.negociacion.veredicto),
            "registro": list(resultado.negociacion.registro),
            "escenarios": como_json(resultado.negociacion.escenarios),
        },
    )


def generar_ficha_opcion(respuestas: list[str]) -> SalidaHerramienta:
    """Genera la ficha textual de la opción recomendada, sin datos personales.

    Args:
        respuestas: ids canónicos de la entrevista.

    Returns:
        El texto equivalente de la tarjeta de Pana y las cifras de la opción.
    """
    entrada = GenerarFichaOpcionEntrada(respuestas=respuestas)
    resultado = diagnostico_de(entrada.respuestas)
    imagen, texto = tarjeta_y_texto(resultado)
    return ok(
        "generar_ficha_opcion",
        {
            "texto": texto,
            "png_bytes": len(imagen),
            "semaforo": resultado.semaforo,
            "cuota_mensual": como_json(resultado.cuota_mensual),
            "tasa_ea": como_json(resultado.tasa_ea),
            "aviso": resultado.aviso,
        },
    )


def responder_sobre_proyecto(pregunta: str, k: int = 3) -> SalidaHerramienta:
    """Responde con el corpus versionado del proyecto usando BM25, sin modelo.

    Args:
        pregunta: pregunta sobre el repositorio, el corpus, el RAG o la escena.
        k: número de fragmentos a devolver.

    Returns:
        Los fragmentos con `Fuente: ruta#ancla`, recortados a 40 palabras.
    """
    entrada = ResponderSobreProyectoEntrada(pregunta=pregunta, k=k)
    if not es_pregunta_del_proyecto(entrada.pregunta):
        return error(
            "responder_sobre_proyecto",
            "fuera_del_corpus",
            "La pregunta no menciona el proyecto; usa la Bóveda para temas del banco.",
        )
    fragmentos = crear_recuperador_proyecto().buscar(entrada.pregunta, k=entrada.k)
    if not fragmentos:
        return ok("responder_sobre_proyecto", {"fragmentos": [], "total": 0})
    datos = []
    for fragmento in fragmentos:
        palabras = fragmento.texto.split()
        texto = " ".join(palabras[:MAXIMO_PALABRAS_PROYECTO])
        if len(palabras) > MAXIMO_PALABRAS_PROYECTO:
            texto += "…"
        datos.append(
            {
                "fuente": f"{fragmento.ruta}#{fragmento.ancla}",
                "titulo": fragmento.titulo,
                "texto": texto,
                "puntaje": round(fragmento.puntaje, 6),
            }
        )
    return ok("responder_sobre_proyecto", {"fragmentos": datos, "total": len(datos)})


def buscar_en_documentos(pregunta: str, k: int = 5) -> SalidaHerramienta:
    """Busca fragmentos citados en la Bóveda del banco.

    Args:
        pregunta: consulta del cliente; se trata siempre como dato.
        k: número de fragmentos, entre 1 y 5.

    Returns:
        Los fragmentos con título, URL, posición y puntaje; nunca inventa.
    """
    entrada = BuscarEnDocumentosEntrada(pregunta=pregunta, k=k)
    resultado = buscar_en_boveda(entrada.pregunta, entrada.k)
    fallo = resultado.get("error")
    if isinstance(fallo, dict):
        return error(
            "buscar_en_documentos",
            str(fallo.get("codigo", "indice_ausente")),
            str(fallo.get("mensaje", "No se pudo consultar la Bóveda.")),
        )
    return ok("buscar_en_documentos", resultado)


def consultar_tarifas(consulta: str, limite: int = 10) -> SalidaHerramienta:
    """Busca tarifas y coberturas exactas en el Tablero estructurado.

    Args:
        consulta: concepto o pregunta del cliente.
        limite: máximo de filas que devuelve.

    Returns:
        Las filas del CSV con su valor, vigencia y URL de la fuente.
    """
    entrada = ConsultarTarifasEntrada(consulta=consulta, limite=limite)
    ruta = ruta_tablero(load_config())
    if not ruta.exists():
        return error(
            "consultar_tarifas",
            "tablero_ausente",
            "No existe data/estructurados/tablero.csv: ejecuta `make tablero`.",
        )
    filas = filas_de_consulta(leer_filas(ruta), entrada.consulta, limite=entrada.limite)
    return ok("consultar_tarifas", {"filas": [fila.como_dict() for fila in filas]})


def clasificar_pregunta(pregunta: str) -> SalidaHerramienta:
    """Asigna el turno del Digiturno a una pregunta, con reglas deterministas.

    Args:
        pregunta: mensaje del cliente.

    Returns:
        El número, la letra y el motivo del turno. Sin clasificador de dudas la
        ruta por defecto es `B`.
    """
    entrada = ClasificarPreguntaEntrada(pregunta=pregunta)
    turno = clasificar(entrada.pregunta)
    return ok("clasificar_pregunta", como_json(turno))


def auditar_respuesta(texto: str, cifras_permitidas: list[str] | None = None) -> SalidaHerramienta:
    """Revisa un texto con el auditor determinístico del comité.

    Args:
        texto: lo que se quiere auditar.
        cifras_permitidas: cifras, solo dígitos, que el texto puede citar.

    Returns:
        `conforme` y los hallazgos en español; vacío significa que pasa.
    """
    entrada = AuditarRespuestaEntrada(texto=texto, cifras_permitidas=cifras_permitidas)
    permitidas = (
        set(entrada.cifras_permitidas[:MAXIMO_CIFRAS_AUDITOR])
        if entrada.cifras_permitidas is not None
        else None
    )
    hallazgos = auditar_texto(entrada.texto, cifras_permitidas=permitidas)
    return ok(
        "auditar_respuesta",
        {
            "conforme": not hallazgos,
            "hallazgos": hallazgos,
            "veredicto": "conforme" if not hallazgos else "objeta",
        },
    )
