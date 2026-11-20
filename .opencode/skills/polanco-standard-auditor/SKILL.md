---
name: polanco-standard-auditor
description: Evaluates any Python/AI repository against Professor Jan Polanco's engineering standard (jan-project-standard), calculates a weighted compliance score across his 10 non-negotiable rules, diagnoses OK/DIFIERE/FALTA artifacts, and generates a prioritized, non-destructive roadmap of adjustments. Use whenever asked to audit, compare, standardize, or align a project with Professor Polanco's standard.
---

# Polanco Standard Auditor (`polanco-standard-auditor`)

This skill clones Professor Jan Polanco's engineering standard ([`hamsomp3/jan_skills_repository`](https://github.com/hamsomp3/jan_skills_repository) / `jan-project-standard`) into an automated **Project Evaluator & Roadmap Generator**.

Use this skill to:
1. Measure how closely an existing repository adheres to Professor Polanco's canonical Python + AI engineering standard.
2. Identify every artifact and rule that is **`OK`**, **`DIFIERE`** (present but missing canonical settings/sections), or **`FALTA`** (missing).
3. Produce a **prioritized, non-destructive adjustment roadmap** that brings the project to 100% compliance while respecting Professor Polanco's golden rule for existing projects:
   > *"En un proyecto existente, nunca sobrescribas a ciegas; conserva lo propio y fusiona."*

---

## Professor Polanco's 10 Non-Negotiable Rules

Every audited project is evaluated against these 10 core principles:

1. **Exclusive `uv` Package Management**: `pyproject.toml` + tracked `uv.lock`. `pip`, `requirements.txt`, `setup.py`, `Pipfile`, and `poetry.lock` are strictly forbidden.
2. **Modern Python + Astral Quality Stack**: `.python-version` (default `3.13`), **Ruff** (`line-length = 100`, double quotes, rules `E, F, I, UP, B, SIM, C4, RUF` + isort `known-first-party`), **`ty`** (static type checker + `py.typed` marker in `src/<pkg>/`), and **`pytest`** (AAA pattern, strict markers/config).
3. **Pre-commit Hygiene & Lockfile Sync**: `.pre-commit-config.yaml` with `pre-commit-hooks`, `ruff-pre-commit` (`ruff` + `ruff-format`), and `uv-pre-commit` (`uv-lock`).
4. **Canonical `Makefile` Entrypoint**: Standard targets (`help`, `install`, `dev`, `pre-commit-install`, `lint`, `format`, `typecheck`, `test`, `check`, `build`, and a **safe** `clean` that only removes build/tool caches and never deletes domain data).
5. **`CONSTITUTION.md` as Single Source of Truth**: Contains all 12 canonical sections (§1 Purpose to §12 Amendment Governance) with zero unresolved template placeholders (`{{...}}`, `<!-- TODO -->`) and at least `docs/adr/0001-*.md`.
6. **Clean Repository Hygiene**: Tracked `.gitignore`, `.editorconfig`, `LICENSE` (MIT), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `docs/README.md`, and structured `README.md` with badges and Table of Contents.
7. **GitHub Governance (`.github/`)**:
   - `.github/workflows/ci.yml` running `uv sync --all-groups`, `pre-commit run --all-files`, `ty check`, and `pytest` with `concurrency` cancellation.
   - Declarative labels in `.github/labels.yml` synced via `.github/workflows/labels.yml`.
   - YAML Issue Forms in `.github/ISSUE_TEMPLATE/` (`bug_report.yml`, `feature_request.yml`, `spike.yml`, `config.yml`).
   - Comprehensive `.github/pull_request_template.md` (or `PULL_REQUEST_TEMPLATE.md`) with Conventional Commits table, test matrix, `CONSTITUTION.md` check, and Squash & Merge checklist.
