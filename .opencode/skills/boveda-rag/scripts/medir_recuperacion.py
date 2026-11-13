"""Mide hit@5, MRR, recall@10 y nDCG@10 de la Bóveda sobre las preguntas de fase 2.

hit@5 y MRR usan una búsqueda de 5 resultados; recall@10 y nDCG@10 usan una
segunda búsqueda de 10, para no cambiar la fusión del recuperador híbrido.

Uso:
    uv run python .opencode/skills/boveda-rag/scripts/medir_recuperacion.py
    uv run python .opencode/skills/boveda-rag/scripts/medir_recuperacion.py --hibrido
    uv run python .opencode/skills/boveda-rag/scripts/medir_recuperacion.py --con-marca
    uv run python .opencode/skills/boveda-rag/scripts/medir_recuperacion.py --con-marca --sin-marca

Por defecto mide solo el componente vectorial; con `--hibrido` usa el
`crear_recuperador` de la Bóveda y los pesos de `config/sucursal.toml`. Con
`--con-marca` inyecta la marca en la consulta para probar robustez y con
`--sin-marca` retira sus menciones antes de buscar, porque el nombre aparece en
casi todos los fragmentos y desvía el vector. Los filtros se aplican en ese
orden, de modo que se pueden combinar. Evalúa solo las preguntas con
`fuentes_esperadas` y escribe el detalle por pregunta en
`data/boveda/mediciones/`, que no se versiona. No usa red salvo la llamada local
a Ollama para calcular embeddings.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from banco_occidente_corpus.arqueo.metricas import (
    K_RECALL,
    hit_at_k,
    mrr,
    ndcg_at_k,
    recall_at_k,
)
from banco_occidente_corpus.boveda.almacen import (
    AlmacenVectorial,
    cerrar_almacen,
    crear_almacen,
)
from banco_occidente_corpus.boveda.configuracion import (
    ConfiguracionRecuperacion,
    cargar_configuracion_recuperacion,
)
from banco_occidente_corpus.boveda.embeddings import crear_embeddings
from banco_occidente_corpus.boveda.fragmentos import Alcance
from banco_occidente_corpus.boveda.indice import comprobar_almacen, ruta_almacen
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

#: Patrones de las menciones de la marca que usan `--con-marca` y `--sin-marca`.
PATRONES_MARCA: tuple[str, ...] = (
    r"banco\s+de\s+occidente",
    r"banco\s+occidente",
)
#: Conectores que quedan colgando al retirar la marca y se van con ella.
CONECTORES: str = r"(?:el|la|los|las|un|una|de|del|al)"
#: Texto que se añade cuando la consulta no menciona el banco.
MENCION_MARCA: str = " del Banco de Occidente"

#: Función que devuelve hasta `k` URL para una consulta.
Recuperar = Callable[[str, int], Sequence[str]]


@dataclass(frozen=True, slots=True)
class RecuperadorAbierto:
    """Recuperador de la medición y el almacén que hay que cerrar al terminar."""

    recuperar: Recuperar
    almacen: AlmacenVectorial

    def cerrar(self) -> None:
        """Cierra el almacén abierto por `construir_recuperador`."""
        cerrar_almacen(self.almacen)


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
    recall_at_10: float
    ndcg_at_10: float
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


def poner_marca(consulta: str) -> str:
    """Inyecta la marca del banco en la consulta para probar robustez.

    Reemplaza «el banco», «del banco» y «al banco» por la marca conservando el
    artículo y su caja. Si la consulta menciona el banco de otra forma, la deja
    intacta; si no lo menciona, añade « del Banco de Occidente» antes del signo
    de cierre.
    """
    if _menciona_marca(consulta):
        return consulta
    texto, reemplazos = re.subn(
        r"\b(el|del|al)\s+banco\b",
        _marca_con_articulo,
        consulta,
        flags=re.IGNORECASE,
    )
    if reemplazos:
        return texto
    if _menciona_banco(consulta):
        return consulta
    return _antes_del_cierre(consulta, MENCION_MARCA)


def limpiar_marca(consulta: str) -> str:
    """Retira de la consulta las menciones de la marca del banco.

    Quita «Banco de Occidente» y «Banco Occidente» sin distinguir mayúsculas,
    arrastra el conector que queda colgando, normaliza los espacios y pega los
    signos a la palabra vecina. Si la consulta no menciona la marca o si al
    limpiarla se queda sin contenido, devuelve la consulta original.
    """
    texto = consulta
    encontrada = False
    for patron in PATRONES_MARCA:
        texto, reemplazos = re.subn(rf"\b{patron}\b", " ", texto, flags=re.IGNORECASE)
        encontrada = encontrada or reemplazos > 0
    if not encontrada:
        return consulta

    texto = re.sub(r"\s+", " ", texto).strip()
    texto = re.sub(r"([¿¡])\s+", r"\1", texto)
    texto = re.sub(r"\s+([,.;:!?])", r"\1", texto)
    texto = re.sub(rf"\s*\b{CONECTORES}\s*([,.;:!?])", r"\1", texto, flags=re.IGNORECASE)
    texto = re.sub(rf"\s*\b{CONECTORES}\s*$", "", texto, flags=re.IGNORECASE).strip()
    if not re.search(r"\w", texto):
        return consulta
    return texto


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
    con_marca: bool = False,
    sin_marca: bool = False,
) -> list[Resultado]:
    """Recupera y puntúa cada pregunta con las métricas del Arqueo.

    hit@5 y MRR se calculan con una búsqueda de `k` resultados; recall@10 y
    nDCG@10, con otra búsqueda de `K_RECALL`, para no alterar la fusión del
    recuperador híbrido. Con `con_marca`, inyecta la marca antes de buscar; con
    `sin_marca`, la limpia. Si se activan ambos, primero se inyecta y después se
    retira.
    """
    resultados: list[Resultado] = []
    limite_recall = max(k, K_RECALL)
    for pregunta in preguntas:
        consulta = consulta_de(pregunta)
        if con_marca:
            consulta = poner_marca(consulta)
        if sin_marca:
            consulta = limpiar_marca(consulta)
        recuperadas = tuple(recuperar(consulta, k))
        recuperadas_recall = tuple(recuperar(consulta, limite_recall))
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
                recall_at_10=float(recall_at_k([recuperadas_recall], esperadas, K_RECALL) or 0.0),
                ndcg_at_10=float(ndcg_at_k([recuperadas_recall], esperadas, K_RECALL) or 0.0),
                acierto_distintas=bool(hit_at_k([distintas], esperadas, k)),
                rr_distintas=float(mrr([distintas], esperadas, k) or 0.0),
            )
        )
    return resultados


def resumir(resultados: Sequence[Resultado], k: int = K_POR_DEFECTO) -> dict[str, Any]:
    """Agrega hit@k, MRR, recall@10 y nDCG@10 por tipo y en total."""
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
            "recall_at_10": _redondear(_promedio([resultado.recall_at_10 for resultado in grupo])),
            "ndcg_at_10": _redondear(_promedio([resultado.ndcg_at_10 for resultado in grupo])),
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
        f"{'Tipo':<12} {'n':>4} {f'hit@{k}':>8} {'MRR':>8} {'recall@10':>10} "
        f"{'nDCG@10':>9} {f'hit@{k}*':>9} {'MRR*':>8}",
        "-" * 87,
    ]
    orden = ["total", *sorted(resumen["por_tipo"])]
    for nombre in orden:
        fila = resumen["total"] if nombre == "total" else resumen["por_tipo"][nombre]
        lineas.append(
            f"{nombre:<12} {fila['n']:>4} {_texto(fila['hit_at_k']):>8} "
            f"{_texto(fila['mrr']):>8} {_texto(fila['recall_at_10']):>10} "
            f"{_texto(fila['ndcg_at_10']):>9} "
            f"{_texto(fila['hit_at_k_distintas']):>9} "
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
    con_marca: bool = False,
    sin_marca: bool = False,
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
            "recall_at_10": round(resultado.recall_at_10, 6),
            "ndcg_at_10": round(resultado.ndcg_at_10, 6),
            "acierto_distintas": resultado.acierto_distintas,
            "rr_distintas": round(resultado.rr_distintas, 6),
        }
        for resultado in resultados
    ]
    contenido = {
        "modo": modo,
        "alcance": alcance,
        "con_marca": con_marca,
        "sin_marca": sin_marca,
        "resumen": resumen,
        "preguntas": detalle,
    }
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(contenido, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _crear_recuperador_ventana(
    config: Config,
    modo: str,
    alcance: Alcance,
    ventana: int,
    *,
    almacen: AlmacenVectorial,
    embeddings: Embeddings,
) -> Recuperar:
    """Devuelve la función de recuperación para una ventana de resultados.

    Recibe el almacén y los embeddings ya abiertos para no abrir dos veces el
    índice persistente al construir la ventana corta y la larga.
    """
    if modo == "hibrido":
        ajustes = cargar_configuracion_recuperacion()
        recuperador = crear_recuperador(
            config,
            alcance,
            configuracion=ConfiguracionRecuperacion(
                k=ventana,
                peso_vectorial=ajustes.peso_vectorial,
                peso_bm25=ajustes.peso_bm25,
            ),
            embeddings=embeddings,
            almacen=almacen,
        )
        return lambda consulta, limite: [
            fragmento.url for fragmento in recuperador.buscar(consulta, limite)
        ]

    vectorial = RecuperadorVectorial(
        almacen=almacen,
        embeddings=embeddings,
        k=ventana,
    )

    def recuperar(consulta: str, limite: int) -> list[str]:
        """Devuelve las URL de los documentos vectoriales recuperados."""
        documentos: list[Document] = vectorial.invoke(consulta)[:limite]
        return [str(documento.metadata.get("url", "")) for documento in documentos]

    return recuperar


def construir_recuperador(
    config: Config,
    modo: str,
    alcance: Alcance,
    k: int,
) -> RecuperadorAbierto:
    """Devuelve la función de recuperación con una ventana corta y otra larga.

    hit@5 y MRR llaman con ``k``; recall@10 y nDCG@10 llaman con
    ``max(k, K_RECALL)``. Se construyen dos recuperadores, uno por ventana, para
    no alterar la fusión del híbrido. El almacén queda abierto mientras dure la
    medición y lo cierra quien recibe el resultado (ver `RecuperadorAbierto`).

    Raises:
        FileNotFoundError: si falta el índice o los fragmentos del alcance.
    """
    if not ruta_almacen(config).exists():
        raise FileNotFoundError(
            f"No hay índice en {ruta_almacen(config)}: ejecuta `make indice` antes de medir."
        )
    comprobar_almacen(config)
    almacen = crear_almacen(config)
    try:
        embeddings = crear_embeddings()
        corta = _crear_recuperador_ventana(
            config,
            modo,
            alcance,
            k,
            almacen=almacen,
            embeddings=embeddings,
        )
        larga = _crear_recuperador_ventana(
            config,
            modo,
            alcance,
            K_RECALL,
            almacen=almacen,
            embeddings=embeddings,
        )
    except Exception:
        cerrar_almacen(almacen)
        raise

    def recuperar(consulta: str, limite: int) -> list[str]:
        """Elige la búsqueda corta o la larga según el límite pedido."""
        usar_larga = limite > k and limite >= K_RECALL
        return larga(consulta, limite) if usar_larga else corta(consulta, limite)

    return RecuperadorAbierto(recuperar=recuperar, almacen=almacen)


def _promedio(valores: Sequence[float]) -> float | None:
    """Promedia una lista de métricas; devuelve `None` si está vacía."""
    return sum(valores) / len(valores) if valores else None


def _redondear(valor: float | None) -> float | None:
    """Redondea una métrica a tres decimales, conservando `None`."""
    return None if valor is None else round(valor, 3)


def _texto(valor: float | None) -> str:
    """Formatea una métrica o un guion si no es evaluable."""
    return "—" if valor is None else f"{valor:.3f}"


def _menciona_marca(texto: str) -> bool:
    """Indica si el texto ya nombra la marca del banco."""
    return any(re.search(rf"\b{patron}\b", texto, flags=re.IGNORECASE) for patron in PATRONES_MARCA)


def _menciona_banco(texto: str) -> bool:
    """Indica si el texto menciona el banco sin nombrar la marca."""
    return re.search(r"\bbancos?\b", texto, flags=re.IGNORECASE) is not None


def _marca_con_articulo(coincidencia: re.Match[str]) -> str:
    """Devuelve la marca conservando el artículo y su caja original."""
    return f"{coincidencia.group(1)} Banco de Occidente"


def _antes_del_cierre(texto: str, añadido: str) -> str:
    """Inserta un texto antes del signo de cierre final, si lo hay."""
    limpio = texto.rstrip()
    if not limpio:
        return añadido.strip()
    if limpio[-1] in "?!.":
        return f"{limpio[:-1].rstrip()}{añadido}{limpio[-1]}"
    return f"{limpio}{añadido}"


def _ruta_salida(
    ruta: Path | None,
    modo: str,
    con_marca: bool = False,
    sin_marca: bool = False,
) -> Path:
    """Resuelve la ruta de salida y usa `data/boveda/mediciones` por defecto."""
    if ruta is None:
        sufijos = ("_con_marca" if con_marca else "") + ("_sin_marca" if sin_marca else "")
        return CARPETA_MEDICIONES / f"recuperacion_{modo}{sufijos}.json"
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
        description=(
            "Mide hit@k, MRR, recall@10 y nDCG@10 de la Bóveda sobre las preguntas de fase 2."
        ),
    )
    parser.add_argument("--hibrido", action="store_true", help="usa el recuperador híbrido")
    parser.add_argument(
        "--con-marca",
        action="store_true",
        help="inyecta la marca del banco en la consulta antes de buscar",
    )
    parser.add_argument(
        "--sin-marca",
        action="store_true",
        help="retira las menciones de la marca de la consulta antes de buscar",
    )
    parser.add_argument(
        "--k",
        type=int,
        default=K_POR_DEFECTO,
        help=(
            f"ventana de hit@k y MRR; recall@10 y nDCG@10 usan siempre una búsqueda de {K_RECALL}"
        ),
    )
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
        help=(
            "JSON de resultados; por defecto "
            "data/boveda/mediciones/recuperacion_<modo><filtros>.json"
        ),
    )
    args = parser.parse_args(argv)

    if args.k <= 0:
        print("Error: --k debe ser mayor que cero.", file=sys.stderr)
        return 1
    if not args.preguntas.exists():
        print(f"Error: no existe el set de preguntas {args.preguntas}", file=sys.stderr)
        return 1

    if args.con_marca or args.sin_marca:
        filtros = [
            nombre
            for activo, nombre in (
                (args.con_marca, "con marca"),
                (args.sin_marca, "sin marca"),
            )
            if activo
        ]
        print(f"Filtros: {', '.join(filtros)}", flush=True)
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

    abierto: RecuperadorAbierto | None = None
    try:
        preguntas = cargar_preguntas(args.preguntas)
        if not preguntas:
            print("Error: no hay preguntas con fuentes esperadas.", file=sys.stderr)
            return 1
        config = load_config()
        abierto = construir_recuperador(config, modo, args.alcance, args.k)
        resultados = evaluar(
            preguntas,
            abierto.recuperar,
            args.k,
            con_marca=args.con_marca,
            sin_marca=args.sin_marca,
        )
    except (FileNotFoundError, ValueError, RuntimeError, httpx.HTTPError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        if abierto is not None:
            abierto.cerrar()

    resumen = resumir(resultados, args.k)
    print(formatear(resumen))
    destino = _ruta_salida(args.salida, modo, args.con_marca, args.sin_marca)
    guardar_salida(
        destino,
        modo,
        args.alcance,
        resumen,
        resultados,
        args.con_marca,
        args.sin_marca,
    )
    print(f"\nDetalle guardado en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
