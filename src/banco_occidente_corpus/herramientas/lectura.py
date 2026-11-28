"""Herramientas de lectura y cálculo del agente `pana` (1–11 y 17–20).

Todas son deterministas sobre artefactos ya construidos —Tablero, Gold, Bóveda,
configuración y documentos del proyecto— y ninguna escribe en el corpus. Las que
podrían necesitar un modelo devuelven un error explicable cuando no hay clave,
en lugar de abrir la red por su cuenta.
"""

from __future__ import annotations

import base64
import logging
import os
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from ..asistente.validacion import cifras_duras
from ..canal.contratos import EntradaDiagnostico, ResultadoDiagnostico
from ..cifras_legibles import (
    anotar,
    cifra,
    formatear_dias,
    formatear_meses,
    formatear_pesos,
    formatear_porcentaje,
    formatear_puntos,
    formatear_tasa_ea,
    formatear_veces,
)
from ..diagnostico.comite import auditar_texto, construir_escenarios
from ..diagnostico.escenarios import CambioEscenario, comparar_resultado
from ..diagnostico.motor import calcular, entrada_desde_respuestas
from ..escena.auditor import (
    ETIQUETA_VEREDICTO,
    turno_auditor,
    veredicto_desde_hallazgos,
)
from ..escena.comparacion import alertas_comparacion, turnos_pana_comparacion
from ..escena.comparacion import comparar_gota_banco as _comparar_gota_banco
from ..escena.contratos import (
    CifraEscena,
    EscenarioEscena,
    FuenteCifra,
    HallazgoEscena,
    TurnoEscena,
    VeredictoAuditor,
)
from ..escena.en_vivo import publicar_turnos
from ..escena.ficha_entrega import dejar_ficha
from ..escena.gota import calcular_prestamo_gota as _calcular_gota
from ..escena.gota import turnos_don_gota
from ..escena.negociacion import construir_mesa, negociar
from ..escena.proyecto import crear_recuperador_proyecto, es_pregunta_del_proyecto
from ..mcp_servidor import conocimiento, control
from ..mcp_servidor.control import Personaje
from ..mcp_servidor.servidor import buscar_en_boveda
from ..mcp_servidor.servidor import consultar_tasa as _consultar_tasa
from ..mcp_servidor.servidor import simular_cuota as _simular_cuota
from ..pana.desde_diagnostico import tarjeta_y_texto
from ..pana.tarjetas import monto_corto
from ..sucursal.ajustes import leer_modo_demo
from ..tablero.tasas import cargar_config_tasas, clave_producto
from .comun import aplicar_monto_exacto, como_json, error, mensaje_de_validacion, ok
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
    pregunta_pendiente,
    respuestas_o_error,
)

#: Preguntas máximas de palabras que se muestran de un fragmento del proyecto.
MAXIMO_PALABRAS_PROYECTO: int = 40
#: Tope de cifras permitidas que acepta el auditor.
MAXIMO_CIFRAS_AUDITOR: int = 40
#: Tope de la tasa que se lee como fracción cuando no se declara la unidad.
TOPE_FRACCION: float = 100.0
#: Id del turno de Pana que abre la escena con el diagnóstico completo.
ID_TURNO_DIAGNOSTICO: str = "pana.diagnostico.v1"
#: Orden del turno del diagnóstico: antes de Don Gota (1) y de la comparación (8).
ORDEN_TURNO_DIAGNOSTICO: int = 0
#: Avisos de la escena continua; se registran por código, sin textos ni cifras.
AVISO_GOTA: str = "no se pudo calcular la oferta de Don Gota"
AVISO_COMPARACION: str = "no se pudo comparar con el banco"
AVISO_NEGOCIACION: str = "no se pudo negociar la opción"

logger = logging.getLogger(__name__)

#: Última ficha publicada por este proceso; evita repetir el mismo turno.
_ULTIMA_FICHA_PUBLICADA: str | None = None


def _publicar_escena(
    construir: Callable[[], Iterable[TurnoEscena]],
    *,
    publicar: bool = False,
) -> None:
    """Publica un lote en la escena en vivo sin cambiar la respuesta.

    La construcción del lote ocurre dentro del resguardo: si un módulo de la
    escena lanza, la herramienta responde igual que hoy y no se publica nada.
    El publicador tampoco lanza, pero el resguardo cubre las dos orillas.

    Args:
        construir: fábrica que arma los turnos ya calculados.
        publicar: ``True`` solo cuando el canal conduce la escena y llama a la
            herramienta directo. Pana, por el MCP, nunca publica.
    """
    if not publicar:
        return
    with suppress(Exception):
        publicar_turnos(construir(), origen="herramienta")


def _publicar_ficha(turno: TurnoEscena, *, publicar: bool) -> None:
    """Publica la ficha una sola vez, aunque la herramienta se repita.

    Args:
        turno: turno `vivo.ficha.v1` ya armado.
        publicar: ``True`` solo en la llamada directa del canal.
    """
    global _ULTIMA_FICHA_PUBLICADA
    if not publicar or os.environ.get("ESCENA_EN_VIVO", "").strip() != "1":
        return
    if turno.texto == _ULTIMA_FICHA_PUBLICADA:
        return
    _publicar_escena(lambda: (turno,), publicar=True)
    _ULTIMA_FICHA_PUBLICADA = turno.texto


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
            ajustada = aplicar_monto_exacto(herramienta, entrada, monto)
            if isinstance(ajustada, SalidaHerramienta):
                return ajustada
            entrada = ajustada
        return calcular(entrada)
    except ValidationError as exc:
        return error_de_respuestas(herramienta, mensaje_de_validacion(exc))
    except ValueError as exc:
        return error_de_respuestas(herramienta, str(exc))


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
    datos = {
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
    }
    anotar(
        datos,
        (
            cifra("tasa_ea", tasa, formatear_tasa_ea(tasa), "porcentaje_ea", etiqueta="tasa E.A."),
            cifra(
                "tasa_ea_pct",
                round(tasa * 100, 4),
                formatear_porcentaje(tasa),
                "porcentaje",
                etiqueta="tasa E.A. en porcentaje",
            ),
            cifra(
                "usura_ea",
                limite,
                formatear_tasa_ea(limite),
                "porcentaje_ea",
                etiqueta="usura vigente",
            ),
            cifra(
                "usura_ea_pct",
                round(limite * 100, 4),
                formatear_porcentaje(limite),
                "porcentaje",
                etiqueta="usura vigente en porcentaje",
            ),
            cifra(
                "exceso_puntos",
                round(exceso * 100, 4),
                formatear_puntos(exceso * 100),
                "puntos",
                etiqueta="exceso sobre la usura",
            ),
        ),
    )
    return ok("verificar_usura", datos)


