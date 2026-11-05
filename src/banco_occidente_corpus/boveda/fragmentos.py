"""Construcción determinista de fragmentos de la Bóveda desde chunks y hechos.

El módulo no hace peticiones de red ni modifica Gold: lee los chunks de la capa
Knowledge, los fragmentos de navegación repetida y los hechos verificados, y
escribe el JSONL de fragmentos en `data/boveda/`.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any, Literal

from ..asistente.validacion import detectar_pii
from ..config import Config
from ..dedupe import find_boilerplate, is_noise, normalize_line
from ..utils import CHARS_PER_TOKEN, read_jsonl, sha256_text, stable_tokens, write_jsonl
from .tipos import Fragmento, TipoFragmento

Alcance = Literal["base", "completo"]

#: Tokens mínimos que debe alcanzar un fragmento fusionado.
TOKENS_MINIMOS: int = 80
#: Tokens a partir de los cuales un fragmento se parte por párrafos.
TOKENS_MAXIMOS: int = 400
#: Proporción de páginas web en la que una línea debe aparecer para ser ruido repetido.
#: 0.07 equivale a unas 17 de las 241 páginas web, de modo que se elimina el menú
#: de navegación ("- Canales digitales", "- Segmentos", etc.), que aparece en 19
#: páginas y quedaba al inicio de 19 fragmentos.
RATIO_REPETIDAS: float = 0.07
#: Mínimo absoluto de páginas web para considerar una línea como repetida.
MIN_DOCS_REPETIDAS: int = 5
#: Alcances que puede construir la Bóveda.
ALCANCES: tuple[Alcance, ...] = ("base", "completo")
#: Nombre por defecto cuando un hecho no declara una entidad conocida.
ENTIDAD_POR_DEFECTO: str = "Banco de Occidente"


@dataclass(frozen=True, slots=True)
class LineaRepetida:
    """Línea de navegación repetida y número de páginas web que la contienen."""

    texto: str
    paginas: int


@dataclass(frozen=True, slots=True)
class ResumenFragmentos:
    """Métricas del proceso de construcción de fragmentos."""

    total: int
    por_tipo: dict[str, int]
    tokens_min: int
    tokens_mediana: float
    tokens_max: int
    cortos: int
    fragmentos_largos: int
    tablas_enteras: int
    tablas_partidas: int
    partes_tablas_partidas: int
    lineas_repetidas: int
    lineas_frecuentes: tuple[LineaRepetida, ...]
    hechos_por_revision: dict[str, int]
    omitidos_sin_evidencia: int
    omitidos_pii: int
    duplicados: int = 0


@dataclass(frozen=True, slots=True)
class ResultadoFragmentos:
    """Fragmentos construidos y el resumen de su construcción."""

    fragmentos: tuple[Fragmento, ...]
    resumen: ResumenFragmentos


@dataclass(frozen=True, slots=True)
class _Origen:
    """Origen de un page_id dentro del corpus."""

    tipo: TipoFragmento
    titulo: str
    categoria: str = ""


def ruta_fragmentos(config: Config, alcance: Alcance = "base") -> Path:
    """Devuelve la ruta del JSONL de fragmentos para un alcance."""
    _validar_alcance(alcance)
    return config.paths.root / "data" / "boveda" / f"fragmentos_{alcance}.jsonl"


def cargar_chunks(config: Config) -> list[dict[str, Any]]:
    """Lee los chunks web y completos sin duplicar los que aparecen en ambos."""
    rutas = (config.paths.knowledge_chunks_web, config.paths.knowledge_chunks)
    if not any(ruta.exists() for ruta in rutas):
        raise FileNotFoundError(
            "No hay chunks en data/knowledge: ejecuta `make chunks` antes de construir fragmentos."
        )

    vistos: set[str] = set()
    filas: list[dict[str, Any]] = []
    for ruta in rutas:
        for fila in read_jsonl(ruta):
            chunk_id = str(fila.get("chunk_id", "")).strip()
            if chunk_id and chunk_id in vistos:
                continue
            if chunk_id:
                vistos.add(chunk_id)
            filas.append(fila)
    return filas


def construir_fragmentos(config: Config, alcance: Alcance = "base") -> ResultadoFragmentos:
    """Construye los fragmentos del alcance pedido a partir de chunks y hechos."""
    _validar_alcance(alcance)
    chunks = cargar_chunks(config)
    origenes = _mapa_origen(config)
    repetidas, frecuentes = _detectar_lineas_repetidas(chunks, origenes)

    fragmentos: list[Fragmento] = []
    tablas_enteras = 0
    tablas_partidas = 0
    partes_tablas_partidas = 0
    paginas: dict[str, list[dict[str, Any]]] = {}
    for fila in chunks:
        page_id = str(fila.get("page_id", "")).strip()
        if not page_id:
            continue
        paginas.setdefault(page_id, []).append(fila)

    for page_id, filas in paginas.items():
        origen = origenes.get(page_id, _Origen(tipo="pagina", titulo=page_id))
        if not _incluido(origen, alcance):
            continue
        limpios: list[tuple[dict[str, Any], str]] = []
        for fila in filas:
            texto = _limpiar_chunk(
                str(fila.get("text", "")),
                str(fila.get("heading", "")),
                repetidas,
            )
            if texto:
                limpios.append((fila, texto))
        for grupo in _agrupar(limpios):
            texto_grupo = "\n".join(texto for _, texto in grupo)
            enteras, partidas, partes = _estadisticas_tablas(texto_grupo)
            tablas_enteras += enteras
            tablas_partidas += partidas
            partes_tablas_partidas += partes
            for pieza in _partir_texto(texto_grupo):
                fragmentos.append(_crear_fragmento(page_id, origen, grupo, pieza))

    hechos, revisiones, omitidos_sin_evidencia, omitidos_pii = _fragmentos_de_hechos(config)
    fragmentos.extend(hechos)
    fragmentos, duplicados = _sin_repetidos(fragmentos)

    resumen = _resumir(
        fragmentos,
        tablas_enteras=tablas_enteras,
        tablas_partidas=tablas_partidas,
        partes_tablas_partidas=partes_tablas_partidas,
        repetidas=repetidas,
        frecuentes=frecuentes,
        revisiones=revisiones,
        omitidos_sin_evidencia=omitidos_sin_evidencia,
        omitidos_pii=omitidos_pii,
        duplicados=duplicados,
    )
    return ResultadoFragmentos(fragmentos=tuple(fragmentos), resumen=resumen)


def escribir_fragmentos(
    config: Config, alcance: Alcance = "base"
) -> tuple[Path, ResumenFragmentos]:
    """Construye los fragmentos y escribe el JSONL del alcance en data/boveda."""
    resultado = construir_fragmentos(config, alcance)
    ruta = ruta_fragmentos(config, alcance)
    write_jsonl(ruta, (asdict(fragmento) for fragmento in resultado.fragmentos))
    return ruta, resultado.resumen


def formatear_resumen(resumen: ResumenFragmentos, ruta: Path) -> str:
    """Devuelve el texto legible con el resumen de los fragmentos escritos."""
    tipos = ", ".join(f"{tipo}={cantidad}" for tipo, cantidad in sorted(resumen.por_tipo.items()))
    lineas = [
        f"Fragmentos escritos: {resumen.total} en {ruta}",
        f"Por tipo: {tipos or 'sin fragmentos'}",
        (
            f"Tokens: min={resumen.tokens_min}, mediana={resumen.tokens_mediana:.1f}, "
            f"max={resumen.tokens_max}"
        ),
        f"Fragmentos con menos de {TOKENS_MINIMOS} tokens: {resumen.cortos}",
        f"Fragmentos con más de {TOKENS_MAXIMOS} tokens: {resumen.fragmentos_largos}",
        f"Tablas enteras: {resumen.tablas_enteras}",
        (
            f"Tablas partidas por filas: {resumen.tablas_partidas} "
            f"en {resumen.partes_tablas_partidas} partes"
        ),
        f"lineas_repetidas: {resumen.lineas_repetidas} (líneas distintas marcadas)",
        f"Duplicados descartados: {resumen.duplicados}",
    ]
    if resumen.lineas_frecuentes:
        lineas.append("Líneas repetidas más frecuentes:")
        lineas.extend(
            f"  - {item.paginas} páginas: {item.texto}" for item in resumen.lineas_frecuentes
        )
    else:
        lineas.append("Líneas repetidas más frecuentes: ninguna")
    omitidos = resumen.omitidos_sin_evidencia + resumen.omitidos_pii
    lineas.append(
        f"Hechos omitidos: {omitidos} "
        f"(sin evidencia={resumen.omitidos_sin_evidencia}, PII={resumen.omitidos_pii})"
    )
    revisiones = ", ".join(
        f"{estado}={cantidad}" for estado, cantidad in sorted(resumen.hechos_por_revision.items())
    )
    lineas.append(f"Hechos por revisión: {revisiones or 'sin hechos'}")
    return "\n".join(lineas)


def _validar_alcance(alcance: str) -> None:
    """Comprueba que el alcance sea uno de los admitidos."""
    if alcance not in ALCANCES:
        permitidos = ", ".join(ALCANCES)
        raise ValueError(f"Alcance desconocido: {alcance!r}. Usa uno de: {permitidos}.")


def _mapa_origen(config: Config) -> dict[str, _Origen]:
    """Construye el mapa page_id -> origen usando los índices de Gold."""
    origenes: dict[str, _Origen] = {}
    for fila in read_jsonl(config.paths.corpus_file):
        page_id = str(fila.get("id", "")).strip()
        if page_id:
            titulo = str(fila.get("titulo", "")).strip() or page_id
            origenes[page_id] = _Origen(tipo="pagina", titulo=titulo)
    for fila in read_jsonl(config.paths.documents_index):
        page_id = str(fila.get("id", "")).strip()
        if page_id:
            titulo = str(fila.get("titulo", "")).strip() or page_id
            categoria = str(fila.get("categoria_documento", "")).strip()
            origenes[page_id] = _Origen(tipo="pdf", titulo=titulo, categoria=categoria)
    for fila in read_jsonl(config.paths.videos_index):
        page_id = str(fila.get("id", "")).strip()
        if page_id:
            titulo = str(fila.get("titulo", "")).strip() or page_id
            origenes[page_id] = _Origen(tipo="video", titulo=titulo)
    return origenes


def _mapa_entidades(config: Config) -> dict[str, str]:
    """Devuelve el nombre legible de cada entidad de la capa Knowledge."""
    nombres: dict[str, str] = {}
    for fila in read_jsonl(config.paths.knowledge_entities):
        entity_id = str(fila.get("id", "")).strip()
        nombre = str(fila.get("name", "")).strip()
        if entity_id and nombre:
            nombres[entity_id] = nombre
    return nombres


def _incluido(origen: _Origen, alcance: Alcance) -> bool:
    """Indica si un origen entra en el alcance pedido."""
    if alcance == "completo":
        return True
    if origen.tipo in ("pagina", "hecho verificado"):
        return True
    return origen.tipo == "pdf" and origen.categoria == "producto"


def _detectar_lineas_repetidas(
    chunks: Sequence[dict[str, Any]], origenes: dict[str, _Origen]
) -> tuple[set[str], tuple[LineaRepetida, ...]]:
    """Detecta el ruido repetido entre páginas web y las cinco líneas más frecuentes."""
    paginas: dict[str, list[str]] = {}
    for fila in chunks:
        page_id = str(fila.get("page_id", "")).strip()
        if not page_id:
            continue
        origen = origenes.get(page_id, _Origen(tipo="pagina", titulo=page_id))
        if origen.tipo != "pagina":
            continue
        paginas.setdefault(page_id, []).extend(str(fila.get("text", "")).splitlines())

    documentos = list(paginas.values())
    repetidas = find_boilerplate(
        documentos,
        min_docs=MIN_DOCS_REPETIDAS,
        ratio=RATIO_REPETIDAS,
    )
    if not repetidas:
        return repetidas, ()

    originales: dict[str, str] = {}
    conteo: Counter[str] = Counter()
    for documento in documentos:
        presentes: set[str] = set()
        for linea in documento:
            normal = normalize_line(linea)
            if not normal:
                continue
            originales.setdefault(normal, linea.strip())
            if normal in repetidas:
                presentes.add(normal)
        conteo.update(presentes)

    frecuentes = tuple(
        LineaRepetida(texto=originales[normal], paginas=paginas_count)
        for normal, paginas_count in sorted(
            conteo.items(), key=lambda item: (-item[1], originales[item[0]])
        )[:5]
    )
    return repetidas, frecuentes


def _bloques(texto: str) -> list[tuple[str, tuple[str, ...]]]:
    """Separa un texto en bloques de párrafo y de tabla, conservando su orden."""
    bloques: list[tuple[str, tuple[str, ...]]] = []
    parrafo: list[str] = []
    tabla: list[str] = []

    def cerrar_parrafo() -> None:
        """Cierra el párrafo acumulado si tiene líneas."""
        if parrafo:
            bloques.append(("parrafo", tuple(parrafo)))
            parrafo.clear()

    def cerrar_tabla() -> None:
        """Cierra la tabla acumulada si tiene líneas."""
        if tabla:
            bloques.append(("tabla", tuple(tabla)))
            tabla.clear()

    for linea in texto.splitlines():
        if linea.lstrip().startswith("|"):
            cerrar_parrafo()
            tabla.append(linea.rstrip())
            continue
        cerrar_tabla()
        if not linea.strip():
            cerrar_parrafo()
            continue
        parrafo.append(linea.rstrip())
    cerrar_tabla()
    cerrar_parrafo()
    return bloques


def _limpiar_chunk(texto: str, heading: str, repetidas: set[str]) -> str:
    """Quita ruido y líneas repetidas de un chunk y antepone su encabezado."""
    partes: list[str] = []
    vistos: set[str] = set()
    for tipo, lineas in _bloques(texto):
        if tipo == "tabla":
            partes.append("\n".join(lineas))
            continue
        utiles: list[str] = []
        for linea in lineas:
            if is_noise(linea):
                continue
            normal = normalize_line(linea)
            if normal in repetidas or normal in vistos:
                continue
            vistos.add(normal)
            utiles.append(linea)
        if utiles:
            partes.append("\n".join(utiles))

    limpio = "\n\n".join(partes).strip()
    encabezado = heading.strip()
    if encabezado:
        primera = limpio.splitlines()[0].strip() if limpio else ""
        if primera != encabezado:
            limpio = f"{encabezado}\n{limpio}" if limpio else encabezado
    return limpio


def _agrupar(
    limpios: Sequence[tuple[dict[str, Any], str]],
) -> list[list[tuple[dict[str, Any], str]]]:
    """Agrupa chunks consecutivos mientras el texto acumulado no llegue a 80 tokens."""
    grupos: list[list[tuple[dict[str, Any], str]]] = []
    actual: list[tuple[dict[str, Any], str]] = []
    for item in limpios:
        if not actual:
            actual = [item]
            continue
        acumulado = "\n".join(texto for _, texto in actual)
        if stable_tokens(acumulado) < TOKENS_MINIMOS:
            actual.append(item)
        else:
            grupos.append(actual)
            actual = [item]
    if actual:
        grupos.append(actual)
    return grupos


def _partir_texto(texto: str, max_tokens: int = TOKENS_MAXIMOS) -> list[str]:
    """Parte un texto en piezas de tamaño acotado sin romper tablas completas."""
    if stable_tokens(texto) <= max_tokens:
        return [texto]

    unidades: list[str] = []
    for tipo, lineas in _bloques(texto):
        if tipo == "tabla":
            unidades.extend(_partir_tabla(lineas, max_tokens))
        else:
            unidades.extend(_partir_por_lineas(lineas, max_tokens))

    piezas = _empaquetar(unidades, max_tokens)
    resultado: list[str] = []
    max_chars = max_tokens * CHARS_PER_TOKEN
    for pieza in piezas:
        if len(pieza) <= max_chars:
            resultado.append(pieza)
        else:
            resultado.extend(_partir_por_lineas(pieza.splitlines(), max_tokens))
    return resultado


def _empaquetar(unidades: Sequence[str], max_tokens: int) -> list[str]:
    """Agrupa unidades consecutivas sin superar el máximo de caracteres."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    piezas: list[str] = []
    actual: list[str] = []
    for unidad in unidades:
        candidato = "\n\n".join([*actual, unidad])
        if actual and len(candidato) > max_chars:
            piezas.append("\n\n".join(actual))
            actual = [unidad]
        else:
            actual.append(unidad)
    if actual:
        piezas.append("\n\n".join(actual))
    return piezas


