"""Carga de prompts versionados desde ``config/prompts/``.

Cada archivo se llama ``<tarea>_<version>.md`` (por ejemplo ``qa_v1.md``) y
tiene frontmatter YAML con ``version``, ``tarea`` y ``fecha``. El cuerpo se
divide en ``## Sistema`` y, opcionalmente, ``## Recordatorio``; el recordatorio
se repite despues del contexto para reforzar las reglas clave.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .. import config as config_mod

#: Tareas que tienen prompt propio.
TAREAS: tuple[str, ...] = ("qa", "faq", "resumen")

#: Version por defecto cuando no se pasa ``--version``.
VERSION_POR_DEFECTO = "v1"

_NOMBRE = re.compile(r"^(?P<tarea>[a-z]+)_(?P<version>v\d+)\.md$")
_FRONTMATTER = re.compile(r"^---\s*\n(?P<meta>.*?)\n---\s*\n", re.DOTALL)
_SECCION = re.compile(r"^##\s+(?P<nombre>Sistema|Recordatorio)\s*$", re.MULTILINE)


class PromptNoEncontrado(FileNotFoundError):
    """No existe el archivo de prompt para la tarea y version pedidas."""


@dataclass(frozen=True, slots=True)
class Prompt:
    """Prompt versionado de una tarea del asistente."""

    tarea: str
    version: str
    sistema: str
    recordatorio: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def nombre(self) -> str:
        """Identificador legible, por ejemplo ``qa_v1``."""
        return f"{self.tarea}_{self.version}"


def directorio_prompts() -> Path:
    """Resuelve ``config/prompts`` y respeta ``CORPUS_PROMPTS_DIR`` (pruebas)."""
    raw = os.getenv("CORPUS_PROMPTS_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return config_mod.PROJECT_ROOT / "config" / "prompts"


def versiones_disponibles(tarea: str) -> list[str]:
    """Lista las versiones existentes para una tarea, ordenadas por numero."""
    directorio = directorio_prompts()
    if not directorio.exists():
        return []
    versiones: list[str] = []
    for archivo in directorio.glob(f"{tarea}_v*.md"):
        match = _NOMBRE.match(archivo.name)
        if match and match.group("tarea") == tarea:
            versiones.append(match.group("version"))
    return sorted(set(versiones), key=lambda version: int(version[1:]))


def _separar_frontmatter(texto: str) -> tuple[dict[str, Any], str]:
    """Separa el frontmatter YAML del cuerpo Markdown."""
    match = _FRONTMATTER.match(texto)
    if not match:
        return {}, texto.strip()
    meta = yaml.safe_load(match.group("meta")) or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, texto[match.end() :].strip()


def _separar_secciones(cuerpo: str) -> tuple[str, str]:
    """Devuelve (sistema, recordatorio) a partir de los encabezados ``##``."""
    partes = _SECCION.split(cuerpo)
    secciones: dict[str, str] = {}
    for indice in range(1, len(partes), 2):
        secciones[partes[indice]] = partes[indice + 1].strip()
    sistema = secciones.get("Sistema", "").strip()
    if not sistema:
        raise ValueError("El prompt no tiene una seccion '## Sistema' con contenido.")
    return sistema, secciones.get("Recordatorio", "").strip()


def cargar_prompt(tarea: str, version: str = VERSION_POR_DEFECTO) -> Prompt:
    """Carga ``config/prompts/<tarea>_<version>.md`` y valida su contrato."""
    if tarea not in TAREAS:
        raise ValueError(f"Tarea desconocida: {tarea}. Usa una de: {', '.join(TAREAS)}.")

    archivo = directorio_prompts() / f"{tarea}_{version}.md"
    if not archivo.exists():
        disponibles = ", ".join(versiones_disponibles(tarea)) or "ninguna"
        raise PromptNoEncontrado(
            f"No existe el prompt {archivo.name} en {archivo.parent}. "
            f"Versiones disponibles para {tarea}: {disponibles}."
        )

    meta, cuerpo = _separar_frontmatter(archivo.read_text(encoding="utf-8"))
    sistema, recordatorio = _separar_secciones(cuerpo)

    if str(meta.get("tarea", tarea)) != tarea:
        raise ValueError(f"El prompt {archivo.name} declara otra tarea: {meta.get('tarea')}.")
    if str(meta.get("version", version)) != version:
        raise ValueError(f"El prompt {archivo.name} declara otra version: {meta.get('version')}.")

    return Prompt(
        tarea=tarea,
        version=version,
        sistema=sistema,
        recordatorio=recordatorio,
        meta=meta,
    )