def _diagnostico_completo(resultado: ResultadoDiagnostico) -> bool:
    """Indica si el diagnóstico ya tiene producto, monto y plazo.

    Args:
        resultado: resultado del motor del diagnóstico.

    Returns:
        `True` cuando el crédito se puede prolongar con Don Gota, la comparación
        y la negociación.
    """
    entrada = resultado.entrada
    return entrada.monto_credito is not None and entrada.plazo_meses is not None


def _turno_diagnostico(resultado: ResultadoDiagnostico) -> TurnoEscena:
    """Arma el turno de Pana que presenta el diagnóstico completo.

    Args:
        resultado: resultado del motor con monto y plazo.

    Returns:
        El turno determinista que abre la escena, antes de Don Gota.

    Raises:
        ValueError: si el resultado no trae monto o plazo.
    """
    entrada = resultado.entrada
    monto = entrada.monto_credito
    plazo = entrada.plazo_meses
    if monto is None or plazo is None:
        raise ValueError("el diagnóstico no tiene monto y plazo")
    partes = [f"por {formatear_pesos(monto)} a {formatear_meses(plazo)}"]
    cuota = resultado.cuota_mensual
    if cuota is not None:
        desde = formatear_pesos(cuota.desde)
        hasta = formatear_pesos(cuota.hasta)
        if desde == hasta:
            partes.append(f"con una cuota de {desde} al mes")
        else:
            partes.append(f"con una cuota de {desde} a {hasta} al mes")
    return TurnoEscena(
        id=ID_TURNO_DIAGNOSTICO,
        orden=ORDEN_TURNO_DIAGNOSTICO,
        personaje="pana",
        texto="Tu diagnóstico: " + " ".join(partes) + ".",
        subtitulo="Diagnóstico",
        origen="motor",
    )


def _agregar_cifras(destino: list[str], valores: object) -> None:
    """Suma las cifras legibles de una salida, sin repetirlas.

    Args:
        destino: lista de cifras permitidas que se completa en el sitio.
        valores: lista o tupla de textos legibles de una herramienta.
    """
    if not isinstance(valores, (list, tuple)):
        return
    for valor in valores:
        texto = str(valor).strip()
        if texto and texto not in destino:
            destino.append(texto)


def _opciones_negociacion(
    escenarios: object,
    monto: int,
    producto: str,
) -> list[dict[str, Any]]:
    """Elige la opción de cuota más baja (A) y la de menor total (B).

    Solo entran escenarios ofertables del mismo monto y producto que pidió el
    invitado: así A y B cambian el plazo, no el capital ni el producto. Si la
    opción más barata al mes es también la de menor total, B toma el siguiente
    total distinto; si no hay otro, repite la misma opción.

    Args:
        escenarios: `escenarios` de `negociar_opcion`, ya serializados.
        monto: monto solicitado, en pesos.
        producto: producto del diagnóstico.

    Returns:
        Las dos opciones con su cuota, su plazo y su total legibles.
    """
    if not isinstance(escenarios, (list, tuple)):
        return []
    capital = Decimal(monto)
    candidatas = [
        escenario
        for escenario in escenarios
        if isinstance(escenario, Mapping)
        and escenario.get("ofertable") is True
        and escenario.get("producto") == producto
        and escenario.get("monto") is not None
        and Decimal(str(escenario["monto"])) == capital
        and escenario.get("cuota_mensual") is not None
        and escenario.get("total_pagado") is not None
        and escenario.get("plazo_meses") is not None
    ]
    if not candidatas:
        return []
    cuota_baja = min(candidatas, key=lambda escenario: Decimal(str(escenario["cuota_mensual"])))
    total_bajo = min(candidatas, key=lambda escenario: Decimal(str(escenario["total_pagado"])))
    if total_bajo["codigo"] == cuota_baja["codigo"]:
        otros = sorted(
            (escenario for escenario in candidatas if escenario["codigo"] != cuota_baja["codigo"]),
            key=lambda escenario: Decimal(str(escenario["total_pagado"])),
        )
        if otros:
            total_bajo = otros[0]
    return [_opcion("A", cuota_baja), _opcion("B", total_bajo)]


def _opcion(letra: str, escenario: Mapping[str, Any]) -> dict[str, Any]:
    """Da forma a una opción de la negociación para el resumen de Pana.

    Args:
        letra: `A` o `B`.
        escenario: escenario ofertable serializado.

    Returns:
        La opción con sus cifras de máquina y sus textos legibles.
    """
    cuota = Decimal(str(escenario["cuota_mensual"]))
    total = Decimal(str(escenario["total_pagado"]))
    plazo = int(str(escenario["plazo_meses"]))
    return {
        "letra": letra,
        "codigo": escenario["codigo"],
        "descripcion": escenario["descripcion"],
        "cuota_mensual": str(cuota),
        "cuota_mensual_legible": formatear_pesos(cuota),
        "plazo_meses": plazo,
        "plazo_legible": formatear_meses(plazo),
        "total_pagado": str(total),
        "total_pagado_legible": formatear_pesos(total),
    }