def _partir_por_lineas(lineas: Sequence[str], max_tokens: int) -> list[str]:
    """Parte un bloque por líneas y, si una línea no cabe, por oraciones."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    unidades: list[str] = []
    for linea in lineas:
        if len(linea) <= max_chars:
            unidades.append(linea)
        else:
            unidades.extend(_partir_linea(linea, max_chars))

    piezas: list[str] = []
    actual: list[str] = []
    for unidad in unidades:
        candidato = "\n".join([*actual, unidad])
        if actual and len(candidato) > max_chars:
            piezas.append("\n".join(actual))
            actual = [unidad]
        else:
            actual.append(unidad)
    if actual:
        piezas.append("\n".join(actual))
    return piezas


def _partir_linea(linea: str, max_chars: int) -> list[str]:
    """Parte una línea por oraciones y, como último recurso, por ventanas."""
    if len(linea) <= max_chars:
        return [linea]

    oraciones = [parte for parte in re.split(r"(?<=\.)\s+", linea) if parte]
    if len(oraciones) <= 1:
        return _ventanas(linea, max_chars)

    segmentos: list[str] = []
    actual: list[str] = []
    for oracion in oraciones:
        candidato = " ".join([*actual, oracion])
        if actual and len(candidato) > max_chars:
            segmentos.append(" ".join(actual))
            actual = [oracion]
        else:
            actual.append(oracion)
    if actual:
        segmentos.append(" ".join(actual))

    resultado: list[str] = []
    for segmento in segmentos:
        if len(segmento) <= max_chars:
            resultado.append(segmento)
        else:
            resultado.extend(_ventanas(segmento, max_chars))
    return resultado


def _ventanas(texto: str, max_chars: int) -> list[str]:
    """Divide un texto en ventanas de caracteres como último recurso."""
    limite = max(1, max_chars)
    return [texto[inicio : inicio + limite] for inicio in range(0, len(texto), limite)]


def _es_separador_tabla(linea: str) -> bool:
    """Indica si una línea es el separador de encabezado de una tabla Markdown."""
    texto = linea.strip()
    return bool(texto) and "-" in texto and set(texto) <= set("|-: ")


def _partir_tabla(lineas: Sequence[str], max_tokens: int) -> list[str]:
    """Parte una tabla por filas repitiendo el encabezado y el separador."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    texto = "\n".join(lineas)
    if len(texto) <= max_chars:
        return [texto]

    encabezado = lineas[0]
    if len(lineas) >= 2 and _es_separador_tabla(lineas[1]):
        prefijo = [encabezado, lineas[1]]
        filas = list(lineas[2:])
    else:
        prefijo = [encabezado]
        filas = list(lineas[1:])
    prefijo_texto = "\n".join(prefijo)
    margen = max_chars - len(prefijo_texto) - 1
    if not filas or margen < 1:
        return _partir_por_lineas(lineas, max_tokens)

    unidades: list[str] = []
    for fila in filas:
        if len(fila) <= margen:
            unidades.append(fila)
        else:
            unidades.extend(_partir_linea(fila, margen))

    piezas: list[str] = []
    actual: list[str] = []
    for fila in unidades:
        candidato = "\n".join([prefijo_texto, *actual, fila])
        if actual and len(candidato) > max_chars:
            piezas.append("\n".join([prefijo_texto, *actual]))
            actual = [fila]
        else:
            actual.append(fila)
    if actual:
        piezas.append("\n".join([prefijo_texto, *actual]))
    return piezas