8. **AI Agent Context (`AGENTS.md` + `CLAUDE.md` + `tgrep`)**:
   - `AGENTS.md` pointing to `CONSTITUTION.md`, daily workflow, `make` commands, and `tgrep` usage.
   - `CLAUDE.md` containing `@AGENTS.md`.
   - `.opencode/rules/tgrep.md` tracked in Git, while `.tgrep/` is ignored in `.gitignore`.
9. **Git & Conventional Commits Discipline**: Commits follow `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`; SSH remote preferred (`git@github.com:<owner>/<repo>.git`).
10. **Visual Architecture (Optional Showcase)**: Interactive self-contained architecture map in `docs/arquitectura.json` + `docs/arquitectura.html` (generated via `Archify`).

---

## Step-by-Step Evaluation Workflow

> **Note:** All paths below (`scripts/...`, `references/...`) are relative to this skill's directory (`<SKILL_DIR>`).

### Step 1 — Run the Semantic Evaluator Script

Execute the bundled Python 3.11+ evaluator against the target repository root:

```bash
python "<SKILL_DIR>/scripts/evaluate_polanco_standard.py" "<PROJECT_PATH>"
```

- Pass `--json` if you need machine-readable JSON output.
- Pass `--markdown-out <FILE_PATH>` to save the full diagnostic report and roadmap directly to a file.

### Step 2 — Inspect Domain Customizations

Before recommending edits to any file marked **`DIFIERE`**, inspect the project's existing domain logic:
- **`Makefile`**: Identify custom domain targets (e.g., `pipeline`, `capture`, `etl`, `chunk`, `evaluate`, `stats`). Never delete them; merge Professor Polanco's canonical targets alongside them, and ensure `make clean` only removes Python/tool caches.
- **`CONSTITUTION.md` & `AGENTS.md`**: Preserve all project-specific architecture diagrams, domain constraints, and ADRs while adding any missing canonical sections (such as §12 in `CONSTITUTION.md` or the `tgrep` section in `AGENTS.md`).
- **`pyproject.toml`**: Keep all project dependencies and CLI `[project.scripts]` entrypoints while adding missing metadata (`license-files`, `classifiers`, `[project.urls]`, Ruff `"C4"` and `[tool.ruff.lint.isort]`).

### Step 3 — Present the Audit & 4-Phase Roadmap

Structure your findings for the user in three parts:
1. **Executive Scorecard**: Overall score `/ 100` and category breakdown across the 6 pillars.
2. **Comparison Matrix (`OK` / `DIFIERE` / `FALTA`)**: Clear table explaining *why* each item differs from Professor Polanco's standard.
3. **Prioritized Adjustment Roadmap**:
   - **Phase 1 — Quick Wins (Package & Metadata Parity)**: `py.typed`, `pyproject.toml`, `.editorconfig`, `CONSTITUTION.md` (§1–§12), `docs/README.md`.
   - **Phase 2 — Tooling, `Makefile` & Pre-Commit Parity**: Non-destructive `Makefile` merge, `.pre-commit-config.yaml` (`uv-lock`), and `.github/workflows/ci.yml`.
   - **Phase 3 — GitHub Governance Parity**: `.github/labels.yml`, `.github/workflows/labels.yml`, YAML Issue Forms (`bug_report.yml`, `feature_request.yml`, `spike.yml`, `config.yml`), and PR template.
   - **Phase 4 — Agent Context & Showcase Polish**: `CLAUDE.md`, `.opencode/rules/tgrep.md`, `AGENTS.md` `tgrep` section, `README.md` badges/TOC, and optional `Archify` diagram (`docs/arquitectura.html`).

### Step 4 — Apply Adjustments & Verify (When Requested)

When the user asks to apply the roadmap:
1. Use the canonical templates in [`references/canonical_snippets.md`](./references/canonical_snippets.md) and [`references/polanco_10_rules_and_rubric.md`](./references/polanco_10_rules_and_rubric.md).
2. Re-run `evaluate_polanco_standard.py` to confirm the compliance score reaches **95–100 / 100**.
3. Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, and `uv run pytest` to verify zero regressions.