def _cifras_de_la_ficha(
    resultado: ResultadoDiagnostico,
    *,
    monto: int | None = None,
    plazo_meses: int | None = None,
    cuota: Decimal | None = None,
    total: Decimal | None = None,
) -> list[str]:
    """Reúne las cifras legibles de la ficha y del cierre para el auditor.

    Incluye el monto completo y el corto de la tarjeta, el plazo, el rango de
    la cuota, el total, las tasas E.A. y M.V. y el porcentaje del ingreso. Así
    el cierre se audita contra todo lo que la ficha dice, sin falsos hallazgos.

    Args:
        resultado: diagnóstico de la opción.
        monto: monto exacto de la opción, si cambió respecto de la entrevista.
        plazo_meses: plazo de la opción, si cambió respecto de la entrevista.
        cuota: cuota exacta de la opción elegida.
        total: total pagado de la opción elegida.

    Returns:
        Las cifras permitidas, sin repetir y con el tope del auditor.
    """
    cifras: list[str] = []
    entrada = resultado.entrada
    monto_final = (
        monto
        if monto is not None
        else (int(entrada.monto_credito) if entrada.monto_credito is not None else None)
    )
    if monto_final is not None:
        _agregar_cifras(
            cifras,
            [formatear_pesos(monto_final), monto_corto(Decimal(monto_final))],
        )
    plazo = plazo_meses if plazo_meses is not None else entrada.plazo_meses
    if plazo:
        _agregar_cifras(cifras, [formatear_meses(plazo)])
    if resultado.cuota_mensual is not None:
        _agregar_cifras(
            cifras,
            [
                formatear_pesos(resultado.cuota_mensual.desde),
                formatear_pesos(resultado.cuota_mensual.hasta),
            ],
        )
    if cuota is not None:
        _agregar_cifras(cifras, [formatear_pesos(cuota)])
    if total is not None:
        _agregar_cifras(cifras, [formatear_pesos(total)])
    if resultado.total_pagado is not None:
        _agregar_cifras(
            cifras,
            [
                formatear_pesos(resultado.total_pagado.desde),
                formatear_pesos(resultado.total_pagado.hasta),
            ],
        )
    if resultado.tasa_ea is not None:
        _agregar_cifras(
            cifras,
            [
                formatear_tasa_ea(resultado.tasa_ea.desde),
                formatear_tasa_ea(resultado.tasa_ea.hasta),
            ],
        )
    if resultado.tasa_mensual is not None:
        _agregar_cifras(
            cifras,
            [
                f"{formatear_porcentaje(resultado.tasa_mensual.desde)} M.V.",
                f"{formatear_porcentaje(resultado.tasa_mensual.hasta)} M.V.",
            ],
        )
    if resultado.razon_endeudamiento is not None:
        _agregar_cifras(cifras, [formatear_porcentaje(resultado.razon_endeudamiento)])
    if resultado.ahorro_mensual_estimado is not None:
        _agregar_cifras(cifras, [formatear_pesos(resultado.ahorro_mensual_estimado)])
    return cifras[:MAXIMO_CIFRAS_AUDITOR]


def _mensaje_resumen(resumen: Mapping[str, Any]) -> str:
    """Escribe el resumen corto con las opciones A y B para copiar tal cual.

    Args:
        resumen: `resumen_escena` ya armado con el diagnóstico y las opciones.

    Returns:
        La cuota del plan, la advertencia del gota a gota, las dos opciones y
        la instrucción «Responde A o B».
    """
    lineas: list[str] = []
    diagnostico = resumen.get("diagnostico")
    if isinstance(diagnostico, Mapping):
        monto = diagnostico.get("monto_legible")
        plazo = diagnostico.get("plazo_legible")
        cuota = diagnostico.get("cuota_desde_legible")
        if monto and plazo and cuota:
            frase = f"Con {monto} a {plazo} tu cuota sería {cuota} al mes"
            total = diagnostico.get("total_legible")
            if total:
                frase += f" y el total {total}"
            lineas.append(f"{frase}.")
    lineas.append(
        "Antes de firmar, ten en cuenta que el gota a gota cobra tasas mucho "
        "más altas y sin control: mejor un banco vigilado."
    )
    opciones = resumen.get("opciones")
    if isinstance(opciones, (list, tuple)):
        for opcion in opciones:
            if not isinstance(opcion, Mapping):
                continue
            letra = opcion.get("letra")
            plazo = opcion.get("plazo_legible")
            cuota = opcion.get("cuota_mensual_legible")
            total = opcion.get("total_pagado_legible")
            if letra and plazo and cuota and total:
                lineas.append(f"Opción {letra}: {plazo}, cuota {cuota}, total {total}.")
    lineas.append("Responde A o B.")
    return "\n\n".join(lineas)


