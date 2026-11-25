"""Herramientas de lectura y cálculo del agente `pana` (1–11 y 17–20).

Todas son deterministas sobre artefactos ya construidos —Tablero, Gold, Bóveda,
configuración y documentos del proyecto— y ninguna escribe en el corpus. Las que
podrían necesitar un modelo devuelven un error explicable cuando no hay clave,
en lugar de abrir la red por su cuenta.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from decimal import Decimal

from pydantic import BaseModel, ValidationError

from ..asistente.validacion import cifras_duras
from ..canal.contratos import EntradaDiagnostico, ResultadoDiagnostico
from ..diagnostico.comite import auditar_texto, construir_escenarios
from ..diagnostico.escenarios import CambioEscenario, comparar_resultado
from ..diagnostico.motor import calcular, entrada_desde_respuestas
from ..escena.auditor import ETIQUETA_VEREDICTO, veredicto_desde_hallazgos
from ..escena.comparacion import alertas_comparacion
from ..escena.comparacion import comparar_gota_banco as _comparar_gota_banco
from ..escena.contratos import HallazgoEscena
from ..escena.gota import calcular_prestamo_gota as _calcular_gota
from ..escena.gota import formatear_pesos
from ..escena.negociacion import negociar
from ..escena.proyecto import crear_recuperador_proyecto, es_pregunta_del_proyecto
from ..mcp_servidor import conocimiento, control
from ..mcp_servidor.control import Personaje
from ..mcp_servidor.servidor import buscar_en_boveda
from ..mcp_servidor.servidor import consultar_tasa as _consultar_tasa
from ..mcp_servidor.servidor import simular_cuota as _simular_cuota
from ..pana.desde_diagnostico import tarjeta_y_texto
from ..sucursal.ajustes import leer_modo_demo
from ..tablero.tasas import cargar_config_tasas, clave_producto
from .comun import como_json, error, mensaje_de_validacion, ok
from .esquemas import (
    LIMITES_MONTO,
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
    MontoExactoEntrada,
    NegociarOpcionEntrada,
    PreguntaProyecto,
    ResponderSobreProyectoEntrada,
    RespuestasEntrevista,
    SalidaHerramienta,
    SimularCuotaEntrada,
    TasaEfectivaAnual,
    UnidadTasaEntrada,
    VerificarUsuraEntrada,
    error_de_respuestas,
    respuestas_o_error,
)

#: Preguntas máximas de palabras que se muestran de un fragmento del proyecto.
MAXIMO_PALABRAS_PROYECTO: int = 40
#: Tope de cifras permitidas que acepta el auditor.
MAXIMO_CIFRAS_AUDITOR: int = 40
#: Tope de la tasa que se lee como fracción cuando no se declara la unidad.
TOPE_FRACCION: float = 100.0


def _diagnostico(
    herramienta: str,
    respuestas: list[str],
    monto: int | None = None,
) -> ResultadoDiagnostico | SalidaHerramienta:
    """Calcula el diagnóstico o devuelve el error con el catálogo de la entrevista.

    Args:
        herramienta: nombre del catálogo, para el sobre de error.
        respuestas: ids canónicos de la entrevista.
        monto: monto exacto del invitado para reemplazar el valor del rango.

    Returns:
        El resultado del motor o el sobre de error con los valores válidos.
    """
    fallo = respuestas_o_error(herramienta, respuestas)
    if fallo is not None:
        return fallo
    try:
        entrada = entrada_desde_respuestas(respuestas)
        if monto is not None:
            ajustada = _monto_exacto(herramienta, entrada, monto)
            if isinstance(ajustada, SalidaHerramienta):
                return ajustada
            entrada = ajustada
        return calcular(entrada)
    except ValidationError as exc:
        return error_de_respuestas(herramienta, mensaje_de_validacion(exc))
    except ValueError as exc:
        return error_de_respuestas(herramienta, str(exc))


def _monto_exacto(
    herramienta: str,
    entrada: EntradaDiagnostico,
    monto: int,
) -> EntradaDiagnostico | SalidaHerramienta:
    """Reemplaza el valor del rango por el monto exacto, si cabe en sus límites.

    Args:
        herramienta: nombre del catálogo, para el sobre de error.
        entrada: entrada del diagnóstico con el valor de cálculo del rango.
        monto: monto exacto que dijo el invitado, en pesos.

    Returns:
        La entrada con el monto exacto, o el error `entrada_invalida` con los
        límites del rango elegido.
    """
    ident = next(
        (valor for valor in entrada.rango_usado.values() if valor.startswith("monto.")),
        None,
    )
    if ident is None:
        return error(
            herramienta,
            "entrada_invalida",
            "El producto no lleva monto de crédito; no se puede aplicar un monto exacto.",
        )
    limites = LIMITES_MONTO.get(ident)
    if limites is None:
        return error(
            herramienta,
            "entrada_invalida",
            f"El rango {ident} no declara límites de monto.",
        )
    desde, hasta = limites
    if not desde <= monto <= hasta:
        salida = error(
            herramienta,
            "entrada_invalida",
            (
                f"El monto {monto} no cabe en el rango {ident}: desde "
                f"{formatear_pesos(Decimal(desde))} hasta {formatear_pesos(Decimal(hasta))}."
            ),
        )
        salida.datos.update(
            {
                "monto": monto,
                "rango": ident,
                "limites": {"desde": desde, "hasta": hasta},
            }
        )
        return salida
    return entrada.model_copy(update={"monto_credito": Decimal(monto)})


def _tasa_efectiva(valor: float, unidad: str | None) -> tuple[float, str]:
    """Normaliza la tasa E.A. a fracción y declara cómo se interpretó.

    Args:
        valor: tasa recibida, en fracción o en porcentaje.
        unidad: `fraccion`, `porcentaje` o `None` para inferirla.

    Returns:
        La tasa como fracción (0,2834 = 28,34 %) y la unidad interpretada.
    """
    if unidad == "porcentaje" or (unidad is None and valor > TOPE_FRACCION):
        return valor / 100, "porcentaje"
    return valor, "fraccion"


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


def verificar_usura(
    tasa_ea: TasaEfectivaAnual,
    producto: str | None = None,
    unidad: UnidadTasaEntrada = None,
) -> SalidaHerramienta:
    """Compara una tasa E.A. con la usura certificada en `config/tasas.toml`.

    Acepta tasas por encima del 100 % (el gota a gota es 791,61 % E.A.). Si no
    se declara `unidad`, una cifra de hasta 100 se lee como fracción y una mayor
    como porcentaje.

    Args:
        tasa_ea: tasa efectiva anual, en fracción (7,9161 = 791,61 %) o en
            porcentaje (791,61), según `unidad`.
        producto: producto al que se aplicaría; vivienda, ahorro y CDT están
            exceptuados de la usura de consumo y ordinario.
        unidad: `fraccion`, `porcentaje` o `None` para inferirla.

    Returns:
        Si la tasa excede la usura, el exceso en puntos y la fuente certificada.
    """
    entrada = VerificarUsuraEntrada(tasa_ea=tasa_ea, producto=producto, unidad=unidad)
    ajustes = cargar_config_tasas()
    usura = ajustes.usura
    if not usura.certificada:
        return error(
            "verificar_usura",
            "usura_sin_certificar",
            "La usura no está certificada en config/tasas.toml.",
        )
    tasa, interpretada = _tasa_efectiva(entrada.tasa_ea, entrada.unidad)
    limite = float(usura.tasa_ea)
    exceso = max(0.0, tasa - limite)
    clave = clave_producto(entrada.producto) if entrada.producto else ""
    aplica = not clave or clave not in usura.exceptuados
    return ok(
        "verificar_usura",
        {
            "tasa_ea": round(tasa, 6),
            "tasa_ea_pct": round(tasa * 100, 4),
            "unidad_interpretada": interpretada,
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
                "La usura se mide en tasa efectiva anual y no tiene tope de entrada: "
                "el gota a gota supera el 100 %. Un spread sobre IPC o IBR no es una "
                "tasa y no se compara con este límite."
            ),
        },
    )


def diagnosticar_capacidad(respuestas: RespuestasEntrevista) -> SalidaHerramienta:
    """Calcula el diagnóstico completo a partir de las respuestas de la entrevista.

    Args:
        respuestas: ids canónicos de la entrevista en la forma bloque.valor:
            objetivo.* y vinculacion.* (uno de cada lista), ingresos.*,
            gastos.* y cuotas.* (obligatorios), monto.* y plazo.* (en crédito) y
            cuota_trasladar.* (solo en compra de cartera). El esquema del campo
            trae todas las opciones. Si falta un bloque, el error devuelve el
            catálogo en `datos["valores_validos"]` para corregir en un intento.

    Returns:
        El resultado determinista con cuota, semáforo, alertas y trazabilidad.
    """
    fallo = respuestas_o_error("diagnosticar_capacidad", respuestas)
    if fallo is not None:
        return fallo
    entrada = DiagnosticarCapacidadEntrada(respuestas=respuestas)
    resultado = _diagnostico("diagnosticar_capacidad", entrada.respuestas)
    if isinstance(resultado, SalidaHerramienta):
        return resultado
    return ok("diagnosticar_capacidad", {"resultado": como_json(resultado)})


def comparar_escenario(
    respuestas: RespuestasEntrevista,
    campo: CampoEscenarioHerramienta,
    valor: float,
) -> SalidaHerramienta:
    """Compara un «¿Y si…?» contra el diagnóstico original, sin el grafo.

    Args:
        respuestas: ids canónicos de la entrevista original, como en
            `diagnosticar_capacidad`.
        campo: insumo que cambia (`monto_credito`, `plazo_meses`, `ingreso_mensual`,
            `gastos_mensuales` o `cuotas_deudas`).
        valor: valor nuevo del insumo.

    Returns:
        El escenario calculado y la comparación con su tendencia.
    """
    fallo = respuestas_o_error("comparar_escenario", respuestas)
    if fallo is not None:
        return fallo
    entrada = CompararEscenarioEntrada(respuestas=respuestas, campo=campo, valor=valor)
    resultado = _diagnostico("comparar_escenario", entrada.respuestas)
    if isinstance(resultado, SalidaHerramienta):
        return resultado
    cambio = CambioEscenario(campo=entrada.campo, valor=Decimal(str(entrada.valor)))
    nuevo, comparacion = comparar_resultado(resultado, cambio, origen="herramienta")
    return ok(
        "comparar_escenario",
        {
            "escenario": como_json(nuevo),
            "comparacion": como_json(comparacion),
        },
    )


def convocar_comite(respuestas: RespuestasEntrevista) -> SalidaHerramienta:
    """Convoca el comité de crédito cuando el diagnóstico es amarillo o rojo.

    El comité usa el modelo de DeepSeek del proyecto. Sin `DEEPSEEK_API_KEY` la
    herramienta no inventa una deliberación: devuelve los escenarios
    precalculados y un error explicable para que el agente ofrezca el respaldo.

    Args:
        respuestas: ids canónicos de la entrevista, como en
            `diagnosticar_capacidad`.

    Returns:
        La deliberación con posturas, recomendación y hallazgos, o el motivo por
        el que no se convocó.
    """
    fallo = respuestas_o_error("convocar_comite", respuestas)
    if fallo is not None:
        return fallo
    entrada = ConvocarComiteEntrada(respuestas=respuestas)
    resultado = _diagnostico("convocar_comite", entrada.respuestas)
    if isinstance(resultado, SalidaHerramienta):
        return resultado
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


def comparar_gota_banco(monto: int, respuestas: RespuestasEntrevista) -> SalidaHerramienta:
    """Compara el gota a gota con el banco y con la usura vigente.

    Args:
        monto: mismo monto para los dos lados.
        respuestas: ids canónicos de la entrevista con ingresos, gastos, deudas,
            monto y plazo, como en `diagnosticar_capacidad`.

    Returns:
        La comparación con los totales, la usura y los supuestos.
    """
    fallo = respuestas_o_error("comparar_gota_banco", respuestas)
    if fallo is not None:
        return fallo
    entrada = CompararGotaBancoEntrada(monto=monto, respuestas=respuestas)
    diagnostico = _diagnostico("comparar_gota_banco", entrada.respuestas)
    if isinstance(diagnostico, SalidaHerramienta):
        return diagnostico
    prestamo = _calcular_gota(entrada.monto)
    comparacion = _comparar_gota_banco(prestamo, diagnostico.entrada)
    return ok(
        "comparar_gota_banco",
        {
            "comparacion": como_json(comparacion),
            "alertas": list(alertas_comparacion(comparacion)),
        },
    )


def negociar_opcion(
    respuestas: RespuestasEntrevista,
    monto: MontoExactoEntrada = None,
) -> SalidaHerramienta:
    """Negocia la opción del joven y del banco sobre la mesa precalculada.

    La negociación usa siempre las respuestas del invitado. El modo demo no lo
    decide el modelo: lo lee el servidor de `SUCURSAL_DEMO` con
    `leer_modo_demo`, y sin `DEEPSEEK_API_KEY` la lógica ya cae a reglas.

    Args:
        respuestas: ids canónicos de la entrevista que arman la mesa, como en
            `diagnosticar_capacidad`.
        monto: monto exacto que dijo el invitado. Si se pasa, debe ser el mismo
            que se usó en `calcular_prestamo_gota`; reemplaza el valor de
            cálculo del rango solo si cae dentro de sus límites y, si no, la
            herramienta devuelve `entrada_invalida` con los límites. Sin este
            campo se usa el valor del rango.

    Returns:
        Los turnos, el acuerdo o `None`, el veredicto y el registro de validaciones.
    """
    fallo = respuestas_o_error("negociar_opcion", respuestas)
    if fallo is not None:
        return fallo
    entrada = NegociarOpcionEntrada(respuestas=respuestas, monto=monto)
    diagnostico = _diagnostico("negociar_opcion", entrada.respuestas, monto=entrada.monto)
    if isinstance(diagnostico, SalidaHerramienta):
        return diagnostico
    resultado = negociar(diagnostico.entrada, entorno=_entorno_negociacion())
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


def _entorno_negociacion() -> Mapping[str, str]:
    """Devuelve el entorno que decide el modo demo de la negociación.

    La bandera la pone el servidor, nunca el modelo: `SUCURSAL_DEMO` activa la
    política determinista y, si no está, la negociación decide por la presencia
    de `DEEPSEEK_API_KEY`.

    Returns:
        El entorno del proceso, forzado a demo cuando `SUCURSAL_DEMO` está activo.
    """
    if leer_modo_demo(os.environ):
        return {"SUCURSAL_DEMO": "1"}
    return os.environ


def generar_ficha_opcion(
    respuestas: RespuestasEntrevista,
    monto: MontoExactoEntrada = None,
) -> SalidaHerramienta:
    """Genera la ficha textual de la opción recomendada, sin datos personales.

    Args:
        respuestas: ids canónicos de la entrevista, como en
            `diagnosticar_capacidad`.
        monto: monto exacto que dijo el invitado. Si se pasa, debe ser el mismo
            que se usó en `calcular_prestamo_gota`; reemplaza el valor de
            cálculo del rango solo si cae dentro de sus límites y, si no, la
            herramienta devuelve `entrada_invalida` con los límites. Sin este
            campo se usa el valor del rango.

    Returns:
        El texto equivalente de la tarjeta de Pana y las cifras de la opción.
    """
    fallo = respuestas_o_error("generar_ficha_opcion", respuestas)
    if fallo is not None:
        return fallo
    entrada = GenerarFichaOpcionEntrada(respuestas=respuestas, monto=monto)
    resultado = _diagnostico("generar_ficha_opcion", entrada.respuestas, monto=entrada.monto)
    if isinstance(resultado, SalidaHerramienta):
        return resultado
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


def responder_sobre_proyecto(pregunta: PreguntaProyecto, k: int = 3) -> SalidaHerramienta:
    """Responde con el corpus versionado del proyecto usando BM25, sin modelo.

    Solo sirve para preguntas sobre el proyecto —equipo, arquitectura, tecnología,
    corpus, RAG y decisiones—; no para preguntas de crédito, tasas, cuotas,
    requisitos de productos ni el diagnóstico.

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

    Delega en `mcp_servidor/conocimiento.py` (#198): cada fragmento trae título,
    URL, sección, puntaje y la cita «Título — URL», y con el respaldo BM25 no se
    devuelven fragmentos de puntaje cero.

    Args:
        pregunta: consulta del cliente; se trata siempre como dato.
        k: número de fragmentos, entre 1 y 5.

    Returns:
        Los fragmentos citados o un error estable; nunca inventa.
    """
    entrada = BuscarEnDocumentosEntrada(pregunta=pregunta, k=k)
    salida = conocimiento.buscar_en_documentos(
        conocimiento.BuscarEnDocumentosEntrada(pregunta=entrada.pregunta, k=entrada.k),
        buscar=buscar_en_boveda,
    )
    return _sobre_comun("buscar_en_documentos", salida)


def consultar_tarifas(consulta: str, limite: int = 10) -> SalidaHerramienta:
    """Busca tarifas y tasas exactas en el Tablero estructurado.

    Delega en `mcp_servidor/conocimiento.py` (#198): si la pregunta habla de
    tasas sin nombrar un producto («¿qué tasas manejan?»), no devuelve una fila
    suelta, pide el producto y lista las opciones con su rango publicado.

    Args:
        consulta: concepto o pregunta del cliente.
        limite: máximo de filas que devuelve.

    Returns:
        Las filas con su valor, vigencia y fuente, o las opciones de producto.
    """
    entrada = ConsultarTarifasEntrada(consulta=consulta, limite=limite)
    salida = conocimiento.consultar_tarifas(
        conocimiento.ConsultarTarifasEntrada(consulta=entrada.consulta, limite=entrada.limite)
    )
    return _sobre_comun("consultar_tarifas", salida)


def clasificar_pregunta(pregunta: str) -> SalidaHerramienta:
    """Asigna el turno del Digiturno a una pregunta, con reglas deterministas.

    Delega en `mcp_servidor/control.py` (#199): además de la letra y el motivo,
    devuelve la ruta, la herramienta sugerida y si la pregunta se responde
    directo (cortesía) o se rechaza.

    Args:
        pregunta: mensaje del cliente.

    Returns:
        Letra, ruta, motivo, herramienta sugerida y banderas de cortesía y
        rechazo. Sin clasificador de dudas la ruta por defecto es `B`.
    """
    entrada = ClasificarPreguntaEntrada(pregunta=pregunta)
    salida = control.clasificar_pregunta(
        control.ClasificarPreguntaEntrada(pregunta=entrada.pregunta)
    )
    return _sobre_comun("clasificar_pregunta", salida)


def auditar_respuesta(
    texto: str,
    cifras_permitidas: list[str] | None = None,
    personaje: Personaje = "pana",
) -> SalidaHerramienta:
    """Revisa un texto antes de enviarlo, con el auditor de la escena y el del comité.

    Delega en `mcp_servidor/control.py` (#199) y suma las frases de promesa y
    los datos personales de `auditar_texto` del comité. Toda cifra del texto
    debe estar en `cifras_permitidas`: sin lista, cualquier cifra es
    `cifra_inventada`. No cuentan las referencias legales («Ley 1581 de 2012»)
    ni los años sueltos. También detecta la fuga de instrucciones.

    Args:
        texto: lo que se quiere auditar.
        cifras_permitidas: cifras que el texto puede citar, en dígitos como las
            devuelven las herramientas.
        personaje: quién envía el texto.

    Returns:
        `conforme`, el veredicto, si se puede enviar y los hallazgos en español.
    """
    entrada = AuditarRespuestaEntrada(texto=texto, cifras_permitidas=cifras_permitidas)
    revision = control.auditar_respuesta(
        control.AuditarRespuestaEntrada(texto=entrada.texto, personaje=personaje)
    )
    permitidas: set[str] = set()
    for cifra in (entrada.cifras_permitidas or [])[:MAXIMO_CIFRAS_AUDITOR]:
        permitidas |= cifras_duras(cifra) or {cifra.strip()}
    hallazgos = [h for h in revision.hallazgos if h.codigo != "cifra_inventada"]
    for cifra in sorted(control.cifras_sin_respaldo(entrada.texto) - permitidas):
        hallazgos.append(
            HallazgoEscena(
                codigo="cifra_inventada",
                turno_id=control.ID_RESPUESTA,
                detalle=f"El texto dice {cifra} y no está entre las cifras permitidas.",
                gravedad="alta",
            )
        )
    del_comite = auditar_texto(entrada.texto)
    veredicto = "objeta" if del_comite else veredicto_desde_hallazgos(hallazgos)
    return ok(
        "auditar_respuesta",
        {
            "conforme": veredicto == "conforme",
            "veredicto": veredicto,
            "etiqueta": ETIQUETA_VEREDICTO[veredicto],
            "permite_enviar": veredicto != "objeta",
            "hallazgos": [*del_comite, *(f"{h.codigo}: {h.detalle}" for h in hallazgos)],
            "detalle": [como_json(h) for h in hallazgos],
        },
    )


def _sobre_comun(herramienta: str, salida: BaseModel) -> SalidaHerramienta:
    """Envuelve la salida de `conocimiento.py` o `control.py` en el sobre común.

    Args:
        herramienta: nombre del catálogo.
        salida: modelo de salida o `SobreError` de la herramienta delegada.

    Returns:
        `SalidaHerramienta` con los datos, o con el código y el mensaje del error.
    """
    if isinstance(salida, conocimiento.SobreError):
        return error(herramienta, salida.codigo, salida.mensaje)
    datos = salida.model_dump(mode="json")
    datos.pop("ok", None)
    return ok(herramienta, datos)