def _estadisticas_tablas(texto: str) -> tuple[int, int, int]:
    """Cuenta tablas enteras, tablas partidas por filas y las partes resultantes."""
    max_chars = TOKENS_MAXIMOS * CHARS_PER_TOKEN
    enteras = 0
    partidas = 0
    partes = 0
    for tipo, lineas in _bloques(texto):
        if tipo != "tabla":
            continue
        if len("\n".join(lineas)) <= max_chars:
            enteras += 1
        else:
            partidas += 1
            partes += len(_partir_tabla(lineas, TOKENS_MAXIMOS))
    return enteras, partidas, partes


def _crear_fragmento(
    page_id: str,
    origen: _Origen,
    grupo: Sequence[tuple[dict[str, Any], str]],
    texto: str,
) -> Fragmento:
    """Crea un fragmento con id estable a partir de un grupo y su texto final."""
    primero = grupo[0][0]
    encabezado = str(primero.get("heading", "")).strip()
    url = str(primero.get("url", "")).strip()
    seccion = str(primero.get("section", "")).strip() or "otros"
    digest = sha256_text(f"{page_id}|{encabezado}|{texto}")
    return Fragmento(
        id=f"frag:{digest[:12]}",
        texto=texto,
        url=url,
        titulo=origen.titulo,
        seccion=seccion,
        encabezado=encabezado,
        tipo=origen.tipo,
        tokens=stable_tokens(texto),
    )


