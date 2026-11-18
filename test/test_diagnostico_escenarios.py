"""Pruebas sin red de los escenarios «¿Y si…?» (OpenSpec corresponsal-whatsapp, 8.2 y 8.3).

Usan un grafo de diagnóstico simulado con ``InMemorySaver`` y un motor de
cálculo de prueba (cuota francesa con una tasa fija), para comprobar la
bifurcación sin depender del grafo real ni del motor de Nayla:

- el escenario cambia el plazo y compara cuota y semáforo;
- el hilo original conserva sus valores y su checkpoint;
- un monto o plazo fuera de rango explica el límite y no crea la rama.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from banco_occidente_corpus.canal.contratos import (
    EntradaDiagnostico,
    RangoDecimal,
    ResultadoDiagnostico,
)
from banco_occidente_corpus.diagnostico.escenarios import (
    MAXIMO_ESCENARIOS,
    CambioEscenario,
    DiagnosticoNoTerminado,
    EscenarioFueraDeRango,
    aplicar_cambio,
    bifurcar_escenario,
    formatear_pesos,
    formatear_rango,
    interpretar_pedido,
)

USUARIO = "h" * 64
HILO = f"diag:{USUARIO}"
#: Tasa mensual fija del motor de prueba (≈ 26,8 % E.A.).
TASA_MENSUAL = Decimal("0.02")


class EstadoPrueba(TypedDict, total=False):
    """Subconjunto del estado del diagnóstico que usa la bifurcación."""

    etapa: str
    entrada: dict[str, Any]
    resultado: dict[str, Any]
    escenario: dict[str, Any]
    respuestas: dict[str, str]


def calcular(entrada: EntradaDiagnostico) -> ResultadoDiagnostico:
    """Motor de prueba: cuota francesa con tasa fija y semáforo 0,30/0,40."""
    n = entrada.plazo_meses
    factor = (1 + TASA_MENSUAL) ** n
    cuota = (entrada.monto_credito * TASA_MENSUAL * factor / (factor - 1)).quantize(Decimal(1))
    razon = ((entrada.cuotas_deudas + cuota) / entrada.ingreso_mensual).quantize(Decimal("0.0001"))
    semaforo = (
        "verde" if razon <= Decimal("0.30") else "amarillo" if razon <= Decimal("0.40") else "rojo"
    )
    total = cuota * n

    def fijo(valor: Decimal) -> RangoDecimal:
        """Rango con los dos extremos iguales."""
        return RangoDecimal(desde=valor, hasta=valor)

    return ResultadoDiagnostico(
        entrada=entrada,
        tasa_ea=fijo(Decimal("0.2682")),
        tasa_mensual=fijo(TASA_MENSUAL),
        cuota_mensual=fijo(cuota),
        total_intereses=fijo(total - entrada.monto_credito),
        total_pagado=fijo(total),
        razon_endeudamiento=razon,
        capacidad_pago=entrada.ingreso_mensual
        - entrada.gastos_mensuales
        - entrada.cuotas_deudas
        - cuota,
        semaforo=semaforo,
        recomendaciones=[],
        fuente_tasa="prueba",
        vigencia_tasa_desde=date(2026, 11, 1),
        vigencia_tasa_hasta=date(2026, 11, 30),
        sha256_pdf="0" * 64,
        umbrales={"verde_hasta": Decimal("0.30"), "amarillo_hasta": Decimal("0.40")},
        aviso="Orientativo.",
    )


def construir_grafo() -> Any:
    """Grafo mínimo calcular → cerrar con checkpointer en memoria."""

    def nodo_calcular(estado: EstadoPrueba) -> EstadoPrueba:
        """Calcula el resultado desde la entrada."""
        resultado = calcular(EntradaDiagnostico.model_validate(estado["entrada"]))
        return {"resultado": resultado.model_dump(mode="json"), "etapa": "calculo"}

    def nodo_cerrar(estado: EstadoPrueba) -> EstadoPrueba:
        """Marca el diagnóstico como terminado."""
        return {"etapa": "terminado"}

    constructor = StateGraph(EstadoPrueba)
    constructor.add_node("calcular", nodo_calcular)
    constructor.add_node("cerrar", nodo_cerrar)
    constructor.add_edge(START, "calcular")
    constructor.add_edge("calcular", "cerrar")
    constructor.add_edge("cerrar", END)
    return constructor.compile(checkpointer=InMemorySaver())


def entrada_base(**cambios: Any) -> EntradaDiagnostico:
    """Libre inversión de 10 millones a 24 meses con ingreso de 2,5 millones."""
    datos: dict[str, Any] = {
        "producto": "libre_inversion",
        "ingreso_mensual": Decimal(2_500_000),
        "gastos_mensuales": Decimal(1_200_000),
        "cuotas_deudas": Decimal(500_000),
        "monto_credito": Decimal(10_000_000),
        "plazo_meses": 24,
    }
    datos.update(cambios)
    return EntradaDiagnostico(**datos)


@pytest.fixture
def grafo_terminado() -> Any:
    """Grafo con un diagnóstico original ya terminado en ``HILO``."""
    grafo = construir_grafo()
    grafo.invoke(
        {
            "entrada": entrada_base().model_dump(mode="json"),
            "respuestas": {"ingresos": "ingresos.DE_2M_A_3M"},
        },
        {"configurable": {"thread_id": HILO}},
    )
    return grafo


def valores(grafo: Any, hilo: str) -> dict[str, Any]:
    """Valores actuales de un hilo."""
    return dict(grafo.get_state({"configurable": {"thread_id": hilo}}).values)


def test_cambio_de_plazo_compara_cuota_y_semaforo(grafo_terminado: Any) -> None:
    """«¿y si el plazo fuera 48 meses?»: la cuota baja y el semáforo mejora."""
    cambio = interpretar_pedido("¿Y si el plazo fuera 48 meses?")
    assert cambio == CambioEscenario(campo="plazo_meses", valor=Decimal(48))

    comparacion = bifurcar_escenario(grafo_terminado, USUARIO, HILO, cambio, calcular)

    assert comparacion.thread_escenario == f"diag:{USUARIO}:esc:1"
    assert comparacion.escenario.cuota_mensual.hasta < comparacion.original.cuota_mensual.hasta
    assert (comparacion.original.semaforo, comparacion.escenario.semaforo) == ("rojo", "amarillo")
    assert comparacion.tendencia == "mejora"
    assert "48 meses" in comparacion.mensaje
    assert "de rojo a amarillo" in comparacion.mensaje
    assert "tu diagnóstico original no cambia" in comparacion.mensaje


def test_el_hilo_original_queda_intacto(grafo_terminado: Any) -> None:
    """El original conserva valores y número de checkpoints después del escenario."""
    configuracion = {"configurable": {"thread_id": HILO}}
    antes = valores(grafo_terminado, HILO)
    checkpoints_antes = len(list(grafo_terminado.get_state_history(configuracion)))

    bifurcar_escenario(
        grafo_terminado,
        USUARIO,
        HILO,
        CambioEscenario(campo="plazo_meses", valor=Decimal(48)),
        calcular,
    )

    assert valores(grafo_terminado, HILO) == antes
    assert len(list(grafo_terminado.get_state_history(configuracion))) == checkpoints_antes
    assert antes["entrada"]["plazo_meses"] == 24


def test_la_rama_guarda_el_escenario_y_su_origen(grafo_terminado: Any) -> None:
    """La rama queda terminada, con la entrada nueva y ``escenario_de``."""
    comparacion = bifurcar_escenario(
        grafo_terminado,
        USUARIO,
        HILO,
        CambioEscenario(campo="plazo_meses", valor=Decimal(48)),
        calcular,
    )
    rama = valores(grafo_terminado, comparacion.thread_escenario)
    assert rama["etapa"] == "terminado"
    assert rama["entrada"]["plazo_meses"] == 48
    assert rama["resultado"]["escenario_de"] == HILO
    assert rama["escenario"] == {
        "escenario_de": HILO,
        "campo": "plazo_meses",
        "valor": "48",
        "numero": 1,
    }
    assert rama["respuestas"] == {"ingresos": "ingresos.DE_2M_A_3M"}


def test_escenarios_seguidos_usan_numeros_nuevos(grafo_terminado: Any) -> None:
    """Dos escenarios crean ``esc:1`` y ``esc:2`` sin pisarse."""
    primero = bifurcar_escenario(
        grafo_terminado,
        USUARIO,
        HILO,
        CambioEscenario(campo="plazo_meses", valor=Decimal(36)),
        calcular,
    )
    segundo = bifurcar_escenario(
        grafo_terminado,
        USUARIO,
        HILO,
        CambioEscenario(campo="monto_credito", valor=Decimal(5_000_000)),
        calcular,
    )
    assert primero.thread_escenario.endswith(":esc:1")
    assert segundo.thread_escenario.endswith(":esc:2")
    assert valores(grafo_terminado, primero.thread_escenario)["entrada"]["plazo_meses"] == 36


def test_maximo_de_escenarios(grafo_terminado: Any) -> None:
    """Pasado el máximo, se ofrece un asesor y no se crea otra rama."""
    cambio = CambioEscenario(campo="plazo_meses", valor=Decimal(36))
    for _ in range(MAXIMO_ESCENARIOS):
        bifurcar_escenario(grafo_terminado, USUARIO, HILO, cambio, calcular)
    with pytest.raises(EscenarioFueraDeRango, match="asesor"):
        bifurcar_escenario(grafo_terminado, USUARIO, HILO, cambio, calcular)


@pytest.mark.parametrize(
    ("cambio", "texto"),
    [
        (CambioEscenario(campo="plazo_meses", valor=Decimal(96)), "de 6 a 72 meses"),
        (CambioEscenario(campo="plazo_meses", valor=Decimal(3)), "de 6 a 72 meses"),
        (CambioEscenario(campo="plazo_meses", valor=Decimal("36.5")), "de 6 a 72 meses"),
        (CambioEscenario(campo="monto_credito", valor=Decimal(100)), "entre $500.000"),
        (CambioEscenario(campo="ingreso_mensual", valor=Decimal(0)), "valor mensual"),
    ],
)
def test_fuera_de_rango_explica_y_no_crea_rama(
    grafo_terminado: Any, cambio: CambioEscenario, texto: str
) -> None:
    """Un monto o plazo fuera de rango explica el límite y no escribe la rama."""
    with pytest.raises(EscenarioFueraDeRango) as error:
        bifurcar_escenario(grafo_terminado, USUARIO, HILO, cambio, calcular)
    assert texto in error.value.mensaje
    assert valores(grafo_terminado, f"diag:{USUARIO}:esc:1") == {}


def test_vivienda_admite_plazos_largos() -> None:
    """Vivienda acepta 240 meses; libre inversión no."""
    vivienda = entrada_base(
        producto="vivienda", monto_credito=Decimal(150_000_000), plazo_meses=180
    )
    cambio = CambioEscenario(campo="plazo_meses", valor=Decimal(240))
    assert aplicar_cambio(vivienda, cambio).plazo_meses == 240
    with pytest.raises(EscenarioFueraDeRango):
        aplicar_cambio(entrada_base(), cambio)


def test_aplicar_cambio_no_modifica_la_entrada_original() -> None:
    """La entrada original sigue igual después de aplicar el cambio."""
    original = entrada_base()
    nueva = aplicar_cambio(
        original, CambioEscenario(campo="monto_credito", valor=Decimal(8_000_000))
    )
    assert original.monto_credito == Decimal(10_000_000)
    assert nueva.monto_credito == Decimal(8_000_000)


def test_sin_diagnostico_terminado_no_bifurca() -> None:
    """Un hilo inexistente o sin terminar responde con un error explicable."""
    grafo = construir_grafo()
    with pytest.raises(DiagnosticoNoTerminado, match="terminemos"):
        bifurcar_escenario(
            grafo, USUARIO, HILO, CambioEscenario(campo="plazo_meses", valor=Decimal(48)), calcular
        )


@pytest.mark.parametrize(
    ("texto", "campo", "valor"),
    [
        ("¿y si el plazo fuera 48 meses?", "plazo_meses", 48),
        ("y si fuera a 4 años", "plazo_meses", 48),
        ("¿Y si pido 8 millones?", "monto_credito", 8_000_000),
        ("y si pidiera 2.500.000", "monto_credito", 2_500_000),
        ("¿y si gano 3,5 millones?", "ingreso_mensual", 3_500_000),
        ("y si mis gastos fueran 800 mil", "gastos_mensuales", 800_000),
        ("y si pago 500 mil de cuotas", "cuotas_deudas", 500_000),
    ],
)
def test_interpretar_pedido(texto: str, campo: str, valor: int) -> None:
    """Las frases típicas se convierten en un cambio sin usar el modelo."""
    cambio = interpretar_pedido(texto)
    assert cambio is not None
    assert (cambio.campo, cambio.valor) == (campo, Decimal(valor))


@pytest.mark.parametrize("texto", ["¿Cuál es la cuota de manejo?", "hola", "y si", "si gracias"])
def test_textos_que_no_son_escenarios(texto: str) -> None:
    """Un mensaje sin «¿y si…?» o sin cifra no se toma como escenario."""
    assert interpretar_pedido(texto) is None


def test_formatos_en_pesos() -> None:
    """Pesos con punto de miles; un rango con extremos iguales es una cifra."""
    assert formatear_pesos(Decimal("1250000.4")) == "$1.250.000"
    assert (
        formatear_rango(RangoDecimal(desde=Decimal(410_000), hasta=Decimal(455_000)))
        == "$410.000–$455.000"
    )
    assert formatear_rango(RangoDecimal(desde=Decimal(5), hasta=Decimal(5))) == "$5"
