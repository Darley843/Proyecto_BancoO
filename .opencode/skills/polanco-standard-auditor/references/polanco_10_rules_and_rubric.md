# Professor Jan Polanco's 10 Non-Negotiable Rules & Scoring Rubric

Source of truth: [`hamsomp3/jan_skills_repository`](https://github.com/hamsomp3/jan_skills_repository) (`skills/jan-project-standard`).

## 1. Scoring Categories (100 Points Total + Showcase Bonus)

| Category | Max Points | Key Checks |
| :--- | :---: | :--- |
| **1. Python & `uv` Stack** | **20** | `.python-version`, `uv.lock`, no `requirements.txt`/`setup.py`, `src/<pkg>/py.typed`, `pyproject.toml` (`uv_build`, `license-files`, `classifiers`, `[project.urls]`, `ruff` with `C4` & `isort`, `ty`, `pytest`) |
| **2. Quality Gates & Automation** | **20** | `Makefile` (`help`, `install`, `dev`, `pre-commit-install`, `lint`, `format`, `typecheck`, `test`, `check`, `build`, safe `clean`), `.pre-commit-config.yaml` (`pre-commit-hooks`, `ruff-pre-commit`, `uv-pre-commit` `uv-lock`), `.editorconfig` |
| **3. Constitution & Documentation** | **20** | `CONSTITUTION.md` (12 sections §1–§12, zero `{{...}}` placeholders), `docs/adr/0001-*.md`, `docs/README.md`, `README.md` (badges + TOC), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `LICENSE` |
| **4. GitHub Governance** | **20** | `.github/workflows/ci.yml` (`concurrency`, `uv sync --all-groups`, `pre-commit run --all-files`, `ty`, `pytest`), `.github/labels.yml` + `.github/workflows/labels.yml`, YAML Issue Forms (`bug_report.yml`, `feature_request.yml`, `spike.yml`, `config.yml`), PR Template |
| **5. AI Agent Context** | **10** | `AGENTS.md` (points to `CONSTITUTION.md` + `tgrep` section), `CLAUDE.md` (`@AGENTS.md`), `.opencode/rules/tgrep.md`, `.gitignore` ignores `.tgrep/` and allows `.opencode/rules/tgrep.md` |
| **6. Git & Workflow Discipline** | **10** | Conventional Commits in `git log`, Git remote configured, clean tracked files |
| **Bonus: Archify Visual Map** | **+5 (Showcase)** | `docs/arquitectura.json` + `docs/arquitectura.html` |

---

## 2. The 12 Required Sections of `CONSTITUTION.md`

Professor Polanco requires `CONSTITUTION.md` to act as the single technical source of truth with these 12 sections:

1. `## 1. Propósito, alcance y criterios de éxito` (1.1 Problema, 1.2 Alcance / No-alcance, 1.3 Criterios de éxito / métricas)
2. `## 2. Stack tecnológico`
3. `## 3. Arquitectura del sistema` (Diagrama de componentes + Flujo de datos + Modelo de datos)
4. `## 4. Estructura del repositorio`
5. `## 5. Convenciones de código`
6. `## 6. Gestión de dependencias y entorno`
7. `## 7. Estrategia de pruebas y calidad`
8. `## 8. Flujo de Git y gobierno de ramas`
9. `## 9. Seguridad, datos y cumplimiento`
10. `## 10. Operaciones y observabilidad`
11. `## 11. Historial de decisiones (ADR)`
12. `## 12. Gobierno de este documento`
