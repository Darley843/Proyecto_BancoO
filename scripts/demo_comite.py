"""Demo del comité de crédito con DeepSeek real, fuera de la suite de pruebas.

Corre el comité sobre Andrés (rojo) y Jaime (amarillo) de las personas
sintéticas, usando el motor real y la tabla Gold de tasas. Compara el modo con
razonamiento y el modo sin razonamiento (`reasoning_effort="none"`): tres rondas
por configuración, tasa de abstención, costo y tiempo. Se queda con la
configuración que menos se abstiene y muestra la deliberación final.

Cuando una llamada falla, la demo imprime la causa técnica de la abstención
—clase del error, `finish_reason` y tokens de salida—. Ese detalle vive solo
aquí: nunca viaja a la recomendación que recibe la persona. La corrida final usa
por defecto la configuración sin razonamiento, la que menos se abstuvo en la
comparación.

Uso:
    uv run python scripts/demo_comite.py
    uv run python scripts/demo_comite.py --configuracion auto --rondas 3

Necesita ``DEEPSEEK_API_KEY`` en el entorno. No lo ejecuta ``make check``.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from banco_occidente_corpus.arqueo.metricas import ResumenUso, resumen_uso
from banco_occidente_corpus.asistente.metricas import leer_uso
from banco_occidente_corpus.asistente.modelo import (
    FaltaApiKey,
    api_key_desde_entorno,
    crear_modelo,
)
from banco_occidente_corpus.canal.contratos import EntradaDiagnostico, ResultadoDiagnostico
from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.diagnostico import motor
from banco_occidente_corpus.diagnostico.comite import (
    DeliberacionComite,
    LimitesComite,
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


@dataclass(frozen=True, slots=True)
class Configuracion:
    """Modo de razonamiento del comité que se va a comparar."""

    nombre: str
    razonamiento: bool


#: Las dos configuraciones de la comparación.
CONFIGURACIONES: tuple[Configuracion, ...] = (
    Configuracion("con_razonamiento", True),
    Configuracion("sin_razonamiento", False),
)


@dataclass(slots=True)
class Corrida:
    """Una deliberación completa sobre una persona."""

    persona: str
    deliberacion: DeliberacionComite | None
    registro: RegistroComite
    segundos: float
    ronda: int = 1


@dataclass(slots=True)
class Balance:
    """Resultados acumulados de una configuración."""

    configuracion: Configuracion
    corridas: list[Corrida] = field(default_factory=list)

    @property
    def posturas(self) -> int:
        """Posturas emitidas en la configuración (tres por deliberación)."""
        return sum(
            len(corrida.deliberacion.posturas)
            for corrida in self.corridas
            if corrida.deliberacion is not None
        )

    @property
    def abstenciones(self) -> int:
        """Posturas que quedaron en abstención."""
        return sum(
            postura.postura == "abstencion"
            for corrida in self.corridas
            if corrida.deliberacion is not None
            for postura in corrida.deliberacion.posturas
        )

    @property
    def tasa_abstencion(self) -> float:
        """Abstenciones sobre posturas emitidas."""
        return self.abstenciones / self.posturas if self.posturas else 0.0

    @property
    def abstenciones_por_rol(self) -> dict[str, int]:
        """Conteo de abstenciones por rol del comité."""
        conteo = {"riesgo": 0, "comercial": 0, "auditor": 0}
        for corrida in self.corridas:
            if corrida.deliberacion is None:
                continue
            for postura in corrida.deliberacion.posturas:
                if postura.postura == "abstencion":
                    conteo[postura.agente] += 1
        return conteo

    @property
    def objeciones(self) -> int:
        """Veces que el agente auditor objetó antes de la corrección."""
        return sum(
            1
            for corrida in self.corridas
            if corrida.deliberacion is not None
            for postura in corrida.deliberacion.posturas
            if postura.agente == "auditor" and postura.postura == "objeta"
        )

    def motivos_objecion(self) -> list[str]:
        """Explica cada objeción del auditor con su ronda y su persona.

        Returns:
            Una línea por objeción, con los argumentos que dejó el agente; la
            lista queda vacía si el auditor no objetó.
        """
        lineas: list[str] = []
        for corrida in self.corridas:
            if corrida.deliberacion is None:
                continue
            for postura in corrida.deliberacion.posturas:
                if postura.agente != "auditor" or postura.postura != "objeta":
                    continue
                motivo = " | ".join(postura.argumentos) or "sin argumentos"
                lineas.append(f"ronda {corrida.ronda} {corrida.persona}: {motivo}")
        return lineas

    @property
    def costo_usd(self) -> float:
        """Costo de todas las llamadas, incluidas las que fallaron."""
        return sum(_resumen(corrida.registro).costo_usd_total for corrida in self.corridas)

    @property
    def segundos(self) -> float:
        """Tiempo total de las deliberaciones de la configuración."""
        return sum(corrida.segundos for corrida in self.corridas)

    @property
    def tiempo_promedio(self) -> float:
        """Tiempo promedio por deliberación."""
        return self.segundos / len(self.corridas) if self.corridas else 0.0


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


def _resumen(registro: RegistroComite) -> ResumenUso:
    """Agrega tokens, costo y tiempo de todas las llamadas del registro.

    ``resumen_uso`` excluye las llamadas con error; aquí se incluyen para no
    subestimar el costo de una deliberación que falló.

    Args:
        registro: llamadas y métricas de una deliberación.

    Returns:
        El resumen con costo y tiempos.
    """
    return resumen_uso(
        [
            {"metricas": llamada["metricas"], "segundos": llamada["segundos"], "error": ""}
            for llamada in registro.llamadas
        ]
    )


def _numero(valor: int | None) -> str:
    """Formatea un contador o ``n/d`` cuando el proveedor no lo informa.

    Args:
        valor: contador de tokens.

    Returns:
        El número con separadores de miles o ``n/d``.
    """
    return f"{valor:,}" if valor is not None else "n/d"


def _correr(
    ident: str,
    caso: tuple[EntradaDiagnostico, ResultadoDiagnostico],
    modelo: Any,
    limites: LimitesComite,
    *,
    ronda: int = 1,
) -> Corrida:
    """Corre una deliberación y mide su tiempo.

    Args:
        ident: id de la persona.
        caso: entrada y resultado del motor.
        modelo: chat model ya configurado.
        limites: límites de la deliberación.
        ronda: número de ronda de la comparación.

    Returns:
        La corrida con su deliberación, registro y tiempo.
    """
    entrada, resultado = caso
    registro = RegistroComite()
    inicio = time.monotonic()
    deliberacion = deliberar(
        entrada,
        resultado,
        modelo=modelo,
        limites=limites,
        registro=registro,
    )
    return Corrida(ident, deliberacion, registro, time.monotonic() - inicio, ronda)


def _ultimo_fallo(registro: RegistroComite, agente: str) -> dict[str, Any] | None:
    """Busca la última llamada fallida de un rol.

    Args:
        registro: llamadas de una deliberación.
        agente: rol buscado.

    Returns:
        La última llamada con error o `None` si no hubo.
    """
    for llamada in reversed(registro.llamadas):
        if llamada["agente"] == agente and (llamada["clase_error"] or llamada["error"]):
            return llamada
    return None


def _imprimir_abstenciones(balance: Balance) -> None:
    """Muestra la causa técnica de cada abstención de una configuración.

    Args:
        balance: resultados acumulados de una configuración.
    """
    abstenciones = [
        (corrida, postura)
        for corrida in balance.corridas
        if corrida.deliberacion is not None
        for postura in corrida.deliberacion.posturas
        if postura.postura == "abstencion"
    ]
    if not abstenciones:
        return
    print(f"  causa técnica de las abstenciones de {balance.configuracion.nombre}:")
    for corrida, postura in abstenciones:
        motivo = postura.argumentos[0] if postura.argumentos else "sin motivo"
        fallo = _ultimo_fallo(corrida.registro, postura.agente)
        if fallo is None:
            print(
                f"    - ronda {corrida.ronda} {corrida.persona} {postura.agente}: "
                f"{motivo} (sin llamada fallida registrada)"
            )
            continue
        uso = leer_uso(fallo["metricas"])
        print(
            f"    - ronda {corrida.ronda} {corrida.persona} {postura.agente}: "
            f"{fallo['clase_error'] or 'sin_clase'}"
            f" | finish_reason={uso.finish_reason or 'n/d'}"
            f" | salida={_numero(uso.salida)}"
            f" | razonamiento={_numero(uso.razonamiento)}"
            f" | {fallo['segundos']:.2f} s"
        )


def _imprimir_comparacion(balances: Sequence[Balance]) -> None:
    """Muestra la tabla de abstención, costo y tiempo por configuración.

    Args:
        balances: resultados de cada configuración comparada.
    """
    print("\n=== Resumen por configuración ===")
    print(
        f"{'configuración':<20} {'posturas':>9} {'absten.':>8} {'tasa':>7} "
        f"{'costo USD':>12} {'tiempo s':>9} {'promedio s':>11}"
    )
    for balance in balances:
        print(
            f"{balance.configuracion.nombre:<20} {balance.posturas:>9} "
            f"{balance.abstenciones:>8} {balance.tasa_abstencion:>7.1%} "
            f"{balance.costo_usd:>12.6f} {balance.segundos:>9.2f} "
            f"{balance.tiempo_promedio:>11.2f}"
        )
        por_rol = balance.abstenciones_por_rol
        print(
            "  abstenciones por rol: "
            f"riesgo={por_rol['riesgo']}, comercial={por_rol['comercial']}, "
            f"auditor={por_rol['auditor']}"
        )
        print(f"  objeciones del auditor: {balance.objeciones}")
        for linea in balance.motivos_objecion():
            print(f"    - {linea}")
        _imprimir_abstenciones(balance)


def _imprimir_resumen(nombre: str, resumen: ResumenUso, segundos: float) -> None:
    """Muestra tokens y costo de una deliberación.

    Args:
        nombre: etiqueta de la persona.
        resumen: agregado de uso del comité.
        segundos: tiempo total de la deliberación.
    """
    print(
        f"  Tokens {nombre}: entrada={resumen.entrada_total}, "
        f"salida={resumen.salida_total}, caché={resumen.cache_total}"
    )
    print(
        f"  Costo {nombre}: USD {resumen.costo_usd_total:.6f} "
        f"(promedio por llamada USD {resumen.costo_usd_promedio:.6f})"
    )
    print(
        f"  Tiempo {nombre}: {segundos:.2f} s "
        f"(promedio por llamada {resumen.tiempo_promedio:.2f} s)"
    )


def _imprimir_diagnostico(corrida: Corrida) -> None:
    """Muestra la causa técnica de cada llamada fallida y de cada abstención.

    Args:
        corrida: deliberación con su registro de llamadas.
    """
    fallidas = [
        llamada
        for llamada in corrida.registro.llamadas
        if llamada["clase_error"] or llamada["error"]
    ]
    if not fallidas:
        return
    print("  Causa técnica de las llamadas fallidas:")
    for llamada in fallidas:
        uso = leer_uso(llamada["metricas"])
        print(
            f"    - {llamada['agente']}: {llamada['clase_error'] or 'sin_clase'}"
            f" | finish_reason={uso.finish_reason or 'n/d'}"
            f" | salida={_numero(uso.salida)}"
            f" | razonamiento={_numero(uso.razonamiento)}"
            f" | {llamada['segundos']:.2f} s"
        )


def _imprimir_deliberacion(nombre: str, corrida: Corrida) -> None:
    """Muestra posturas, recomendación, alternativas y diagnóstico técnico.

    Args:
        nombre: etiqueta de la persona.
        corrida: deliberación, registro y tiempo.
    """
    deliberacion = corrida.deliberacion
    print(f"\n=== {nombre} ===")
    if deliberacion is None:
        print("  Sin comité para este diagnóstico.")
        return
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
    _imprimir_diagnostico(corrida)
    _imprimir_resumen(nombre, _resumen(corrida.registro), corrida.segundos)


def _argumentos(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Lee las opciones de la demo.

    Args:
        argv: argumentos de línea de comandos; por defecto los del proceso.

    Returns:
        Las opciones con sus valores por defecto.
    """
    parser = argparse.ArgumentParser(description="Demo y comparación del comité de crédito.")
    parser.add_argument(
        "--rondas",
        type=int,
        default=3,
        help="rondas por configuración en la comparación (por defecto 3).",
    )
    parser.add_argument(
        "--configuracion",
        choices=("auto", *(configuracion.nombre for configuracion in CONFIGURACIONES)),
        default="sin_razonamiento",
        help=(
            "configuración de la corrida final; `auto` compara las dos con "
            "`--rondas` cada una y elige la más estable (por defecto "
            "sin_razonamiento, la medida en la demo)."
        ),
    )
    parser.add_argument(
        "--tope-tokens",
        type=int,
        default=None,
        help=(
            "tope de tokens por agente; por defecto el de "
            "config/diagnostico.toml. Bajarlo reproduce una abstención y su "
            "causa técnica en el diagnóstico."
        ),
    )
    return parser.parse_args(argv)


