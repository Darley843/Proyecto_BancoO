# Canonical Snippets (`jan-project-standard`)

Use these exact snippets from Professor Jan Polanco's `jan-project-standard` when remediating `DIFIERE` or `FALTA` items. Always **merge non-destructively** with existing project logic.

---

## 1. `.editorconfig`

```ini
# https://editorconfig.org
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4

[*.{yml,yaml,json,toml}]
indent_size = 2

[*.{md,markdown}]
trim_trailing_whitespace = false

[Makefile]
indent_style = tab
```

---

## 2. `.pre-commit-config.yaml`

```yaml
# https://pre-commit.com
# Instalación: uv run pre-commit install  (o: make dev)
# Ejecución manual: uv run pre-commit run --all-files

default_language_version:
  python: python3.13

minimum_pre_commit_version: "3.7.0"
fail_fast: false

repos:
  # --- Higiene general del repositorio ---
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: check-added-large-files
        args: ["--maxkb=2048"]
      - id: check-case-conflict
      - id: check-merge-conflict
      - id: check-json
      - id: check-toml
      - id: check-yaml
        args: ["--allow-multiple-documents"]
      - id: end-of-file-fixer
      - id: trailing-whitespace
        args: ["--markdown-linebreak-ext=md"]
      - id: mixed-line-ending
      - id: detect-private-key

  # --- Ruff: lint + formato (Astral) ---
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.11.0
    hooks:
      - id: ruff
        args: ["--fix", "--exit-non-zero-on-fix"]
      - id: ruff-format

  # --- uv: mantiene uv.lock sincronizado (Astral) ---
  - repo: https://github.com/astral-sh/uv-pre-commit
    rev: 0.6.6
    hooks:
      - id: uv-lock
```

---

## 3. `pyproject.toml` Additions

Ensure `[project]` includes `license-files`, `classifiers`, and `[project.urls]`, and `[tool.ruff.lint]` includes `"C4"` and `[tool.ruff.lint.isort]`:

```toml
license = { text = "MIT" }
license-files = ["LICENSE"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.13",
    "Typing :: Typed",
]

[project.urls]
Homepage = "https://github.com/<owner>/<repo>"
Repository = "https://github.com/<owner>/<repo>.git"
Issues = "https://github.com/<owner>/<repo>/issues"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle (errores)
    "F",   # pyflakes
    "I",   # isort (orden de imports)
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "SIM", # flake8-simplify
    "C4",  # flake8-comprehensions
    "RUF", # reglas propias de Ruff
]
ignore = []

[tool.ruff.lint.isort]
known-first-party = ["<package_name>"]
```

---

## 4. `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  quality:
    name: Calidad
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Instalar uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
          cache-dependency-glob: uv.lock

      - name: Sincronizar entorno
        run: uv sync --all-groups

      - name: Pre-commit (higiene + Ruff + uv-lock)
        run: uv run pre-commit run --all-files --show-diff-on-failure

      - name: Verificación de tipos (ty)
        run: uv run ty check

      - name: Pruebas
        run: uv run pytest
```

---

## 5. `.github/workflows/labels.yml` & `.github/labels.yml`

`.github/workflows/labels.yml`:
```yaml
name: Labels

on:
  push:
    branches: [main]
    paths:
      - .github/labels.yml
      - .github/workflows/labels.yml
  workflow_dispatch:

permissions:
  contents: read
  issues: write

jobs:
  labeler:
    name: Sync labels
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Apply labels
        uses: crazy-max/ghaction-github-labeler@v5
        with:
          yaml: .github/labels.yml
          skip-delete: true
```

---

## 6. `.opencode/rules/tgrep.md`

```markdown
# OpenCode Rule: tgrep

Esta regla configura al agente de OpenCode para usar `tgrep` (Microsoft Trigram-indexed
Grep) en búsquedas rápidas de regex y símbolos sobre el código.

## Directrices para el agente

1. **Usa `tgrep` en lugar de `grep` o `find`** cuando esté disponible:
   - `tgrep` usa un índice de trigramas precalculado (`.tgrep/`) que permite búsquedas
     instantáneas.
2. **Reglas de ejecución**:
   - Coloca siempre `--` antes del patrón para evitar ambigüedades de parseo:
     ```bash
     tgrep -- "patrón" .
     ```
   - Usa `-F` para símbolos o identificadores literales:
     ```bash
     tgrep -F -- "nombre_de_funcion" .
     ```
   - Filtra por extensión o directorio:
     ```bash
     tgrep -t py -- "class Modelo" .
     tgrep -g "src/**" -- "keyword" .
     ```
   - Lista solo los archivos coincidentes:
     ```bash
     tgrep -l -- "import torch" .
     ```
   - Reindexa tras modificar muchos archivos si el daemon no está corriendo:
     ```bash
     tgrep index .
     ```
   - Daemon en segundo plano:
     ```bash
     tgrep serve . &
     ```
3. **Fallback:** si `tgrep` no está instalado, usa `grep`/`rg` de forma normal.
```
