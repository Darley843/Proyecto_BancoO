"""Capa Contexto: prompt de sistema del asistente, derivado de Gold.

Lee solo ``data/gold/corpus.jsonl`` y ``data/gold/pages/*.md`` (nunca Bronze,
Silver ni la web), quita el frontmatter, descarta paginas clonadas y lineas
repetidas, y escribe un Markdown acotado por tokens mas un manifest de auditoria.
El recorte se decide con ``utils.stable_tokens``: sin red y determinista.

El modulo es autocontenido: su configuracion (``config/contexto.toml``) y sus
rutas (``data/contexto/``) viven aqui, no en ``config.py``, y se ejecuta con
``uv run python -m banco_occidente_corpus.contexto`` sin pasar por el CLI del
pipeline.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config as config_mod
from .config import Config, load_config
from .dedupe import find_boilerplate, normalize_line, strip_boilerplate_detailed
from .knowledge import load_page
from .utils import read_jsonl, sha256_text, stable_tokens

log = logging.getLogger(__name__)

#: Tipos de ficha de noticias/prensa dentro de Gold.
FICHA_TIPOS = ("hecho", "noticia")

#: Cuerpo minimo (caracteres) para que una pagina aporte algo al prompt.
MIN_CUERPO = 40

#: Titulo del bloque que rescata las lineas repetidas.
TITULO_COMUN = "Información común del sitio"

#: Encabezado del documento (sin fecha, para que el archivo sea reproducible).
PREAMBULO = (
    "# Contexto del Banco de Occidente",
    "Documento generado a partir de data/gold. No editar a mano: make contexto.",
)

#: Encabezados del cuerpo (niveles 1-5) que se degradan para no romper el bloque.
_HEADING = re.compile(r"^(#{1,5})(\s)")
_FENCE = re.compile(r"^\s*(```|~~~)")

#: Tope de tokens por defecto del prompt de sistema (igual que config/contexto.toml).
DEFAULT_MAX_TOKENS = 175000

#: Regex de URL excluidas por defecto (igual que config/contexto.toml).
DEFAULT_PATRONES_URL_EXCLUIDOS: tuple[str, ...] = ("/buscador", "/error", "^https?://[^/]+/?$")

#: Secciones de Gold y su prioridad por defecto en el contexto (1 = mas importante).
DEFAULT_SECCIONES: dict[str, int] = {
    "identidad": 1,
    "atencion": 2,
    "oferta": 3,
    "legal": 4,
    "datos": 5,
    "presencia": 6,
    "otros": 7,
}


@dataclass(slots=True)
class ContextoConfig:
    """Parametros del contexto que consume el asistente Q&A (config/contexto.toml)."""

    max_tokens: int = DEFAULT_MAX_TOKENS
    incluir_noticias: bool = True
    max_noticias: int = 12
    boilerplate_min_docs: int = 5
    boilerplate_ratio: float = 0.10
    bloque_comun: bool = True
    secciones: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_SECCIONES))
    patrones_url_excluidos: list[str] = field(
        default_factory=lambda: list(DEFAULT_PATRONES_URL_EXCLUIDOS)
    )


@dataclass(frozen=True, slots=True)
class RutasContexto:
    """Rutas de la capa Contexto, resueltas aqui y no en ``config.py``."""

    base: Path
    archivo: Path
    manifest: Path

    @classmethod
    def desde(cls, config: Config) -> RutasContexto:
        """Resuelve ``data/contexto`` respetando ``CORPUS_CONTEXTO_DIR``."""
        raw = os.getenv("CORPUS_CONTEXTO_DIR")
        base = Path(raw).expanduser().resolve() if raw else config.paths.root / "data/contexto"
        return cls(
            base=base,
            archivo=base / "contexto_banco.md",
            manifest=base / "manifest.json",
        )


def load_contexto_config(path: str | Path | None = None) -> ContextoConfig:
    """Carga config/contexto.toml; si falta, usa los valores por defecto."""
    if path:
        config_path = Path(path)
    else:
        raw = os.getenv("CORPUS_CONTEXTO_CONFIG")
        config_path = (
            Path(raw).expanduser().resolve()
            if raw
            else config_mod.PROJECT_ROOT / "config" / "contexto.toml"
        )
    if not config_path.exists():
        return ContextoConfig()

    with config_path.open("rb") as fh:
        data = tomllib.load(fh)

    secciones = {str(k): int(v) for k, v in (data.get("secciones") or {}).items()}
    return ContextoConfig(
        max_tokens=int(data.get("max_tokens", DEFAULT_MAX_TOKENS)),
        incluir_noticias=bool(data.get("incluir_noticias", True)),
        max_noticias=int(data.get("max_noticias", 12)),
        boilerplate_min_docs=int(data.get("boilerplate_min_docs", 5)),
        boilerplate_ratio=float(data.get("boilerplate_ratio", 0.10)),
        bloque_comun=bool(data.get("bloque_comun", True)),
        secciones=secciones or dict(DEFAULT_SECCIONES),
        patrones_url_excluidos=[
            str(p) for p in data.get("patrones_url_excluidos", DEFAULT_PATRONES_URL_EXCLUIDOS)
        ],
    )


def _heading_shift(body: str) -> int:
    """Desplazamiento necesario para que ningun encabezado del cuerpo quede en ``##``."""
    niveles: list[int] = []
    en_codigo = False
    for linea in body.splitlines():
        if _FENCE.match(linea):
            en_codigo = not en_codigo
            continue
        if en_codigo:
            continue
        match = _HEADING.match(linea)
        if match:
            niveles.append(len(match.group(1)))
    if not niveles:
        return 1
    return max(1, 3 - min(niveles))


