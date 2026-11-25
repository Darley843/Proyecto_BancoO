"""Catálogo de las veinte herramientas del agente `pana`.

El orden y la dueña son los del cambio OpenSpec `agente-openclaw`. El catálogo
es la única fuente: el servidor MCP se construye recorriéndolo y la consola
`make herramientas` imprime lo mismo que ve el agente, con el esquema Pydantic
de cada entrada.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from . import estado, lectura
from .esquemas import (
    AuditarRespuestaEntrada,
    BuscarEnDocumentosEntrada,
    CalcularPrestamoGotaEntrada,
    ClasificarPreguntaEntrada,
    CompararEscenarioEntrada,
    CompararGotaBancoEntrada,
    ConsultarCasoEntrada,
    ConsultarTarifasEntrada,
    ConsultarTasaEntrada,
    ConvocarComiteEntrada,
    DiagnosticarCapacidadEntrada,
    GenerarFichaOpcionEntrada,
    GenerarTarjetaPanaEntrada,
    NegociarOpcionEntrada,
    OlvidarMisDatosEntrada,
    RegistrarConsentimientoEntrada,
    ResponderSobreProyectoEntrada,
    SalidaHerramienta,
    SimularCuotaEntrada,
    SolicitarAsesorEntrada,
    VerificarUsuraEntrada,
)

#: Dueña de cada herramienta, según el reparto del OpenSpec.
Duena = Literal["Nayla", "Darley", "Anny"]


@dataclass(frozen=True, slots=True)
class Herramienta:
    """Una herramienta declarada con su entrada Pydantic y su dueña."""

    nombre: str
    duena: Duena
    funcion: Callable[..., SalidaHerramienta]
    entrada: type[BaseModel]


#: Las veinte herramientas, en el orden del contrato.
CATALOGO: tuple[Herramienta, ...] = (
    Herramienta("consultar_tasa", "Nayla", lectura.consultar_tasa, ConsultarTasaEntrada),
    Herramienta("simular_cuota", "Nayla", lectura.simular_cuota, SimularCuotaEntrada),
    Herramienta("verificar_usura", "Nayla", lectura.verificar_usura, VerificarUsuraEntrada),
    Herramienta(
        "diagnosticar_capacidad",
        "Nayla",
        lectura.diagnosticar_capacidad,
        DiagnosticarCapacidadEntrada,
    ),
    Herramienta(
        "comparar_escenario", "Nayla", lectura.comparar_escenario, CompararEscenarioEntrada
    ),
    Herramienta("convocar_comite", "Nayla", lectura.convocar_comite, ConvocarComiteEntrada),
    Herramienta(
        "calcular_prestamo_gota",
        "Nayla",
        lectura.calcular_prestamo_gota,
        CalcularPrestamoGotaEntrada,
    ),
    Herramienta(
        "comparar_gota_banco",
        "Nayla",
        lectura.comparar_gota_banco,
        CompararGotaBancoEntrada,
    ),
    Herramienta("negociar_opcion", "Nayla", lectura.negociar_opcion, NegociarOpcionEntrada),
    Herramienta(
        "generar_ficha_opcion",
        "Nayla",
        lectura.generar_ficha_opcion,
        GenerarFichaOpcionEntrada,
    ),
    Herramienta(
        "responder_sobre_proyecto",
        "Nayla",
        lectura.responder_sobre_proyecto,
        ResponderSobreProyectoEntrada,
    ),
    Herramienta(
        "registrar_consentimiento",
        "Darley",
        estado.registrar_consentimiento,
        RegistrarConsentimientoEntrada,
    ),
    Herramienta("olvidar_mis_datos", "Darley", estado.olvidar_mis_datos, OlvidarMisDatosEntrada),
    Herramienta("solicitar_asesor", "Darley", estado.solicitar_asesor, SolicitarAsesorEntrada),
    Herramienta("consultar_caso", "Darley", estado.consultar_caso, ConsultarCasoEntrada),
    Herramienta(
        "generar_tarjeta_pana", "Darley", estado.generar_tarjeta_pana, GenerarTarjetaPanaEntrada
    ),
    Herramienta(
        "buscar_en_documentos",
        "Anny",
        lectura.buscar_en_documentos,
        BuscarEnDocumentosEntrada,
    ),
    Herramienta("consultar_tarifas", "Anny", lectura.consultar_tarifas, ConsultarTarifasEntrada),
    Herramienta(
        "clasificar_pregunta", "Anny", lectura.clasificar_pregunta, ClasificarPreguntaEntrada
    ),
    Herramienta("auditar_respuesta", "Anny", lectura.auditar_respuesta, AuditarRespuestaEntrada),
)


def nombres() -> tuple[str, ...]:
    """Devuelve los nombres del catálogo, en orden.

    Returns:
        Las veinte claves que ve el agente.
    """
    return tuple(herramienta.nombre for herramienta in CATALOGO)


def por_nombre(nombre: str) -> Herramienta | None:
    """Busca una herramienta por su nombre.

    Args:
        nombre: clave del catálogo.

    Returns:
        La herramienta o `None` si no está declarada.
    """
    return next((herramienta for herramienta in CATALOGO if herramienta.nombre == nombre), None)


def esquemas() -> list[dict[str, object]]:
    """Arma el contrato JSON de las veinte herramientas.

    Returns:
        Una lista con nombre, dueña y el JSON Schema de la entrada Pydantic.
    """
    return [
        {
            "nombre": herramienta.nombre,
            "duena": herramienta.duena,
            "entrada": herramienta.entrada.model_json_schema(),
        }
        for herramienta in CATALOGO
    ]


def _tabla(herramientas: Sequence[Herramienta]) -> str:
    """Arma la tabla de consola con nombre, dueña y resumen de la entrada."""
    lineas = ["#  herramienta                 dueña    campos de entrada", "-" * 78]
    for posicion, herramienta in enumerate(herramientas, start=1):
        campos = ", ".join(herramienta.entrada.model_fields)
        lineas.append(f"{posicion:>2} {herramienta.nombre:<26} {herramienta.duena:<8} {campos}")
    return "\n".join(lineas)


def main(argv: Sequence[str] | None = None) -> int:
    """Imprime el catálogo o su contrato JSON.

    Args:
        argv: argumentos de consola; `--json` imprime los esquemas completos.

    Returns:
        Código de salida de la consola.
    """
    argumentos = list(argv or ())
    if "--json" in argumentos:
        print(json.dumps(esquemas(), ensure_ascii=False, indent=2))
        return 0
    print(_tabla(CATALOGO))
    print(f"\nTotal: {len(CATALOGO)} herramientas. Usa --json para ver los esquemas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