def _titulo_predicado(predicado: str) -> str:
    """Convierte un predicado snake_case en un título legible."""
    texto = predicado.replace("_", " ").strip()
    for prefijo in ("tiene ", "es ", "son "):
        if texto.startswith(prefijo):
            texto = texto[len(prefijo) :]
            break
    return texto[:1].upper() + texto[1:] if texto else "Hecho"


def _fragmentos_de_hechos(
    config: Config,
) -> tuple[list[Fragmento], dict[str, int], int, int]:
    """Convierte los hechos con evidencia en fragmentos verificados, sin PII."""
    nombres = _mapa_entidades(config)
    fragmentos: list[Fragmento] = []
    revisiones: Counter[str] = Counter()
    omitidos_sin_evidencia = 0
    omitidos_pii = 0

    for fila in read_jsonl(config.paths.knowledge_facts):
        if str(fila.get("record_type", "fact")) != "fact":
            continue
        evidencia = fila.get("evidence")
        if not isinstance(evidencia, dict):
            omitidos_sin_evidencia += 1
            continue
        url = str(evidencia.get("url", "")).strip()
        seccion = str(evidencia.get("section", "")).strip()
        valor = str(fila.get("value", "")).strip()
        if not (url and seccion and valor):
            omitidos_sin_evidencia += 1
            continue
        encabezado = str(evidencia.get("heading", "")).strip()

        texto_revisable = " ".join(
            parte for parte in (valor, str(evidencia.get("quote", "")).strip(), encabezado) if parte
        )
        if detectar_pii(texto_revisable) is not None:
            omitidos_pii += 1
            continue

        predicado = str(fila.get("predicate", "")).strip()
        titulo = _titulo_predicado(predicado)
        entity_id = str(fila.get("entity_id", "")).strip()
        entidad = nombres.get(entity_id, ENTIDAD_POR_DEFECTO)
        texto = f"{titulo} del {entidad}: {valor}"
        page_id = str(evidencia.get("page_id", "")).strip() or str(fila.get("id", "")).strip()
        for pieza in _partir_texto(texto):
            digest = sha256_text(f"{page_id}|{encabezado}|{pieza}")
            fragmentos.append(
                Fragmento(
                    id=f"frag:{digest[:12]}",
                    texto=pieza,
                    url=url,
                    titulo=titulo,
                    seccion=seccion,
                    encabezado=encabezado,
                    tipo="hecho verificado",
                    tokens=stable_tokens(pieza),
                )
            )
        revisiones[str(fila.get("review", "")).strip() or "sin_revision"] += 1

    return fragmentos, dict(revisiones), omitidos_sin_evidencia, omitidos_pii


