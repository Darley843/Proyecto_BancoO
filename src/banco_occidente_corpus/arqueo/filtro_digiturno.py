"""Mide el filtro de dominio del Digiturno real con el conjunto de ``docs/ALCANCE.md``.

Adapta ``sucursal.digiturno.clasificar`` al contrato ``texto -> Decision`` de
``arqueo.filtro_dominio``: la ruta ``X`` es rechazo y ``B`` o ``T`` es aceptación.

Hay dos modos:

- **Solo reglas** (por defecto): sin clasificador de dudas, como en las pruebas.
  Costo US$ 0 y sin red. Las dudas caen en ``B`` con motivo ``defecto``.
- **Reglas + modelo** (``--con-modelo``): las dudas van a DeepSeek a temperatura 0,
  igual que en la app. Usa la clave del entorno y gasta tokens.

Uso::

    uv run python -m banco_occidente_corpus.arqueo.filtro_digiturno
    uv run python -m banco_occidente_corpus.arqueo.filtro_digiturno --con-modelo
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT
from ..sucursal.digiturno import (
    Clasificador as ClasificadorDudas,
)
from ..sucursal.digiturno import (
    ConfiguracionDigiturno,
    RegistradorUso,
    cargar_configuracion_digiturno,
    clasificar,
)
from ..sucursal.tipos import Turno
from .filtro_dominio import (
    CasoDominio,
    Categoria,
    Clasificador,
    Decision,
    IntervaloWilson,
    cargar_casos,
    evaluar_filtro,
    intervalo,
    reporte_markdown,
)

#: Motivo con el que el Digiturno marca una duda que el modelo no respondió.
MOTIVO_SIN_RESPUESTA = "modelo_sin_respuesta"
#: Motivos que asignan las reglas del Digiturno; cualquier otro lo escribió el modelo.
MOTIVOS_REGLAS: frozenset[str] = frozenset(
    {
        "pii",
        "fuera_alcance",
        "perfil",
        "diagnostico",
        "cortesia",
        "identidad",
        "mixta",
        "tarifas",
        "defecto",
    }
)
#: Conjunto versionado del filtro de dominio.
RUTA_CONJUNTO: Path = PROJECT_ROOT / "data" / "evaluacion" / "filtro_dominio.jsonl"
#: Decimales de las proporciones del filtro en ``arqueo.json``.
DECIMALES_DOMINIO: int = 6
#: Motivo del Digiturno cuando ninguna regla decide y el texto es una duda.
MOTIVO_DUDA = "defecto"
#: Último informe publicado de la corrida con modelo (lo escribe `medir_varias`).
RUTA_INFORME_MODELO: Path = (
    PROJECT_ROOT / "data" / "evaluacion" / "filtro_dominio_informe_despues.md"
)
#: Fila de corrida de ese informe: ``| 1 | 0/50 | 3/50 | 14/14 | 2 |``.
FILA_CORRIDA = re.compile(
    r"^\|\s*(\d+)\s*\|\s*(\d+)/(\d+)\s*\|\s*(\d+)/(\d+)\s*\|\s*(\d+)/(\d+)\s*\|\s*(\d+)\s*\|$"
)
#: Más ids que estos no se listan en la tabla del Markdown, solo en el JSON.
MAXIMO_IDS_TABLA: int = 10


def decision_de_turno(turno: Turno) -> Decision:
    """Traduce la letra del Digiturno a la decisión del filtro: ``X`` rechaza."""
    return Decision.RECHAZAR if turno.letra == "X" else Decision.ACEPTAR


def clasificador_digiturno(
    *,
    configuracion: ConfiguracionDigiturno | None = None,
    clasificador_dudas: ClasificadorDudas | None = None,
    registrar_uso: RegistradorUso | None = None,
    turnos: dict[str, Turno] | None = None,
) -> Clasificador:
    """Construye un clasificador ``texto -> Decision`` sobre el Digiturno real.

    Args:
        configuracion: palabras y patrones; se cargan una sola vez del TOML si faltan.
        clasificador_dudas: clasificador de dudas (DeepSeek o un doble); sin él,
            las dudas caen en ``B`` con motivo ``defecto``.
        registrar_uso: callback que recibe las métricas de cada llamada al modelo.
        turnos: diccionario opcional donde se guarda el turno de cada texto, para
            reportar el motivo de los errores.

    Returns:
        Una función que decide si un texto se acepta o se rechaza.
    """
    ajustes = configuracion or cargar_configuracion_digiturno()

    def decidir(texto: str) -> Decision:
        turno = clasificar(
            texto,
            configuracion=ajustes,
            clasificador=clasificador_dudas,
            registrar_uso=registrar_uso,
        )
        if turnos is not None:
            turnos[texto] = turno
        return decision_de_turno(turno)

    return decidir


def origen_turno(turno: Turno) -> str:
    """Agrupa el motivo del turno: regla que decidió, letra del modelo o modelo sin respuesta."""
    if turno.motivo.endswith(MOTIVO_SIN_RESPUESTA):
        return "modelo sin respuesta"
    base = turno.motivo.split(":")[0]
    if base in MOTIVOS_REGLAS:
        return f"regla {base}"
    return f"modelo → {turno.letra}"


def sumar_metricas(uso: Counter[str], metricas: dict[str, Any], prefijo: str = "") -> None:
    """Acumula en ``uso`` los valores numéricos de ``metricas``, también los anidados."""
    for clave, valor in metricas.items():
        nombre = f"{prefijo}{clave}"
        if isinstance(valor, dict):
            sumar_metricas(uso, valor, f"{nombre}.")
        elif isinstance(valor, int | float) and not isinstance(valor, bool):
            uso[nombre] += valor


def detalle_errores(
    casos: Sequence[CasoDominio],
    ids: Sequence[str],
    turnos: dict[str, Turno],
) -> str:
    """Tabla Markdown con el texto, la letra y el motivo de cada caso con error."""
    por_id = {caso.id: caso for caso in casos}
    lineas = ["| Caso | Texto | Letra | Motivo |", "|---|---|---|---|"]
    for caso_id in ids:
        caso = por_id[caso_id]
        turno = turnos.get(caso.texto)
        letra = turno.letra if turno else "?"
        motivo = turno.motivo if turno else "?"
        texto = caso.texto.replace("|", "\\|")
        lineas.append(f"| {caso_id} | {texto} | {letra} | {motivo} |")
    return "\n".join(lineas) + "\n"


def medir(
    *,
    ruta: Path = RUTA_CONJUNTO,
    clasificador_dudas: ClasificadorDudas | None = None,
    registrar_uso: RegistradorUso | None = None,
    turnos: dict[str, Turno] | None = None,
) -> str:
    """Corre el conjunto contra el Digiturno y devuelve el informe en Markdown.

    Si se pasa ``turnos``, se llena con el turno de cada texto para revisarlo después.
    """
    casos = cargar_casos(ruta)
    turnos = {} if turnos is None else turnos
    resultado = evaluar_filtro(
        casos,
        clasificador_digiturno(
            clasificador_dudas=clasificador_dudas,
            registrar_uso=registrar_uso,
            turnos=turnos,
        ),
    )
    origenes = Counter(origen_turno(t) for t in turnos.values())
    partes = [
        reporte_markdown(resultado),
        "\n**Quién decidió** (todos los casos): "
        + ", ".join(f"{origen} {n}" for origen, n in origenes.most_common())
        + "\n",
    ]
    sin_respuesta = tuple(
        caso.id
        for caso in casos
        if caso.texto in turnos and turnos[caso.texto].motivo.endswith(MOTIVO_SIN_RESPUESTA)
    )
    for titulo, ids in (
        ("Fugas", resultado.ids_fuga),
        ("Rechazos indebidos", resultado.ids_rechazo_indebido),
        ("Frontera con decisión distinta", resultado.ids_frontera_fallidos),
        ("Dudas sin respuesta del modelo", sin_respuesta),
    ):
        if ids:
            partes.append(f"\n### {titulo}\n\n{detalle_errores(casos, ids, turnos)}")
    return "".join(partes)


def _fraccion(intervalo: Any) -> str:
    """``exitos/n`` de un intervalo, o una raya si no hay casos."""
    return f"{intervalo.exitos}/{intervalo.n}" if intervalo is not None else "—"


def _rango(valores: Sequence[int], n: int) -> str:
    """Rango ``mín a máx`` en conteo y porcentaje."""
    if n == 0 or not valores:
        return "—"
    bajo, alto = min(valores), max(valores)
    pct_bajo = f"{bajo / n * 100:.1f}".replace(".", ",")
    pct_alto = f"{alto / n * 100:.1f}".replace(".", ",")
    if bajo == alto:
        return f"{bajo}/{n} ({pct_bajo} %)"
    return f"{bajo} a {alto} de {n} ({pct_bajo} a {pct_alto} %)"


def medir_varias(
    repeticiones: int,
    *,
    ruta: Path = RUTA_CONJUNTO,
    clasificador_dudas: ClasificadorDudas | None = None,
    registrar_uso: RegistradorUso | None = None,
    turnos_por_corrida: list[dict[str, Turno]] | None = None,
) -> str:
    """Corre el conjunto varias veces y reporta el rango de cada métrica y los casos inestables.

    El modelo no es determinista aunque use temperatura 0, así que una sola corrida no
    basta. No se agrupan las corridas en un solo intervalo de Wilson: son los mismos casos
    repetidos, no muestras independientes. Se reporta el rango y, por caso, cuántas
    corridas fallaron y con qué letra.
    """
    if repeticiones < 1:
        raise ValueError("repeticiones debe ser al menos 1")
    casos = cargar_casos(ruta)
    corridas = [] if turnos_por_corrida is None else turnos_por_corrida
    resultados = []
    for _ in range(repeticiones):
        turnos: dict[str, Turno] = {}
        resultados.append(
            evaluar_filtro(
                casos,
                clasificador_digiturno(
                    clasificador_dudas=clasificador_dudas,
                    registrar_uso=registrar_uso,
                    turnos=turnos,
                ),
            )
        )
        corridas.append(turnos)

    lineas = [
        "| Corrida | Fuga | Rechazo indebido | Acierto en frontera | Dudas sin respuesta |",
        "|---:|---|---|---|---:|",
    ]
    for numero, (resultado, turnos) in enumerate(zip(resultados, corridas, strict=True), start=1):
        sin_respuesta = sum(1 for t in turnos.values() if t.motivo.endswith(MOTIVO_SIN_RESPUESTA))
        lineas.append(
            f"| {numero} | {_fraccion(resultado.fuga)} | {_fraccion(resultado.rechazo_indebido)} "
            f"| {_fraccion(resultado.acierto_frontera)} | {sin_respuesta} |"
        )
    n_fuera = resultados[0].fuga.n if resultados[0].fuga else 0
    n_dentro = resultados[0].rechazo_indebido.n if resultados[0].rechazo_indebido else 0
    n_frontera = resultados[0].acierto_frontera.n if resultados[0].acierto_frontera else 0
    lineas.append(
        "| **Rango** | "
        + _rango([len(r.ids_fuga) for r in resultados], n_fuera)
        + " | "
        + _rango([len(r.ids_rechazo_indebido) for r in resultados], n_dentro)
        + " | "
        + _rango([n_frontera - len(r.ids_frontera_fallidos) for r in resultados], n_frontera)
        + " | |"
    )

    errores = [
        "| Caso | Texto | Esperado | Corridas con error | Letra por corrida |",
        "|---|---|---|---:|---|",
    ]
    for caso in casos:
        letras = [t[caso.texto].letra if caso.texto in t else "?" for t in corridas]
        fallos = sum(
            1
            for t in corridas
            if caso.texto in t and decision_de_turno(t[caso.texto]) is not caso.esperado
        )
        if fallos:
            texto = caso.texto.replace("|", "\\|")
            errores.append(
                f"| {caso.id} | {texto} | {caso.esperado.value} | {fallos} de {repeticiones} | {', '.join(letras)} |"
            )

    partes = ["\n".join(lineas) + "\n"]
    if len(errores) > 2:
        partes.append(
            "\n### Casos con error en al menos una corrida\n\n"
            "Un caso con error en todas las corridas es un fallo estable de la regla o del prompt; "
            "uno con error en algunas es inestable.\n\n" + "\n".join(errores) + "\n"
        )
    else:
        partes.append("\nNingún caso tuvo error en ninguna corrida.\n")
    return "".join(partes)


def _intervalo_json(valor: IntervaloWilson | None) -> dict[str, Any] | None:
    """Convierte un intervalo de Wilson en el bloque del JSON, o ``None`` sin casos."""
    if valor is None:
        return None
    return {
        "exitos": valor.exitos,
        "n": valor.n,
        "proporcion": round(valor.proporcion, DECIMALES_DOMINIO),
        "inferior": round(valor.inferior, DECIMALES_DOMINIO),
        "superior": round(valor.superior, DECIMALES_DOMINIO),
        "confianza": valor.confianza,
    }


def _ruta_visible(ruta: Path) -> str:
    """Ruta relativa al proyecto, o solo el nombre si está fuera de él."""
    try:
        return ruta.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return ruta.name


def leer_corridas_modelo(ruta: Path = RUTA_INFORME_MODELO) -> list[dict[str, int]]:
    """Lee la tabla de corridas del informe con modelo que escribe `medir_varias`.

    El Arqueo no llama a DeepSeek: resume la última corrida publicada.

    Args:
        ruta: informe Markdown de ``--con-modelo --repeticiones N``.

    Returns:
        Una fila por corrida con fuga, rechazo indebido, acierto en frontera,
        sus totales y las dudas sin respuesta; vacía si el informe no existe.
    """
    if not ruta.exists():
        return []
    corridas: list[dict[str, int]] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        coincidencia = FILA_CORRIDA.match(linea.strip())
        if coincidencia is None:
            continue
        numero, fuga, n_fuera, rechazo, n_dentro, frontera, n_frontera, dudas = (
            int(valor) for valor in coincidencia.groups()
        )
        corridas.append(
            {
                "corrida": numero,
                "fuga": fuga,
                "n_fuera": n_fuera,
                "rechazo_indebido": rechazo,
                "n_dentro": n_dentro,
                "acierto_frontera": frontera,
                "n_frontera": n_frontera,
                "dudas_sin_respuesta": dudas,
            }
        )
    return corridas


def seccion_dominio(
    ruta: Path = RUTA_CONJUNTO,
    *,
    configuracion: ConfiguracionDigiturno | None = None,
    informe_modelo: Path = RUTA_INFORME_MODELO,
) -> dict[str, Any]:
    """Arma la sección ``dominio`` de ``arqueo.json``.

    Pone lado a lado dos lecturas del mismo conjunto:

    - **Reglas solas**, medidas en cada Arqueo (US$ 0 y determinista): cuántos
      casos deciden las reglas (cobertura) y cuántos errores cometen entre los
      que deciden. Un caso que ninguna regla decide es una duda: en la app la
      resuelve el modelo, así que no se cuenta como fuga de las reglas.
    - **Sistema real con modelo**, leído del último informe publicado con
      ``--con-modelo``, sin volver a llamar a DeepSeek.

    Solo se guardan ids, nunca el texto de los casos.

    Args:
        ruta: conjunto JSONL del filtro de dominio.
        configuracion: palabras y patrones del Digiturno; por defecto los del TOML.
        informe_modelo: informe Markdown de la corrida con modelo.

    Returns:
        ``{"conjunto", "casos", "reglas", "modelo"}``; ``modelo`` es ``None`` si
        no hay informe publicado.
    """
    casos = cargar_casos(ruta)
    turnos: dict[str, Turno] = {}
    decidir = clasificador_digiturno(configuracion=configuracion, turnos=turnos)
    grupos: dict[str, dict[str, Any]] = {
        categoria.value: {"n": 0, "deciden": 0, "ids": []} for categoria in Categoria
    }
    for caso in casos:
        obtenida = decidir(caso.texto)
        grupo = grupos[caso.categoria.value]
        grupo["n"] += 1
        if turnos[caso.texto].motivo.split(":")[0] == MOTIVO_DUDA:
            continue
        grupo["deciden"] += 1
        if obtenida is not caso.esperado:
            grupo["ids"].append(caso.id)

    decidio = Counter(origen_turno(turnos[caso.texto]) for caso in casos)
    total = sum(grupo["n"] for grupo in grupos.values())
    deciden = sum(grupo["deciden"] for grupo in grupos.values())
    corridas = leer_corridas_modelo(informe_modelo)
    return {
        "conjunto": _ruta_visible(ruta),
        "casos": {clave: grupo["n"] for clave, grupo in grupos.items()},
        "reglas": {
            "modo": "solo_reglas",
            "cobertura": _intervalo_json(intervalo(deciden, total)),
            "grupos": {
                clave: {
                    "n": grupo["n"],
                    "deciden": grupo["deciden"],
                    "cobertura": _intervalo_json(intervalo(grupo["deciden"], grupo["n"])),
                    "errores": _intervalo_json(intervalo(len(grupo["ids"]), grupo["deciden"])),
                    "ids": list(grupo["ids"]),
                }
                for clave, grupo in grupos.items()
            },
            "decidio": dict(sorted(decidio.items())),
        },
        "modelo": (
            {"fuente": _ruta_visible(informe_modelo), "corridas": corridas} if corridas else None
        ),
    }


def _porcentaje(valor: float) -> str:
    """Escribe una proporción como porcentaje con coma decimal, p. ej. ``4,0 %``."""
    return f"{valor * 100:.1f}".replace(".", ",") + " %"


def _proporcion(datos: Mapping[str, Any]) -> str:
    """``p % [inf %; sup %]`` de un intervalo del JSON."""
    return (
        f"{_porcentaje(datos['proporcion'])} "
        f"[{_porcentaje(datos['inferior'])}; {_porcentaje(datos['superior'])}]"
    )


def _celda_intervalo(datos: Mapping[str, Any] | None) -> str:
    """``exitos/n (p % [inf %; sup %])`` o una raya si no hay casos."""
    if not datos:
        return "—"
    return f"{datos['exitos']}/{datos['n']} ({_proporcion(datos)})"


def _celda_ids(ids: Sequence[str]) -> str:
    """Lista los ids con error, o remite al JSON si son demasiados."""
    if len(ids) > MAXIMO_IDS_TABLA:
        return f"{len(ids)} casos; la lista está en `arqueo.json`"
    return ", ".join(ids) or "—"


def markdown_dominio(seccion: Mapping[str, Any] | None) -> list[str]:
    """Escribe la sección «Filtro de dominio» de ``docs/ARQUEO.md``.

    Se arma desde el mismo bloque del JSON, así que las cifras coinciden.

    Args:
        seccion: el bloque ``dominio`` de ``arqueo.json``.

    Returns:
        Las líneas de la sección, listas para unir con saltos de línea.
    """
    lineas = ["## Filtro de dominio", ""]
    if not seccion:
        return [*lineas, "No se midió el filtro de dominio en esta corrida.", ""]
    casos: Mapping[str, int] = seccion.get("casos") or {}
    reglas: Mapping[str, Any] = seccion.get("reglas") or {}
    grupos: Mapping[str, Any] = reglas.get("grupos") or {}
    cobertura: Mapping[str, Any] = reglas.get("cobertura") or {}
    lineas += [
        f"Conjunto `{seccion.get('conjunto', RUTA_CONJUNTO.name)}`: "
        f"{casos.get('dentro', 0)} dentro, {casos.get('fuera', 0)} fuera y "
        f"{casos.get('frontera', 0)} de frontera. Se muestran lado a lado las reglas solas, "
        "que el Arqueo mide en cada corrida, y el sistema real con el modelo, tomado del "
        "último informe publicado.",
        "",
        "### Reglas solas (US$ 0, determinista)",
        "",
        f"Las reglas deciden {cobertura.get('exitos', 0)} de {cobertura.get('n', 0)} casos"
        + (f" ({_proporcion(cobertura)})" if cobertura else "")
        + ". El resto son dudas: en la app las resuelve el "
        "modelo, así que no cuentan como error de las reglas.",
        "",
        "| Grupo | Casos | Deciden las reglas | Error entre los que deciden | Casos con error |",
        "|---|---:|---|---|---|",
    ]
    for clave, nombre in (
        ("fuera", "Fuera de tema (fuga)"),
        ("dentro", "Dentro del dominio (rechazo indebido)"),
        ("frontera", "Frontera (decisión distinta)"),
    ):
        datos: Mapping[str, Any] = grupos.get(clave) or {}
        lineas.append(
            f"| {nombre} | {datos.get('n', 0)} | {_celda_intervalo(datos.get('cobertura'))} "
            f"| {_celda_intervalo(datos.get('errores'))} | {_celda_ids(datos.get('ids') or [])} |"
        )
    decidio: Mapping[str, int] = reglas.get("decidio") or {}
    if decidio:
        resumen = ", ".join(f"{origen} {n}" for origen, n in decidio.items())
        lineas += ["", f"**Quién decidió** (todos los casos): {resumen}."]

    lineas += ["", "### Sistema real: reglas + modelo (DeepSeek)", ""]
    modelo: Mapping[str, Any] | None = seccion.get("modelo")
    if not modelo:
        lineas += [
            f"Todavía no hay una corrida con modelo publicada en `{RUTA_INFORME_MODELO.name}`.",
            "",
        ]
    else:
        corridas: Sequence[Mapping[str, int]] = modelo["corridas"]
        lineas += [
            f"{len(corridas)} corridas publicadas en `{modelo['fuente']}`. El Arqueo no las "
            "recalcula porque gastan tokens; se actualizan con "
            "`uv run python -m banco_occidente_corpus.arqueo.filtro_digiturno --con-modelo "
            f"--repeticiones 3 --salida {modelo['fuente']}`.",
            "",
            "| Corrida | Fuga | Rechazo indebido | Acierto en frontera | Dudas sin respuesta |",
            "|---:|---|---|---|---:|",
        ]
        lineas += [
            f"| {c['corrida']} | {c['fuga']}/{c['n_fuera']} | "
            f"{c['rechazo_indebido']}/{c['n_dentro']} | "
            f"{c['acierto_frontera']}/{c['n_frontera']} | {c['dudas_sin_respuesta']} |"
            for c in corridas
        ]
        primera = corridas[0]
        lineas.append(
            "| **Rango** | "
            + _rango([c["fuga"] for c in corridas], primera["n_fuera"])
            + " | "
            + _rango([c["rechazo_indebido"] for c in corridas], primera["n_dentro"])
            + " | "
            + _rango([c["acierto_frontera"] for c in corridas], primera["n_frontera"])
            + " | |"
        )
        lineas.append("")
    lineas += [
        "Solo se publican los ids de los casos con error; el texto está en el conjunto.",
        "",
    ]
    return lineas


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada de línea de comandos."""
    parser = argparse.ArgumentParser(description="Mide el filtro de dominio del Digiturno real.")
    parser.add_argument(
        "--con-modelo",
        action="store_true",
        help="manda las dudas a DeepSeek (gasta tokens; usa la clave del entorno)",
    )
    parser.add_argument("--salida", type=Path, help="archivo Markdown donde guardar el informe")
    parser.add_argument(
        "--repeticiones",
        type=int,
        default=1,
        help="corre el conjunto N veces y reporta el rango (útil con --con-modelo)",
    )
    args = parser.parse_args(argv)
    if args.repeticiones < 1:
        parser.error("--repeticiones debe ser al menos 1")

    clasificador_dudas: ClasificadorDudas | None = None
    uso: Counter[str] = Counter()
    llamadas = 0

    def registrar(metricas: dict[str, Any]) -> None:
        nonlocal llamadas
        llamadas += 1
        sumar_metricas(uso, metricas)

    if args.con_modelo:
        from ..sucursal.digiturno import crear_clasificador

        clasificador_dudas = crear_clasificador()

    modo = "reglas + modelo (DeepSeek)" if args.con_modelo else "solo reglas (sin modelo, US$ 0)"
    registrador = registrar if args.con_modelo else None
    turnos: dict[str, Turno] = {}
    if args.repeticiones == 1:
        cuerpo = medir(
            clasificador_dudas=clasificador_dudas, registrar_uso=registrador, turnos=turnos
        )
        todas = [turnos]
    else:
        todas = []
        cuerpo = medir_varias(
            args.repeticiones,
            clasificador_dudas=clasificador_dudas,
            registrar_uso=registrador,
            turnos_por_corrida=todas,
        )
        modo += f", {args.repeticiones} corridas"
    informe = f"## Filtro de dominio del Digiturno: {modo}\n\n" + cuerpo
    sin_respuesta = sum(
        1 for t in todas for turno in t.values() if turno.motivo.endswith(MOTIVO_SIN_RESPUESTA)
    )
    if args.con_modelo and llamadas == 0 and sin_respuesta:
        print(
            f"ERROR: el modelo no respondió ninguna de las {sin_respuesta} dudas. Revisa DEEPSEEK_API_KEY "
            "y la conexión; no se guardó el informe porque mediría solo las reglas.",
            file=sys.stderr,
        )
        return 2
    if sin_respuesta:
        informe += (
            f"\n> **Atención:** {sin_respuesta} dudas quedaron sin respuesta del modelo (sumando todas las "
            "corridas); el Digiturno las resolvió con su respaldo y no con el modelo.\n"
        )
    if args.con_modelo:
        claves = [c for c in uso if c.startswith("uso.")] or list(uso)
        resumen = ", ".join(
            f"{clave.removeprefix('uso.')} {uso[clave]:g}" for clave in sorted(claves)
        )
        informe += (
            f"\n**Llamadas al modelo:** {llamadas}. Uso acumulado: {resumen or 'sin métricas'}.\n"
        )

    if args.salida:
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_text(informe, encoding="utf-8", newline="\n")
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    print(informe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
