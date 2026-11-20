"""Demo del comité de crédito con DeepSeek real, fuera de la suite de pruebas.

Corre el comité sobre Andrés (rojo) y Jaime (amarillo) de las personas
sintéticas, usando el motor real y la tabla Gold de tasas. Muestra las posturas,
la recomendación, los tokens y el costo de la deliberación.

Uso:
    uv run python scripts/demo_comite.py

Necesita ``DEEPSEEK_API_KEY`` en el entorno. No lo ejecuta ``make check``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from typing import Any

from banco_occidente_corpus.arqueo.metricas import ResumenUso, resumen_uso
from banco_occidente_corpus.asistente.modelo import FaltaApiKey, crear_modelo
from banco_occidente_corpus.canal.contratos import EntradaDiagnostico, ResultadoDiagnostico
from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.diagnostico import motor
from banco_occidente_corpus.diagnostico.comite import (
    RegistroComite,
    cargar_limites,
    deliberar,
)

#: Personas sintéticas del Taller.
RUTA_PERSONAS = PROJECT_ROOT / "data" / "evaluacion" / "personas_sinteticas.json"
#: Personas que pide la demo: Andrés (rojo) y Jaime (amarillo).
PERSONAS = ("independiente_rojo", "pensionado_amarillo")
#: Prefijos que identifican una respuesta de la entrevista.
PREFIJOS = frozenset(
    {"objetivo", "vinculacion", "ingresos", "gastos", "cuotas", "cuota_trasladar", "monto", "plazo"}
)


def _personas() -> dict[str, dict[str, Any]]:
    """Carga las personas sintéticas indexadas por su id.

    Returns:
        El diccionario persona por id.
    """
    datos = json.loads(RUTA_PERSONAS.read_text(encoding="utf-8"))
    return {persona["id"]: persona for persona in datos["personas"]}


def _ids(persona: dict[str, Any]) -> list[str]:
    """Extrae de los turnos los ids canónicos de la entrevista.

    Args:
        persona: persona sintética con su lista de turnos.

    Returns:
        Los ids elegidos, en el orden de la entrevista.
    """
    return [
        str(turno["valor"])
        for turno in persona["turnos"]
        if turno.get("tipo") in {"lista", "boton"}
        and str(turno["valor"]).split(".", 1)[0] in PREFIJOS
    ]


def _diagnostico(ident: str) -> tuple[EntradaDiagnostico, ResultadoDiagnostico]:
    """Corre el motor real para una persona sintética.

    Args:
        ident: id de la persona en el JSON.

    Returns:
        La entrada y el resultado del motor.
    """
    entrada = motor.entrada_desde_respuestas(_ids(_personas()[ident]))
    return entrada, motor.calcular(entrada, hoy=date.today())


def _imprimir_resumen(nombre: str, resumen: ResumenUso) -> None:
    """Muestra tokens y costo de una deliberación.

    Args:
        nombre: etiqueta de la persona.
        resumen: agregado de uso del comité.
    """
    print(
        f"  Tokens {nombre}: entrada={resumen.entrada_total}, "
        f"salida={resumen.salida_total}, caché={resumen.cache_total}"
    )
    print(
        f"  Costo {nombre}: USD {resumen.costo_usd_total:.6f} "
        f"(promedio por llamada USD {resumen.costo_usd_promedio:.6f})"
    )
    print(f"  Tiempo {nombre}: promedio {resumen.tiempo_promedio:.2f} s")


def _imprimir_deliberacion(nombre: str, registro: RegistroComite, deliberacion: Any) -> None:
    """Muestra posturas, recomendación y alternativas.

    Args:
        nombre: etiqueta de la persona.
        registro: llamadas y uso del modelo.
        deliberacion: salida del comité.
    """
    print(f"\n=== {nombre} ===")
    for postura in deliberacion.posturas:
        print(f"  {postura.agente}: {postura.postura}")
        for argumento in postura.argumentos:
            print(f"    - {argumento}")
    print("  Recomendación:")
    for linea in deliberacion.recomendacion.splitlines():
        print(f"    {linea}")
    if deliberacion.alternativas:
        print("  Alternativas:")
        for alternativa in deliberacion.alternativas:
            print(f"    - {alternativa}")
    if deliberacion.hallazgos_auditor:
        print("  Hallazgos del auditor:")
        for hallazgo in deliberacion.hallazgos_auditor:
            print(f"    - {hallazgo}")
    _imprimir_resumen(
        nombre,
        resumen_uso(
            [
                {
                    "metricas": llamada["metricas"],
                    "segundos": llamada["segundos"],
                    "error": llamada["error"],
                }
                for llamada in registro.llamadas
            ]
        ),
    )


def main() -> int:
    """Corre la demo del comité sobre Andrés y Jaime.

    Returns:
        Código de salida: 0 si la demo terminó, 2 si falta la clave.
    """
    limites = cargar_limites()
    try:
        modelo = crear_modelo(
            temperatura=0.0,
            max_tokens=limites.max_tokens_agente,
            timeout=limites.tiempo_maximo_segundos,
        )
    except FaltaApiKey as error:
        print(error)
        return 2

    personas = _personas()
    pendientes: Sequence[str] = PERSONAS
    for ident in pendientes:
        entrada, resultado = _diagnostico(ident)
        registro = RegistroComite()
        deliberacion = deliberar(
            entrada, resultado, modelo=modelo, limites=limites, registro=registro
        )
        if deliberacion is None:
            print(f"\n{personas[ident]['nombre']}: sin comité (semáforo {resultado.semaforo}).")
            continue
        _imprimir_deliberacion(personas[ident]["nombre"], registro, deliberacion)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
