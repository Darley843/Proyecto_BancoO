"""Linea de comandos del asistente: preguntar, faq, resumen y evaluar.

Se ejecuta con ``uv run python -m banco_occidente_corpus.asistente``. No toca
el CLI del pipeline ni escribe en Bronze, Silver o Gold.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel

from .contexto_prompt import (
    ContextoAusente,
    ContextoPrompt,
    PresupuestoContextoError,
    cargar_contexto,
)
from .evaluacion import (
    ARCHIVO_REVISION,
    ETIQUETAS,
    SALIDA_JSONL,
    SALIDA_MARKDOWN,
    PreguntasInvalidas,
    ResultadoEvaluacion,
    RevisionInvalida,
    cargar_preguntas,
    cargar_resultados,
    cargar_revision,
    escribir_jsonl,
    escribir_markdown,
    evaluar,
    fusionar,
    resumen_clasificaciones,
    revalidar,
)
from .evaluacion import render_markdown as render_evaluacion
from .faq import FAQInvalida, generar_faq, render_markdown
from .metricas import formatear_metricas
from .modelo import MODELO_POR_DEFECTO, FaltaApiKey, crear_modelo, parametros_de
from .prompts import VERSION_POR_DEFECTO, Prompt, PromptNoEncontrado, cargar_prompt
from .qa import responder
from .resumen import ResumenInvalido, generar_resumen

PROG = "python -m banco_occidente_corpus.asistente"


def _configurar_salida() -> None:
    """Fuerza UTF-8 en stdout/stderr cuando la plataforma lo permita."""
    for salida in (sys.stdout, sys.stderr):
        reconfigure = getattr(salida, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            continue


def _positivo(valor: str) -> int:
    """Valida un entero positivo para ``--max-contexto``."""
    try:
        numero = int(valor)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("debe ser un entero positivo") from exc
    if numero <= 0:
        raise argparse.ArgumentTypeError("debe ser un entero positivo")
    return numero


def _opciones_comunes() -> argparse.ArgumentParser:
    """Opciones compartidas por los subcomandos."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--version",
        dest="version_prompt",
        default=VERSION_POR_DEFECTO,
        metavar="VERSION",
        help=f"version del prompt (por defecto: {VERSION_POR_DEFECTO})",
    )
    parser.add_argument(
        "--max-contexto",
        type=_positivo,
        default=None,
        metavar="N",
        help=(
            "EXPERIMENTO: recorta el contexto a N tokens; por defecto se envia "
            "contexto_banco.md completo"
        ),
    )
    parser.add_argument(
        "--modelo",
        default=MODELO_POR_DEFECTO,
        help=f"modelo de DeepSeek (por defecto: {MODELO_POR_DEFECTO})",
    )
    parser.add_argument(
        "--contexto",
        type=Path,
        default=None,
        help="ruta alternativa a contexto_banco.md",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="muestra modelo, prompt, contexto, respuesta cruda y metricas",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser con los subcomandos preguntar, faq, resumen y evaluar."""
    comun = _opciones_comunes()
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Asistente Q&A del corpus de Banco de Occidente (DeepSeek).",
    )
    subparsers = parser.add_subparsers(dest="comando", required=True)

    preguntar = subparsers.add_parser(
        "preguntar",
        parents=[comun],
        help="responde una pregunta con el contexto consolidado",
    )
    preguntar.add_argument("texto", nargs="+", help="pregunta del usuario")

    faq = subparsers.add_parser(
        "faq",
        parents=[comun],
        help="genera diez preguntas frecuentes con su fuente",
    )
    faq.add_argument("--salida", type=Path, default=None, help="archivo Markdown de salida")

    resumen = subparsers.add_parser(
        "resumen",
        parents=[comun],
        help="genera un resumen ejecutivo de maximo 300 palabras",
    )
    resumen.add_argument("--tema", default="", help="tema opcional para enfocar el resumen")
    resumen.add_argument("--salida", type=Path, default=None, help="archivo Markdown de salida")

    evaluar_cmd = subparsers.add_parser(
        "evaluar",
        parents=[comun],
        help="corre las 20 preguntas del alcance y escribe la tabla de resultados",
    )
    evaluar_cmd.add_argument(
        "--preguntas",
        type=Path,
        default=None,
        help="archivo TOML de preguntas (por defecto: config/evaluacion/preguntas_alcance.toml)",
    )
    evaluar_cmd.add_argument(
        "--solo",
        type=_lista_ids,
        default=None,
        metavar="IDS",
        help="evalua solo estas preguntas, separadas por coma (ej. 1,7,9)",
    )
    evaluar_cmd.add_argument(
        "--pausa",
        type=float,
        default=0.0,
        metavar="SEG",
        help="segundos de espera entre preguntas (por defecto: 0)",
    )
    evaluar_cmd.add_argument(
        "--revalidar",
        action="store_true",
        help=(
            "no llama al modelo: vuelve a validar y clasificar las respuestas guardadas "
            "en --jsonl y aplica la revision humana (no requiere DEEPSEEK_API_KEY)"
        ),
    )
    evaluar_cmd.add_argument(
        "--revision",
        type=Path,
        default=ARCHIVO_REVISION,
        help="revision humana (por defecto: config/evaluacion/revision_humana.toml)",
    )
    evaluar_cmd.add_argument(
        "--salida",
        type=Path,
        default=SALIDA_MARKDOWN,
        help="tabla Markdown (por defecto: docs/RESULTADOS_20_PREGUNTAS.md)",
    )
    evaluar_cmd.add_argument(
        "--jsonl",
        type=Path,
        default=SALIDA_JSONL,
        help="detalle por pregunta (por defecto: data/evaluacion/resultados.jsonl)",
    )

    return parser


def _lista_ids(valor: str) -> set[int]:
    """Convierte ``1,7,9`` en un conjunto de ids para ``--solo``."""
    try:
        ids = {int(parte) for parte in valor.split(",") if parte.strip()}
    except ValueError as exc:
        raise argparse.ArgumentTypeError("usa ids separados por coma, por ejemplo 1,7,9") from exc
    if not ids:
        raise argparse.ArgumentTypeError("indica al menos un id")
    return ids


def _parametros(comando: str) -> tuple[float, int]:
    """Temperatura y maximo de tokens fijos por tarea.

    Los valores viven en ``modelo.PARAMETROS_POR_TAREA`` para que la app no los
    duplique. El maximo cubre el razonamiento de DeepSeek Flash ademas del
    contenido; con topes bajos el razonamiento agotaba el presupuesto y la
    respuesta llegaba vacia con ``finish_reason="length"``.
    """
    parametros = parametros_de("qa" if comando in {"preguntar", "evaluar"} else comando)
    return parametros.temperatura, parametros.max_tokens


def _imprimir_metricas(metricas: dict[str, Any] | None) -> None:
    """Muestra tokens, razonamiento, cache y fin en una linea legible."""
    linea = formatear_metricas(metricas)
    if linea:
        print(f"Uso     : {linea}", file=sys.stderr)


def _diagnostico(args: argparse.Namespace, contexto: ContextoPrompt) -> None:
    """Muestra el experimento de recorte y, con --verbose, el detalle."""
    if args.max_contexto:
        print(
            "Contexto: EXPERIMENTO de recorte a "
            f"{contexto.tokens:,} tokens; por defecto se envia completo "
            f"({contexto.bloques} bloques, {contexto.descartados} descartados).",
            file=sys.stderr,
        )
    if not args.verbose:
        return
    estado = "completo" if contexto.completo else "recortado (experimento)"
    print(f"Modelo  : {args.modelo}", file=sys.stderr)
    print(f"Prompt  : {args.comando} {args.version_prompt}", file=sys.stderr)
    print(
        f"Contexto: {estado}, {contexto.tokens:,} tokens, {contexto.bloques} bloques",
        file=sys.stderr,
    )
    if contexto.canal:
        print(f"Canal   : {contexto.canal.telefono} - {contexto.canal.url}", file=sys.stderr)


def _emitir(texto: str, salida: Path | None) -> None:
    """Imprime en stdout o escribe el archivo indicado por ``--salida``."""
    if salida is None:
        print(texto)
        return
    destino = salida.expanduser()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto.rstrip() + "\n", encoding="utf-8", newline="\n")
    print(f"Escrito: {destino}", file=sys.stderr)


def _imprimir_respuesta_cruda(texto: str | None) -> None:
    """Muestra lo que devolvio el modelo antes de la validacion (``--verbose``)."""
    if texto is None:
        return
    print(f"Respuesta cruda:\n{texto}", file=sys.stderr)


def _comando_preguntar(
    args: argparse.Namespace,
    modelo: BaseChatModel,
    prompt: Prompt,
    contexto: ContextoPrompt,
) -> int:
    """Ejecuta el Q&A e imprime la respuesta validada."""
    pregunta = " ".join(args.texto).strip()
    resultado = responder(modelo, prompt, contexto, pregunta)
    if args.verbose:
        _imprimir_respuesta_cruda(resultado.texto_crudo)
    print(resultado.texto)
    if resultado.avisos:
        print(f"Avisos: {', '.join(resultado.avisos)}", file=sys.stderr)
    if args.verbose:
        _imprimir_metricas(resultado.metricas)
    return 0


def _imprimir_avance(resultado: ResultadoEvaluacion) -> None:
    """Muestra una linea por pregunta mientras corre la evaluacion."""
    etiqueta = ETIQUETAS.get(resultado.clasificacion, resultado.clasificacion)
    print(
        f"{resultado.id:>2}. {etiqueta:<32} {resultado.segundos:5.1f} s  {resultado.pregunta}",
        file=sys.stderr,
    )


def _comando_evaluar(
    args: argparse.Namespace,
    modelo: BaseChatModel | None,
    prompt: Prompt,
    contexto: ContextoPrompt,
) -> int:
    """Corre (o revalida) las preguntas del alcance y escribe la tabla y el detalle.

    Con ``--solo`` solo se reemplazan esas filas en la corrida anterior; con
    ``--revalidar`` no se llama al modelo.
    """
    revision = cargar_revision(args.revision.expanduser())
    todas = cargar_preguntas(args.preguntas)
    preguntas = [p for p in todas if p.id in args.solo] if args.solo else todas
    if not preguntas:
        print("Error: ninguna pregunta coincide con --solo.", file=sys.stderr)
        return 2
    destino_jsonl = args.jsonl.expanduser()
    previos = cargar_resultados(destino_jsonl)

    if modelo is None:
        if not previos:
            print(f"Error: no hay resultados para revalidar en {destino_jsonl}.", file=sys.stderr)
            return 2
        print(f"Revalidando {len(previos)} respuestas guardadas (sin API)...", file=sys.stderr)
        resultados = revalidar(previos, todas, contexto)
        for resultado in resultados:
            _imprimir_avance(resultado)
    else:
        print(
            f"Evaluando {len(preguntas)} preguntas con qa_{args.version_prompt}...",
            file=sys.stderr,
        )
        nuevos = evaluar(
            modelo, prompt, contexto, preguntas, pausa=args.pausa, al_terminar=_imprimir_avance
        )
        resultados = fusionar(previos, nuevos) if args.solo else nuevos
    texto = render_evaluacion(
        resultados, modelo=args.modelo, version_prompt=args.version_prompt, revision=revision
    )
    markdown = escribir_markdown(texto, args.salida.expanduser())
    detalle = escribir_jsonl(resultados, args.jsonl.expanduser())
    conteo = resumen_clasificaciones(resultados)
    resumen = ", ".join(f"{ETIQUETAS[c]}: {n}" for c, n in conteo.items())
    print(f"Resumen : {resumen}", file=sys.stderr)
    print(f"Tabla   : {markdown}", file=sys.stderr)
    print(f"Detalle : {detalle}", file=sys.stderr)
    return 3 if conteo["error"] else 0


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del asistente; devuelve el codigo de salida."""
    _configurar_salida()
    args = build_parser().parse_args(argv)
    tarea = "qa" if args.comando in {"preguntar", "evaluar"} else args.comando
    temperatura, max_tokens = _parametros(args.comando)

    try:
        contexto = cargar_contexto(archivo=args.contexto, max_tokens=args.max_contexto)
        _diagnostico(args, contexto)
        prompt = cargar_prompt(tarea, args.version_prompt)
        if args.comando == "evaluar" and args.revalidar:
            return _comando_evaluar(args, None, prompt, contexto)
        modelo = crear_modelo(
            modelo=args.modelo,
            temperatura=temperatura,
            max_tokens=max_tokens,
        )

        if args.comando == "preguntar":
            return _comando_preguntar(args, modelo, prompt, contexto)

        if args.comando == "evaluar":
            return _comando_evaluar(args, modelo, prompt, contexto)

        if args.comando == "faq":
            metricas: dict[str, Any] = {}
            faq = generar_faq(modelo, prompt, contexto, metricas=metricas)
            _emitir(render_markdown(faq, prompt, args.modelo), args.salida)
            if args.verbose:
                _imprimir_metricas(metricas)
            return 0

        resumen = generar_resumen(modelo, prompt, contexto, args.tema)
        _emitir(resumen.texto, args.salida)
        if resumen.avisos:
            print(f"Avisos: {', '.join(resumen.avisos)}", file=sys.stderr)
        if args.verbose:
            _imprimir_metricas(resumen.metricas)
        return 0

    except FaltaApiKey as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (PreguntasInvalidas, RevisionInvalida) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except PromptNoEncontrado as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (ContextoAusente, PresupuestoContextoError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (FAQInvalida, ResumenInvalido) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrumpido.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - frontera del CLI
        print(f"Error del modelo: {exc}", file=sys.stderr)
        return 3
