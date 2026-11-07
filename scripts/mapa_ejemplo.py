"""Genera ``app/web/datos-ejemplo/mapa.json`` con fragmentos reales de la Bóveda.

    uv run python scripts/mapa_ejemplo.py

La maqueta de la Bóveda (``?ejemplo=1``) necesita un mapa sin Ollama ni Chroma.
Este script usa los fragmentos del alcance ``base`` construidos **solo con los
datos versionados**: ignora ``data/knowledge/chunks.jsonl`` aunque exista, porque
ese archivo (con PDF y videos) no se versiona y haría que la maqueta dependiera
de la máquina. Los ubica en 2D con una **aproximación**: TF-IDF en lugar de los
embeddings ``nomic-embed-text-v2-moe`` y PCA de dos componentes, con ``x`` e
``y`` normalizados de 0 a 100 como hace el servidor. El top de la pregunta se
ordena por similitud coseno sobre esos mismos vectores TF-IDF.

Es determinista: dos ejecuciones dan el mismo archivo. El mapa real lo calcula
``boveda/mapa.py`` (PR 11) con los vectores del índice.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.decomposition import PCA
from sklearn.feature_extraction.text import TfidfVectorizer

from banco_occidente_corpus.boveda.fragmentos import construir_fragmentos
from banco_occidente_corpus.boveda.tipos import Fragmento
from banco_occidente_corpus.config import PROJECT_ROOT, Config, Paths, load_config

SALIDA = PROJECT_ROOT / "app" / "web" / "datos-ejemplo" / "mapa.json"

PREGUNTA = "¿Qué beneficios tiene la cuenta de nómina?"
"""Pregunta de la maqueta: la vista la muestra como ejemplo."""

TOP_K = 5
"""Fragmentos que devuelve el top, igual que la Bóveda real."""


class _RutasSoloVersionadas(Paths):
    """Rutas en las que ``chunks.jsonl`` no existe, aunque el archivo esté en disco.

    ``chunks.jsonl`` incluye PDF y videos y no se versiona, así que apuntar su
    ruta a un archivo inexistente deja fuera ese contenido sin tocar ``make
    fragmentos`` ni ``make indice``, que siguen usando ``Paths`` completo.
    """

    @property
    def knowledge_chunks(self) -> Path:
        """Ruta inexistente: ``construir_fragmentos`` solo lee ``chunks_web.jsonl``."""
        return self.knowledge / "chunks.jsonl.no-versionado"


def config_versionada() -> Config:
    """Configuración del proyecto que usa solo los datos versionados.

    Mantiene las rutas que resuelve ``load_config`` (incluidas las variables de
    entorno) salvo la de ``chunks.jsonl``, que apunta a un archivo inexistente.

    Returns:
        Configuración lista para ``construir_fragmentos``.
    """
    config = load_config()
    rutas = _RutasSoloVersionadas(
        root=config.paths.root,
        raw=config.paths.raw,
        processed=config.paths.processed,
        gold=config.paths.gold,
        knowledge=config.paths.knowledge,
    )
    return replace(config, paths=rutas)


def generar(fragmentos: Sequence[Fragmento], pregunta: str = PREGUNTA) -> dict[str, Any]:
    """Calcula puntos, pregunta y top con la forma de ``GET /api/boveda/mapa``.

    Args:
        fragmentos: Fragmentos de la Bóveda, en el orden en que se indexan.
        pregunta: Texto que se proyecta sobre el mismo plano.

    Returns:
        Diccionario con ``puntos``, ``pregunta`` y ``top``; las coordenadas
        van redondeadas a un decimal y entre 0 y 100.
    """
    textos = [f"{f.titulo}\n{f.encabezado}\n{f.texto}" for f in fragmentos]
    vectorizador = TfidfVectorizer(
        strip_accents="unicode", lowercase=True, min_df=2, sublinear_tf=True
    )
    matriz = vectorizador.fit_transform(textos)
    consulta = vectorizador.transform([pregunta])

    pca = PCA(n_components=2, svd_solver="full")
    planos = pca.fit_transform(matriz.toarray())
    plano_pregunta = pca.transform(consulta.toarray())[0]

    todos = np.vstack([planos, plano_pregunta])
    minimo = todos.min(axis=0)
    rango = np.where(todos.max(axis=0) - minimo == 0, 1, todos.max(axis=0) - minimo)
    normalizados = (todos - minimo) / rango * 100

    similitudes = (matriz @ consulta.T).toarray().ravel()
    candidatos = sorted(range(len(fragmentos)), key=lambda i: (-similitudes[i], fragmentos[i].id))
    orden = candidatos[:TOP_K]

    puntos = [
        {
            "x": _redondear(normalizados[i][0]),
            "y": _redondear(normalizados[i][1]),
            "seccion": f.seccion,
            "titulo": f.titulo,
        }
        for i, f in enumerate(fragmentos)
    ]
    top = [
        {
            "id": fragmentos[i].id,
            "texto": fragmentos[i].texto,
            "url": fragmentos[i].url,
            "titulo": fragmentos[i].titulo,
            "seccion": fragmentos[i].seccion,
            "encabezado": fragmentos[i].encabezado,
            "tipo": fragmentos[i].tipo,
            "tokens": fragmentos[i].tokens,
            "puntaje": round(float(similitudes[i]), 2),
        }
        for i in orden
    ]
    ultimo = normalizados[-1]
    return {
        "puntos": puntos,
        "pregunta": {"x": _redondear(ultimo[0]), "y": _redondear(ultimo[1])},
        "top": top,
    }


def _redondear(valor: float) -> float:
    """Redondea una coordenada a un decimal y la deja dentro de 0–100."""
    return round(min(max(float(valor), 0.0), 100.0), 1)


def escribir(datos: dict[str, Any], ruta: Path = SALIDA) -> None:
    """Escribe el JSON con sangría de dos espacios y salto de línea final."""
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    """Construye los fragmentos versionados del alcance ``base`` y escribe la maqueta."""
    resultado = construir_fragmentos(config_versionada(), "base")
    datos = generar(resultado.fragmentos)
    escribir(datos)
    destino = SALIDA.relative_to(PROJECT_ROOT)
    print(f"{len(datos['puntos'])} puntos y top de {len(datos['top'])} en {destino}")


if __name__ == "__main__":
    main()
