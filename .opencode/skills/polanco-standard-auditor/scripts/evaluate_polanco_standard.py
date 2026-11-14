#!/usr/bin/env python3
"""Evaluates a project against Professor Jan Polanco's engineering standard (jan-project-standard).

Performs a deep semantic audit across his 10 non-negotiable rules, file manifest,
pyproject.toml, Makefile, .pre-commit-config.yaml, CONSTITUTION.md (12 sections),
GitHub governance (.github/), AI agent context (AGENTS.md / CLAUDE.md / tgrep),
and Git workflow, then outputs a weighted compliance score and a 4-phase roadmap.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CheckItem:
    category: str
    artifact: str
    status: str  # "OK", "DIFIERE", "FALTA", "OPCIONAL"
    points: float
    max_points: float
    diagnosis: str
    remediation: str = ""
    phase: int = 1  # 1=Quick Wins, 2=Tooling/CI, 3=GitHub Governance, 4=Agent/Showcase


@dataclass
class AuditReport:
    project_path: str
    project_name: str
    package_name: str
    total_points: float = 0.0
    max_points: float = 100.0
    bonus_points: float = 0.0
    items: list[CheckItem] = field(default_factory=list)

    @property
    def percentage(self) -> float:
        if self.max_points <= 0:
            return 0.0
        return round((self.total_points / self.max_points) * 100.0, 1)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _detect_package_name(root: Path, pyproject_data: dict[str, Any]) -> str:
    proj_name = pyproject_data.get("project", {}).get("name", root.name)
    slug_pkg = re.sub(r"[^a-zA-Z0-9_]", "_", proj_name).lower()
    src_dir = root / "src"
    if src_dir.is_dir():
        for child in sorted(src_dir.iterdir()):
            if child.is_dir() and (child / "__init__.py").exists():
                return child.name
    return slug_pkg


def evaluate_project(root: Path) -> AuditReport:
    pyproject_path = root / "pyproject.toml"
    pyproject_data: dict[str, Any] = {}
    if pyproject_path.is_file():
        try:
            pyproject_data = tomllib.loads(_read_text(pyproject_path))
        except Exception:
            pyproject_data = {}

    project_name = pyproject_data.get("project", {}).get("name", root.name)
    package_name = _detect_package_name(root, pyproject_data)
    report = AuditReport(
        project_path=str(root.resolve()),
        project_name=project_name,
        package_name=package_name,
    )

    # =========================================================================
    # CATEGORY 1: Python & uv Stack (20 pts)
    # =========================================================================
    cat1 = "1. Python & uv Stack"

    # 1.1 Exclusive uv (no pip/requirements.txt/setup.py/Pipfile) + uv.lock (5 pts)
    forbidden = [
        f
        for f in ("requirements.txt", "requirements-dev.txt", "setup.py", "setup.cfg", "Pipfile")
        if (root / f).exists()
    ]
    has_uv_lock = (root / "uv.lock").is_file()
    if has_uv_lock and not forbidden:
        report.items.append(
            CheckItem(
                cat1,
                "uv.lock & exclusividad uv",
                "OK",
                5.0,
                5.0,
                "`uv.lock` versionado y cero archivos prohibidos (`requirements.txt`, `setup.py`).",
            )
        )
    elif has_uv_lock and forbidden:
        report.items.append(
            CheckItem(
                cat1,
                "uv.lock & exclusividad uv",
                "DIFIERE",
                2.5,
                5.0,
                f"Existe `uv.lock`, pero se detectaron archivos prohibidos por el estándar: {', '.join(forbidden)}.",
                f"Eliminar {', '.join(forbidden)} y gestionar dependencias exclusivamente en `pyproject.toml` con `uv`.",
                phase=1,
            )
        )
    else:
        report.items.append(
            CheckItem(
                cat1,
                "uv.lock & exclusividad uv",
                "FALTA",
                0.0,
                5.0,
                "No existe `uv.lock` en la raíz del proyecto.",
                "Ejecutar `uv lock && uv sync` y versionar `uv.lock`.",
                phase=1,
            )
        )

    # 1.2 .python-version (2 pts)
    py_ver_file = root / ".python-version"
    if py_ver_file.is_file():
        ver_txt = _read_text(py_ver_file).strip()
        if ver_txt.startswith("3.1"):
            report.items.append(
                CheckItem(
                    cat1,
                    ".python-version",
                    "OK",
                    2.0,
                    2.0,
                    f"Versión de Python fijada en `{ver_txt}`.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat1,
                    ".python-version",
                    "DIFIERE",
                    1.0,
                    2.0,
                    f"`.python-version` tiene `{ver_txt}` (el estándar usa `3.13`).",
                    "Fijar `3.13` en `.python-version`.",
                    phase=1,
                )
            )
    else:
        report.items.append(
            CheckItem(
                cat1,
                ".python-version",
                "FALTA",
                0.0,
                2.0,
                "Falta `.python-version` en la raíz.",
                "Crear `.python-version` con `3.13`.",
                phase=1,
            )
        )

    # 1.3 src/<pkg>/py.typed (3 pts)
    src_pkg_dir = root / "src" / package_name
    py_typed = src_pkg_dir / "py.typed"
    if src_pkg_dir.is_dir():
        if py_typed.is_file():
            report.items.append(
                CheckItem(
                    cat1,
                    f"src/{package_name}/py.typed",
                    "OK",
                    3.0,
                    3.0,
                    "Marcador PEP 561 `py.typed` presente en el paquete.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat1,
                    f"src/{package_name}/py.typed",
                    "FALTA",
                    0.0,
                    3.0,
                    f"Falta el marcador PEP 561 `src/{package_name}/py.typed` requerido con `src/` layout y `ty`.",
                    f"Crear archivo vacío `src/{package_name}/py.typed`.",
                    phase=1,
                )
            )
    else:
        main_py = root / "main.py"
        if main_py.is_file():
            report.items.append(
                CheckItem(
                    cat1,
                    "main.py (layout flat)",
                    "OK",
                    3.0,
                    3.0,
                    "Layout flat con `main.py` detectado.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat1,
                    f"src/{package_name}/",
                    "FALTA",
                    0.0,
                    3.0,
                    "No se encontró `src/<paquete>/` ni `main.py`.",
                    "Estructurar el código bajo `src/<paquete>/` con `__init__.py` y `py.typed`.",
                    phase=1,
                )
            )

    # 1.4 pyproject.toml metadata & tool stack (10 pts)
    if not pyproject_path.is_file():
        report.items.append(
            CheckItem(
                cat1,
                "pyproject.toml",
                "FALTA",
                0.0,
                10.0,
                "No existe `pyproject.toml`.",
                "Crear `pyproject.toml` siguiendo la plantilla canónica del estándar.",
                phase=1,
            )
        )
    else:
        proj = pyproject_data.get("project", {})
        tool = pyproject_data.get("tool", {})
        build_backend = pyproject_data.get("build-system", {}).get("build-backend", "")
        diffs: list[str] = []
        pts = 10.0

        if "license-files" not in proj:
            diffs.append("falta `license-files = [\"LICENSE\"]`")
            pts -= 1.5
        if "classifiers" not in proj or not proj.get("classifiers"):
            diffs.append("faltan `classifiers` (Python 3.13, Typing :: Typed)")
            pts -= 1.5
        urls = proj.get("urls", {})
        if not all(k in urls for k in ("Homepage", "Repository", "Issues")):
            diffs.append("falta `[project.urls]` (`Homepage`, `Repository`, `Issues`)")
            pts -= 2.0
        if src_pkg_dir.is_dir() and build_backend != "uv_build":
            diffs.append(f"`build-backend` es `{build_backend}` en vez de `uv_build`")
            pts -= 1.5

        ruff_cfg = tool.get("ruff", {})
        ruff_select = set(ruff_cfg.get("lint", {}).get("select", []))
        expected_rules = {"E", "F", "I", "UP", "B", "SIM", "C4", "RUF"}
        missing_rules = sorted(expected_rules - ruff_select)
        if missing_rules:
            diffs.append(f"en `[tool.ruff.lint].select` faltan reglas: {missing_rules}")
            pts -= 1.5
        isort_cfg = ruff_cfg.get("lint", {}).get("isort", {})
        if "known-first-party" not in isort_cfg:
            diffs.append("falta `[tool.ruff.lint.isort]` con `known-first-party`")
            pts -= 1.0

        if "ty" not in tool:
            diffs.append("falta configuración `[tool.ty]`")
            pts -= 1.0

        pts = max(0.0, round(pts, 1))
        if not diffs:
            report.items.append(
                CheckItem(
                    cat1,
                    "pyproject.toml",
                    "OK",
                    10.0,
                    10.0,
                    "Metadatos completos, `uv_build`, `[project.urls]`, Ruff (`E..C4..RUF` + `isort`), `ty` y `pytest` alineados.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat1,
                    "pyproject.toml",
                    "DIFIERE",
                    pts,
                    10.0,
                    "Diferencias respecto al estándar: " + "; ".join(diffs) + ".",
                    "Completar metadatos (`license-files`, `classifiers`, `[project.urls]`) y reglas Ruff (`C4`, `[tool.ruff.lint.isort]`) en `pyproject.toml`.",
                    phase=1,
                )
            )

    # =========================================================================
    # CATEGORY 2: Quality Gates & Automation (20 pts)
    # =========================================================================
    cat2 = "2. Quality Gates & Automation"

    # 2.1 Makefile (8 pts)
    makefile_path = root / "Makefile"
    if not makefile_path.is_file():
        report.items.append(
            CheckItem(
                cat2,
                "Makefile",
                "FALTA",
                0.0,
                8.0,
                "No existe `Makefile`.",
                "Crear `Makefile` con los targets canónicos (`help`, `install`, `dev`, `pre-commit-install`, `lint`, `format`, `typecheck`, `test`, `check`, `build`, `clean`).",
                phase=2,
            )
        )
    else:
        mk_txt = _read_text(makefile_path)
        targets = set(re.findall(r"^([a-zA-Z0-9_-]+)\s*:", mk_txt, flags=re.MULTILINE))
        required_targets = {
            "help",
            "install",
            "dev",
            "pre-commit-install",
            "lint",
            "format",
            "typecheck",
            "test",
            "check",
            "clean",
        }
        if src_pkg_dir.is_dir():
            required_targets.add("build")
        missing_targets = sorted(required_targets - targets)

        # Check if clean target deletes data/gold or domain data directly
        clean_match = re.search(
            r"^clean\s*:.*?(?=^[a-zA-Z0-9_.-]+\s*:|\Z)",
            mk_txt,
            flags=re.MULTILINE | re.DOTALL,
        )
        clean_body = clean_match.group(0) if clean_match else ""
        unsafe_clean = any(tok in clean_body for tok in ("data/gold", "data/raw", "data/processed"))

        pts = 8.0
        diffs = []
        if missing_targets:
            diffs.append(f"faltan targets canónicos: {', '.join(missing_targets)}")
            pts -= min(4.0, len(missing_targets) * 1.0)
        if unsafe_clean:
            diffs.append(
                "`make clean` borra datos del proyecto (`data/...`) en lugar de limpiar únicamente cachés de Python (`.pytest_cache`, `.ruff_cache`, `dist`, `build`, `__pycache__`)"
            )
            pts -= 2.5

        pts = max(0.0, round(pts, 1))
        if not diffs:
            report.items.append(
                CheckItem(
                    cat2,
                    "Makefile",
                    "OK",
                    8.0,
                    8.0,
                    "Contiene todos los targets canónicos del estándar y `clean` seguro (conservando targets de dominio).",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat2,
                    "Makefile",
                    "DIFIERE",
                    pts,
                    8.0,
                    "Diferencias en `Makefile`: " + "; ".join(diffs) + ".",
                    "Fusionar los targets canónicos (`install`, `dev`, `pre-commit-install`, `build`) conservando los targets propios del proyecto, y asegurar que `clean` solo limpie cachés de Python/build.",
                    phase=2,
                )
            )

    # 2.2 .pre-commit-config.yaml (8 pts)
    pc_path = root / ".pre-commit-config.yaml"
    if not pc_path.is_file():
        report.items.append(
            CheckItem(
                cat2,
                ".pre-commit-config.yaml",
                "FALTA",
                0.0,
                8.0,
                "Falta `.pre-commit-config.yaml`.",
                "Crear `.pre-commit-config.yaml` con `pre-commit-hooks`, `ruff-pre-commit` y `uv-pre-commit` (`uv-lock`).",
                phase=2,
            )
        )
    else:
        pc_txt = _read_text(pc_path)
        diffs = []
        pts = 8.0
        if "uv-pre-commit" not in pc_txt or "uv-lock" not in pc_txt:
            diffs.append("falta el hook `astral-sh/uv-pre-commit` (`id: uv-lock`)")
            pts -= 3.0
        if "default_language_version:" not in pc_txt:
            diffs.append("falta `default_language_version: python: python3.13`")
            pts -= 1.0
        if "minimum_pre_commit_version:" not in pc_txt:
            diffs.append("falta `minimum_pre_commit_version: \"3.7.0\"`")
            pts -= 1.0
        for hook_id in (
            "check-case-conflict",
            "mixed-line-ending",
            "detect-private-key",
        ):
            if hook_id not in pc_txt:
                diffs.append(f"falta hook de higiene `{hook_id}`")
                pts -= 0.5
        if "--markdown-linebreak-ext=md" not in pc_txt:
            diffs.append("falta `--markdown-linebreak-ext=md` en `trailing-whitespace`")
            pts -= 0.5

        pts = max(0.0, round(pts, 1))
        if not diffs:
            report.items.append(
                CheckItem(
                    cat2,
                    ".pre-commit-config.yaml",
                    "OK",
                    8.0,
                    8.0,
                    "Hooks completos: higiene general, `ruff` (`--fix`), `ruff-format` y `uv-lock`.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat2,
                    ".pre-commit-config.yaml",
                    "DIFIERE",
                    pts,
                    8.0,
                    "Diferencias en `.pre-commit-config.yaml`: " + "; ".join(diffs) + ".",
                    "Actualizar `.pre-commit-config.yaml` para incluir `uv-lock`, `default_language_version` y todos los hooks de higiene canónicos.",
                    phase=2,
                )
            )

    # 2.3 .editorconfig (4 pts)
    ec_path = root / ".editorconfig"
    if not ec_path.is_file():
        report.items.append(
            CheckItem(
                cat2,
                ".editorconfig",
                "FALTA",
                0.0,
                4.0,
                "Falta `.editorconfig`.",
                "Crear `.editorconfig` canónico.",
                phase=1,
            )
        )
    else:
        ec_txt = _read_text(ec_path)
        diffs = []
        pts = 4.0
        if "toml" not in ec_txt:
            diffs.append("falta `toml` en la regla de indentación de 2 espacios (`[*.{yml,yaml,json,toml}]`)")
            pts -= 1.5
        if "trim_trailing_whitespace = false" not in ec_txt:
            diffs.append("falta `[*.{md,markdown}] trim_trailing_whitespace = false`")
            pts -= 1.5
        if not diffs:
            report.items.append(
                CheckItem(
                    cat2,
                    ".editorconfig",
                    "OK",
                    4.0,
                    4.0,
                    "`.editorconfig` alineado al 100% con el estándar.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat2,
                    ".editorconfig",
                    "DIFIERE",
                    max(0.0, pts),
                    4.0,
                    "Diferencias en `.editorconfig`: " + "; ".join(diffs) + ".",
                    "Ajustar `.editorconfig` para incluir `[*.{yml,yaml,json,toml}]` y `[*.{md,markdown}] trim_trailing_whitespace = false`.",
                    phase=1,
                )
            )

    # =========================================================================
    # CATEGORY 3: Constitution & Documentation (20 pts)
    # =========================================================================
    cat3 = "3. Constitution & Documentation"

    # 3.1 CONSTITUTION.md (8 pts)
    const_path = root / "CONSTITUTION.md"
    if not const_path.is_file():
        report.items.append(
            CheckItem(
                cat3,
                "CONSTITUTION.md",
                "FALTA",
                0.0,
                8.0,
                "Falta `CONSTITUTION.md` (fuente única de verdad obligatoria).",
                "Crear `CONSTITUTION.md` con las 12 secciones canónicas.",
                phase=1,
            )
        )
    else:
        c_txt = _read_text(const_path)
        sec_nums = set(re.findall(r"^##\s+(\d+)\.", c_txt, flags=re.MULTILINE))
        missing_secs = sorted(set(str(i) for i in range(1, 13)) - sec_nums, key=int)
        unresolved_vars = re.findall(r"\{\{[A-Z0-9_]+\}\}", c_txt)
        todos = re.findall(r"<!--\s*TODO", c_txt, flags=re.IGNORECASE)
        pts = 8.0
        diffs = []
        if missing_secs:
            diffs.append(f"faltan secciones numeradas: {', '.join(missing_secs)}")
            pts -= min(4.0, len(missing_secs) * 1.0)
        if unresolved_vars:
            diffs.append(f"placeholders sin resolver: {sorted(set(unresolved_vars))}")
            pts -= 2.5
        if todos:
            diffs.append(f"contiene {len(todos)} bloques `<!-- TODO -->` sin completar")
            pts -= 2.0

        if not diffs:
            report.items.append(
                CheckItem(
                    cat3,
                    "CONSTITUTION.md",
                    "OK",
                    8.0,
                    8.0,
                    "Contiene las 12 secciones canónicas (§1–§12) completas y sin placeholders pendientes.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat3,
                    "CONSTITUTION.md",
                    "DIFIERE",
                    max(0.0, pts),
                    8.0,
                    "Observaciones en `CONSTITUTION.md`: " + "; ".join(diffs) + ".",
                    "Completar las 12 secciones canónicas y eliminar cualquier placeholder `{{...}}` o `<!-- TODO -->`.",
                    phase=1,
                )
            )

    # 3.2 docs/adr/ & docs/README.md (5 pts)
    adr_dir = root / "docs" / "adr"
    adr_files = sorted(adr_dir.glob("0001-*.md")) if adr_dir.is_dir() else []
    has_adr_0001 = len(adr_files) > 0
    docs_readme = root / "docs" / "README.md"
    if has_adr_0001 and docs_readme.is_file():
        report.items.append(
            CheckItem(
                cat3,
                "docs/README.md & docs/adr/",
                "OK",
                5.0,
                5.0,
                f"`docs/README.md` y `{adr_files[0].name}` presentes.",
            )
        )
    elif has_adr_0001 and not docs_readme.is_file():
        report.items.append(
            CheckItem(
                cat3,
                "docs/README.md",
                "FALTA",
                3.0,
                5.0,
                f"`docs/adr/{adr_files[0].name}` existe, pero falta el índice `docs/README.md` de la plantilla base.",
                "Crear `docs/README.md` indexando `adr/`, reportes de evaluación y enlace a `CONSTITUTION.md`.",
                phase=1,
            )
        )
    else:
        report.items.append(
            CheckItem(
                cat3,
                "docs/README.md & docs/adr/",
                "FALTA",
                0.0,
                5.0,
                "Faltan `docs/README.md` y/o `docs/adr/0001-*.md`.",
                "Crear `docs/README.md` y al menos el primer ADR `docs/adr/0001-*.md`.",
                phase=1,
            )
        )

    # 3.3 README.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, LICENSE (7 pts)
    readme_path = root / "README.md"
    gov_files = [f for f in ("CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "LICENSE") if (root / f).is_file()]
    if readme_path.is_file() and len(gov_files) == 3:
        r_txt = _read_text(readme_path)
        diffs = []
        pts = 7.0
        if "actions/workflows/ci.yml/badge.svg" not in r_txt:
            diffs.append("falta badge dinámico de CI (`actions/workflows/ci.yml/badge.svg`)")
            pts -= 0.5
        if "pre--commit-enabled" not in r_txt and "pre-commit" not in r_txt.lower():
            diffs.append("falta badge de `pre-commit`")
            pts -= 0.5
        if "Conventional%20Commits" not in r_txt:
            diffs.append("falta badge de `Conventional Commits`")
            pts -= 0.5
        if "CONSTITUTION.md" not in r_txt:
            diffs.append("`README.md` no enlaza a `CONSTITUTION.md`")
            pts -= 1.5

        if not diffs:
            report.items.append(
                CheckItem(
                    cat3,
                    "README.md & Comunidad (CONTRIBUTING, CODE_OF_CONDUCT, LICENSE)",
                    "OK",
                    7.0,
                    7.0,
                    "Archivos de comunidad completos y `README.md` con badges canónicos (CI, uv, Ruff, pre-commit, Conventional Commits) y enlace a `CONSTITUTION.md`.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat3,
                    "README.md & Comunidad",
                    "DIFIERE",
                    max(0.0, round(pts, 1)),
                    7.0,
                    "En `README.md`: " + "; ".join(diffs) + ".",
                    "Añadir los badges canónicos (CI, pre-commit, Conventional Commits) en el encabezado de `README.md`.",
                    phase=4,
                )
            )
    else:
        missing_gov = [
            f
            for f in ("README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "LICENSE")
            if not (root / f).is_file()
        ]
        report.items.append(
            CheckItem(
                cat3,
                "README.md & Comunidad",
                "FALTA",
                2.0,
                7.0,
                f"Faltan archivos base de comunidad: {', '.join(missing_gov)}.",
                f"Crear {', '.join(missing_gov)} según las plantillas del estándar.",
                phase=1,
            )
        )

    # =========================================================================
    # CATEGORY 4: GitHub Governance (20 pts)
    # =========================================================================
    cat4 = "4. GitHub Governance (.github/)"

    # 4.1 .github/workflows/ci.yml (5 pts)
    ci_path = root / ".github" / "workflows" / "ci.yml"
    if not ci_path.is_file():
        report.items.append(
            CheckItem(
                cat4,
                ".github/workflows/ci.yml",
                "FALTA",
                0.0,
                5.0,
                "Falta el workflow de integración continua `.github/workflows/ci.yml`.",
                "Crear `.github/workflows/ci.yml`.",
                phase=2,
            )
        )
    else:
        ci_txt = _read_text(ci_path)
        diffs = []
        pts = 5.0
        if "concurrency:" not in ci_txt:
            diffs.append("falta bloque `concurrency` para cancelar ejecuciones redundantes")
            pts -= 1.0
        if "pre-commit run --all-files" not in ci_txt:
            diffs.append("no ejecuta `uv run pre-commit run --all-files --show-diff-on-failure`")
            pts -= 1.5
        if "--all-groups" not in ci_txt:
            diffs.append("usa `uv sync` sin `--all-groups`")
            pts -= 0.5
        if not diffs:
            report.items.append(
                CheckItem(
                    cat4,
                    ".github/workflows/ci.yml",
                    "OK",
                    5.0,
                    5.0,
                    "Workflow CI con `concurrency`, `uv sync --all-groups`, `pre-commit`, `ty` y `pytest`.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat4,
                    ".github/workflows/ci.yml",
                    "DIFIERE",
                    max(0.0, round(pts, 1)),
                    5.0,
                    "En `.github/workflows/ci.yml`: " + "; ".join(diffs) + ".",
                    "Actualizar `.github/workflows/ci.yml` con `concurrency`, `uv sync --all-groups` y `pre-commit run --all-files`.",
                    phase=2,
                )
            )

    # 4.2 .github/labels.yml & .github/workflows/labels.yml (5 pts)
    labels_yml = root / ".github" / "labels.yml"
    labels_wf = root / ".github" / "workflows" / "labels.yml"
    if labels_yml.is_file() and labels_wf.is_file():
        report.items.append(
            CheckItem(
                cat4,
                ".github/labels.yml & workflows/labels.yml",
                "OK",
                5.0,
                5.0,
                "Etiquetas declarativas y workflow de sincronización presentes.",
            )
        )
    else:
        missing_lbl = []
        if not labels_yml.is_file():
            missing_lbl.append(".github/labels.yml")
        if not labels_wf.is_file():
            missing_lbl.append(".github/workflows/labels.yml")
        report.items.append(
            CheckItem(
                cat4,
                ".github/labels.yml & workflows/labels.yml",
                "FALTA",
                0.0,
                5.0,
                f"Faltan: {', '.join(missing_lbl)}.",
                "Crear `.github/labels.yml` (fuente declarativa de etiquetas) y `.github/workflows/labels.yml`.",
                phase=3,
            )
        )

    # 4.3 .github/ISSUE_TEMPLATE/ YAML Issue Forms (5 pts)
    issue_dir = root / ".github" / "ISSUE_TEMPLATE"
    expected_ymls = ("bug_report.yml", "feature_request.yml", "spike.yml", "config.yml")
    present_ymls = [f for f in expected_ymls if (issue_dir / f).is_file()]
    legacy_mds = list(issue_dir.glob("*.md")) if issue_dir.is_dir() else []

    if len(present_ymls) == 4 and not legacy_mds:
        report.items.append(
            CheckItem(
                cat4,
                ".github/ISSUE_TEMPLATE/ (YAML Forms)",
                "OK",
                5.0,
                5.0,
                "Los 4 formularios YAML canónicos (`bug_report.yml`, `feature_request.yml`, `spike.yml`, `config.yml`) están activos.",
            )
        )
    elif present_ymls or legacy_mds:
        missing_y = [f for f in expected_ymls if f not in present_ymls]
        msg_parts = []
        if legacy_mds:
            msg_parts.append(
                f"usa plantillas Markdown antiguas ({', '.join(p.name for p in legacy_mds)}) en lugar de GitHub Issue Forms YAML"
            )
        if missing_y:
            msg_parts.append(f"faltan formularios YAML: {', '.join(missing_y)}")
        report.items.append(
            CheckItem(
                cat4,
                ".github/ISSUE_TEMPLATE/",
                "DIFIERE",
                1.5,
                5.0,
                "; ".join(msg_parts) + ".",
                "Reemplazar las plantillas `.md` antiguas por los 4 formularios YAML canónicos (`bug_report.yml`, `feature_request.yml`, `spike.yml`, `config.yml`).",
                phase=3,
            )
        )
    else:
        report.items.append(
            CheckItem(
                cat4,
                ".github/ISSUE_TEMPLATE/",
                "FALTA",
                0.0,
                5.0,
                "No existe `.github/ISSUE_TEMPLATE/`.",
                "Crear `.github/ISSUE_TEMPLATE/` con `bug_report.yml`, `feature_request.yml`, `spike.yml` y `config.yml`.",
                phase=3,
            )
        )

    # 4.4 Pull Request Template (5 pts)
    pr_candidates = [
        root / ".github" / "pull_request_template.md",
        root / ".github" / "PULL_REQUEST_TEMPLATE.md",
    ]
    pr_file = next((p for p in pr_candidates if p.is_file()), None)
    if pr_file is None:
        report.items.append(
            CheckItem(
                cat4,
                ".github/pull_request_template.md",
                "FALTA",
                0.0,
                5.0,
                "Falta plantilla de Pull Request.",
                "Crear `.github/pull_request_template.md` con la estructura canónica del profesor Polanco.",
                phase=3,
            )
        )
    else:
        pr_txt = _read_text(pr_file)
        diffs = []
        pts = 5.0
        if "Conventional Commits" not in pr_txt:
            diffs.append("falta tabla guía de prefijos Conventional Commits")
            pts -= 1.0
        if "CONSTITUTION.md" not in pr_txt:
            diffs.append("no exige verificar/actualizar `CONSTITUTION.md` en el checklist")
            pts -= 1.5
        if "Squash & Merge" not in pr_txt:
            diffs.append("falta sección de integración y post-merge (`Squash & Merge`)")
            pts -= 1.0

        if not diffs:
            report.items.append(
                CheckItem(
                    cat4,
                    f".github/{pr_file.name}",
                    "OK",
                    5.0,
                    5.0,
                    "Plantilla de PR completa con tabla Conventional Commits, trazabilidad, matriz de pruebas, check de `CONSTITUTION.md` y guía `Squash & Merge`.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat4,
                    f".github/{pr_file.name}",
                    "DIFIERE",
                    max(0.0, round(pts, 1)),
                    5.0,
                    f"En `{pr_file.name}`: " + "; ".join(diffs) + ".",
                    "Enriquecer la plantilla de PR con las secciones canónicas (tabla Conventional Commits, matriz de pruebas, check de `CONSTITUTION.md` y post-merge `Squash & Merge`).",
                    phase=3,
                )
            )

    # =========================================================================
    # CATEGORY 5: AI Agent Context (10 pts)
    # =========================================================================
    cat5 = "5. AI Agent Context (AGENTS.md & OpenCode)"

    # 5.1 AGENTS.md & CLAUDE.md (5 pts)
    agents_md = root / "AGENTS.md"
    claude_md = root / "CLAUDE.md"
    if agents_md.is_file() or claude_md.is_file():
        a_txt = _read_text(agents_md) if agents_md.is_file() else ""
        c_txt = _read_text(claude_md).strip() if claude_md.is_file() else ""
        diffs = []
        pts = 5.0
        if not agents_md.is_file():
            diffs.append("falta `AGENTS.md`")
            pts -= 3.0
        else:
            if "CONSTITUTION.md" not in a_txt:
                diffs.append("`AGENTS.md` no referencia `CONSTITUTION.md`")
                pts -= 1.5
            if "tgrep" not in a_txt:
                diffs.append("`AGENTS.md` no incluye la sección de búsqueda de código con `tgrep`")
                pts -= 1.0
        if not claude_md.is_file():
            diffs.append("falta `CLAUDE.md` (puente `@AGENTS.md`)")
            pts -= 1.5
        elif "@AGENTS.md" not in c_txt:
            diffs.append("`CLAUDE.md` no contiene `@AGENTS.md`")
            pts -= 1.0
        if not diffs:
            report.items.append(
                CheckItem(
                    cat5,
                    "AGENTS.md & CLAUDE.md",
                    "OK",
                    5.0,
                    5.0,
                    "`AGENTS.md` (con referencia a `CONSTITUTION.md`, comandos y `tgrep`) y `CLAUDE.md` (`@AGENTS.md`) alineados.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat5,
                    "AGENTS.md & CLAUDE.md",
                    "DIFIERE",
                    max(0.0, round(pts, 1)),
                    5.0,
                    "; ".join(diffs) + ".",
                    "Crear `CLAUDE.md` con `@AGENTS.md` y añadir la sección `## Búsqueda de código: tgrep` a `AGENTS.md` conservando el contexto de dominio existente.",
                    phase=4,
                )
            )
    else:
        report.items.append(
            CheckItem(
                cat5,
                "AGENTS.md & CLAUDE.md",
                "FALTA",
                0.0,
                5.0,
                "Faltan `AGENTS.md` y `CLAUDE.md`.",
                "Crear `AGENTS.md` y `CLAUDE.md` (`@AGENTS.md`).",
                phase=4,
            )
        )

    # 5.2 .opencode/rules/tgrep.md & .gitignore (.tgrep/) (5 pts)
    tgrep_rule = root / ".opencode" / "rules" / "tgrep.md"
    gitignore_path = root / ".gitignore"
    gi_txt = _read_text(gitignore_path)
    has_tgrep_ignore = ".tgrep/" in gi_txt
    opencode_blanket_ignored = bool(re.search(r"^\.opencode/?\s*$", gi_txt, flags=re.MULTILINE))

    if tgrep_rule.is_file() and has_tgrep_ignore and not opencode_blanket_ignored:
        report.items.append(
            CheckItem(
                cat5,
                ".opencode/rules/tgrep.md & .gitignore",
                "OK",
                5.0,
                5.0,
                "`.opencode/rules/tgrep.md` versionado y `.tgrep/` ignorado en `.gitignore`.",
            )
        )
    else:
        diffs = []
        pts = 5.0
        if not tgrep_rule.is_file():
            diffs.append("falta `.opencode/rules/tgrep.md`")
            pts -= 3.0
        if not has_tgrep_ignore:
            diffs.append("falta `.tgrep/` en `.gitignore`")
            pts -= 1.0
        if opencode_blanket_ignored:
            diffs.append("`.gitignore` ignora todo `.opencode/`, impidiendo versionar `.opencode/rules/tgrep.md`")
            pts -= 1.0
        report.items.append(
            CheckItem(
                cat5,
                ".opencode/rules/tgrep.md & .gitignore",
                "FALTA" if not tgrep_rule.is_file() else "DIFIERE",
                max(0.0, round(pts, 1)),
                5.0,
                "; ".join(diffs) + ".",
                "Crear `.opencode/rules/tgrep.md`, añadir `.tgrep/` a `.gitignore` y permitir `.opencode/rules/tgrep.md` en Git.",
                phase=4,
            )
        )

    # =========================================================================
    # CATEGORY 6: Git & Workflow Discipline (10 pts)
    # =========================================================================
    cat6 = "6. Git & Workflow Discipline"

    # 6.1 Conventional Commits & Git repository (10 pts)
    try:
        log_out = subprocess.check_output(
            ["git", "-C", str(root), "log", "-n", "15", "--pretty=format:%s"],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        ).splitlines()
    except Exception:
        log_out = []

    cc_pattern = re.compile(
        r"^(feat|fix|docs|refactor|style|test|chore|build|ci|perf|revert)(\([a-zA-Z0-9_-]+\))?!?:\s+.+"
    )
    if log_out:
        non_merge = [s for s in log_out if not s.startswith("Merge ")]
        matching = [s for s in non_merge if cc_pattern.match(s)]
        ratio = len(matching) / max(1, len(non_merge))
        if ratio >= 0.8:
            report.items.append(
                CheckItem(
                    cat6,
                    "Historial Git (Conventional Commits)",
                    "OK",
                    10.0,
                    10.0,
                    f"{len(matching)}/{len(non_merge)} commits recientes siguen Conventional Commits.",
                )
            )
        else:
            report.items.append(
                CheckItem(
                    cat6,
                    "Historial Git (Conventional Commits)",
                    "DIFIERE",
                    5.0,
                    10.0,
                    f"Solo {len(matching)}/{len(non_merge)} commits recientes usan prefijos Conventional Commits.",
                    "Usar siempre `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:` en nuevos commits.",
                    phase=4,
                )
            )
    else:
        report.items.append(
            CheckItem(
                cat6,
                "Historial Git",
                "FALTA",
                0.0,
                10.0,
                "No se detectó historial de commits en Git.",
                "Inicializar Git y commitear con Conventional Commits.",
                phase=1,
            )
        )

    # =========================================================================
    # BONUS / OPTIONAL: Archify Visual Architecture (+5 pts)
    # =========================================================================
    cat_bonus = "Bonus: Visual Architecture (Archify)"
    arch_json = root / "docs" / "arquitectura.json"
    arch_html = root / "docs" / "arquitectura.html"
    if arch_json.is_file() and arch_html.is_file():
        report.bonus_points = 5.0
        report.items.append(
            CheckItem(
                cat_bonus,
                "docs/arquitectura.json & .html",
                "OK",
                5.0,
                0.0,
                "Mapa interactivo Archify presente (`docs/arquitectura.json` + `docs/arquitectura.html`).",
                phase=4,
            )
        )
    else:
        report.items.append(
            CheckItem(
                cat_bonus,
                "docs/arquitectura.json & .html",
                "OPCIONAL",
                0.0,
                0.0,
                "Extra opcional (`--with-archify`): mapa interactivo de arquitectura no generado aún.",
                "(Opcional Showcase) Generar `docs/arquitectura.json` y `docs/arquitectura.html` con Archify.",
                phase=4,
            )
        )

    report.total_points = round(sum(i.points for i in report.items if i.max_points > 0), 1)
    report.max_points = round(sum(i.max_points for i in report.items if i.max_points > 0), 1)
    return report


def format_markdown_report(report: AuditReport) -> str:
    lines: list[str] = []
    lines.append(f"# Auditoría Estándar Profesor Jan Polanco: `{report.project_name}`")
    lines.append("")
    lines.append(f"- **Ruta evaluada**: `{report.project_path}`")
    lines.append(f"- **Paquete detectado**: `{report.package_name}`")
    bonus_str = f" (+{report.bonus_points:.0f} pts Bonus Archify)" if report.bonus_points > 0 else ""
    lines.append(
        f"- **Puntaje de cumplimiento**: **{report.total_points:.1f} / {report.max_points:.1f} ({report.percentage}%)**{bonus_str}"
    )
    lines.append("")

    # Summary by category
    lines.append("## 1. Resumen por Categoría")
    lines.append("")
    lines.append("| Categoría | Puntaje | Estado |")
    lines.append("| :--- | :---: | :---: |")
    categories: dict[str, list[CheckItem]] = {}
    for item in report.items:
        if item.max_points == 0:
            continue
        categories.setdefault(item.category, []).append(item)

    for cat, items in categories.items():
        pts = sum(i.points for i in items)
        m_pts = sum(i.max_points for i in items)
        status = "✅ OK" if pts == m_pts else ("⚠️ DIFIERE" if pts >= m_pts * 0.5 else "❌ FALTA")
        lines.append(f"| **{cat}** | {pts:.1f} / {m_pts:.1f} | {status} |")
    lines.append("")

    # Detailed table
    lines.append("## 2. Matriz Detallada (`OK` / `DIFIERE` / `FALTA`)")
    lines.append("")
    lines.append("| Categoría | Artefacto / Regla | Estado | Pts | Diagnóstico |")
    lines.append("| :--- | :--- | :---: | :---: | :--- |")
    for item in report.items:
        pts_label = f"{item.points:.1f}/{item.max_points:.1f}" if item.max_points > 0 else "Bonus"
        lines.append(
            f"| {item.category} | `{item.artifact}` | **{item.status}** | {pts_label} | {item.diagnosis} |"
        )
    lines.append("")

    # Roadmap
    actionable = [i for i in report.items if i.status in ("DIFIERE", "FALTA") and i.remediation]
    lines.append("## 3. Hoja de Ruta de Ajustes (Roadmap No-Destructivo)")
    lines.append("")
    if not actionable:
        lines.append(
            "🎉 **¡El proyecto cumple al 100% con el estándar obligatorio del profesor Jan Polanco!** No se requieren ajustes adicionales."
        )
    else:
        phase_titles = {
            1: "Fase 1 — Quick Wins: Empaquetado, Metadatos y Documentación Base",
            2: "Fase 2 — Tooling, `Makefile`, Pre-commit y CI",
            3: "Fase 3 — Gobernanza de GitHub (`.github/`)",
            4: "Fase 4 — Contexto de Agentes IA (`tgrep`) y Pulido Visual",
        }
        for phase_num in (1, 2, 3, 4):
            phase_items = [i for i in actionable if i.phase == phase_num]
            if not phase_items:
                continue
            lines.append(f"### {phase_titles[phase_num]}")
            lines.append("")
            for idx, item in enumerate(phase_items, 1):
                lines.append(
                    f"{idx}. **`{item.artifact}` (`{item.status}`)**: {item.remediation}"
                )
            lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evalúa un proyecto contra el estándar de ingeniería del profesor Jan Polanco."
    )
    parser.add_argument(
        "project_path",
        nargs="?",
        default=".",
        help="Ruta a la raíz del proyecto a auditar (default: directorio actual).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime el resultado en formato JSON.",
    )
    parser.add_argument(
        "--markdown-out",
        type=str,
        default="",
        help="Ruta opcional donde guardar el reporte en formato Markdown.",
    )
    args = parser.parse_args()

    target = Path(args.project_path).resolve()
    if not target.is_dir():
        print(f"Error: '{target}' no es un directorio válido.", file=sys.stderr)
        return 2

    report = evaluate_project(target)

    if args.markdown_out:
        out_path = Path(args.markdown_out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(format_markdown_report(report), encoding="utf-8")

    if args.json:
        payload = asdict(report)
        payload["percentage"] = report.percentage
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        print(format_markdown_report(report))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
