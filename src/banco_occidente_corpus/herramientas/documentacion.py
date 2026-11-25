"""Genera la parte del catálogo que vive en `docs/HERRAMIENTAS.md`.

El documento tiene dos secciones escritas a mano —las herramientas del gateway
de OpenClaw y el control de la alucinación— y un bloque generado entre marcas.
El bloque se arma desde :data:`catalogo.CATALOGO`: nombres, dueñas, entradas
Pydantic, fuentes y módulos delegados. La prueba
`test_herramientas_documentacion.py` falla si el documento no coincide con el
catálogo, así que la documentación no puede quedar desactualizada.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .catalogo import Herramienta

#: Marca que abre el bloque generado del documento.
MARCA_INICIO: str = "<!-- inicio:generado por herramientas --markdown -->"
#: Marca que cierra el bloque generado del documento.
MARCA_FIN: str = "<!-- fin:generado -->"


def _texto(valor: Any) -> str:
    """Normaliza un valor del JSON Schema a una sola línea."""
    return " ".join(str(valor).split())


def _tipo(campo: Mapping[str, Any], *, enum: bool = True) -> str:
    """Escribe el tipo de un campo del JSON Schema en forma legible.

    Args:
        campo: fragmento del JSON Schema del modelo Pydantic.
        enum: si se listan los valores de un `enum`; las listas largas, como los
            ids de la entrevista, se resumen con el tipo del elemento.

    Returns:
        Un tipo como ``string``, ``array<string>`` o ``"fraccion" | "porcentaje"``.
    """
    if "anyOf" in campo:
        return " | ".join(_tipo(opcion, enum=enum) for opcion in campo["anyOf"])
    if "const" in campo:
        return f"`{campo['const']}`"
    if enum and "enum" in campo:
        return " | ".join(f"`{valor}`" for valor in campo["enum"])
    tipo = campo.get("type")
    if isinstance(tipo, list):
        return " | ".join(str(valor) for valor in tipo)
    if tipo == "array":
        item = campo.get("items", {})
        return f"array<{_tipo(item, enum=False)}>"
    return str(tipo or "any")


def _restricciones(campo: Mapping[str, Any]) -> str:
    """Resume los límites numéricos, de largo y de cantidad de un campo."""
    partes: list[str] = []
    if "minimum" in campo:
        partes.append(f"≥ {campo['minimum']}")
    if "maximum" in campo:
        partes.append(f"≤ {campo['maximum']}")
    if "exclusiveMinimum" in campo:
        partes.append(f"> {campo['exclusiveMinimum']}")
    if "exclusiveMaximum" in campo:
        partes.append(f"< {campo['exclusiveMaximum']}")
    if "minLength" in campo:
        partes.append(f"largo mínimo {campo['minLength']}")
    if "maxLength" in campo:
        partes.append(f"largo máximo {campo['maxLength']}")
    if "minItems" in campo:
        partes.append(f"mínimo {campo['minItems']} elementos")
    if "maxItems" in campo:
        partes.append(f"máximo {campo['maxItems']} elementos")
    return " · ".join(partes)


def _campo(nombre: str, campo: Mapping[str, Any], obligatorio: bool) -> str:
    """Escribe una viñeta con el nombre, el tipo, la obligación y la descripción."""
    etiqueta = "obligatorio" if obligatorio else "opcional"
    restricciones = _restricciones(campo)
    if restricciones:
        etiqueta = f"{etiqueta}; {restricciones}"
    if "default" in campo and campo["default"] is not None:
        etiqueta = f"{etiqueta}; por defecto `{campo['default']}`"
    tipo = _tipo(campo)
    tipo_legible = tipo if "`" in tipo else f"`{tipo}`"
    descripcion = _texto(campo.get("description", ""))
    detalle = f" — {descripcion}" if descripcion else ""
    return f"- **`{nombre}`** · {tipo_legible} · {etiqueta}{detalle}"


def _entrada(herramienta: Herramienta) -> list[str]:
    """Arma la lista de campos de entrada desde el esquema Pydantic."""
    esquema = herramienta.entrada.model_json_schema()
    propiedades: Mapping[str, Any] = esquema.get("properties", {})
    requeridos = set(esquema.get("required", []))
    lineas = [
        f"**Entrada** (`{herramienta.entrada.__name__}`, "
        f'`extra="{herramienta.entrada.model_config.get("extra", "ignorar")}"`):',
        "",
    ]
    if not propiedades:
        lineas.append("- Sin campos: la herramienta no recibe argumentos.")
        return lineas
    for nombre, campo in propiedades.items():
        lineas.append(_campo(nombre, campo, nombre in requeridos))
    return lineas


def _ficha(posicion: int, herramienta: Herramienta) -> list[str]:
    """Escribe la ficha completa de una herramienta del catálogo."""
    documentacion = herramienta.documentacion
    lineas = [
        f"### {posicion}. `{herramienta.nombre}`",
        "",
        f"**Dueña.** {herramienta.duena}",
        "",
        f"**Confirmación.** {documentacion.confirmacion}",
        "",
        f"**Para qué sirve.** {documentacion.para_que}",
        "",
        f"**Cuándo NO usarla.** {documentacion.cuando_no}",
        "",
        *_entrada(herramienta),
        "",
        f"**Qué devuelve.** {documentacion.devuelve}",
        "",
        f"**De dónde salen sus cifras.** {documentacion.fuente}",
        "",
        f"**Módulo en el que delega.** `{documentacion.modulo}`",
        "",
    ]
    return lineas


def _resumen(herramientas: Sequence[Herramienta]) -> list[str]:
    """Escribe la tabla de las veinte herramientas."""
    lineas = [
        "| # | Herramienta | Dueña | Confirmación |",
        "|---|---|---|---|",
    ]
    for posicion, herramienta in enumerate(herramientas, start=1):
        lineas.append(
            f"| {posicion} | `{herramienta.nombre}` | {herramienta.duena} | "
            f"{herramienta.documentacion.confirmacion} |"
        )
    return lineas


def render_markdown(herramientas: Sequence[Herramienta]) -> str:
    """Arma el bloque generado del documento, sin las marcas.

    Args:
        herramientas: el catálogo en el orden que ve el agente.

    Returns:
        Markdown con el resumen y la ficha de cada herramienta.
    """
    lineas = [
        "## Catálogo de las veinte herramientas",
        "",
        "Este bloque lo escribe `make herramientas-doc` desde "
        "`src/banco_occidente_corpus/herramientas/`. No se edita a mano: la prueba "
        "`test_herramientas_documentacion.py` falla si el documento y el catálogo "
        "no coinciden.",
        "",
        f"Total: **{len(herramientas)} herramientas**.",
        "",
        *_resumen(herramientas),
        "",
    ]
    for posicion, herramienta in enumerate(herramientas, start=1):
        lineas.extend(_ficha(posicion, herramienta))
    return "\n".join(lineas).strip()


def bloque_generado(texto: str) -> str:
    """Extrae el bloque que está entre las dos marcas del documento.

    Args:
        texto: contenido completo de `docs/HERRAMIENTAS.md`.

    Returns:
        El bloque generado, sin espacios en los extremos.

    Raises:
        ValueError: si faltan las marcas o están invertidas.
    """
    if MARCA_INICIO not in texto or MARCA_FIN not in texto:
        raise ValueError("docs/HERRAMIENTAS.md no tiene las marcas del bloque generado")
    inicio = texto.index(MARCA_INICIO) + len(MARCA_INICIO)
    fin = texto.index(MARCA_FIN, inicio)
    return texto[inicio:fin].strip()


def actualizar(ruta: Path, herramientas: Sequence[Herramienta]) -> None:
    """Reemplaza el bloque generado de un documento existente.

    Args:
        ruta: archivo Markdown con las dos marcas.
        herramientas: catálogo con el que se regenera el bloque.

    Raises:
        ValueError: si el archivo no existe o no tiene las marcas.
        FileNotFoundError: si la ruta no existe.
    """
    contenido = ruta.read_text(encoding="utf-8")
    if MARCA_INICIO not in contenido or MARCA_FIN not in contenido:
        raise ValueError(f"{ruta} no tiene las marcas del bloque generado")
    inicio = contenido.index(MARCA_INICIO) + len(MARCA_INICIO)
    fin = contenido.index(MARCA_FIN, inicio)
    nuevo = contenido[:inicio] + "\n\n" + render_markdown(herramientas) + "\n\n" + contenido[fin:]
    ruta.write_text(nuevo, encoding="utf-8", newline="\n")
