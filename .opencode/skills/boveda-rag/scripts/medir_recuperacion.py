"""Mide hit@5 y MRR de la Bóveda sobre el set de preguntas de fase 2.

Uso:
    uv run python .opencode/skills/boveda-rag/scripts/medir_recuperacion.py
    uv run python .opencode/skills/boveda-rag/scripts/medir_recuperacion.py --hibrido

Por defecto mide solo el componente vectorial; con `--hibrido` usa el
`crear_recuperador` de la Bóveda y los pesos de `config/sucursal.toml`. Evalúa
solo las preguntas con `fuentes_esperadas` y escribe el detalle por pregunta en
`data/boveda/mediciones/`, que no se versiona. No usa red salvo la llamada local
a Ollama para calcular embeddings.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from langchain_core.documents import Document

from banco_occidente_corpus.arqueo.metricas import hit_at_k, mrr
from banco_occidente_corpus.boveda.almacen import ChromaAlmacen
from banco_occidente_corpus.boveda.configuracion import (
    ConfiguracionRecuperacion,
    cargar_configuracion_recuperacion,
)
from banco_occidente_corpus.boveda.embeddings import crear_embeddings
from banco_occidente_corpus.boveda.fragmentos import Alcance
from banco_occidente_corpus.boveda.indice import ruta_almacen
from banco_occidente_corpus.boveda.recuperador import (
    RecuperadorVectorial,
    crear_recuperador,
)
from banco_occidente_corpus.config import PROJECT_ROOT, Config, load_config

#: Ruta por defecto del set de preguntas de la fase 2.
RUTA_PREGUNTAS: Path = PROJECT_ROOT / "config" / "evaluacion" / "preguntas_fase2.toml"
#: Carpeta por defecto de las mediciones (dentro de `data/boveda/`, ignorado).
CARPETA_MEDICIONES: Path = PROJECT_ROOT / "data" / "boveda" / "mediciones"
#: k usado cuando no se indica otro.
K_POR_DEFECTO: int = 5
#: Nivel de confianza del intervalo de Wilson.
Z_95: float = 1.96

#: Función que devuelve hasta `k` URL para una consulta.
Recuperar = Callable[[str, int], Sequence[str]]


@dataclass(frozen=True, slots=True)
class Pregunta:
    """Pregunta evaluable con sus fuentes esperadas."""

    id: int
    tipo: str
    pregunta: str
    previa: str
    fuentes_esperadas: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Resultado:
    """Resultado de recuperación de una pregunta."""

    pregunta: Pregunta
    consulta: str
    recuperadas: tuple[str, ...]
    distintas: tuple[str, ...]
    acierto: bool
    rr: float
    acierto_distintas: bool
    rr_distintas: float


def cargar_preguntas(ruta: Path = RUTA_PREGUNTAS) -> list[Pregunta]:
    """Carga las preguntas que tienen fuentes esperadas, ordenadas por id.

    Raises:
        FileNotFoundError: si el TOML no existe.
        ValueError: si una pregunta no tiene `id` entero o no trae pregunta.
    """
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el set de preguntas: {ruta}")
    datos: dict[str, Any] = tomllib.loads(ruta.read_text(encoding="utf-8"))
    filas = datos.get("pregunta", [])
    if not isinstance(filas, list):
        raise ValueError(f"{ruta} no contiene una lista [[pregunta]]")

    preguntas: list[Pregunta] = []
    for fila in filas:
        if not isinstance(fila, dict):
            continue
        fuentes = tuple(
            str(url).strip() for url in fila.get("fuentes_esperadas", []) if str(url).strip()
        )
        if not fuentes:
            continue
        texto = str(fila.get("pregunta", "")).strip()
        if not texto:
            raise ValueError(f"Pregunta sin texto en {ruta}: {fila!r}")
        identificador = fila.get("id")
        if not isinstance(identificador, int):
            raise ValueError(f"Pregunta sin id entero en {ruta}: {fila!r}")
        preguntas.append(
            Pregunta(
                id=identificador,
                tipo=str(fila.get("tipo", "")).strip(),
                pregunta=texto,
                previa=str(fila.get("previa", "")).strip(),
                fuentes_esperadas=fuentes,
            )
        )
    preguntas.sort(key=lambda item: item.id)
    return preguntas


def consulta_de(pregunta: Pregunta) -> str:
    """Une la pregunta previa y la actual cuando es un seguimiento."""
    if pregunta.previa:
        return f"{pregunta.previa} {pregunta.pregunta}".strip()
    return pregunta.pregunta


def urls_distintas(urls: Sequence[str], limite: int = K_POR_DEFECTO) -> tuple[str, ...]:
    """Conserva hasta `limite` URL no repetidas, en el orden de recuperación."""
    vistas: set[str] = set()
    distintas: list[str] = []
    for url in urls:
        if not url or url in vistas:
            continue
        vistas.add(url)
        distintas.append(url)
        if len(distintas) >= limite:
            break
    return tuple(distintas)


def intervalo_wilson(
    aciertos: int,
    total: int,
    z: float = Z_95,
) -> tuple[float, float]:
    """Intervalo de confianza de Wilson para una proporción."""
    if total <= 0:
        return (0.0, 0.0)
    proporcion = aciertos / total
    denominador = 1 + (z * z / total)
    centro = (proporcion + (z * z / (2 * total))) / denominador
    margen = (
        z
        * math.sqrt((proporcion * (1 - proporcion) / total) + (z * z / (4 * total * total)))
        / denominador
    )
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def evaluar(
    preguntas: Sequence[Pregunta],
    recuperar: Recuperar,
    k: int = K_POR_DEFECTO,
) -> list[Resultado]:
    """Recupera y puntúa cada pregunta con `hit_at_k` y `mrr` del Arqueo."""
    resultados: list[Resultado] = []
    for pregunta in preguntas:
        consulta = consulta_de(pregunta)
        recuperadas = tuple(recuperar(consulta, k))
        distintas = urls_distintas(recuperadas, k)
        esperadas = [pregunta.fuentes_esperadas]
        resultados.append(
            Resultado(
                pregunta=pregunta,
                consulta=consulta,
                recuperadas=recuperadas,
                distintas=distintas,
                acierto=bool(hit_at_k([recuperadas], esperadas, k)),
                rr=float(mrr([recuperadas], esperadas, k) or 0.0),
                acierto_distintas=bool(hit_at_k([distintas], esperadas, k)),
                rr_distintas=float(mrr([distintas], esperadas, k) or 0.0),
            )
        )
    return resultados


def resumir(resultados: Sequence[Resultado], k: int = K_POR_DEFECTO) -> dict[str, Any]:
    """Agrega hit@k y MRR por tipo y en total, con el intervalo de Wilson."""
    tipos = sorted({resultado.pregunta.tipo for resultado in resultados})
    grupos: dict[str, list[Resultado]] = {"total": list(resultados)}
    for tipo in tipos:
        grupos[tipo] = [resultado for resultado in resultados if resultado.pregunta.tipo == tipo]

    filas: dict[str, dict[str, Any]] = {}
    for nombre, grupo in grupos.items():
        recuperadas = [resultado.recuperadas for resultado in grupo]
        distintas = [resultado.distintas for resultado in grupo]
        esperadas = [resultado.pregunta.fuentes_esperadas for resultado in grupo]
        filas[nombre] = {
            "n": len(grupo),
            "hit_at_k": _redondear(hit_at_k(recuperadas, esperadas, k)),
            "mrr": _redondear(mrr(recuperadas, esperadas, k)),
            "hit_at_k_distintas": _redondear(hit_at_k(distintas, esperadas, k)),
            "mrr_distintas": _redondear(mrr(distintas, esperadas, k)),
        }

    aciertos = sum(1 for resultado in resultados if resultado.acierto)
    limite_inferior, limite_superior = intervalo_wilson(aciertos, len(resultados))
    return {
        "k": k,
        "evaluables": len(resultados),
        "aciertos": aciertos,
        "intervalo_wilson_95": [
            round(limite_inferior, 4),
            round(limite_superior, 4),
        ],
        "total": filas.pop("total"),
        "por_tipo": filas,
    }


def formatear(resumen: dict[str, Any]) -> str:
    """Devuelve la tabla legible de la medición."""
    k = int(resumen["k"])
    lineas = [
        f"{'Tipo':<12} {'n':>4} {f'hit@{k}':>8} {'MRR':>8} {f'hit@{k}*':>9} {'MRR*':>8}",
        "-" * 56,
    ]
    orden = ["total", *sorted(resumen["por_tipo"])]
    for nombre in orden:
        fila = resumen["total"] if nombre == "total" else resumen["por_tipo"][nombre]
        lineas.append(
            f"{nombre:<12} {fila['n']:>4} {_texto(fila['hit_at_k']):>8} "
            f"{_texto(fila['mrr']):>8} {_texto(fila['hit_at_k_distintas']):>9} "
            f"{_texto(fila['mrr_distintas']):>8}"
        )
    inferior, superior = resumen["intervalo_wilson_95"]
    lineas.extend(
        [
            "",
            f"* variante de {k} URL distintas.",
            (
                f"hit@{k} total: {_texto(resumen['total']['hit_at_k'])} "
                f"({resumen['aciertos']}/{resumen['evaluables']}) "
                f"IC95% Wilson: [{inferior:.3f}, {superior:.3f}]"
            ),
        ]
    )
    return "\n".join(lineas)


def guardar_salida(
    ruta: Path,
    modo: str,
    alcance: Alcance,
    resumen: dict[str, Any],
    resultados: Sequence[Resultado],
) -> None:
    """Escribe el resumen y el detalle por pregunta en un JSON determinista."""
    detalle = [
        {
            "id": resultado.pregunta.id,
            "tipo": resultado.pregunta.tipo,
            "consulta": resultado.consulta,
            "esperadas": list(resultado.pregunta.fuentes_esperadas),
            "recuperadas": list(resultado.recuperadas),
            "distintas": list(resultado.distintas),
            "acierto": resultado.acierto,
            "rr": round(resultado.rr, 6),
            "acierto_distintas": resultado.acierto_distintas,
            "rr_distintas": round(resultado.rr_distintas, 6),
        }
        for resultado in resultados
    ]
    contenido = {
        "modo": modo,
        "alcance": alcance,
        "resumen": resumen,
        "preguntas": detalle,
    }
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(contenido, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def construir_recuperador(
    config: Config,
    modo: str,
    alcance: Alcance,
    k: int,
) -> Recuperar:
    """Devuelve la función de recuperación del modo pedido.

    Raises:
        FileNotFoundError: si falta el índice o los fragmentos del alcance.
    """
    if modo == "hibrido":
        ajustes = cargar_configuracion_recuperacion()
        recuperador = crear_recuperador(
            config,
            alcance,
            configuracion=ConfiguracionRecuperacion(
                k=k,
                peso_vectorial=ajustes.peso_vectorial,
                peso_bm25=ajustes.peso_bm25,
            ),
        )
        return lambda consulta, limite: [
            fragmento.url for fragmento in recuperador.buscar(consulta, limite)
        ]

    if not ruta_almacen(config).exists():
        raise FileNotFoundError(
            "No hay índice en data/boveda/chroma: ejecuta `make indice` antes de medir."
        )
    vectorial = RecuperadorVectorial(
        almacen=ChromaAlmacen(ruta_almacen(config)),
        embeddings=crear_embeddings(),
        k=k,
    )

    def recuperar(consulta: str, limite: int) -> list[str]:
        """Devuelve las URL de los documentos vectoriales recuperados."""
        documentos: list[Document] = vectorial.invoke(consulta)[:limite]
        return [str(documento.metadata.get("url", "")) for documento in documentos]

    return recuperar


def _redondear(valor: float | None) -> float | None:
    """Redondea una métrica a tres decimales, conservando `None`."""
    return None if valor is None else round(valor, 3)


def _texto(valor: float | None) -> str:
    """Formatea una métrica o un guion si no es evaluable."""
    return "—" if valor is None else f"{valor:.3f}"


def _ruta_salida(ruta: Path | None, modo: str) -> Path:
    """Resuelve la ruta de salida y usa `data/boveda/mediciones` por defecto."""
    if ruta is None:
        return CARPETA_MEDICIONES / f"recuperacion_{modo}.json"
    return ruta if ruta.is_absolute() else PROJECT_ROOT / ruta


def _configurar_salida() -> None:
    """Fuerza UTF-8 en la salida para que las tildes se vean en Windows."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta la medición y devuelve el código de salida."""
    _configurar_salida()
    parser = argparse.ArgumentParser(
        prog="medir_recuperacion.py",
        description="Mide hit@k y MRR de la Bóveda sobre las preguntas de fase 2.",
    )
    parser.add_argument("--hibrido", action="store_true", help="usa el recuperador híbrido")
    parser.add_argument("--k", type=int, default=K_POR_DEFECTO, help="fragmentos a recuperar")
    parser.add_argument(
        "--alcance",
        choices=("base", "completo"),
        default="base",
        help="alcance del índice que se mide",
    )
    parser.add_argument("--preguntas", type=Path, default=RUTA_PREGUNTAS)
    parser.add_argument(
        "--salida",
        type=Path,
        default=None,
        help="JSON de resultados; por defecto data/boveda/mediciones/recuperacion_<modo>.json",
    )
    args = parser.parse_args(argv)

    if args.k <= 0:
        print("Error: --k debe ser mayor que cero.", file=sys.stderr)
        return 1
    if not args.preguntas.exists():
        print(f"Error: no existe el set de preguntas {args.preguntas}", file=sys.stderr)
        return 1

    modo = "hibrido" if args.hibrido else "vectorial"
    if modo == "hibrido":
        ajustes = cargar_configuracion_recuperacion()
        print(
            f"Modo: híbrido (vectorial={ajustes.peso_vectorial:g}, "
            f"bm25={ajustes.peso_bm25:g}; k={args.k})",
            flush=True,
        )
    else:
        print(f"Modo: solo vectorial (k={args.k})", flush=True)

    try:
        preguntas = cargar_preguntas(args.preguntas)
        if not preguntas:
            print("Error: no hay preguntas con fuentes esperadas.", file=sys.stderr)
            return 1
        config = load_config()
        recuperar = construir_recuperador(config, modo, args.alcance, args.k)
        resultados = evaluar(preguntas, recuperar, args.k)
    except (FileNotFoundError, ValueError, RuntimeError, httpx.HTTPError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    resumen = resumir(resultados, args.k)
    print(formatear(resumen))
    destino = _ruta_salida(args.salida, modo)
    guardar_salida(destino, modo, args.alcance, resumen, resultados)
    print(f"\nDetalle guardado en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