def _escenarios_sin_publicar(
    respuestas: list[str],
    monto: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Calcula la mesa de negociación sin publicar turnos en la escena.

    `generar_ficha_opcion` necesita el escenario de la opción elegida, pero no
    debe repetir la negociación en la pantalla.

    Args:
        respuestas: ids canónicos de la entrevista.
        monto: monto exacto del invitado, si lo dio.

    Returns:
        Los escenarios serializados y las dos opciones A/B; listas vacías si la
        mesa no se puede armar.
    """
    try:
        entrada = entrada_desde_respuestas(respuestas)
        if monto is not None:
            ajustada = aplicar_monto_exacto("generar_ficha_opcion", entrada, monto)
            if isinstance(ajustada, SalidaHerramienta):
                return [], []
            entrada = ajustada
        if entrada.monto_credito is None:
            return [], []
        escenarios = [
            dict(escenario)
            for escenario in como_json(construir_mesa(entrada))
            if isinstance(escenario, dict)
        ]
        opciones = _opciones_negociacion(escenarios, int(entrada.monto_credito), entrada.producto)
        return escenarios, opciones
    except Exception:  # noqa: BLE001 - la ficha cae al diagnóstico de la entrevista
        logger.warning("generar_ficha_opcion no pudo armar la mesa de la opción")
        return [], []


def _entrada_de_la_opcion(
    respuestas: list[str],
    monto: int,
    plazo_meses: int | None,
) -> EntradaDiagnostico:
    """Ajusta la entrada del diagnóstico al monto y al plazo de la opción.

    Args:
        respuestas: ids canónicos de la entrevista.
        monto: monto de la opción elegida.
        plazo_meses: plazo de la opción elegida.

    Returns:
        La entrada del motor con el monto y el plazo de la opción.
    """
    entrada = entrada_desde_respuestas(respuestas)
    cambios: dict[str, Any] = {"monto_credito": Decimal(monto)}
    if plazo_meses is not None:
        cambios["plazo_meses"] = int(plazo_meses)
    return entrada.model_copy(update=cambios)


def _cifras_del_turno_ficha(
    resultado: ResultadoDiagnostico,
    *,
    monto: int,
    plazo_meses: int,
    cuota: Decimal,
    total: Decimal | None,
) -> tuple[CifraEscena, ...]:
    """Arma las cifras del turno de la ficha para el panel de la pantalla.

    Args:
        resultado: diagnóstico de la opción.
        monto: monto de la opción elegida.
        plazo_meses: plazo de la opción elegida.
        cuota: cuota exacta de la opción elegida.
        total: total pagado de la opción elegida.

    Returns:
        Las cifras con su fuente `motor`, sin repetir el mismo valor.
    """
    fuente = FuenteCifra(tipo="motor", referencia="diagnostico.motor#ficha_opcion")
    candidatas: list[CifraEscena] = [
        CifraEscena(
            etiqueta="monto",
            valor=Decimal(monto),
            valor_legible=formatear_pesos(monto),
            unidad="pesos",
            fuente=fuente,
        ),
        CifraEscena(
            etiqueta="plazo",
            valor=Decimal(plazo_meses),
            valor_legible=str(plazo_meses),
            unidad="meses",
            fuente=fuente,
        ),
        CifraEscena(
            etiqueta="cuota mensual",
            valor=cuota,
            valor_legible=formatear_pesos(cuota),
            unidad="pesos",
            fuente=fuente,
        ),
    ]
    if total is not None:
        candidatas.append(
            CifraEscena(
                etiqueta="total pagado",
                valor=total,
                valor_legible=formatear_pesos(total),
                unidad="pesos",
                fuente=fuente,
            )
        )
    if resultado.cuota_mensual is not None:
        candidatas.extend(
            (
                CifraEscena(
                    etiqueta="cuota desde",
                    valor=resultado.cuota_mensual.desde,
                    valor_legible=formatear_pesos(resultado.cuota_mensual.desde),
                    unidad="pesos",
                    fuente=fuente,
                ),
                CifraEscena(
                    etiqueta="cuota hasta",
                    valor=resultado.cuota_mensual.hasta,
                    valor_legible=formatear_pesos(resultado.cuota_mensual.hasta),
                    unidad="pesos",
                    fuente=fuente,
                ),
            )
        )
    if resultado.tasa_ea is not None:
        candidatas.append(
            CifraEscena(
                etiqueta="tasa E.A.",
                valor=resultado.tasa_ea.hasta,
                valor_legible=formatear_tasa_ea(resultado.tasa_ea.hasta),
                unidad="porcentaje_ea",
                fuente=fuente,
            )
        )
    if resultado.tasa_mensual is not None:
        candidatas.append(
            CifraEscena(
                etiqueta="tasa M.V.",
                valor=resultado.tasa_mensual.hasta,
                valor_legible=formatear_porcentaje(resultado.tasa_mensual.hasta),
                unidad="porcentaje",
                fuente=fuente,
            )
        )
    if resultado.razon_endeudamiento is not None:
        candidatas.append(
            CifraEscena(
                etiqueta="porcentaje del ingreso",
                valor=resultado.razon_endeudamiento,
                valor_legible=formatear_porcentaje(resultado.razon_endeudamiento),
                unidad="porcentaje",
                fuente=fuente,
            )
        )
    vistas: set[tuple[Decimal, str]] = set()
    unicas: list[CifraEscena] = []
    for item in candidatas:
        clave = (item.valor, item.unidad)
        if clave in vistas:
            continue
        vistas.add(clave)
        unicas.append(item)
    return tuple(unicas)


def _escenario_de_la_opcion(
    resultado: ResultadoDiagnostico,
    *,
    monto: int,
    plazo_meses: int,
    cuota: Decimal,
    total: Decimal | None,
) -> EscenarioEscena:
    """Arma el escenario del diagnóstico cuando no hay una opción A/B elegida.

    Args:
        resultado: diagnóstico de la entrevista.
        monto: monto del diagnóstico.
        plazo_meses: plazo del diagnóstico.
        cuota: cuota exacta.
        total: total pagado.

    Returns:
        El escenario que pinta el panel de cifras con la opción elegida.
    """
    entrada = resultado.entrada
    return EscenarioEscena(
        codigo="entrevista",
        descripcion=f"{entrada.producto} a {plazo_meses} meses",
        producto=entrada.producto,
        monto=Decimal(monto),
        plazo_meses=plazo_meses,
        cuota_mensual=cuota,
        total_pagado=total,
        total_intereses=(
            resultado.total_intereses.hasta if resultado.total_intereses is not None else None
        ),
        semaforo=resultado.semaforo,
        razon_endeudamiento=resultado.razon_endeudamiento,
        margen_despues_cuota=resultado.margen_despues_cuota,
        aceptable=resultado.semaforo != "rojo",
        ofertable=True,
    )


def _continuar_escena(
    resultado: ResultadoDiagnostico,
    respuestas: list[str],
    *,
    publicar: bool,
) -> dict[str, Any]:
    """Prolonga la escena con Don Gota, la comparación y la negociación.

    Reutiliza las mismas herramientas del recorrido (`calcular_prestamo_gota`,
    `comparar_gota_banco` y `negociar_opcion`), de modo que cada una publica sus
    turnos en la escena en vivo en orden. Si un paso falla, el diagnóstico sigue
    y el aviso queda en el resumen y en el registro, sin cifras ni textos.

    Args:
        resultado: diagnóstico completo del motor.
        respuestas: ids canónicos de la entrevista.
        publicar: ``True`` solo en la llamada directa del canal.

    Returns:
        El resumen corto para Pana: oferta de Don Gota, comparación con el banco
        y las opciones A y B, con las `cifras_permitidas` y los avisos.

    Raises:
        ValueError: si el diagnóstico no trae monto, aunque el llamador ya lo
            comprobó con `_diagnostico_completo`.
    """
    entrada = resultado.entrada
    monto_credito = entrada.monto_credito
    if monto_credito is None:
        raise ValueError("el diagnóstico no tiene monto para continuar la escena")
    monto = int(monto_credito)
    resumen: dict[str, Any] = {}
    avisos: list[str] = []
    cifras: list[str] = []

    _publicar_escena(lambda: (_turno_diagnostico(resultado),), publicar=publicar)
    cuota = resultado.cuota_mensual
    diagnostico: dict[str, Any] = {
        "semaforo": resultado.semaforo,
        "monto_legible": formatear_pesos(monto_credito),
        "plazo_legible": formatear_meses(entrada.plazo_meses or 0),
    }
    _agregar_cifras(cifras, [diagnostico["monto_legible"], diagnostico["plazo_legible"]])
    if cuota is not None:
        diagnostico["cuota_desde_legible"] = formatear_pesos(cuota.desde)
        diagnostico["cuota_hasta_legible"] = formatear_pesos(cuota.hasta)
        _agregar_cifras(
            cifras,
            [diagnostico["cuota_desde_legible"], diagnostico["cuota_hasta_legible"]],
        )
    if resultado.total_pagado is not None:
        diagnostico["total_legible"] = formatear_pesos(resultado.total_pagado.desde)
        _agregar_cifras(
            cifras,
            [
                formatear_pesos(resultado.total_pagado.desde),
                formatear_pesos(resultado.total_pagado.hasta),
            ],
        )
    resumen["diagnostico"] = diagnostico

    try:
        gota = calcular_prestamo_gota(monto, publicar=publicar)
    except Exception:  # noqa: BLE001 - la escena no rompe el diagnóstico
        gota = None
    if gota is None or not gota.ok:
        avisos.append(AVISO_GOTA)
        logger.warning("diagnosticar_capacidad escena_continua aviso gota")
    else:
        datos = gota.datos
        resumen["gota"] = {
            "monto_legible": datos.get("monto_legible"),
            "tasa_ea_legible": datos.get("tasa_ea_legible"),
            "total_legible": datos.get("total_pagado_horizonte_legible"),
            "resumen": datos.get("resumen"),
        }
        _agregar_cifras(cifras, datos.get("cifras_permitidas"))

    try:
        comparacion = comparar_gota_banco(monto, respuestas, publicar=publicar)
    except Exception:  # noqa: BLE001 - la escena no rompe el diagnóstico
        comparacion = None
    if comparacion is None or not comparacion.ok:
        avisos.append(AVISO_COMPARACION)
        logger.warning("diagnosticar_capacidad escena_continua aviso comparacion")
    else:
        detalle = comparacion.datos.get("comparacion")
        campos = (
            "tasa_ea_gota_legible",
            "tasa_ea_banco_legible",
            "total_gota_legible",
            "total_banco_legible",
            "diferencia_legible",
            "veces_total_legible",
        )
        if isinstance(detalle, Mapping):
            resumen["comparacion"] = {campo: detalle.get(campo) for campo in campos}
        _agregar_cifras(cifras, comparacion.datos.get("cifras_permitidas"))

    try:
        negociacion = negociar_opcion(respuestas, monto=monto, publicar=publicar)
    except Exception:  # noqa: BLE001 - la escena no rompe el diagnóstico
        negociacion = None
    if negociacion is None or not negociacion.ok:
        avisos.append(AVISO_NEGOCIACION)
        logger.warning("diagnosticar_capacidad escena_continua aviso negociacion")
    else:
        try:
            opciones = _opciones_negociacion(
                negociacion.datos.get("escenarios"),
                monto,
                entrada.producto,
            )
        except Exception:  # noqa: BLE001 - la escena no rompe el diagnóstico
            opciones = []
            avisos.append(AVISO_NEGOCIACION)
            logger.warning("diagnosticar_capacidad escena_continua aviso opciones")
        resumen["opciones"] = opciones
        for opcion in opciones:
            _agregar_cifras(
                cifras,
                [
                    opcion["cuota_mensual_legible"],
                    opcion["plazo_legible"],
                    opcion["total_pagado_legible"],
                ],
            )

    resumen["avisos"] = avisos
    _agregar_cifras(cifras, _cifras_de_la_ficha(resultado))
    resumen["cifras_permitidas"] = cifras[:MAXIMO_CIFRAS_AUDITOR]
    resumen["mensaje_listo"] = _mensaje_resumen(resumen)
    return resumen


def diagnosticar_capacidad(
    respuestas: RespuestasEntrevista,
    monto: MontoExactoEntrada = None,
    *,
    publicar: bool = False,
) -> SalidaHerramienta:
    """Conduce la entrevista y calcula el diagnóstico completo.

    Con respuestas parciales no falla: devuelve `faltan_datos` con la siguiente
    pregunta de la entrevista del canal y sus opciones exactas. Después del
    bloque de monto pide el monto exacto en un paso aparte; cuando llega, lo usa
    si cae dentro de los límites del rango. Si falta `objetivo.*` no supone el
    producto: pregunta «¿Qué quieres hacer?» con las opciones del esquema
    (libre inversión, vehículo, vivienda, etc.).

    Cuando el diagnóstico queda completo —producto, monto y plazo—, la misma
    llamada calcula la oferta de Don Gota, la comparación con el banco y la
    negociación con las funciones del recorrido, publica sus turnos en la
    escena en vivo (si está encendida y `publicar`) y devuelve además el
    `resumen_escena` con las opciones A y B y las `cifras_permitidas` para
    `auditar_respuesta`.

    Args:
        respuestas: ids canónicos de la entrevista en la forma bloque.valor:
            objetivo.* y vinculacion.* (uno de cada lista), ingresos.*,
            gastos.* y cuotas.* (obligatorios), monto.* y plazo.* (en crédito) y
            cuota_trasladar.* (solo en compra de cartera). Puede venir vacía o
            incompleta: la herramienta indica qué preguntar.
        monto: monto exacto que dijo el invitado, en pesos.
        publicar: ``True`` solo cuando el canal conduce la entrevista directo.
            Pana, por el MCP, no publica nada en la pantalla.

    Returns:
        El paso `faltan_datos` con la pregunta y sus opciones, o el resultado
        determinista con cuota, semáforo, alertas y trazabilidad. Con el
        diagnóstico completo añade `resumen_escena`; si un paso de la escena
        falla, el diagnóstico se devuelve igual y el aviso queda en `avisos`.
    """
    fallo = respuestas_o_error("diagnosticar_capacidad", respuestas, parcial=True)
    if fallo is not None:
        return fallo
    entrada = DiagnosticarCapacidadEntrada(respuestas=respuestas, monto=monto)
    pendiente = pregunta_pendiente(entrada.respuestas, entrada.monto)
    if pendiente is not None:
        return ok("diagnosticar_capacidad", pendiente)
    resultado = _diagnostico("diagnosticar_capacidad", entrada.respuestas, monto=entrada.monto)
    if isinstance(resultado, SalidaHerramienta):
        return resultado
    datos: dict[str, Any] = {"resultado": como_json(resultado)}
    if _diagnostico_completo(resultado):
        try:
            resumen = _continuar_escena(resultado, entrada.respuestas, publicar=publicar)
            datos["resumen_escena"] = resumen
            datos["mensaje_listo"] = resumen.get("mensaje_listo")
            datos["cifras_permitidas"] = resumen.get("cifras_permitidas", [])
        except Exception:  # noqa: BLE001 - el diagnóstico nunca se pierde
            logger.warning("diagnosticar_capacidad escena_continua aviso resumen")
    return ok("diagnosticar_capacidad", datos)


def comparar_escenario(
    respuestas: RespuestasEntrevista,
    campo: CampoEscenarioHerramienta,
    valor: float,
    monto: MontoExactoEntrada = None,
) -> SalidaHerramienta:
    """Compara un «¿Y si…?» contra el diagnóstico original, sin el grafo.

    Args:
        respuestas: ids canónicos de la entrevista original, como en
            `diagnosticar_capacidad`.
        campo: insumo que cambia (`monto_credito`, `plazo_meses`, `ingreso_mensual`,
            `gastos_mensuales` o `cuotas_deudas`).
        valor: valor nuevo del insumo.
        monto: monto exacto que dijo el invitado; se usa igual que en
            `diagnosticar_capacidad`.

    Returns:
        El escenario calculado y la comparación con su tendencia.
    """
    fallo = respuestas_o_error("comparar_escenario", respuestas)
    if fallo is not None:
        return fallo
    entrada = CompararEscenarioEntrada(
        respuestas=respuestas,
        monto=monto,
        campo=campo,
        valor=valor,
    )
    resultado = _diagnostico("comparar_escenario", entrada.respuestas, monto=entrada.monto)
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


def convocar_comite(
    respuestas: RespuestasEntrevista,
    monto: MontoExactoEntrada = None,
) -> SalidaHerramienta:
    """Convoca el comité de crédito cuando el diagnóstico es amarillo o rojo.

    El comité usa el modelo de DeepSeek del proyecto. Sin `DEEPSEEK_API_KEY` la
    herramienta no inventa una deliberación: devuelve los escenarios
    precalculados y un error explicable para que el agente ofrezca el respaldo.

    Args:
        respuestas: ids canónicos de la entrevista, como en
            `diagnosticar_capacidad`.
        monto: monto exacto que dijo el invitado; se usa igual que en
            `diagnosticar_capacidad`.

    Returns:
        La deliberación con posturas, recomendación y hallazgos, o el motivo por
        el que no se convocó.
    """
    fallo = respuestas_o_error("convocar_comite", respuestas)
    if fallo is not None:
        return fallo
    entrada = ConvocarComiteEntrada(respuestas=respuestas, monto=monto)
    resultado = _diagnostico("convocar_comite", entrada.respuestas, monto=entrada.monto)
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


def calcular_prestamo_gota(monto: int, *, publicar: bool = False) -> SalidaHerramienta:
    """Calcula el préstamo de Don Gota con la aritmética de la escena.

    Cada cifra viaja con su ``valor_legible`` en formato colombiano y con
    ``cifras_permitidas`` para ``auditar_respuesta``. La tasa E.A. se entrega
    como ``791,61 % E.A.`` y el identificador de la fórmula queda solo en
    ``metadatos``: nunca en un campo de texto que el modelo pueda copiar.

    Args:
        monto: capital en pesos.
        publicar: ``True`` solo en la llamada directa del canal; Pana no publica.

    Returns:
        Interés, cuota diaria, totales y tasa E.A. equivalente, con su fuente,
        sus cifras legibles y el resumen para leer en voz alta.
    """
    entrada = CalcularPrestamoGotaEntrada(monto=monto)
    prestamo = _calcular_gota(entrada.monto)
    datos = como_json(prestamo)
    version = datos.pop("version_formula", None)
    datos["metadatos"] = {
        "version_formula": version,
        "dias_ciclo": prestamo.dias_ciclo,
        "meses_horizonte": prestamo.meses_horizonte,
        "supuesto": prestamo.supuesto,
    }
    datos["resumen"] = (
        f"{formatear_pesos(prestamo.monto)} al "
        f"{formatear_porcentaje(prestamo.tasa_mensual)} mensual: "
        f"interés de {formatear_pesos(prestamo.interes_mensual)} y cuota diaria de "
        f"{formatear_pesos(prestamo.cuota_diaria)}."
    )
    anotar(
        datos,
        (
            cifra(
                "monto",
                prestamo.monto,
                formatear_pesos(prestamo.monto),
                "pesos",
                etiqueta="monto prestado",
            ),
            cifra(
                "tasa_mensual",
                prestamo.tasa_mensual,
                f"{formatear_porcentaje(prestamo.tasa_mensual)} mensual",
                "porcentaje",
                etiqueta="tasa mensual",
            ),
            cifra(
                "interes_mensual",
                prestamo.interes_mensual,
                formatear_pesos(prestamo.interes_mensual),
                "pesos",
                etiqueta="interés del ciclo",
            ),
            cifra(
                "total_ciclo",
                prestamo.total_ciclo,
                formatear_pesos(prestamo.total_ciclo),
                "pesos",
                etiqueta="total del ciclo",
            ),
            cifra(
                "cuota_diaria",
                prestamo.cuota_diaria,
                formatear_pesos(prestamo.cuota_diaria),
                "pesos",
                etiqueta="cuota diaria",
            ),
            cifra(
                "dias_ciclo",
                prestamo.dias_ciclo,
                formatear_dias(prestamo.dias_ciclo),
                "dias",
                etiqueta="días del ciclo",
            ),
            cifra(
                "meses_horizonte",
                prestamo.meses_horizonte,
                formatear_meses(prestamo.meses_horizonte),
                "meses",
                etiqueta="meses del horizonte",
            ),
            cifra(
                "intereses_horizonte",
                prestamo.intereses_horizonte,
                formatear_pesos(prestamo.intereses_horizonte),
                "pesos",
                etiqueta=f"intereses de {formatear_meses(prestamo.meses_horizonte)}",
            ),
            cifra(
                "total_pagado_horizonte",
                prestamo.total_pagado_horizonte,
                formatear_pesos(prestamo.total_pagado_horizonte),
                "pesos",
                etiqueta="total pagado en el horizonte",
            ),
            cifra(
                "tasa_ea",
                prestamo.tasa_ea,
                formatear_tasa_ea(prestamo.tasa_ea),
                "porcentaje_ea",
                etiqueta="tasa efectiva anual",
            ),
        ),
    )
    _publicar_escena(lambda: turnos_don_gota(prestamo, perfil="vivo"), publicar=publicar)
    return ok("calcular_prestamo_gota", datos)


def comparar_gota_banco(
    monto: int,
    respuestas: RespuestasEntrevista,
    *,
    publicar: bool = False,
) -> SalidaHerramienta:
    """Compara el gota a gota con el banco y con la usura vigente.

    La comparación es siempre contra **libre inversión a la tasa máxima del
    banco**, aunque las respuestas nombren otro producto: la escena conserva ese
    producto y las cifras verificadas de la demostración.

    Las tasas y los totales se devuelven con ``valor_legible`` y el bloque
    ``cifras_permitidas``; el identificador de la fórmula del préstamo no sale
    en ningún campo de texto.

    Args:
        monto: mismo monto para los dos lados.
        respuestas: ids canónicos de la entrevista con ingresos, gastos, deudas,
            monto y plazo, como en ``diagnosticar_capacidad``. El producto de
            estas respuestas no cambia el lado del banco: siempre es libre
            inversión a la tasa máxima.
        publicar: ``True`` solo en la llamada directa del canal; Pana no publica.

    Returns:
        La comparación con los totales, la usura y los supuestos, con sus cifras
        legibles listas para auditar.
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
    detalle = como_json(comparacion)
    cifras = [
        cifra(
            "monto",
            comparacion.monto,
            formatear_pesos(comparacion.monto),
            "pesos",
            etiqueta="monto del préstamo",
        ),
        cifra(
            "plazo_meses",
            comparacion.plazo_meses,
            formatear_meses(comparacion.plazo_meses),
            "meses",
            etiqueta="plazo del horizonte",
        ),
        cifra(
            "tasa_ea_gota",
            comparacion.tasa_ea_gota,
            formatear_tasa_ea(comparacion.tasa_ea_gota),
            "porcentaje_ea",
            etiqueta="tasa E.A. de Don Gota",
        ),
        cifra(
            "tasa_ea_banco",
            comparacion.tasa_ea_banco,
            formatear_tasa_ea(comparacion.tasa_ea_banco),
            "porcentaje_ea",
            etiqueta="tasa E.A. máxima del banco",
        ),
        cifra(
            "total_gota",
            comparacion.total_gota,
            formatear_pesos(comparacion.total_gota),
            "pesos",
            etiqueta="total pagado con Don Gota",
        ),
        cifra(
            "total_banco",
            comparacion.total_banco,
            formatear_pesos(comparacion.total_banco),
            "pesos",
            etiqueta="total pagado con el banco",
        ),
        cifra(
            "diferencia",
            comparacion.diferencia,
            formatear_pesos(comparacion.diferencia),
            "pesos",
            etiqueta="diferencia entre los dos totales",
        ),
    ]
    if comparacion.usura_ea is not None:
        cifras.append(
            cifra(
                "usura_ea",
                comparacion.usura_ea,
                formatear_tasa_ea(comparacion.usura_ea),
                "porcentaje_ea",
                etiqueta="usura vigente",
            )
        )
    if comparacion.veces_total is not None:
        cifras.append(
            cifra(
                "veces_total",
                comparacion.veces_total,
                formatear_veces(comparacion.veces_total),
                "veces",
                etiqueta="veces el total del banco",
            )
        )
    if comparacion.veces_usura is not None:
        cifras.append(
            cifra(
                "veces_usura",
                comparacion.veces_usura,
                formatear_veces(comparacion.veces_usura),
                "veces",
                etiqueta="veces la usura",
            )
        )
    anotar(detalle, cifras)
    _publicar_escena(
        lambda: turnos_pana_comparacion(comparacion, orden_inicial=8), publicar=publicar
    )
    return ok(
        "comparar_gota_banco",
        {
            "comparacion": detalle,
            "alertas": list(alertas_comparacion(comparacion)),
            "cifras": detalle["cifras"],
            "cifras_permitidas": detalle["cifras_permitidas"],
        },
    )


def negociar_opcion(
    respuestas: RespuestasEntrevista,
    monto: MontoExactoEntrada = None,
    *,
    publicar: bool = False,
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
        publicar: ``True`` solo en la llamada directa del canal; Pana no publica.

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
    _publicar_escena(
        lambda: tuple(
            turno
            for turno in resultado.negociacion.turnos
            if turno.personaje in {"agente_joven", "agente_banco"}
        ),
        publicar=publicar,
    )
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
    opcion: Literal["A", "B"] | None = None,
    *,
    publicar: bool = False,
    devolver_imagen: bool = False,
) -> SalidaHerramienta:
    """Genera la ficha de la opción elegida y su cierre corto para WhatsApp.

    Con la letra elegida (`A` o `B`) la ficha usa el monto y el plazo de esa
    opción, y el turno de la escena lleva su escenario y sus cifras para que el
    panel se actualice. La ficha se deja para que el canal la envíe como
    mensaje aparte; Pana solo responde el `mensaje_listo`.

    Args:
        respuestas: ids canónicos de la entrevista, como en
            `diagnosticar_capacidad`.
        monto: monto exacto que dijo el invitado. Si se pasa, debe ser el mismo
            que se usó en `calcular_prestamo_gota`; reemplaza el valor de
            cálculo del rango solo si cae dentro de sus límites y, si no, la
            herramienta devuelve `entrada_invalida` con los límites. Sin este
            campo se usa el valor del rango.
        opcion: letra de la opción que eligió el invitado (`A` o `B`); sin ella
            se usa el plazo de la entrevista.
        publicar: ``True`` solo cuando el canal conduce la escena directo.
        devolver_imagen: ``True`` cuando el canal, que ya tiene el número del
            voluntario, envía la ficha en el mismo turno: devuelve el PNG en
            `png_base64` y no deja `data/escena/ficha_entrega.json`.

    Returns:
        El texto de la ficha, su cierre corto (`mensaje_listo`), las cifras que
        puede citar (`cifras_permitidas`) y el escenario de la opción.
    """
    fallo = respuestas_o_error("generar_ficha_opcion", respuestas)
    if fallo is not None:
        return fallo
    entrada = GenerarFichaOpcionEntrada(
        respuestas=respuestas,
        monto=monto,
        opcion=opcion,
    )
    resultado = _diagnostico("generar_ficha_opcion", entrada.respuestas, monto=entrada.monto)
    if isinstance(resultado, SalidaHerramienta):
        return resultado

    escenario: EscenarioEscena | None = None
    if entrada.opcion is not None:
        escenarios, opciones = _escenarios_sin_publicar(entrada.respuestas, entrada.monto)
        elegida = next(
            (opcion_ab for opcion_ab in opciones if opcion_ab.get("letra") == entrada.opcion),
            None,
        )
        if elegida is not None:
            datos = next(
                (
                    escenario_ab
                    for escenario_ab in escenarios
                    if escenario_ab.get("codigo") == elegida.get("codigo")
                ),
                None,
            )
            if datos is not None:
                try:
                    escenario = EscenarioEscena.model_validate(datos)
                    ajustada = _entrada_de_la_opcion(
                        entrada.respuestas,
                        int(escenario.monto),
                        escenario.plazo_meses,
                    )
                    resultado = calcular(ajustada)
                except Exception:  # noqa: BLE001 - la ficha no se pierde por la opción
                    escenario = None
                    logger.warning("generar_ficha_opcion no pudo recalcular la opción")

    imagen, texto = tarjeta_y_texto(resultado)
    ficha = texto.strip()
    monto_final = (
        int(escenario.monto)
        if escenario is not None
        else (
            int(resultado.entrada.monto_credito)
            if resultado.entrada.monto_credito is not None
            else None
        )
    )
    plazo_final = (
        escenario.plazo_meses
        if escenario is not None and escenario.plazo_meses is not None
        else resultado.entrada.plazo_meses
    )
    cuota_final = (
        escenario.cuota_mensual
        if escenario is not None
        else (resultado.cuota_mensual.desde if resultado.cuota_mensual is not None else None)
    )
    total_final = (
        escenario.total_pagado
        if escenario is not None
        else (resultado.total_pagado.desde if resultado.total_pagado is not None else None)
    )
    if escenario is None and monto_final is not None and plazo_final and cuota_final is not None:
        escenario = _escenario_de_la_opcion(
            resultado,
            monto=monto_final,
            plazo_meses=int(plazo_final),
            cuota=cuota_final,
            total=total_final,
        )

    letra = f"la opción {entrada.opcion}" if entrada.opcion else "esta opción"
    if monto_final is not None and plazo_final and cuota_final is not None:
        cierre = (
            f"Elegiste {letra}: {formatear_pesos(monto_final)} a "
            f"{formatear_meses(plazo_final)}, cuota de {formatear_pesos(cuota_final)} al mes"
        )
        if total_final is not None:
            cierre += f" y total de {formatear_pesos(total_final)}"
        mensaje_listo = (
            f"{cierre}. Ya te envié la ficha por WhatsApp. "
            "Es orientativo: la decisión es del banco."
        )
    else:
        mensaje_listo = (
            "Ya te envié la ficha por WhatsApp. Es orientativo: la decisión es del banco."
        )

    cifras_permitidas = _cifras_de_la_ficha(
        resultado,
        monto=monto_final,
        plazo_meses=int(plazo_final) if plazo_final else None,
        cuota=cuota_final,
        total=total_final,
    )
    cifras_turno = (
        _cifras_del_turno_ficha(
            resultado,
            monto=monto_final,
            plazo_meses=int(plazo_final),
            cuota=cuota_final,
            total=total_final,
        )
        if monto_final is not None and plazo_final and cuota_final is not None
        else ()
    )

    if ficha:
        _publicar_ficha(
            TurnoEscena(
                id="vivo.ficha.v1",
                orden=91,
                personaje="pana",
                texto=texto,
                subtitulo="Ficha de la opción",
                cifras=cifras_turno,
                escenario=escenario,
                origen="reglas",
            ),
            publicar=publicar,
        )
        if not devolver_imagen:
            dejar_ficha(texto, imagen)
    salida: dict[str, Any] = {
        "texto": texto,
        "mensaje_listo": mensaje_listo,
        "cifras_permitidas": cifras_permitidas,
        "opcion": entrada.opcion,
        "escenario": como_json(escenario),
        "png_bytes": len(imagen),
        "semaforo": resultado.semaforo,
        "cuota_mensual": como_json(resultado.cuota_mensual),
        "tasa_ea": como_json(resultado.tasa_ea),
        "aviso": resultado.aviso,
    }
    if devolver_imagen and imagen:
        salida["png_base64"] = base64.b64encode(imagen).decode("ascii")
    return ok("generar_ficha_opcion", salida)


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
    *,
    publicar: bool = False,
) -> SalidaHerramienta:
    """Revisa un texto antes de enviarlo, con el auditor de la escena y el del comité.

    Delega en `mcp_servidor/control.py` (#199) y suma las frases de promesa y
    los datos personales de `auditar_texto` del comité. Toda cifra del texto
    debe estar en `cifras_permitidas`: sin lista, cualquier cifra es
    `cifra_inventada`. No cuentan las referencias legales («Ley 1581 de 2012»)
    ni los años sueltos. También detecta la fuga de instrucciones.

    Args:
        texto: lo que se quiere auditar.
        cifras_permitidas: cifras que el texto puede citar; normalmente se pasa
            el `cifras_permitidas` que devuelve la herramienta. Acepta el texto
            legible («791,61 % E.A.») y también los dígitos de máquina.
        personaje: quién envía el texto.
        publicar: ``True`` solo cuando el canal conduce la escena directo; el
            turno del auditor no se publica desde el MCP.

    Returns:
        `conforme`, el veredicto, si se puede enviar y los hallazgos en español.
    """
    entrada = AuditarRespuestaEntrada(texto=texto, cifras_permitidas=cifras_permitidas)
    revision = control.auditar_respuesta(
        control.AuditarRespuestaEntrada(texto=entrada.texto, personaje=personaje)
    )
    permitidas: set[str] = set()
    for permitida in (entrada.cifras_permitidas or [])[:MAXIMO_CIFRAS_AUDITOR]:
        permitidas |= cifras_duras(permitida) or {permitida.strip()}
    hallazgos = [h for h in revision.hallazgos if h.codigo != "cifra_inventada"]
    for inventada in sorted(control.cifras_sin_respaldo(entrada.texto) - permitidas):
        hallazgos.append(
            HallazgoEscena(
                codigo="cifra_inventada",
                turno_id=control.ID_RESPUESTA,
                detalle=f"El texto dice {inventada} y no está entre las cifras permitidas.",
                gravedad="alta",
            )
        )
    del_comite = auditar_texto(entrada.texto)
    veredicto = "objeta" if del_comite else veredicto_desde_hallazgos(hallazgos)
    todos = tuple(hallazgos) + tuple(
        HallazgoEscena(
            codigo=detalle.partition(": ")[0] or "auditoria",
            detalle=detalle,
            gravedad="alta",
        )
        for detalle in del_comite
    )
    _publicar_escena(
        lambda: (
            turno_auditor(
                VeredictoAuditor(
                    veredicto=veredicto,
                    hallazgos=todos,
                    turnos_revisados=(),
                    reglas=(),
                ),
                orden=90,
            ).model_copy(update={"hallazgos": todos}),
        ),
        publicar=publicar,
    )
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
