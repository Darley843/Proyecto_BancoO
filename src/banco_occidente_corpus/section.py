"""Clasificacion de paginas en las secciones del checklist del Taller 1."""

from __future__ import annotations

import re

#: Reglas ordenadas: la primera que coincide gana.
#: Se evaluan sobre "url + titulo" en minusculas y sin acentos.
_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "legal",
        (
            "terminos",
            "condiciones",
            "politica",
            "habeas",
            "tratamiento-de-datos",
            "privacidad",
            "cookies",
            "transparencia",
            "defensor-del-consumidor",
            "tarifario",
        ),
    ),
    (
        "atencion",
        (
            "atencion",
            "canales",
            "sucursales",
            "oficinas",
            "contacto",
            "contactenos",
            "pqrs",
            "ayuda",
            "preguntas-frecuentes",
            "faq",
            "linea-de-atencion",
        ),
    ),
    (
        "identidad",
        (
            "quienes-somos",
            "nosotros",
            "mision",
            "vision",
            "historia",
            "gobierno-corporativo",
            "junta",
            "directiv",
            "presidente",
            "gerente",
            "valores",
            "proposito",
            "informacion-corporativa",
            "filiales",
            "grupo-empresarial",
        ),
    ),
    (
        "datos",
        (
            "informe",
            "memoria-anual",
            "estados-financieros",
            "indicadores",
            "calificacion",
            "sostenibilidad",
            "inversionistas",
            "accionistas",
            "nit",
            "datos-abiertos",
            "superintendencia",
        ),
    ),
    (
        "presencia",
        (
            "noticia",
            "prensa",
            "comunicado",
            "blog",
            "actualidad",
            "evento",
            "sala-de-prensa",
            "revista",
            "podcast",
            "video",
            "youtube",
        ),
    ),
    (
        "oferta",
        (
            "producto",
            "servicio",
            "cuenta",
            "tarjeta",
            "credito",
            "prestamo",
            "ahorro",
            "inversion",
            "seguro",
            "leasing",
            "fiducia",
            "empresarial",
            "pyme",
            "vivienda",
            "vehiculo",
            "libre-inversion",
            "cdt",
            "nomina",
            "remesa",
            "canal",
            "app",
            "banca-virtual",
        ),
    ),
]

_ACCENTS = str.maketrans("áéíóúüñ", "aeiouun")


def _normalize(text: str) -> str:
    return text.lower().translate(_ACCENTS)


def classify(url: str, title: str = "") -> str:
    """Devuelve la seccion (identidad, oferta, presencia, datos, atencion, legal u otros)."""
    haystack = _normalize(f"{url} {title}")
    for section, needles in _RULES:
        if any(needle in haystack for needle in needles):
            return section
    return "otros"


def section_label(section: str) -> str:
    """Etiqueta legible para el indice y el markdown."""
    return {
        "identidad": "Identidad corporativa",
        "oferta": "Productos y servicios",
        "presencia": "Presencia digital / noticias",
        "datos": "Datos duros e informes",
        "atencion": "Atencion al cliente",
        "legal": "Legal y terminos",
        "otros": "Otros",
    }.get(section, section.title())


def is_relevant(section: str) -> bool:
    """Las paginas de 'otros' suelen ser ruido de navegacion."""
    return section != "otros"


def extract_keywords(text: str, limit: int = 8) -> list[str]:
    """Palabras clave simples por frecuencia (sin stopwords) para el frontmatter."""
    stop = {
        "para",
        "como",
        "con",
        "los",
        "las",
        "del",
        "que",
        "una",
        "por",
        "mas",
        "sus",
        "este",
        "esta",
        "entre",
        "desde",
        "sobre",
        "tambien",
        "puede",
        "todo",
        "todos",
        "nuestros",
        "nuestras",
        "banco",
        "occidente",
        "ser",
        "son",
        "the",
        "and",
    }
    words = re.findall(r"[a-záéíóúüñ]{4,}", _normalize(text))
    freq: dict[str, int] = {}
    for word in words:
        if word in stop:
            continue
        freq[word] = freq.get(word, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [word for word, _ in ranked[:limit]]
