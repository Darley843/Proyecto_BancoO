"""Linea de comandos del asistente: preguntar, faq y resumen.

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
from .faq import FAQInvalida, generar_faq, render_markdown
from .metricas import formatear_metricas
from .modelo import MODELO_POR_DEFECTO, FaltaApiKey, crear_modelo
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
    """Opciones compartidas por los tres subcomandos."""
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
    """Construye el parser con los subcomandos preguntar, faq y resumen."""
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

    return parser


def _parametros(comando: str) -> tuple[float, int]:
    """Temperatura y maximo de tokens fijos por tarea.

    El maximo cubre el razonamiento de DeepSeek Flash ademas del contenido; con
    topes bajos el razonamiento agotaba el presupuesto y la respuesta llegaba
    vacia con ``finish_reason="length"``.
    """
    if comando == "faq":
        return 0.0, 8000
    if comando == "resumen":
        return 0.2, 4000
    return 0.0, 2000


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


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada del asistente; devuelve el codigo de salida."""
    _configurar_salida()
    args = build_parser().parse_args(argv)
    tarea = "qa" if args.comando == "preguntar" else args.comando
    temperatura, max_tokens = _parametros(args.comando)

    try:
        contexto = cargar_contexto(archivo=args.contexto, max_tokens=args.max_contexto)
        _diagnostico(args, contexto)
        prompt = cargar_prompt(tarea, args.version_prompt)
        modelo = crear_modelo(
            modelo=args.modelo,
            temperatura=temperatura,
            max_tokens=max_tokens,
        )

        if args.comando == "preguntar":
            return _comando_preguntar(args, modelo, prompt, contexto)

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
