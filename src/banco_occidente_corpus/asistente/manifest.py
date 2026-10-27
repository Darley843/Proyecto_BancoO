"""Metadatos del contexto para la app: tokens del manifest y fecha del commit.

El manifest no guarda fecha de generacion a proposito: se omite para que
``make contexto`` sea reproducible. La app muestra, en su lugar, la fecha del
ultimo commit que versiono ``data/contexto/manifest.json``, etiquetada como
"Contexto versionado el". La consulta se hace con ``git log`` sobre el
repositorio y nunca sobre el sitio del banco: no hay red.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import PROJECT_ROOT, load_config
from ..contexto import RutasContexto

#: Ruta del manifest dentro del repositorio, relativa y en POSIX (para git).
RUTA_MANIFEST_RELATIVA = "data/contexto/manifest.json"

#: Segundos maximos que la app espera la respuesta de git.
TIMEOUT_GIT = 5.0


class ManifestAusente(RuntimeError):
    """No existe el manifest del contexto; hay que generarlo con ``make contexto``."""


@dataclass(frozen=True, slots=True)
class MetadatosContexto:
    """Tokens, tope y paginas incluidas que declara el manifest."""

    tokens: int
    max_tokens: int
    tokens_metodo: str
    paginas_incluidas: int


def ruta_manifest(manifest: Path | None = None) -> Path:
    """Devuelve la ruta del manifest pedida o la del contexto del proyecto."""
    if manifest is not None:
        return Path(manifest).expanduser()
    return RutasContexto.desde(load_config()).manifest


def cargar_metadatos(manifest: Path | None = None) -> MetadatosContexto:
    """Lee tokens, tope y paginas del manifest. Solo json; sin red."""
    ruta = ruta_manifest(manifest)
    if not ruta.exists():
        raise ManifestAusente(
            f"No hay manifest en {ruta}. Ejecuta 'make contexto' para generarlo desde Gold."
        )

    datos = json.loads(ruta.read_text(encoding="utf-8"))
    paginas = datos.get("paginas")
    incluidas = paginas.get("incluidas", 0) if isinstance(paginas, dict) else 0
    return MetadatosContexto(
        tokens=int(datos.get("tokens", 0) or 0),
        max_tokens=int(datos.get("max_tokens", 0) or 0),
        tokens_metodo=str(datos.get("tokens_metodo", "")),
        paginas_incluidas=int(incluidas or 0),
    )


def _ruta_para_git(ruta: Path) -> str:
    """Ruta relativa al repositorio; si no se puede, la constante conocida."""
    try:
        return ruta.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return RUTA_MANIFEST_RELATIVA


def fecha_version_contexto(
    *,
    ruta: Path | None = None,
    cwd: Path | None = None,
    timeout: float = TIMEOUT_GIT,
) -> str | None:
    """Fecha ISO del ultimo commit que modifico el manifest, o ``None``.

    Se ejecuta ``git log`` con una lista de argumentos (sin shell), con
    ``timeout`` y con el directorio de trabajo en la raiz del repositorio, para
    que funcione aunque la app se lance desde otra carpeta. Devuelve ``None``
    si git no esta disponible, el archivo no esta versionado o se agota el
    tiempo: la app muestra "no disponible" y no se cae.
    """
    raiz = Path(cwd).expanduser() if cwd is not None else PROJECT_ROOT
    archivo = _ruta_para_git(ruta_manifest(ruta))
    comando = ["git", "log", "-1", "--format=%cI", "--", archivo]

    try:
        proceso = subprocess.run(
            comando,
            cwd=str(raiz),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if proceso.returncode != 0:
        return None
    salida = (proceso.stdout or "").strip()
    return salida or None
