"""Evaluacion del Q&A con las 20 preguntas del alcance (punto 5 de la actividad).

Lee ``config/evaluacion/preguntas_alcance.toml``, responde cada pregunta con el
mismo flujo que la app (``qa.responder``) y escribe:

- ``docs/RESULTADOS_20_PREGUNTAS.md``: tabla para el informe y la sustentacion.
- ``data/evaluacion/resultados.jsonl``: una fila por pregunta, con la respuesta
  cruda del modelo, avisos y metricas, para revisarlas despues.

La clasificacion automatica es una heuristica que ordena la revision; la
columna "Revision humana" la completa el grupo.
"""

from __future__ import annotations

import json
import time
import tomllib
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import config as config_mod
from .contexto_prompt import ContextoPrompt
from .prompts import Prompt
from .qa import RespuestaQA, responder

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

#: Archivo versionado con las 20 preguntas del alcance.
ARCHIVO_PREGUNTAS = config_mod.PROJECT_ROOT / "config" / "evaluacion" / "preguntas_alcance.toml"
#: Tabla Markdown para el informe.
SALIDA_MARKDOWN = config_mod.PROJECT_ROOT / "docs" / "RESULTADOS_20_PREGUNTAS.md"
#: Detalle por pregunta (respuesta cruda, avisos y metricas).
SALIDA_JSONL = config_mod.PROJECT_ROOT / "data" / "evaluacion" / "resultados.jsonl"

COBERTURAS = ("si", "parcial", "no")

#: Clasificaciones automaticas y su texto en la tabla.
ETIQUETAS: dict[str, str] = {
    "correcta": "Correcta",
    "incompleta": "Incompleta",
    "rechazo_correcto": "Rechazo correcto",
    "remision": "Remisión al canal oficial",
    "sin_respuesta": "Sin respuesta (falso negativo)",
    "revisar": "Revisar",
    "error": "Error",
}


class PreguntasInvalidas(ValueError):
    """El archivo de preguntas no cumple el formato esperado."""


@dataclass(frozen=True, slots=True)
class PreguntaEvaluacion:
    """Una pregunta del alcance con su cobertura esperada."""

    id: int
    pregunta: str
    cobertura: str
    terminos: tuple[tuple[str, ...], ...] = ()
    nota: str = ""


@dataclass(slots=True)
class ResultadoEvaluacion:
    """Resultado de una pregunta: respuesta validada y clasificacion."""

    id: int
    pregunta: str
    cobertura: str
    clasificacion: str
    respuesta: str
    fuente: str
    sin_datos: bool
    avisos: list[str] = field(default_factory=list)
    terminos_encontrados: int = 0
    terminos_esperados: int = 0
    segundos: float = 0.0
    respuesta_cruda: str | None = None
    metricas: dict[str, Any] = field(default_factory=dict)
    error: str = ""


