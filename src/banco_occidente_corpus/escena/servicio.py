"""Servicio de la escena: arma la fase 1, la fase 2 y el núcleo sin estado.

Todo se recalcula desde `PerfilEscena`: el servicio no acepta cifras del cliente,
no crea SQLite, no guarda el perfil y no habla con la red. La fase 1 trae el
perfil, el diagnóstico, Don Gota, la comparación y los turnos base; la fase 2
trae la negociación y el veredicto del auditor. Dos llamadas con el mismo perfil
dan las mismas cifras y los mismos turnos.

Las pruebas viven en ``test/test_escena_servicio.py``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal

from ..canal.contratos import ResultadoDiagnostico
from ..config import PROJECT_ROOT
from ..diagnostico import motor
from .auditor import auditar_escena, cierre_pana, crear_auditor_negociacion, turno_auditor
from .comparacion import alertas_comparacion, comparar_gota_banco, turnos_pana_comparacion
from .contratos import (
    ComparacionGota,
    Escena,
    NegociacionEscena,
    PerfilEscena,
    PrestamoGota,
    RespuestaEscena,
    SeleccionVoluntario,
    TurnoEscena,
)
from .entrada import PREGUNTAS
from .gota import calcular_prestamo_gota, formatear_pesos, turnos_don_gota
from .negociacion import construir_mesa, negociar
from .perfiles import entrada_del_perfil

#: Identificador estable de la escena; no cambia entre corridas.
ID_ESCENA = "escena.gota_a_gota.v1"
#: Carpeta de los JSON de respaldo, ignorada por Git.
RUTA_SALIDA = "data/escena"
#: Modos posibles del contrato `Escena`.
ModoEscena = Literal["vivo", "seguro", "nucleo", "proyectado"]
#: Archivos cuyo hash queda en `Escena.sellos` para la trazabilidad.
ARCHIVOS_SELLO: tuple[str, ...] = (
    "config/diagnostico.toml",
    "config/tasas.toml",
    "config/escena.toml",
)


def construir_perfil(
    respuestas: Sequence[RespuestaEscena],
    *,
    monto_declarado: Decimal | None = None,
    confirmado: bool = True,
    personaje: str = "Voluntario de la sala",
    proposito: str = "Crédito de libre inversión",
) -> PerfilEscena:
    """Arma un `PerfilEscena` a partir de las cuatro respuestas.

    Args:
        respuestas: una respuesta por pregunta (`monto`, `ingresos`, `gastos`,
            `deudas`), sin repetir.
        monto_declarado: monto que dijo el voluntario; si falta, el de la
            tarjeta de monto.
        confirmado: si Pana ya confirmó las respuestas.
        personaje: descripción ficticia, sin datos personales.
        proposito: para qué pide el crédito.

    Returns:
        El perfil de la escena.

    Raises:
        ValueError: si faltan preguntas, se repiten o el monto no es positivo.
    """
    por_pregunta = {respuesta.pregunta: respuesta for respuesta in respuestas}
    faltan = [pregunta for pregunta in PREGUNTAS if pregunta not in por_pregunta]
    if faltan:
        raise ValueError("faltan respuestas: " + ", ".join(faltan))
    if len(por_pregunta) != len(PREGUNTAS):
        raise ValueError("hay respuestas repetidas en el perfil")
    ordenadas = tuple(por_pregunta[pregunta] for pregunta in PREGUNTAS)
    calculo = por_pregunta["monto"].valor
    declarado = monto_declarado if monto_declarado is not None else calculo
    if calculo <= 0 or declarado <= 0:
        raise ValueError("el monto del perfil debe ser positivo")
    return PerfilEscena(
        personaje=personaje,
        proposito=proposito,
        monto_declarado=declarado,
        monto_calculo=calculo,
        respuestas=ordenadas,
        confirmado=confirmado,
    )


def _sha256(ruta: Path) -> str:
    """Devuelve el hash de un archivo o una cadena vacía si no existe."""
    return sha256(ruta.read_bytes()).hexdigest() if ruta.is_file() else ""


def _tabla_de_tasas(raiz: Path) -> Path | None:
    """Busca la tabla Gold de tasas más reciente, si existe."""
    carpeta = raiz / "data" / "gold" / "tasas"
    if not carpeta.is_dir():
        return None
    tablas = sorted(carpeta.glob("tasas-personas-*.jsonl"))
    return tablas[-1] if tablas else None


def sellos(raiz: Path | None = None) -> dict[str, str]:
    """Calcula los sellos de los archivos que sostienen las cifras.

    Args:
        raiz: carpeta del repositorio; por defecto la del proyecto.

    Returns:
        El hash de cada configuración y de la tabla Gold de tasas, si existe.
    """
    base = raiz if raiz is not None else PROJECT_ROOT
    resultado = {nombre: _sha256(base / nombre) for nombre in ARCHIVOS_SELLO}
    tabla = _tabla_de_tasas(base)
    if tabla is not None:
        resultado["gold_tasas"] = _sha256(tabla)
    return {clave: valor for clave, valor in resultado.items() if valor}


def _apertura(seleccion: SeleccionVoluntario | None) -> TurnoEscena:
    """Arma el turno con que Pana abre y, si hay, menciona al voluntario."""
    texto = (
        "Hola, soy Pana. Hoy te acompañan Don Gota y dos agentes. "
        "Vamos a ver, con tus cifras, cuánto cuesta de verdad un préstamo."
    )
    if seleccion is not None:
        texto = f"{texto} Le toca a la fila {seleccion.fila}, silla {seleccion.silla}."
    return TurnoEscena(
        id="pana.apertura.v1",
        orden=0,
        personaje="pana",
        texto=texto,
        origen="guion_fijo",
    )


def _confirmacion(perfil: PerfilEscena, orden: int) -> TurnoEscena:
    """Repite las cuatro respuestas y el monto antes de seguir."""
    por_pregunta = {respuesta.pregunta: respuesta for respuesta in perfil.respuestas}
    partes = [
        f"monto {por_pregunta['monto'].texto} ({formatear_pesos(perfil.monto_calculo)})",
        f"ingresos {por_pregunta['ingresos'].texto}",
        f"gastos {por_pregunta['gastos'].texto}",
        f"deudas {por_pregunta['deudas'].texto}",
    ]
    return TurnoEscena(
        id="pana.confirmacion.v1",
        orden=orden,
        personaje="pana",
        texto="Confirmo tus respuestas: " + ", ".join(partes) + ". ¿Está bien?",
        origen="entrada_voz",
    )


def _alertas(diagnostico: ResultadoDiagnostico, comparacion: ComparacionGota) -> tuple[str, ...]:
    """Junta las alertas del motor y de la comparación para el auditor."""
    return tuple(dict.fromkeys([*diagnostico.alertas, *alertas_comparacion(comparacion)]))


def _mejor_semaforo(diagnostico: ResultadoDiagnostico) -> str | None:
    """Devuelve el semáforo del diagnóstico, si el motor lo calculó."""
    return diagnostico.semaforo


def _turnos_base(
    perfil: PerfilEscena,
    prestamo: PrestamoGota,
    comparacion: ComparacionGota,
    *,
    seleccion: SeleccionVoluntario | None,
) -> tuple[TurnoEscena, ...]:
    """Arma la fase 1: Pana abre, Don Gota ofrece y Pana compara."""
    apertura = _apertura(seleccion)
    confirmacion = _confirmacion(perfil, orden=1)
    gota = turnos_don_gota(prestamo, perfil=perfil.personaje, orden_inicial=2)
    comparacion_turnos = turnos_pana_comparacion(comparacion, orden_inicial=2 + len(gota))
    return (apertura, confirmacion, *gota, *comparacion_turnos)


def construir_escena(
    perfil: PerfilEscena,
    *,
    seleccion: SeleccionVoluntario | None = None,
    modo: ModoEscena = "vivo",
    incluir_negociacion: bool = False,
    raiz: Path | None = None,
    hoy: date | None = None,
    entorno: Mapping[str, str] | None = None,
) -> Escena:
    """Arma la escena de fase 1 y, si se pide, la completa con la negociación.

    Args:
        perfil: perfil confirmado del voluntario o perfil seguro.
        seleccion: fila y silla elegidas, si hubo voluntario.
        modo: `vivo`, `seguro`, `nucleo` o `proyectado`.
        incluir_negociacion: si añade los turnos de la fase 2 y el cierre.
        raiz: carpeta de tablas Gold alternativa.
        hoy: fecha con la que se comprueba la vigencia de la tasa.
        entorno: variables para decidir el modo demo de la negociación.

    Returns:
        La escena con su diagnóstico, Don Gota, la comparación y los turnos.

    Raises:
        TasaNoDisponible: si el Tablero no publica la tasa del producto.
        ValueError: si el perfil no trae las cuatro respuestas.
    """
    entrada = entrada_del_perfil(perfil)
    diagnostico = motor.calcular(entrada, hoy=hoy, raiz=raiz)
    prestamo = calcular_prestamo_gota(perfil.monto_calculo)
    comparacion = comparar_gota_banco(prestamo, entrada, raiz=raiz, hoy=hoy)
    escenarios = construir_mesa(entrada, hoy=hoy, raiz=raiz)
    turnos = _turnos_base(perfil, prestamo, comparacion, seleccion=seleccion)
    alertas = _alertas(diagnostico, comparacion)
    veredicto = auditar_escena(
        turnos,
        alertas=alertas,
        semaforo=_mejor_semaforo(diagnostico),
    )
    fase1 = Escena(
        id=ID_ESCENA,
        modo=modo,
        perfil=perfil,
        seleccion=seleccion,
        diagnostico=diagnostico,
        gota=prestamo,
        comparacion=comparacion,
        escenarios=escenarios,
        turnos=turnos,
        veredicto=veredicto,
        sellos=sellos(raiz),
    )
    if not incluir_negociacion:
        return fase1
    negociacion = construir_negociacion(
        perfil,
        seleccion=seleccion,
        raiz=raiz,
        hoy=hoy,
        base=fase1,
        entorno=entorno,
    )
    return fase1.model_copy(
        update={
            "turnos": fase1.turnos + negociacion.turnos,
            "escenarios": negociacion.escenarios,
            "veredicto": negociacion.veredicto,
        }
    )


def _siguiente_orden(turnos: Iterable[TurnoEscena]) -> int:
    """Devuelve el orden que sigue después del último turno."""
    return max((turno.orden for turno in turnos), default=-1) + 1


def construir_negociacion(
    perfil: PerfilEscena,
    *,
    seleccion: SeleccionVoluntario | None = None,
    raiz: Path | None = None,
    hoy: date | None = None,
    base: Escena | None = None,
    entorno: Mapping[str, str] | None = None,
) -> NegociacionEscena:
    """Arma la fase 2: cuatro turnos, el veredicto sobre toda la escena y el cierre.

    Args:
        perfil: perfil confirmado o perfil seguro.
        seleccion: fila y silla elegidas, si las hay.
        raiz: carpeta de tablas Gold alternativa.
        hoy: fecha con la que se comprueba la vigencia de la tasa.
        base: fase 1 ya construida, para no recalcularla.
        entorno: variables para decidir el modo demo de la negociación.

    Returns:
        Los turnos de la negociación, el veredicto y el cierre de Pana.

    Raises:
        TasaNoDisponible: si el Tablero no publica la tasa del producto.
        ValueError: si el perfil no trae las cuatro respuestas.
    """
    fase1 = (
        base
        if base is not None
        else construir_escena(
            perfil,
            seleccion=seleccion,
            raiz=raiz,
            hoy=hoy,
        )
    )
    alertas = _alertas(fase1.diagnostico, fase1.comparacion)
    auditor = crear_auditor_negociacion(alertas=alertas, semaforo=fase1.diagnostico.semaforo)
    resultado = negociar(
        perfil,
        auditor=auditor,
        hoy=hoy,
        raiz=raiz,
        entorno=entorno,
        orden_inicial=_siguiente_orden(fase1.turnos),
    )
    mesa = resultado.negociacion.escenarios
    turnos_negociacion = resultado.negociacion.turnos
    completos = fase1.turnos + turnos_negociacion
    veredicto = auditar_escena(
        completos,
        mesa=mesa,
        acuerdo=resultado.acuerdo,
        alertas=alertas,
        exigir_negociacion=True,
        semaforo=fase1.diagnostico.semaforo,
    )
    orden = _siguiente_orden(turnos_negociacion)
    cierre = (
        turno_auditor(veredicto, orden=orden),
        cierre_pana(veredicto, orden=orden + 1),
    )
    return NegociacionEscena(
        turnos=turnos_negociacion + cierre,
        escenarios=mesa,
        veredicto=veredicto,
        registro=resultado.negociacion.registro,
    )


def construir_nucleo(
    perfil: PerfilEscena,
    *,
    seleccion: SeleccionVoluntario | None = None,
    raiz: Path | None = None,
    hoy: date | None = None,
) -> Escena:
    """Arma el núcleo de respaldo: Don Gota, Pana y el auditor, sin negociación.

    Args:
        perfil: perfil confirmado o perfil seguro.
        seleccion: fila y silla elegidas, si las hay.
        raiz: carpeta de tablas Gold alternativa.
        hoy: fecha con la que se comprueba la vigencia de la tasa.

    Returns:
        La escena en `modo="nucleo"`, con el veredicto del auditor.

    Raises:
        TasaNoDisponible: si el Tablero no publica la tasa del producto.
        ValueError: si el perfil no trae las cuatro respuestas.
    """
    base = construir_escena(perfil, seleccion=seleccion, raiz=raiz, hoy=hoy)
    nucleo = tuple(turno for turno in base.turnos if turno.personaje in {"pana", "don_gota"})
    veredicto = auditar_escena(
        nucleo,
        alertas=_alertas(base.diagnostico, base.comparacion),
        semaforo=base.diagnostico.semaforo,
    )
    orden = _siguiente_orden(nucleo)
    turnos = nucleo + (
        turno_auditor(veredicto, orden=orden),
        cierre_pana(veredicto, orden=orden + 1),
    )
    return Escena(
        id=ID_ESCENA,
        modo="nucleo",
        perfil=perfil,
        seleccion=seleccion,
        diagnostico=base.diagnostico,
        gota=base.gota,
        comparacion=base.comparacion,
        escenarios=base.escenarios,
        turnos=turnos,
        veredicto=veredicto,
        sellos=base.sellos,
    )


def guardar_escena(escena: Escena, ruta: Path) -> Path:
    """Escribe una escena en JSON, creando la carpeta si hace falta.

    Args:
        escena: escena validada.
        ruta: archivo de destino.

    Returns:
        La ruta escrita.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(escena.model_dump_json(indent=2), encoding="utf-8")
    return ruta


def resumen_escena(escena: Escena) -> str:
    """Devuelve el resumen corto que imprime el CLI.

    Args:
        escena: escena ya construida.

    Returns:
        Un texto con el modo, los turnos, el veredicto y los sellos.
    """
    turnos = ", ".join(turno.id for turno in escena.turnos)
    sellos_cortos = ", ".join(f"{clave}={valor[:12]}" for clave, valor in escena.sellos.items())
    return (
        f"Escena {escena.id} ({escena.modo}): {len(escena.turnos)} turnos.\n"
        f"Turnos: {turnos}\n"
        f"Veredicto: {escena.veredicto.veredicto} "
        f"({len(escena.veredicto.hallazgos)} hallazgos).\n"
        f"Sellos: {sellos_cortos or 'sin archivos'}."
    )