def _resumir(
    fragmentos: Iterable[Fragmento],
    *,
    tablas_enteras: int,
    tablas_partidas: int,
    partes_tablas_partidas: int,
    repetidas: set[str],
    frecuentes: tuple[LineaRepetida, ...],
    revisiones: dict[str, int],
    omitidos_sin_evidencia: int,
    omitidos_pii: int,
    duplicados: int = 0,
) -> ResumenFragmentos:
    """Calcula las métricas del resumen a partir de los fragmentos construidos."""
    lista = list(fragmentos)
    tokens = [fragmento.tokens for fragmento in lista]
    por_tipo = Counter(fragmento.tipo for fragmento in lista)
    return ResumenFragmentos(
        total=len(lista),
        por_tipo=dict(sorted(por_tipo.items())),
        tokens_min=min(tokens, default=0),
        tokens_mediana=float(median(tokens)) if tokens else 0.0,
        tokens_max=max(tokens, default=0),
        cortos=sum(1 for valor in tokens if valor < TOKENS_MINIMOS),
        fragmentos_largos=sum(1 for valor in tokens if valor > TOKENS_MAXIMOS),
        tablas_enteras=tablas_enteras,
        tablas_partidas=tablas_partidas,
        partes_tablas_partidas=partes_tablas_partidas,
        lineas_repetidas=len(repetidas),
        lineas_frecuentes=frecuentes,
        hechos_por_revision=dict(sorted(revisiones.items())),
        omitidos_sin_evidencia=omitidos_sin_evidencia,
        omitidos_pii=omitidos_pii,
        duplicados=duplicados,
    )


def _sin_repetidos(fragmentos: Sequence[Fragmento]) -> tuple[list[Fragmento], int]:
    """Descarta fragmentos con id repetido y conserva el primero de cada uno."""
    vistos: set[str] = set()
    unicos: list[Fragmento] = []
    for fragmento in fragmentos:
        if fragmento.id in vistos:
            continue
        vistos.add(fragmento.id)
        unicos.append(fragmento)
    return unicos, len(fragmentos) - len(unicos)
