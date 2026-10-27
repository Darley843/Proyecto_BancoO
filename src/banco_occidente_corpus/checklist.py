"""Checklist del Taller 1: que tanto de la empresa quedo cubierto por el corpus."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .section import _normalize  # reutiliza la normalizacion de acentos

#: 4 categorias x 6 items = 24 casillas (igual que la slide "Que capturar").
#: Los patrones usan limites de palabra: sin ellos "mision" tambien coincide con
#: "comision" y "vision" con "supervision" (falsos positivos).
CHECKLIST: dict[str, list[tuple[str, str]]] = {
    "identidad": [
        ("Mision y vision", r"\bmision(es)?\b|\bvision(es)?\b"),
        ("Valores y proposito", r"\bvalores\b|\bproposito\b"),
        (
            "Historia (fundacion, hitos)",
            r"\bhistoria\b|\bfundad\w*|\bhitos?\b|\btrayectoria\b|\baniversario\b",
        ),
        (
            "Fundador / dueno y junta",
            r"\bfundador\w*|\bjunta directiva\b|\baccionistas?\b|\bcontrolante\b",
        ),
        (
            "Gerente y equipo directivo",
            r"\bpresidente\b|\bgerente\b|\bdirectiv\w+|\bvicepresidente\b",
        ),
        (
            "Sedes y ubicaciones",
            r"\bsede\b|\bsucursal\w*|\boficina\w*|\bdireccion\b|\bagencia\w*",
        ),
    ],
    "oferta": [
        ("Productos y servicios", r"\bproductos?\b|\bservicios?\b|\bportafolio\b"),
        (
            "Fichas tecnicas y especificaciones",
            r"\bficha tecnica\b|\bespecificacion\w*|\bcaracteristicas?\b",
        ),
        (
            "Precios y planes",
            r"\btarifas?\b|\btasas?\b|\bprecios?\b|\bplanes?\b|\bcuotas?\b",
        ),
        ("Catalogos en PDF", r"\bcatalogos?\b|\bbrochure\b|\bpdf\b"),
        ("Casos de exito y clientes", r"\bcaso de exito\b|\bclientes?\b|\btestimonio\w*"),
        (
            "Certificaciones",
            r"\biso\s?\d|\bbasc\b|\binvima\b|\bcertificacion\w*|\bsello\b",
        ),
    ],
    "presencia": [
        (
            "Noticias y sala de prensa",
            r"\bnoticias?\b|\bprensa\b|\bcomunicado\w*|\bboletin\w*",
        ),
        (
            "Blog y articulos",
            r"\bblog\b|\barticulos?\b|\baprende\b|\beducacion financiera\b",
        ),
        ("Videos de YouTube", r"\byoutube\b|\bvideos?\b"),
        ("Entrevistas del gerente", r"\bentrevista\w*|\bdeclaracion\w*"),
        (
            "Redes sociales",
            r"\bfacebook\b|\binstagram\b|\blinkedin\b|\bx\.com\b|\btwitter\b|\btiktok\b",
        ),
        (
            "Vacantes de empleo",
            r"\bvacante\w*|\bempleo\w*|\btrabaja con nosotros\b|\bconvocatoria\w*",
        ),
    ],
    "datos": [
        (
            "Informes financieros / memoria anual",
            r"\binformes?\b|\bmemoria anual\b|\bestados financieros\b",
        ),
        (
            "NIT y Camara de Comercio",
            r"\bnit\b|\bcamara de comercio\b|\bmatricula mercantil\b",
        ),
        (
            "Indicadores de sostenibilidad",
            r"\bsostenibilidad\b|\bhuella\b|\bindicador\w*|\besg\b",
        ),
        (
            "Precios publicos y tarifas",
            r"\btarifario\b|\btarifas?\b|\bcomisiones?\b",
        ),
        (
            "Datos abiertos (Superfinanciera, SECOP)",
            r"\bsuperfinanciera\b|\bsuperintendencia\b|\bsecop\b|\bdatos abiertos\b",
        ),
        (
            "Rankings sectoriales",
            r"\branking\b|\bpremios?\b|\breconocimiento\w*|\bcalificacion\w*",
        ),
    ],
}


@dataclass(slots=True)
class ChecklistItem:
    """Una casilla del checklist del Taller 1 y su evidencia en Gold."""

    categoria: str
    item: str
    encontrado: bool
    evidencia: str = ""


def evaluate(corpus: list[dict], texts: dict[str, str] | None = None) -> list[ChecklistItem]:
    """Marca cada casilla buscando evidencia en el texto de los documentos.

    texts: id -> texto. Si no se pasa, solo se evalua sobre titulo y URL.

    La evidencia incluye el fragmento real donde coincidio el patron, para que
    la cobertura sea verificable en la sustentacion (no solo el titulo).
    """
    texts = texts or {}
    results: list[ChecklistItem] = []
    for categoria, items in CHECKLIST.items():
        for label, pattern in items:
            regex = re.compile(pattern, re.IGNORECASE)
            evidence = ""
            for row in corpus:
                original = " ".join(
                    [
                        row.get("titulo", ""),
                        row.get("fuente", ""),
                        texts.get(row.get("id", ""), ""),
                    ]
                )
                # translate() conserva la longitud: los indices del texto
                # normalizado sirven para cortar el texto original.
                match = regex.search(_normalize(original))
                if not match:
                    continue
                start = max(0, match.start() - 60)
                end = min(len(original), match.end() + 80)
                snippet = " ".join(original[start:end].split())
                title = row.get("titulo") or row.get("fuente")
                evidence = f"{title} — «...{snippet}...»"
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
    """Devuelve (encontradas, total, porcentaje) del checklist."""
    found = sum(1 for item in items if item.encontrado)
    total = len(items)
    return found, total, (found / total * 100 if total else 0.0)