def _normalizar(texto: str) -> str:
    """Minusculas y sin tildes, para comparar terminos."""
    descompuesto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def cargar_preguntas(archivo: Path | None = None) -> list[PreguntaEvaluacion]:
    """Lee y valida el archivo TOML de preguntas."""
    ruta = archivo or ARCHIVO_PREGUNTAS
    try:
        datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PreguntasInvalidas(f"No existe el archivo de preguntas: {ruta}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PreguntasInvalidas(f"TOML invalido en {ruta}: {exc}") from exc

    preguntas: list[PreguntaEvaluacion] = []
    for fila in datos.get("pregunta", []):
        cobertura = str(fila.get("cobertura", "")).strip()
        if cobertura not in COBERTURAS:
            raise PreguntasInvalidas(
                f"Pregunta {fila.get('id')}: cobertura '{cobertura}' no es una de {COBERTURAS}"
            )
        texto = str(fila.get("pregunta", "")).strip()
        if not texto:
            raise PreguntasInvalidas(f"Pregunta {fila.get('id')}: texto vacio")
        grupos = tuple(tuple(str(t) for t in grupo) for grupo in fila.get("terminos", []))
        preguntas.append(
            PreguntaEvaluacion(
                id=int(fila["id"]),
                pregunta=texto,
                cobertura=cobertura,
                terminos=grupos,
                nota=str(fila.get("nota", "")),
            )
        )

    ids = [p.id for p in preguntas]
    if len(ids) != len(set(ids)):
        raise PreguntasInvalidas("Hay ids de pregunta repetidos")
    if not preguntas:
        raise PreguntasInvalidas(f"{ruta} no tiene preguntas")
    return sorted(preguntas, key=lambda p: p.id)


def contar_terminos(texto: str, grupos: Sequence[Sequence[str]]) -> int:
    """Cuantos grupos de terminos aparecen en el texto (basta una alternativa)."""
    normal = _normalizar(texto)
    return sum(1 for grupo in grupos if any(_normalizar(t) in normal for t in grupo))


def clasificar(pregunta: PreguntaEvaluacion, respuesta: RespuestaQA) -> tuple[str, int]:
    """Clasifica la respuesta segun la cobertura esperada y los terminos hallados."""
    encontrados = contar_terminos(respuesta.texto, pregunta.terminos)
    esperados = len(pregunta.terminos)

    if pregunta.cobertura == "no":
        return ("rechazo_correcto" if respuesta.sin_datos else "revisar"), encontrados

    if respuesta.sin_datos:
        if pregunta.cobertura == "parcial":
            return "remision", encontrados
        return "sin_respuesta", encontrados

    if esperados == 0 or encontrados == esperados:
        return "correcta", encontrados
    if encontrados > 0:
        return "incompleta", encontrados
    return "revisar", encontrados


def evaluar(
    modelo: BaseChatModel,
    prompt: Prompt,
    contexto: ContextoPrompt,
    preguntas: Iterable[PreguntaEvaluacion],
    *,
    pausa: float = 0.0,
    al_terminar: Callable[[ResultadoEvaluacion], None] | None = None,
) -> list[ResultadoEvaluacion]:
    """Responde cada pregunta y clasifica el resultado.

    Un error del modelo en una pregunta no detiene la corrida: queda registrado
    con la clasificacion ``error`` para reintentarla despues.
    """
    resultados: list[ResultadoEvaluacion] = []
    for indice, pregunta in enumerate(preguntas):
        if indice and pausa > 0:
            time.sleep(pausa)
        inicio = time.perf_counter()
        try:
            respuesta = responder(modelo, prompt, contexto, pregunta.pregunta)
        except Exception as exc:  # noqa: BLE001 - se registra y se sigue
            resultado = ResultadoEvaluacion(
                id=pregunta.id,
                pregunta=pregunta.pregunta,
                cobertura=pregunta.cobertura,
                clasificacion="error",
                respuesta="",
                fuente="",
                sin_datos=False,
                terminos_esperados=len(pregunta.terminos),
                segundos=round(time.perf_counter() - inicio, 2),
                error=f"{type(exc).__name__}: {exc}",
            )
        else:
            clasificacion, encontrados = clasificar(pregunta, respuesta)
            resultado = ResultadoEvaluacion(
                id=pregunta.id,
                pregunta=pregunta.pregunta,
                cobertura=pregunta.cobertura,
                clasificacion=clasificacion,
                respuesta=respuesta.texto,
                fuente=respuesta.fuente,
                sin_datos=respuesta.sin_datos,
                avisos=list(respuesta.avisos),
                terminos_encontrados=encontrados,
                terminos_esperados=len(pregunta.terminos),
                segundos=round(time.perf_counter() - inicio, 2),
                respuesta_cruda=respuesta.texto_crudo,
                metricas=dict(respuesta.metricas),
            )
        resultados.append(resultado)
        if al_terminar:
            al_terminar(resultado)
    return resultados


def _celda(texto: str, limite: int = 0) -> str:
    """Texto apto para una celda de tabla Markdown."""
    limpio = " ".join(texto.replace("|", "\\|").split())
    if limite and len(limpio) > limite:
        limpio = limpio[: limite - 1].rstrip() + "…"
    return limpio


def resumen_clasificaciones(resultados: Sequence[ResultadoEvaluacion]) -> Counter[str]:
    """Cuenta los resultados por clasificacion."""
    return Counter(r.clasificacion for r in resultados)


def render_markdown(
    resultados: Sequence[ResultadoEvaluacion],
    *,
    modelo: str,
    version_prompt: str,
    fecha: date | None = None,
) -> str:
    """Tabla de resultados para el informe, con resumen y detalle por pregunta."""
    dia = (fecha or date.today()).isoformat()
    conteo = resumen_clasificaciones(resultados)
    total = len(resultados)
    aciertos = conteo["correcta"] + conteo["rechazo_correcto"] + conteo["remision"]

    lineas = [
        "# Resultados de las 20 preguntas del alcance",
        "",
        f"Fecha: {dia}. Modelo: `{modelo}`. Prompt: `qa_{version_prompt}`. "
        "Contexto completo (`data/contexto/contexto_banco.md`).",
        "",
        "Generado con `make evaluar`. Las preguntas y su cobertura esperada están en "
        "`config/evaluacion/preguntas_alcance.toml` (ver `docs/ALCANCE.md`). El detalle, "
        "con la respuesta cruda del modelo, queda en `data/evaluacion/resultados.jsonl`.",
        "",
        "## Resumen",
        "",
        "| Clasificación automática | Preguntas |",
        "|---|---:|",
    ]
    for clave, etiqueta in ETIQUETAS.items():
        if conteo[clave]:
            lineas.append(f"| {etiqueta} | {conteo[clave]} |")
    lineas += [
        f"| **Total** | **{total}** |",
        "",
        f"Comportamiento esperado (correctas, rechazos correctos y remisiones): "
        f"**{aciertos} de {total}**.",
        "",
        "Cómo se clasifica: si el corpus no tiene el dato, lo esperado es la frase fija "
        "con el canal oficial (*rechazo correcto*). Si lo tiene, se buscan en la respuesta "
        "los términos esperados: todos (*correcta*), algunos (*incompleta*) o ninguno "
        "(*revisar*). Una respuesta sin datos cuando el corpus sí los tiene es un "
        "*falso negativo*. La clasificación es una heurística; la columna de revisión "
        "humana es la que vale para el informe.",
        "",
        "## Tabla",
        "",
        "| # | Pregunta | Cobertura | Clasificación | Términos | Fuente citada | "
        "Avisos | Revisión humana |",
        "|---:|---|---|---|---:|---|---|---|",
    ]
    for r in resultados:
        terminos = (
            f"{r.terminos_encontrados}/{r.terminos_esperados}" if r.terminos_esperados else "-"
        )
        avisos = ", ".join(r.avisos) or ("-" if not r.error else "error")
        lineas.append(
            f"| {r.id} | {_celda(r.pregunta)} | {r.cobertura} | "
            f"{ETIQUETAS.get(r.clasificacion, r.clasificacion)} | {terminos} | "
            f"{_celda(r.fuente) or '-'} | {_celda(avisos)} |  |"
        )

    lineas += ["", "## Respuestas", ""]
    for r in resultados:
        lineas.append(f"### {r.id}. {r.pregunta}")
        lineas.append("")
        lineas.append(
            f"Cobertura esperada: **{r.cobertura}** · "
            f"Clasificación: **{ETIQUETAS.get(r.clasificacion, r.clasificacion)}** · "
            f"{r.segundos:.1f} s"
        )
        lineas.append("")
        if r.error:
            lineas.append(f"> Error: {_celda(r.error, 300)}")
        else:
            for linea in r.respuesta.strip().splitlines() or [""]:
                lineas.append(f"> {linea}".rstrip())
        lineas.append("")
    return "\n".join(lineas).rstrip() + "\n"


def escribir_jsonl(resultados: Sequence[ResultadoEvaluacion], destino: Path) -> Path:
    """Escribe una fila JSON por pregunta."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    contenido = "\n".join(json.dumps(asdict(r), ensure_ascii=False) for r in resultados)
    destino.write_text(contenido + "\n", encoding="utf-8", newline="\n")
    return destino


def escribir_markdown(texto: str, destino: Path) -> Path:
    """Escribe la tabla Markdown de resultados."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8", newline="\n")
    return destino