def demote_headings(body: str) -> str:
    """Baja los encabezados del cuerpo (## -> ###) y respeta los bloques de codigo.

    El bloque de cada pagina usa ``##`` como frontera. Algunas paginas de Gold ya
    traen ``##`` y las fichas de prensa empiezan con ``#`` (nivel 1): se degrada un
    nivel y, si el cuerpo arranca en ``#``, dos, para que ningun encabezado del
    cuerpo caiga en ``##``. Solo se transforma el texto en memoria: Gold no cambia.
    """
    shift = _heading_shift(body)
    lineas: list[str] = []
    en_codigo = False
    for linea in body.splitlines():
        if _FENCE.match(linea):
            en_codigo = not en_codigo
            lineas.append(linea)
            continue
        match = None if en_codigo else _HEADING.match(linea)
        if match:
            nivel = min(6, len(match.group(1)) + shift)
            linea = "#" * nivel + linea[len(match.group(1)) :]
        lineas.append(linea)
    return "\n".join(lineas)


@dataclass(slots=True)
class Pagina:
    """Pagina Gold lista para entrar al contexto."""

    id: str
    titulo: str
    fuente: str
    seccion: str
    prioridad: int
    cuerpo: str
    tokens: int = 0
    hash: str = ""
    tipo: str = ""
    fecha: str = ""

    def bloque(self) -> str:
        """Bloque Markdown autocontenido de la pagina."""
        cuerpo = demote_headings(self.cuerpo.strip())
        return f"## {self.titulo}\nFuente: {self.fuente}\nSección: {self.seccion}\n\n{cuerpo}"

    def as_manifest(self) -> dict[str, Any]:
        """Fila de la pagina en el manifest."""
        return {
            "id": self.id,
            "titulo": self.titulo,
            "seccion": self.seccion,
            "fuente": self.fuente,
            "prioridad": self.prioridad,
            "tokens": self.tokens,
        }


@dataclass(slots=True)
class ResultadoContexto:
    """Resultado de la generacion del contexto."""

    incluidas: list[Pagina]
    excluidas: list[dict[str, Any]]
    comunes: list[str]
    tokens: int
    tokens_por_seccion: dict[str, int]
    descartadas_por_presupuesto: list[dict[str, Any]]
    archivo: Path
    manifest: Path


