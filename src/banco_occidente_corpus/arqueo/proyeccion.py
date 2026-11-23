"""Proyección t-SNE de la Bóveda: fragmentos, preguntas del Arqueo y sus fallos.

`python -m banco_occidente_corpus.arqueo.proyeccion` lee los vectores del índice
(los mismos que consulta el recuperador), vectoriza las preguntas evaluables del
Arqueo con el mismo modelo local y ajusta un t-SNE de dos dimensiones con
distancia coseno y semilla fija. Escribe la figura en `docs/img/` y las cifras
en `data/evaluacion/proyeccion.json`.

t-SNE es solo una vista: deforma distancias globales y el tamaño de los grupos
no significa nada. Por eso las cifras que se leen salen del espacio original de
768 dimensiones, no del plano:

- **Pureza de vecindario**: de los 10 vecinos más cercanos por coseno de cada
  fragmento, qué proporción es de su misma sección. Una sección con pureza baja
  comparte vocabulario con otras y el recuperador las confunde.
- **Confiabilidad** (*trustworthiness*): cuánto respeta el plano los vecindarios
  originales; cerca de 1 quiere decir que los grupos que se ven existen.
- **Fallos**: para cada pregunta que no encontró su fuente en el top 5 con los
  pesos por defecto, la sección de su vecino más cercano y el puesto, solo por
  coseno, del mejor fragmento de la fuente esperada.

No llama a DeepSeek; usa Ollama, como `make arqueo`.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.manifold import TSNE, trustworthiness

from ..config import PROJECT_ROOT
from .experimentos import PreguntaFase2, cargar_preguntas_fase2, consulta_de, normalizar_url

#: Semilla del t-SNE: el año en que nació el banco.
SEMILLA: int = 1965
#: Perplejidad por defecto; se recorta si hay pocos puntos.
PERPLEJIDAD: float = 30.0
#: Vecinos para la pureza y la confiabilidad.
VECINOS: int = 10
#: Secciones con color propio; el resto se agrupa en «otras».
MAX_GRUPOS: int = 8
#: Etiqueta del grupo que junta las secciones pequeñas.
OTRAS: str = "otras"
#: Configuración del Arqueo cuyos aciertos se dibujan (pesos por defecto).
CONFIGURACION: str = "0.6/0.4"
#: Ventana del acierto (hit@5).
TOP: int = 5
#: Decimales de las cifras del JSON.
DECIMALES: int = 4

#: Salidas versionadas.
SALIDA_JSON: Path = PROJECT_ROOT / "data" / "evaluacion" / "proyeccion.json"
#: JSON del Arqueo del que salen las posiciones (el mismo que escribe `make arqueo`).
ARQUEO_JSON: Path = PROJECT_ROOT / "data" / "evaluacion" / "arqueo.json"
SALIDA_SVG: Path = PROJECT_ROOT / "docs" / "img" / "proyeccion_tsne.svg"

#: Paleta categórica (ocho colores distinguibles con daltonismo) y gris para «otras».
PALETA: tuple[str, ...] = (
    "#0072B2",
    "#E69F00",
    "#009E73",
    "#CC79A7",
    "#56B4E9",
    "#D55E00",
    "#F0E442",
    "#7F3C8D",
)
GRIS: str = "#B8B8B8"
#: Colores de las preguntas.
COLOR_ACIERTO: str = "#1B1B1B"
COLOR_FALLO: str = "#C0392B"


@dataclass(frozen=True, slots=True)
class PuntoFragmento:
    """Un fragmento del índice con su grupo de color."""

    id: str
    url: str
    seccion: str
    grupo: str


@dataclass(frozen=True, slots=True)
class PreguntaProyectada:
    """Una pregunta evaluable del Arqueo y lo que dice de ella el espacio original."""

    id: int
    tipo: str
    ruta: str
    acierto: bool
    posicion: int | None
    grupo_vecino: str
    url_vecina: str
    puesto_esperado: int | None
    grupo_esperado: str | None


@dataclass(frozen=True, slots=True)
class Proyeccion:
    """Resultado completo: coordenadas, cifras y preguntas."""

    fragmentos: tuple[PuntoFragmento, ...]
    coordenadas: np.ndarray
    coordenadas_preguntas: np.ndarray
    preguntas: tuple[PreguntaProyectada, ...]
    pureza: dict[str, float]
    tamanos: dict[str, int]
    pureza_global: float
    confiabilidad: float
    perplejidad: float


def unitarios(vectores: Sequence[Sequence[float]] | np.ndarray) -> np.ndarray:
    """Normaliza cada vector a norma 1, porque el índice compara por coseno.

    Args:
        vectores: matriz de embeddings.

    Returns:
        La matriz con filas de norma 1.

    Raises:
        ValueError: si hay vectores nulos o con valores no finitos.
    """
    matriz = np.asarray(vectores, dtype=float)
    if matriz.ndim != 2 or matriz.shape[0] == 0:
        raise ValueError("Se necesita una matriz con al menos un vector")
    if not np.all(np.isfinite(matriz)):
        raise ValueError("Hay vectores con valores no finitos")
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    if np.any(normas == 0):
        raise ValueError("Hay vectores nulos")
    return matriz / normas


def agrupar(secciones: Sequence[str], maximo: int = MAX_GRUPOS) -> list[str]:
    """Asigna a cada fragmento su sección o «otras» si la sección es pequeña.

    Las `maximo` secciones con más fragmentos conservan su nombre; empates por
    orden alfabético, para que el resultado no dependa del orden de entrada.

    Args:
        secciones: sección de cada fragmento.
        maximo: cuántas secciones tienen color propio.

    Returns:
        El grupo de cada fragmento, en el mismo orden.
    """
    conteo = Counter(seccion.strip() or OTRAS for seccion in secciones)
    principales = {
        seccion for seccion, _ in sorted(conteo.items(), key=lambda par: (-par[1], par[0]))[:maximo]
    }
    return [
        (seccion.strip() or OTRAS) if (seccion.strip() or OTRAS) in principales else OTRAS
        for seccion in secciones
    ]


def perplejidad_efectiva(cantidad: int, deseada: float = PERPLEJIDAD) -> float:
    """Recorta la perplejidad para que t-SNE acepte pocos puntos.

    Args:
        cantidad: número de puntos.
        deseada: perplejidad pedida.

    Returns:
        La menor entre la deseada y un tercio de los puntos menos uno (mínimo 1).
    """
    return max(1.0, min(deseada, (cantidad - 1) / 3))


def ajustar_tsne(
    matriz: np.ndarray,
    *,
    semilla: int = SEMILLA,
    perplejidad: float = PERPLEJIDAD,
) -> tuple[np.ndarray, float]:
    """Ajusta t-SNE de dos dimensiones con coseno, inicio PCA y semilla fija.

    Args:
        matriz: vectores unitarios.
        semilla: semilla del generador.
        perplejidad: perplejidad pedida; se recorta con pocos puntos.

    Returns:
        Las coordenadas `(n, 2)` y la perplejidad usada.

    Raises:
        ValueError: si hay menos de cuatro puntos.
    """
    if matriz.shape[0] < 4:
        raise ValueError("t-SNE necesita al menos cuatro puntos")
    usada = perplejidad_efectiva(matriz.shape[0], perplejidad)
    modelo = TSNE(
        n_components=2,
        perplexity=usada,
        metric="cosine",
        init="pca",
        random_state=semilla,
    )
    return np.asarray(modelo.fit_transform(matriz), dtype=float), usada


def pureza_vecindario(
    matriz: np.ndarray,
    grupos: Sequence[str],
    vecinos: int = VECINOS,
) -> tuple[dict[str, float], float]:
    """Proporción de vecinos por coseno que comparten grupo, en el espacio original.

    Args:
        matriz: vectores unitarios de los fragmentos.
        grupos: grupo de cada fragmento.
        vecinos: cuántos vecinos se miran, sin contar el propio punto.

    Returns:
        La pureza media por grupo y la pureza media de todos los fragmentos.
    """
    cantidad = matriz.shape[0]
    k = max(1, min(vecinos, cantidad - 1))
    similitud = matriz @ matriz.T
    np.fill_diagonal(similitud, -np.inf)
    cercanos = np.argsort(-similitud, axis=1, kind="stable")[:, :k]
    etiquetas = np.asarray(grupos)
    propias = (etiquetas[cercanos] == etiquetas[:, None]).mean(axis=1)
    por_grupo = {
        grupo: round(float(propias[etiquetas == grupo].mean()), DECIMALES)
        for grupo in sorted(set(grupos))
    }
    return por_grupo, round(float(propias.mean()), DECIMALES)


def proyectar_preguntas(
    matriz: np.ndarray,
    fragmentos: Sequence[PuntoFragmento],
    preguntas: Sequence[PreguntaFase2],
    vectores_preguntas: np.ndarray,
    posiciones: Mapping[int, int | None],
    rutas: Mapping[int, str],
    top: int = TOP,
) -> list[PreguntaProyectada]:
    """Describe cada pregunta con su vecino más cercano y el puesto de su fuente.

    Args:
        matriz: vectores unitarios de los fragmentos.
        fragmentos: fragmentos en el mismo orden que `matriz`.
        preguntas: preguntas evaluables.
        vectores_preguntas: vectores unitarios de las preguntas, en su orden.
        posiciones: posición de la primera fuente esperada en el top del Arqueo
            (`None` si no apareció).
        rutas: ruta esperada de cada pregunta (B o T).
        top: ventana del acierto.

    Returns:
        Una `PreguntaProyectada` por pregunta.
    """
    urls = [normalizar_url(fragmento.url) for fragmento in fragmentos]
    resultado: list[PreguntaProyectada] = []
    for pregunta, vector in zip(preguntas, vectores_preguntas, strict=True):
        similitud = matriz @ vector
        orden = np.argsort(-similitud, kind="stable")
        vecino = fragmentos[int(orden[0])]
        esperadas = {normalizar_url(url) for url in pregunta.fuentes_esperadas}
        puesto: int | None = None
        grupo_esperado: str | None = None
        for posicion, indice in enumerate(orden, start=1):
            if urls[int(indice)] in esperadas:
                puesto = posicion
                grupo_esperado = fragmentos[int(indice)].grupo
                break
        lugar = posiciones.get(pregunta.id)
        resultado.append(
            PreguntaProyectada(
                id=pregunta.id,
                tipo=pregunta.tipo,
                ruta=rutas.get(pregunta.id, pregunta.ruta_esperada),
                acierto=lugar is not None and lugar <= top,
                posicion=lugar,
                grupo_vecino=vecino.grupo,
                url_vecina=vecino.url,
                puesto_esperado=puesto,
                grupo_esperado=grupo_esperado,
            )
        )
    return resultado


def construir_proyeccion(
    fragmentos: Sequence[Any],
    vectores: Sequence[Sequence[float]],
    preguntas: Sequence[PreguntaFase2],
    vectores_preguntas: Sequence[Sequence[float]],
    posiciones: Mapping[int, int | None],
    rutas: Mapping[int, str],
    *,
    semilla: int = SEMILLA,
    perplejidad: float = PERPLEJIDAD,
) -> Proyeccion:
    """Ajusta el t-SNE de fragmentos y preguntas y calcula las cifras de lectura.

    Fragmentos y preguntas se ajustan juntos, porque t-SNE no ubica puntos nuevos
    en un plano ya ajustado. Pureza, confiabilidad y puestos se calculan sobre
    los fragmentos en el espacio original.

    Args:
        fragmentos: fragmentos del índice (con `id`, `url` y `seccion`).
        vectores: sus embeddings, en el mismo orden.
        preguntas: preguntas evaluables del Arqueo.
        vectores_preguntas: embeddings de las preguntas, en su orden.
        posiciones: posición de la fuente esperada en el top del Arqueo.
        rutas: ruta esperada de cada pregunta.
        semilla: semilla del t-SNE.
        perplejidad: perplejidad pedida.

    Returns:
        La proyección con coordenadas y cifras.

    Raises:
        ValueError: si las listas no coinciden en tamaño.
    """
    if len(fragmentos) != len(vectores):
        raise ValueError(f"Hay {len(fragmentos)} fragmentos y {len(vectores)} vectores")
    if len(preguntas) != len(vectores_preguntas):
        raise ValueError(f"Hay {len(preguntas)} preguntas y {len(vectores_preguntas)} vectores")
    grupos = agrupar([str(fragmento.seccion) for fragmento in fragmentos])
    puntos = tuple(
        PuntoFragmento(
            id=str(fragmento.id),
            url=str(fragmento.url),
            seccion=str(fragmento.seccion),
            grupo=grupo,
        )
        for fragmento, grupo in zip(fragmentos, grupos, strict=True)
    )
    matriz = unitarios(vectores)
    matriz_preguntas = (
        unitarios(vectores_preguntas) if len(vectores_preguntas) else np.empty((0, matriz.shape[1]))
    )
    todo = np.vstack([matriz, matriz_preguntas])
    coordenadas, usada = ajustar_tsne(todo, semilla=semilla, perplejidad=perplejidad)
    pureza, pureza_global = pureza_vecindario(matriz, grupos)
    k = max(1, min(VECINOS, (matriz.shape[0] - 1) // 2))
    confiabilidad = trustworthiness(
        matriz, coordenadas[: matriz.shape[0]], n_neighbors=k, metric="cosine"
    )
    proyectadas = proyectar_preguntas(
        matriz, puntos, preguntas, matriz_preguntas, posiciones, rutas
    )
    return Proyeccion(
        fragmentos=puntos,
        coordenadas=coordenadas[: matriz.shape[0]],
        coordenadas_preguntas=coordenadas[matriz.shape[0] :],
        preguntas=tuple(proyectadas),
        pureza=pureza,
        tamanos=dict(sorted(Counter(grupos).items())),
        pureza_global=pureza_global,
        confiabilidad=round(float(confiabilidad), DECIMALES),
        perplejidad=usada,
    )


def resumen(proyeccion: Proyeccion, *, semilla: int = SEMILLA) -> dict[str, Any]:
    """Cifras de la proyección para `data/evaluacion/proyeccion.json`.

    Args:
        proyeccion: resultado de `construir_proyeccion`.
        semilla: semilla usada.

    Returns:
        Diccionario serializable, sin coordenadas.
    """
    preguntas = [asdict(pregunta) for pregunta in proyeccion.preguntas]
    fallos = [pregunta for pregunta in preguntas if not pregunta["acierto"]]
    return {
        "parametros": {
            "metodo": "t-SNE",
            "metrica": "coseno",
            "inicio": "pca",
            "semilla": semilla,
            "perplejidad": proyeccion.perplejidad,
            "vecinos": VECINOS,
            "configuracion_arqueo": CONFIGURACION,
            "top": TOP,
        },
        "fragmentos": len(proyeccion.fragmentos),
        "confiabilidad": proyeccion.confiabilidad,
        "pureza_global": proyeccion.pureza_global,
        "grupos": [
            {
                "grupo": grupo,
                "fragmentos": proyeccion.tamanos[grupo],
                "pureza": proyeccion.pureza[grupo],
            }
            for grupo in sorted(proyeccion.tamanos, key=lambda g: (-proyeccion.tamanos[g], g))
        ],
        "preguntas": preguntas,
        "fallos": len(fallos),
        "fallos_en_otra_seccion": sum(
            1
            for pregunta in fallos
            if pregunta["grupo_esperado"] is not None
            and pregunta["grupo_vecino"] != pregunta["grupo_esperado"]
        ),
    }


def _colores(proyeccion: Proyeccion) -> dict[str, str]:
    """Asigna un color a cada grupo, de mayor a menor tamaño; «otras» va en gris."""
    nombrados = [
        grupo
        for grupo in sorted(proyeccion.tamanos, key=lambda g: (-proyeccion.tamanos[g], g))
        if grupo != OTRAS
    ]
    colores = {grupo: PALETA[i % len(PALETA)] for i, grupo in enumerate(nombrados)}
    colores[OTRAS] = GRIS
    return colores


def dibujar_svg(proyeccion: Proyeccion, *, ancho: int = 960, alto: int = 640) -> str:
    """Dibuja la proyección como SVG autocontenido, sin dependencias de gráficos.

    Fragmentos: círculos por sección. Preguntas: rombo negro si encontraron su
    fuente en el top 5 y cruz roja si no.

    Args:
        proyeccion: resultado de `construir_proyeccion`.
        ancho: ancho del lienzo en píxeles.
        alto: alto del lienzo en píxeles.

    Returns:
        El documento SVG.
    """
    margen, leyenda = 24, 250
    area_x, area_y = ancho - leyenda - 2 * margen, alto - 2 * margen - 28
    todas = np.vstack([proyeccion.coordenadas, proyeccion.coordenadas_preguntas])
    minimo = todas.min(axis=0)
    rango = np.where(todas.max(axis=0) - minimo == 0, 1.0, todas.max(axis=0) - minimo)

    def ubicar(punto: np.ndarray) -> tuple[float, float]:
        x = margen + (float(punto[0]) - minimo[0]) / rango[0] * area_x
        y = margen + 28 + (1 - (float(punto[1]) - minimo[1]) / rango[1]) * area_y
        return round(x, 1), round(y, 1)

    colores = _colores(proyeccion)
    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ancho} {alto}" '
        f'width="{ancho}" height="{alto}" font-family="sans-serif" font-size="12">',
        f'<rect width="{ancho}" height="{alto}" fill="#FFFFFF"/>',
        f'<text x="{margen}" y="{margen + 4}" font-size="16" font-weight="bold">'
        f"Bóveda en t-SNE: {len(proyeccion.fragmentos)} fragmentos y "
        f"{len(proyeccion.preguntas)} preguntas del Arqueo</text>",
    ]
    for fragmento, punto in zip(proyeccion.fragmentos, proyeccion.coordenadas, strict=True):
        x, y = ubicar(punto)
        partes.append(
            f'<circle cx="{x}" cy="{y}" r="3" fill="{colores[fragmento.grupo]}" '
            f'fill-opacity="0.75"><title>{escape(fragmento.seccion)} · '
            f"{escape(fragmento.url)}</title></circle>"
        )
    for pregunta, punto in zip(proyeccion.preguntas, proyeccion.coordenadas_preguntas, strict=True):
        x, y = ubicar(punto)
        titulo = f"<title>Pregunta {pregunta.id} ({pregunta.tipo}, ruta {pregunta.ruta})</title>"
        if pregunta.acierto:
            partes.append(
                f'<path d="M{x} {y - 6}L{x + 6} {y}L{x} {y + 6}L{x - 6} {y}Z" '
                f'fill="{COLOR_ACIERTO}" stroke="#FFFFFF" stroke-width="1">{titulo}</path>'
            )
        else:
            partes.append(
                f'<path d="M{x - 5} {y - 5}L{x + 5} {y + 5}M{x + 5} {y - 5}L{x - 5} {y + 5}" '
                f'stroke="{COLOR_FALLO}" stroke-width="3">{titulo}</path>'
            )
        partes.append(f'<text x="{x + 7}" y="{y - 5}" font-size="10">{pregunta.id}</text>')

    lx = ancho - leyenda + margen // 2
    ly = margen + 40
    partes.append(f'<text x="{lx}" y="{ly}" font-weight="bold">Sección (pureza)</text>')
    for indice, grupo in enumerate(
        sorted(proyeccion.tamanos, key=lambda g: (g == OTRAS, -proyeccion.tamanos[g], g))
    ):
        y = ly + 20 + indice * 20
        etiqueta = grupo if len(grupo) <= 24 else grupo[:23] + "…"
        partes.append(f'<circle cx="{lx + 6}" cy="{y - 4}" r="5" fill="{colores[grupo]}"/>')
        partes.append(
            f'<text x="{lx + 18}" y="{y}">{escape(etiqueta)} '
            f"({_coma(proyeccion.pureza[grupo])})</text>"
        )
    y = ly + 20 + (len(proyeccion.tamanos) + 1) * 20
    partes.append(
        f'<path d="M{lx + 6} {y - 10}L{lx + 12} {y - 4}L{lx + 6} {y + 2}L{lx} {y - 4}Z" '
        f'fill="{COLOR_ACIERTO}"/>'
    )
    partes.append(f'<text x="{lx + 18}" y="{y}">Fuente en el top {TOP}</text>')
    y += 20
    partes.append(
        f'<path d="M{lx + 1} {y - 9}L{lx + 11} {y + 1}M{lx + 11} {y - 9}L{lx + 1} {y + 1}" '
        f'stroke="{COLOR_FALLO}" stroke-width="3"/>'
    )
    partes.append(f'<text x="{lx + 18}" y="{y}">Fuente fuera del top {TOP}</text>')
    y += 30
    for linea in (
        f"Confiabilidad: {_coma(proyeccion.confiabilidad)}",
        f"Pureza global: {_coma(proyeccion.pureza_global)}",
        f"Semilla {SEMILLA}, perplejidad {proyeccion.perplejidad:g}".replace(".", ","),
        "Las distancias entre grupos",
        "no se interpretan en t-SNE.",
    ):
        partes.append(f'<text x="{lx}" y="{y}" fill="#444444">{escape(linea)}</text>')
        y += 16
    partes.append("</svg>")
    return "\n".join(partes) + "\n"


def _coma(valor: float) -> str:
    """Formatea una cifra con coma decimal y dos decimales."""
    return f"{valor:.2f}".replace(".", ",")


def escribir(proyeccion: Proyeccion, *, json_destino: Path, svg_destino: Path) -> None:
    """Escribe el JSON de cifras y la figura SVG.

    Args:
        proyeccion: resultado de `construir_proyeccion`.
        json_destino: ruta del JSON.
        svg_destino: ruta del SVG.
    """
    json_destino.parent.mkdir(parents=True, exist_ok=True)
    svg_destino.parent.mkdir(parents=True, exist_ok=True)
    json_destino.write_text(
        json.dumps(resumen(proyeccion), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    svg_destino.write_text(dibujar_svg(proyeccion), encoding="utf-8", newline="\n")


def _datos_del_arqueo(ruta: Path) -> tuple[dict[int, int | None], dict[int, str], set[int]]:
    """Lee del Arqueo la posición, la ruta y si cada pregunta es evaluable.

    Args:
        ruta: `data/evaluacion/arqueo.json`.

    Returns:
        Posiciones con los pesos por defecto, rutas y el conjunto de evaluables
        con fuente indexada.
    """
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    posiciones: dict[int, int | None] = {}
    rutas: dict[int, str] = {}
    evaluables: set[int] = set()
    for fila in datos["detalle"]["preguntas"]:
        identificador = int(fila["id"])
        posiciones[identificador] = fila["posiciones"].get(CONFIGURACION)
        rutas[identificador] = str(fila["ruta_esperada"])
        if fila["evaluable"] and fila.get("fuente_indexada") is not False:
            evaluables.add(identificador)
    return posiciones, rutas, evaluables


def ejecutar(
    *,
    leer_indice: Callable[[], tuple[Sequence[Any], Sequence[Sequence[float]]]] | None = None,
    vectorizar: Callable[[list[str]], list[list[float]]] | None = None,
    arqueo: Path = ARQUEO_JSON,
    preguntas: Sequence[PreguntaFase2] | None = None,
    json_destino: Path = SALIDA_JSON,
    svg_destino: Path = SALIDA_SVG,
) -> Proyeccion:
    """Lee índice y Arqueo, vectoriza las preguntas, proyecta y escribe.

    Args:
        leer_indice: devuelve fragmentos y vectores; por defecto el índice real.
        vectorizar: vectoriza consultas; por defecto los embeddings de la Bóveda.
        arqueo: JSON del Arqueo; por defecto `data/evaluacion/arqueo.json`.
        preguntas: banco de preguntas; por defecto `config/evaluacion/preguntas_fase2.toml`.
        json_destino: ruta del JSON de cifras.
        svg_destino: ruta de la figura.

    Returns:
        La proyección escrita.
    """
    lector = leer_indice or _indice_real
    vectorizador = vectorizar or _vectorizador_real()
    posiciones, rutas, evaluables = _datos_del_arqueo(arqueo)
    banco = cargar_preguntas_fase2() if preguntas is None else preguntas
    seleccion = [pregunta for pregunta in banco if pregunta.id in evaluables]
    fragmentos, vectores = lector()
    vectores_preguntas = vectorizador([consulta_de(pregunta) for pregunta in seleccion])
    proyeccion = construir_proyeccion(
        fragmentos, vectores, seleccion, vectores_preguntas, posiciones, rutas
    )
    escribir(proyeccion, json_destino=json_destino, svg_destino=svg_destino)
    return proyeccion


def _indice_real() -> tuple[Sequence[Any], Sequence[Sequence[float]]]:
    """Lee fragmentos y vectores del índice persistente de la Bóveda."""
    from ..boveda.mapa import leer_vectores_indexados
    from ..config import load_config

    return leer_vectores_indexados(load_config())


def _vectorizador_real() -> Callable[[list[str]], list[list[float]]]:
    """Crea el vectorizador de consultas con el modelo local y sus prefijos."""
    from ..boveda.embeddings import crear_embeddings

    embeddings = crear_embeddings()

    def vectorizar(textos: list[str]) -> list[list[float]]:
        return [embeddings.embed_query(texto) for texto in textos]

    return vectorizar


def _imprimir(proyeccion: Proyeccion) -> None:
    """Imprime un resumen para pegar en la lectura del Arqueo."""
    datos = resumen(proyeccion)
    print(f"Fragmentos: {datos['fragmentos']}  Preguntas: {len(proyeccion.preguntas)}")
    print(f"Confiabilidad: {datos['confiabilidad']}  Pureza global: {datos['pureza_global']}")
    print("Grupos (fragmentos, pureza):")
    for grupo in datos["grupos"]:
        print(f"  {grupo['grupo']}: {grupo['fragmentos']}, {grupo['pureza']}")
    print(f"Fallos en el top {TOP}: {datos['fallos']}")
    for pregunta in proyeccion.preguntas:
        if not pregunta.acierto:
            print(
                f"  P{pregunta.id} ({pregunta.tipo}, ruta {pregunta.ruta}): vecino en "
                f"«{pregunta.grupo_vecino}»; fuente esperada en «{pregunta.grupo_esperado}», "
                f"puesto {pregunta.puesto_esperado} por coseno"
            )


def main() -> int:
    """Punto de entrada: `python -m banco_occidente_corpus.arqueo.proyeccion`."""
    try:
        proyeccion = ejecutar()
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    _imprimir(proyeccion)
    for ruta in (SALIDA_JSON, SALIDA_SVG):
        print(f"Escrito: {ruta.relative_to(PROJECT_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "Proyeccion",
    "PreguntaProyectada",
    "PuntoFragmento",
    "agrupar",
    "ajustar_tsne",
    "construir_proyeccion",
    "dibujar_svg",
    "ejecutar",
    "perplejidad_efectiva",
    "proyectar_preguntas",
    "pureza_vecindario",
    "resumen",
    "unitarios",
]
