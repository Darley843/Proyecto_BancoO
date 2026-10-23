"""Checklist del Taller 1: que tanto de la empresa quedo cubierto por el corpus."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .section import _normalize  # reutiliza la normalizacion de acentos

#: 4 categorias x 6 items = 24 casillas (igual que la slide "Que capturar").
CHECKLIST: dict[str, list[tuple[str, str]]] = {
    "identidad": [
        ("Mision y vision", r"mision|vision"),
        ("Valores y proposito", r"valores|proposito"),
        ("Historia (fundacion, hitos)", r"historia|fundad|hitos|trayectoria|aniversario"),
        ("Fundador / dueno y junta", r"fundador|junta directiva|accionistas|controlante"),
        ("Gerente y equipo directivo", r"presidente|gerente|directivo|vicepresidente"),
        ("Sedes y ubicaciones", r"sede|sucursal|oficina|direccion|agencia"),
    ],
    "oferta": [
        ("Productos y servicios", r"producto|servicio|portafolio"),
        ("Fichas tecnicas y especificaciones", r"ficha tecnica|especificacion|caracteristicas"),
        ("Precios y planes", r"tarifa|tasa|precio|plan|cuota"),
        ("Catalogos en PDF", r"catalogo|brochure|pdf"),
        ("Casos de exito y clientes", r"caso de exito|cliente|testimonio"),
        ("Certificaciones", r"iso\s?\d|basc|invima|certificacion|sello"),
    ],
    "presencia": [
        ("Noticias y sala de prensa", r"noticia|prensa|comunicado|boletin"),
        ("Blog y articulos", r"blog|articulo|aprende|educacion financiera"),
        ("Videos de YouTube", r"youtube|video"),
        ("Entrevistas del gerente", r"entrevista|declaracion"),
        ("Redes sociales", r"facebook|instagram|linkedin|x\.com|twitter|tiktok"),
        ("Vacantes de empleo", r"vacante|empleo|trabaja con nosotros|convocatoria"),
    ],
    "datos": [
        ("Informes financieros / memoria anual", r"informe|memoria anual|estados financieros"),
        ("NIT y Camara de Comercio", r"\bnit\b|camara de comercio|matricula mercantil"),
        ("Indicadores de sostenibilidad", r"sostenibilidad|huella|indicador|esg"),
        ("Precios publicos y tarifas", r"tarifario|tarifas|comisiones"),
        (
            "Datos abiertos (Superfinanciera, SECOP)",
            r"superfinanciera|superintendencia|secop|datos abiertos",
        ),
        ("Rankings sectoriales", r"ranking|premio|reconocimiento|calificacion"),
    ],
}


@dataclass(slots=True)
class ChecklistItem:
    categoria: str
    item: str
    encontrado: bool
    evidencia: str = ""


def evaluate(corpus: list[dict], texts: dict[str, str] | None = None) -> list[ChecklistItem]:
    """Marca cada casilla buscando evidencia en el texto de los documentos.

    texts: id -> texto. Si no se pasa, solo se evalua sobre titulo y URL.
    """
    texts = texts or {}
    results: list[ChecklistItem] = []
    for categoria, items in CHECKLIST.items():
        for label, pattern in items:
            regex = re.compile(pattern, re.IGNORECASE)
            evidence = ""
            for row in corpus:
                haystack = _normalize(
                    " ".join(
                        [
                            row.get("titulo", ""),
                            row.get("fuente", ""),
                            texts.get(row.get("id", ""), ""),
                        ]
                    )
                )
                match = regex.search(haystack)
                if match:
                    evidence = f"{row.get('titulo') or row.get('fuente')}"
                    break
            results.append(
                ChecklistItem(
                    categoria=categoria,
                    item=label,
                    encontrado=bool(evidence),
                    evidencia=evidence,
                )
            )
    return results


def coverage(items: list[ChecklistItem]) -> tuple[int, int, float]:
    found = sum(1 for item in items if item.encontrado)
    total = len(items)
    return found, total, (found / total * 100 if total else 0.0)