def _exclusion(
    pagina: Pagina | None,
    motivo: str,
    detalle: str = "",
    *,
    fila: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Entrada uniforme de exclusion para el manifest."""
    if pagina is not None:
        return {
            "id": pagina.id,
            "titulo": pagina.titulo,
            "seccion": pagina.seccion,
            "fuente": pagina.fuente,
            "motivo": motivo,
            "detalle": detalle,
        }
    fila = fila or {}
    return {
        "id": str(fila.get("id", "")),
        "titulo": str(fila.get("titulo", "")),
        "seccion": str(fila.get("seccion", "")),
        "fuente": str(fila.get("fuente", "")),
        "motivo": motivo,
        "detalle": detalle,
    }


def _tipo_ficha(pid: str, meta: dict[str, Any]) -> str:
    """Tipo de ficha segun el frontmatter, con respaldo en el identificador."""
    tipo = str(meta.get("tipo") or "")
    if tipo in FICHA_TIPOS:
        return tipo
    if pid.startswith("hecho-"):
        return "hecho"
    if pid.startswith("noticia-"):
        return "noticia"
    return tipo


def load_paginas(config: Config, ctx: ContextoConfig) -> tuple[list[Pagina], list[dict[str, Any]]]:
    """Lee corpus.jsonl y devuelve las paginas candidatas y las excluidas."""
    paginas: list[Pagina] = []
    excluidas: list[dict[str, Any]] = []
    patrones = [re.compile(patron, re.IGNORECASE) for patron in ctx.patrones_url_excluidos]
    carpeta = config.paths.gold_markdown.resolve()

    for fila in read_jsonl(config.paths.corpus_file):
        archivo = config.paths.root / str(fila.get("archivo", ""))
        try:
            archivo.resolve().relative_to(carpeta)
            dentro = True
        except ValueError:
            dentro = False
        if not dentro:
            excluidas.append(
                _exclusion(
                    None,
                    "fuente_no_pagina",
                    str(fila.get("archivo", "")),
                    fila=fila,
                )
            )
            continue
        if not archivo.exists():
            excluidas.append(_exclusion(None, "archivo_ausente", str(archivo), fila=fila))
            continue

        meta, cuerpo = load_page(archivo)
        pid = str(fila.get("id", archivo.stem))
        tipo = _tipo_ficha(pid, meta)
        if tipo in FICHA_TIPOS and not ctx.incluir_noticias:
            excluidas.append(_exclusion(None, "ficha_excluida", tipo, fila=fila))
            continue
        if tipo in FICHA_TIPOS and str(meta.get("estado") or "") == "pendiente":
            excluidas.append(_exclusion(None, "ficha_pendiente", "estado pendiente", fila=fila))
            continue

        fuente = str(meta.get("fuente") or fila.get("fuente") or "")
        if any(patron.search(fuente) for patron in patrones):
            excluidas.append(_exclusion(None, "url_excluida", fuente, fila=fila))
            continue

        seccion = str(meta.get("seccion") or fila.get("seccion") or "otros")
        if seccion not in ctx.secciones:
            excluidas.append(_exclusion(None, "seccion_no_incluida", seccion, fila=fila))
            continue

        paginas.append(
            Pagina(
                id=pid,
                titulo=str(meta.get("titulo") or fila.get("titulo") or pid),
                fuente=fuente,
                seccion=seccion,
                prioridad=int(ctx.secciones[seccion]),
                cuerpo=cuerpo,
                tipo=tipo,
                fecha=str(meta.get("fecha_publicacion") or ""),
            )
        )

    return _ventana_noticias(paginas, ctx, excluidas)


def _ventana_noticias(
    paginas: list[Pagina],
    ctx: ContextoConfig,
    excluidas: list[dict[str, Any]],
) -> tuple[list[Pagina], list[dict[str, Any]]]:
    """Conserva solo las ``max_noticias`` fichas mas recientes (global, no por tipo)."""
    fichas = [pagina for pagina in paginas if pagina.tipo in FICHA_TIPOS]
    if len(fichas) <= ctx.max_noticias:
        return paginas, excluidas

    ordenadas = sorted(fichas, key=lambda pagina: (pagina.fecha, pagina.id), reverse=True)
    conservadas = ordenadas[: max(ctx.max_noticias, 0)]
    ids = {pagina.id for pagina in conservadas}
    corte = conservadas[-1].fecha if conservadas else ""
    for pagina in ordenadas:
        if pagina.id in ids:
            continue
        fecha = pagina.fecha or "sin fecha"
        excluidas.append(
            _exclusion(
                pagina,
                "ficha_fuera_de_ventana",
                f"fecha_publicacion {fecha} < corte {corte}",
            )
        )
    resto = [pagina for pagina in paginas if pagina.tipo not in FICHA_TIPOS]
    return [*resto, *conservadas], excluidas


def sort_paginas(paginas: list[Pagina]) -> list[Pagina]:
    """Orden determinista: prioridad de seccion y luego titulo."""
    return sorted(
        paginas, key=lambda pagina: (pagina.prioridad, pagina.titulo.casefold(), pagina.id)
    )


def limpiar_paginas(
    paginas: list[Pagina],
    ctx: ContextoConfig,
) -> tuple[list[Pagina], list[dict[str, Any]], list[str]]:
    """Deduplica por hash, quita boilerplate y descarta cuerpos vacios.

    El orden importa: primero se eliminan las paginas clonadas para que sus
    lineas no inflen el conteo de repetidas; despues se calcula el boilerplate
    sobre las paginas unicas.
    """
    ordenadas = sort_paginas(paginas)
    unicas: list[Pagina] = []
    excluidas: list[dict[str, Any]] = []
    vistos: dict[str, str] = {}

    for pagina in ordenadas:
        digest = sha256_text(pagina.cuerpo.strip())
        if digest in vistos:
            excluidas.append(_exclusion(pagina, "duplicado", f"duplicado_de:{vistos[digest]}"))
            continue
        vistos[digest] = pagina.id
        pagina.hash = digest
        unicas.append(pagina)

    boilerplate = find_boilerplate(
        (pagina.cuerpo.splitlines() for pagina in unicas),
        min_docs=ctx.boilerplate_min_docs,
        ratio=ctx.boilerplate_ratio,
    )
    incluidas: list[Pagina] = []
    comunes: list[str] = []
    vistas_comunes: set[str] = set()

    for pagina in unicas:
        cuerpo, retiradas = strip_boilerplate_detailed(pagina.cuerpo, boilerplate)
        if len(cuerpo.strip()) < MIN_CUERPO:
            excluidas.append(
                _exclusion(pagina, "cuerpo_vacio", f"{len(cuerpo.strip())} caracteres")
            )
            continue
        pagina.cuerpo = cuerpo.strip()
        pagina.tokens = stable_tokens(pagina.bloque())
        incluidas.append(pagina)
        if ctx.bloque_comun:
            for linea in retiradas:
                normal = normalize_line(linea)
                if normal and normal not in vistas_comunes:
                    vistas_comunes.add(normal)
                    comunes.append(linea.strip())

    return incluidas, excluidas, comunes


def _bloque_comun(comunes: list[str]) -> str:
    """Bloque inicial que conserva una vez las lineas repetidas del sitio."""
    cuerpo = "\n".join(demote_headings(linea) for linea in comunes)
    return f"## {TITULO_COMUN}\nFuente: data/gold/pages/*.md\nSección: varias\n\n" + cuerpo


def render_contexto(paginas: list[Pagina], comunes: list[str]) -> str:
    """Markdown final: preambulo, bloque comun y un bloque por pagina."""
    bloques: list[str] = []
    if comunes:
        bloques.append(_bloque_comun(comunes))
    bloques.extend(pagina.bloque() for pagina in paginas)
    return "\n\n".join([*PREAMBULO, *bloques]) + "\n"


class PresupuestoExcedido(RuntimeError):
    """El contexto no cabe en ``max_tokens`` ni siquiera sin paginas."""


def fit_budget(
    paginas: list[Pagina],
    comunes: list[str],
    max_tokens: int,
) -> tuple[list[Pagina], list[dict[str, Any]], list[Pagina]]:
    """Descarta secciones de menor prioridad hasta caber en ``max_tokens``."""
    actual = list(paginas)
    retiradas: list[Pagina] = []
    descartadas: list[dict[str, Any]] = []

    while actual and stable_tokens(render_contexto(actual, comunes)) > max_tokens:
        prioridad_baja = max(pagina.prioridad for pagina in actual)
        candidatas = [pagina for pagina in actual if pagina.prioridad == prioridad_baja]
        if len({pagina.seccion for pagina in actual}) == 1:
            # Ultimo recurso: la pagina con el titulo mayor (cola del orden estable).
            candidatas = [max(candidatas, key=lambda pagina: (pagina.titulo.casefold(), pagina.id))]
            motivo = "presupuesto"
        else:
            seccion_baja = min(pagina.seccion for pagina in candidatas)
            candidatas = [pagina for pagina in candidatas if pagina.seccion == seccion_baja]
            motivo = "presupuesto"
        ids = {pagina.id for pagina in candidatas}
        actual = [pagina for pagina in actual if pagina.id not in ids]
        retiradas.extend(candidatas)

        seccion = candidatas[0].seccion
        tokens = sum(pagina.tokens for pagina in candidatas)
        for entrada in descartadas:
            if entrada["seccion"] == seccion:
                entrada["paginas"] += len(candidatas)
                entrada["tokens"] += tokens
                break
        else:
            descartadas.append(
                {
                    "seccion": seccion,
                    "motivo": motivo,
                    "paginas": len(candidatas),
                    "tokens": tokens,
                }
            )

    final = render_contexto(actual, comunes)
    tokens_finales = stable_tokens(final)
    if tokens_finales > max_tokens:
        raise PresupuestoExcedido(
            f"El contexto no cabe en max_tokens={max_tokens}: "
            f"el preambulo y el bloque comun ocupan {tokens_finales} tokens. "
            "Sube max_tokens en config/contexto.toml antes de volver a generarlo."
        )

    return actual, descartadas, retiradas


def build_contexto(
    config: Config,
    ctx: ContextoConfig,
) -> ResultadoContexto:
    """Gold -> contexto_banco.md + manifest.json (determinista, sin red)."""
    paginas, excluidas = load_paginas(config, ctx)
    leidas = len(paginas) + len(excluidas)
    incluidas, otras_excluidas, comunes = limpiar_paginas(paginas, ctx)
    excluidas.extend(otras_excluidas)

    finales, descartadas, retiradas = fit_budget(incluidas, comunes, ctx.max_tokens)
    for pagina in retiradas:
        excluidas.append(_exclusion(pagina, "presupuesto", f"max_tokens {ctx.max_tokens}"))

    contenido = render_contexto(finales, comunes)
    tokens = stable_tokens(contenido)
    tokens_por_seccion: dict[str, int] = {}
    for pagina in finales:
        tokens_por_seccion[pagina.seccion] = (
            tokens_por_seccion.get(pagina.seccion, 0) + pagina.tokens
        )
    tokens_por_seccion = dict(
        sorted(
            tokens_por_seccion.items(),
            key=lambda item: (ctx.secciones.get(item[0], 99), item[0]),
        )
    )
    tokens_bloques = sum(pagina.tokens for pagina in finales)
    tokens_comunes = stable_tokens(_bloque_comun(comunes)) if comunes else 0

    rutas = RutasContexto.desde(config)
    rutas.base.mkdir(parents=True, exist_ok=True)
    archivo = rutas.archivo
    archivo.write_text(contenido, encoding="utf-8", newline="\n")

    manifest_path = rutas.manifest
    manifest: dict[str, Any] = {
        "version": 1,
        "max_tokens": ctx.max_tokens,
        "tokens": tokens,
        "tokens_metodo": "stable_tokens (chars/4, sin red)",
        "tokens_bloques": tokens_bloques,
        "tokens_informacion_comun": tokens_comunes,
        "tokens_cabeceras": max(0, tokens - tokens_bloques - tokens_comunes),
        "paginas": {
            "leidas": leidas,
            "incluidas": len(finales),
            "excluidas": len(excluidas),
        },
        "tokens_por_seccion": tokens_por_seccion,
        "informacion_comun": {
            "lineas": len(comunes),
            "tokens": tokens_comunes,
            "texto": comunes,
        },
        "descartadas_por_presupuesto": descartadas,
        "incluidas": [pagina.as_manifest() for pagina in finales],
        "excluidas": excluidas,
        "config": {
            "secciones": dict(ctx.secciones),
            "patrones_url_excluidos": list(ctx.patrones_url_excluidos),
            "incluir_noticias": ctx.incluir_noticias,
            "max_noticias": ctx.max_noticias,
            "boilerplate_min_docs": ctx.boilerplate_min_docs,
            "boilerplate_ratio": ctx.boilerplate_ratio,
            "bloque_comun": ctx.bloque_comun,
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    log.info(
        "Contexto: %d paginas incluidas de %d leidas, %d tokens (max %d)",
        len(finales),
        leidas,
        tokens,
        ctx.max_tokens,
    )
    return ResultadoContexto(
        incluidas=finales,
        excluidas=excluidas,
        comunes=comunes,
        tokens=tokens,
        tokens_por_seccion=tokens_por_seccion,
        descartadas_por_presupuesto=descartadas,
        archivo=archivo,
        manifest=manifest_path,
    )


def _setup_logging() -> None:
    """Configura el logging del modulo sin depender del CLI del pipeline."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser del generador de contexto (sin subcomandos)."""
    parser = argparse.ArgumentParser(
        prog="python -m banco_occidente_corpus.contexto",
        description="Genera el prompt del asistente desde data/gold (sin red).",
    )
    parser.add_argument("--max-tokens", type=int, default=None, help="tope de tokens")
    parser.add_argument(
        "--sin-noticias",
        action="store_true",
        help="excluye las fichas noticia-*/hecho-*",
    )
    parser.add_argument(
        "--config-contexto",
        default=None,
        help="ruta alternativa a contexto.toml",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Gold -> data/contexto/contexto_banco.md + manifest.json (sin red)."""
    args = build_parser().parse_args(argv)
    _setup_logging()
    config = load_config()
    ctx = load_contexto_config(args.config_contexto)
    if args.max_tokens:
        ctx.max_tokens = int(args.max_tokens)
    if args.sin_noticias:
        ctx.incluir_noticias = False

    if not config.paths.corpus_file.exists():
        log.error("No hay Gold. Ejecuta 'make gold' primero.")
        return 1

    try:
        resultado = build_contexto(config, ctx)
    except PresupuestoExcedido as exc:
        log.error("%s", exc)
        return 1
    if not resultado.incluidas:
        log.error("Contexto vacio: revisa las exclusiones en %s", resultado.manifest)
        return 1

    print(
        f"Contexto      : {len(resultado.incluidas)} paginas, "
        f"{resultado.tokens:,} tokens (max {ctx.max_tokens:,})"
    )
    secciones = " | ".join(
        f"{nombre} {tokens:,}" for nombre, tokens in resultado.tokens_por_seccion.items()
    )
    print(f"Secciones     : {secciones}")
    print(f"Comun         : {len(resultado.comunes)} lineas conservadas en el bloque inicial")

    motivos: dict[str, int] = {}
    for entrada in resultado.excluidas:
        motivos[entrada["motivo"]] = motivos.get(entrada["motivo"], 0) + 1
    detalle = ", ".join(f"{motivo}: {cuenta}" for motivo, cuenta in sorted(motivos.items()))
    print(f"Excluidas     : {len(resultado.excluidas)} ({detalle or 'ninguna'})")

    if resultado.descartadas_por_presupuesto:
        for entrada in resultado.descartadas_por_presupuesto:
            print(
                f"Presupuesto   : se descarto '{entrada['seccion']}' "
                f"({entrada['paginas']} paginas, {entrada['tokens']:,} tokens)"
            )
    else:
        print("Presupuesto   : sin descartes, entran todas las secciones")
    print(f"Archivo       : {resultado.archivo}")
    print(f"Manifest      : {resultado.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