def _elegir(balances: Sequence[Balance]) -> Balance:
    """Elige la configuración con menos abstenciones y, en empate, la más barata.

    Args:
        balances: resultados de las configuraciones comparadas.

    Returns:
        El balance ganador.
    """
    return min(
        balances, key=lambda balance: (balance.abstenciones, balance.costo_usd, balance.segundos)
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Corre la demo y la comparación sobre Andrés y Jaime.

    Args:
        argv: argumentos de línea de comandos; por defecto los del proceso.

    Returns:
        Código de salida: 0 si la demo terminó, 2 si falta la clave.
    """
    opciones = _argumentos(argv)
    limites = cargar_limites()
    if opciones.tope_tokens is not None:
        limites = LimitesComite(
            max_llamadas=limites.max_llamadas,
            max_tokens_agente=opciones.tope_tokens,
            tiempo_maximo_segundos=limites.tiempo_maximo_segundos,
            max_alternativas=limites.max_alternativas,
            razonamiento=limites.razonamiento,
            temperatura=limites.temperatura,
        )
    personas = _personas()
    casos = {ident: _diagnostico(ident) for ident in PERSONAS}
    try:
        api_key_desde_entorno()
    except FaltaApiKey as error:
        print(error)
        return 2

    if opciones.configuracion == "auto":
        configuraciones = CONFIGURACIONES
    else:
        configuraciones = tuple(
            configuracion
            for configuracion in CONFIGURACIONES
            if configuracion.nombre == opciones.configuracion
        )

    balances: list[Balance] = []
    for configuracion in configuraciones:
        modelo = crear_modelo(
            temperatura=limites.temperatura,
            max_tokens=limites.max_tokens_agente,
            timeout=limites.tiempo_maximo_segundos,
            razonamiento=configuracion.razonamiento,
        )
        balance = Balance(configuracion)
        for ronda in range(1, max(1, opciones.rondas) + 1):
            for ident in PERSONAS:
                balance.corridas.append(_correr(ident, casos[ident], modelo, limites, ronda=ronda))
        balances.append(balance)

    _imprimir_comparacion(balances)
    elegida = _elegir(balances)
    print(f"\nConfiguración elegida: {elegida.configuracion.nombre}")

    modelo = crear_modelo(
        temperatura=limites.temperatura,
        max_tokens=limites.max_tokens_agente,
        timeout=limites.tiempo_maximo_segundos,
        razonamiento=elegida.configuracion.razonamiento,
    )
    for ident in PERSONAS:
        corrida = _correr(ident, casos[ident], modelo, limites)
        _imprimir_deliberacion(personas[ident]["nombre"], corrida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
