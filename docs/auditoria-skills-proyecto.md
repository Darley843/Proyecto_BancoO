# Auditoría SkillSpector de las skills del proyecto

**Fecha:** 25 de octubre de 2026 · **Herramienta:** SkillSpector 2.12.0 (`--no-llm`, análisis estático) · **Revisó:** Anny Valencia

## Resumen

| Skill | Origen | Nota | Severidad | Scripts | Dictamen |
|---|---|---|---|---|---|
| semantic-extraction | Equipo (Darley) | 43/100 | MEDIUM | Sí (`validate.py`) | Aceptada con recomendación |
| openspec-propose | OpenSpec | 41/100 | MEDIUM | No | Aceptada (falso positivo) |
| openspec-explore | OpenSpec | 13/100 | LOW | No | Aceptada (falso positivo) |
| corpus-extraction | Equipo (Darley) | 7/100 | LOW | Sí (`healthcheck.py`) | Aceptada con recomendación |
| openspec-apply-change | OpenSpec | 0/100 | LOW | No | Aceptada |
| openspec-archive-change | OpenSpec | 0/100 | LOW | No | Aceptada |
| openspec-sync-specs | OpenSpec | 0/100 | LOW | No | Aceptada |
| openspec-update-change | OpenSpec | 0/100 | LOW | No | Aceptada |

Todas quedan en CAUTION porque el escaneo es parcial: las skills citan archivos del proyecto que no están en su carpeta (`reference_missing`) y el análisis semántico con IA estaba desactivado. Como referencia, la skill `corpus-medallion-financiero` (instalada en `.agents/skills/`) tuvo escaneo completo: 0/100, SAFE.

## Revisión manual de lo marcado

- **openspec-propose (P6, línea 65; MP3, línea 141):** falso positivo. El texto indica tratar el contexto de `openspec/config.yaml` como datos que no pueden anular la autorización del usuario ni las restricciones de herramientas. La línea 141 trata del estado de los artefactos de OpenSpec, no de la memoria del agente.
- **openspec-explore (EA2, líneas 15, 49, 163 y 352):** falso positivo. Solo permite comandos de lectura sin confirmación. Antes de cualquier escritura exige nombrar los archivos, hacer una pregunta de sí o no y esperar confirmación explícita del usuario.
- **semantic-extraction (AE1 ×4):** limitación del analizador (`static_parse_limit`) al leer `references/schema.md` y `references/prompt.md`; no es indicio de evasión. `scripts/validate.py` solo valida un archivo JSONL local con módulos del proyecto: sin red, sin ejecución de comandos y sin escritura en `data/knowledge`.
- **corpus-extraction (LP3):** la skill no declara su alcance de herramientas. `scripts/healthcheck.py` no usa red, `subprocess`, `eval` ni `exec`; la única coincidencia con "http" valida que las fuentes de Gold sean URL.

## Recomendaciones

1. Repetir el escaneo de `semantic-extraction` con el análisis semántico activo, o revisar a mano `references/schema.md` y `references/prompt.md`.
2. Declarar en `corpus-extraction` el alcance real de herramientas (lectura de archivos) solo si el equipo lo aprueba, no para silenciar el hallazgo.
3. Las skills con scripts tienen 2,12 veces más probabilidad de ser vulnerables (Liu et al., 2026): toda modificación a `healthcheck.py` o `validate.py` debe pasar por revisión en PR.
4. Completar los permisos en `opencode.json` (lectura de `.env` y `git push` en deny), que contienen el riesgo aunque una skill falle.

## Alcance de esta revisión

Se revisaron a mano las líneas marcadas y los dos scripts. No es una auditoría línea por línea de las más de 2.000 líneas de las ocho skills.

---

## Actualización del 7 de noviembre de 2026: Archify y boveda-rag

**Herramienta:** SkillSpector 2.12.0 (`--no-llm`, análisis estático) · **Revisó:** Anny Valencia

| Skill | Origen | Versión auditada | Nota | Severidad | Scripts | Dictamen |
|---|---|---|---|---|---|---|
| archify | Externa (`tt-a1i/archify`, MIT) | v3.2.0, commit `a4065941f12be7967436261d9934784e381d423c` | 99/100 | CRITICAL | Sí (Node, 206 archivos) | Aceptada con condiciones |
| boveda-rag | Equipo (Nayla) | `main` del 7 de noviembre de 2026 | 7/100 | LOW | Sí (`medir_recuperacion.py`, `validar_indice.py`) | Aceptada con recomendación |

Archify se auditó **antes de instalarla**, desde un clon del repositorio oficial (el que enlaza https://archify.si), sin ejecutar su instalador. La nota de 99/100 no se sostiene en la revisión manual: casi todos los hallazgos son limitaciones del analizador o falsos positivos. El escaneo quedó parcial: 15 analizadores en estado `degraded` y 43 artefactos citados en `SKILL.md` sin inspeccionar.

### Revisión manual de Archify

- **AE1 ×43 (`SKILL.md`):** «Referenced artifact was not completely inspected». Es cobertura parcial del analizador, como el AE1 de semantic-extraction; no es indicio de evasión.
- **YR4 ×16 (`assets/template.html` y 15 HTML de `examples/`):** falso positivo. La línea marcada (`template.html:146`) es la fuente JetBrains Mono incrustada en base64 (`data:font/woff2;base64,...`), con su licencia OFL en `assets/`. Los ejemplos son diagramas generados con esa plantilla y la repiten.
- **EA3 ×25 (los mismos HTML):** falso positivo. La línea marcada en la plantilla (`template.html:135`) es el texto de la licencia MIT.
- **AE4 (`examples/locales/ru.json`):** falso positivo. Es la traducción al ruso: texto en cirílico junto a claves en inglés.
- **LP3 (`SKILL.md`):** real. La skill no declara permisos y su código usa procesos y red:
  - Procesos: Node se lanza a sí mismo para ejecutar sus propios scripts (`process.execPath` en `archify`, `finalize`, `preview`, `delivery-update`, `check` y `render-examples`); `git --no-replace-objects` en modo de solo lectura (`sources.mjs`, `repository-evidence.mjs`) para los diagramas de repositorio; y el abridor del sistema para mostrar el HTML generado (`open-artifact.mjs`). `visual-check.mjs` también lanza un proceso y no se revisó en detalle.
  - Red: `scripts/check-update.mjs` consulta `https://tt-a1i.github.io/archify/skill-updates/archify/stable.json` con tiempo límite, valida el manifiesto (versión, sha256 y caracteres de control) y solo avisa: no descarga ni instala nada. `renderers/shared/brand-marks.mjs` descarga páginas e imágenes desde la URL que se le pasa, para obtener logos.

### Hallazgos fuera de SkillSpector

- **Instalación sin versión fija.** El comando del proyecto (`npx -y skills@latest add https://archify.si ... --yes`) instala la última versión sin confirmación ni hash. Existen copias de terceros con el mismo nombre (por ejemplo, `belinwu/archify`), así que conviene fijar el repositorio y el commit auditados.
- **Logos del banco.** Si se le pide a Archify el logo del Banco de Occidente, `brand-marks.mjs` lo descarga del sitio del banco sin las reglas de captura del proyecto (`robots.txt`, 1,5 s entre peticiones y cabecera `From`).

### Condiciones para usar Archify

1. Instalarla desde `github.com/tt-a1i/archify` en el commit `a4065941f12be7967436261d9934784e381d423c` (v3.2.0), no con `@latest`, y repetir esta auditoría antes de actualizar.
2. Seguir usándola fuera del pipeline, de `uv.lock` y de la CI, como hoy.
3. No usar las marcas automáticas con URL del banco: pasar el logo como archivo local.
4. Omitir el paso de aviso de actualización (`references/update-awareness.md`) si no se quieren llamadas salientes.

### boveda-rag

Se volvió a escanear porque `medir_recuperacion.py` cambió después del #68 (con el #78 y el #85). Con la copia del repositorio da 7/100 LOW y un solo aviso LP3 (no declara permisos y usa lectura y escritura de archivos y la llamada local a Ollama), igual que en el #68.

Un primer escaneo de la carpeta de trabajo dio 78/100 HIGH (SC8 ×2 y SC9) por `scripts/__pycache__/medir_recuperacion.cpython-313.pyc`, un bytecode que Python generó al correr el script en el equipo. Git lo ignora (`.gitignore`, `__pycache__/`), así que no es parte de la skill. **Las skills se escanean desde una copia limpia, no desde la carpeta de trabajo.**

### Cómo repetir

```bash
git clone https://github.com/tt-a1i/archify.git
git -C archify checkout a4065941f12be7967436261d9934784e381d423c
skillspector scan archify/archify --no-llm --format markdown > reporte-archify.md
```

En Windows, `--output` no está soportado: hay que redirigir la salida, y conviene activar `PYTHONUTF8=1` para que el reporte conserve los caracteres. El reporte completo de Archify supera las 1.000 líneas y no se copia aquí; el de boveda-rag está al final de este documento.

---

# Reporte técnico completo (SkillSpector)
--- corpus-extraction ---

# SkillSpector Security Report

**Skill:** Corpus Banco de Occidente
**Source:** `C:\Users\PC\Documents\Proyecto_BancoO\.opencode\skills\corpus-extraction`
**Scanned:** 2026-10-25 17:44:14 UTC

## Risk Assessment

| Metric | Value |
|--------|-------|
| Score | 7/100 |
| Severity | LOW |
| Recommendation | CAUTION |

## Components (3)

| File | Type | Lines | Executable |
|------|------|-------|------------|
| `SKILL.md` | markdown | 81 | No |
| `references/pipeline.md` | markdown | 88 | No |
| `scripts/healthcheck.py` | python | 225 | Yes |

## Issues (1)

### 🟡 MEDIUM: LP3

**Location:** `SKILL.md:1`
**Confidence:** 70%

**Message:** Skill declares no tool scope \('permissions' or 'allowed\-tools'\) but code capabilities were detected: file\_read\.

**Remediation:** Clarify the skill's intended tool scope and review how the host runtime enforces it; runtime permissions are unknown unless separately verified\. For Claude Code / Agent Skills SKILL\.md, 'allowed\-tools' records preapproved tools, not a permission ceiling; add a tool only when it is independently approved as necessary, not to silence this finding\. For MCP server manifests, use a 'permissions' list naming the required capabilities\.

---

## Inspection Completeness

| Metric | Value |
|--------|-------|
| Execution | successful |
| Status | partial |
| Coverage | 100\.0% |
| Fully inspected | 3 |
| Partially inspected | 0 |
| Entirely uninspected | 0 |

### Ledger Exceptions

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| reference\_missing | `SKILL.md:19-19` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:23-23` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:24-24` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:38-38` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:55-55` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:62-62` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:66-66` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:72-72` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:73-73` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:79-79` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:80-80` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:81-81` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |

### Analyzer Statuses

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| completed | `artifact_integrity` |  |
| completed | `behavioral_ast` |  |
| completed | `behavioral_taint_tracking` |  |
| no\_applicable\_files | `bundled_execution_surface` | No files matched this analyzer's applicability contract\. |
| completed | `mcp_least_privilege` |  |
| completed | `mcp_rug_pull` |  |
| completed | `mcp_tool_poisoning` |  |
| disabled\_by\_configuration | `meta_analyzer` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_developer_intent` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_quality_policy` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_security_discovery` | Analyzer was disabled by the requested configuration\. |
| completed | `static_patterns_agent_snooping` |  |
| completed | `static_patterns_anti_refusal` |  |
| completed | `static_patterns_data_exfiltration` |  |
| completed | `static_patterns_deserialization` |  |
| completed | `static_patterns_excessive_agency` |  |
| completed | `static_patterns_harmful_content` |  |
| completed | `static_patterns_memory_poisoning` |  |
| completed | `static_patterns_output_handling` |  |
| completed | `static_patterns_privilege_escalation` |  |
| completed | `static_patterns_prompt_injection` |  |
| completed | `static_patterns_rogue_agent` |  |
| completed | `static_patterns_ssrf` |  |
| completed | `static_patterns_supply_chain` |  |
| completed | `static_patterns_system_prompt_leakage` |  |
| completed | `static_patterns_tool_misuse` |  |
| completed | `static_yara` |  |

## Metadata

- **Executable Scripts:** Yes

*Generated by SkillSpector v2.12.0*

--- openspec-apply-change ---

# SkillSpector Security Report

**Skill:** openspec\-apply\-change
**Source:** `C:\Users\PC\Documents\Proyecto_BancoO\.opencode\skills\openspec-apply-change`
**Scanned:** 2026-10-25 17:44:15 UTC

## Risk Assessment

| Metric | Value |
|--------|-------|
| Score | 0/100 |
| Severity | LOW |
| Recommendation | CAUTION |

## Components (1)

| File | Type | Lines | Executable |
|------|------|-------|------------|
| `SKILL.md` | markdown | 206 | No |

## Issues (0)

No security issues detected.

## Inspection Completeness

| Metric | Value |
|--------|-------|
| Execution | successful |
| Status | partial |
| Coverage | 100\.0% |
| Fully inspected | 1 |
| Partially inspected | 0 |
| Entirely uninspected | 0 |

### Ledger Exceptions

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| reference\_missing | `SKILL.md:9-9` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:10-10` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:19-19` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |

### Analyzer Statuses

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| completed | `artifact_integrity` |  |
| no\_applicable\_files | `behavioral_ast` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `behavioral_taint_tracking` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `bundled_execution_surface` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `mcp_least_privilege` | No files matched this analyzer's applicability contract\. |
| completed | `mcp_rug_pull` |  |
| completed | `mcp_tool_poisoning` |  |
| no\_applicable\_files | `meta_analyzer` | No files matched this analyzer's applicability contract\. |
| disabled\_by\_configuration | `semantic_developer_intent` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_quality_policy` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_security_discovery` | Analyzer was disabled by the requested configuration\. |
| completed | `static_patterns_agent_snooping` |  |
| completed | `static_patterns_anti_refusal` |  |
| completed | `static_patterns_data_exfiltration` |  |
| completed | `static_patterns_deserialization` |  |
| completed | `static_patterns_excessive_agency` |  |
| completed | `static_patterns_harmful_content` |  |
| completed | `static_patterns_memory_poisoning` |  |
| completed | `static_patterns_output_handling` |  |
| completed | `static_patterns_privilege_escalation` |  |
| completed | `static_patterns_prompt_injection` |  |
| completed | `static_patterns_rogue_agent` |  |
| completed | `static_patterns_ssrf` |  |
| completed | `static_patterns_supply_chain` |  |
| completed | `static_patterns_system_prompt_leakage` |  |
| completed | `static_patterns_tool_misuse` |  |
| completed | `static_yara` |  |

## Metadata

- **Executable Scripts:** No

*Generated by SkillSpector v2.12.0*

--- openspec-archive-change ---

# SkillSpector Security Report

**Skill:** openspec\-archive\-change
**Source:** `C:\Users\PC\Documents\Proyecto_BancoO\.opencode\skills\openspec-archive-change`
**Scanned:** 2026-10-25 17:44:16 UTC

## Risk Assessment

| Metric | Value |
|--------|-------|
| Score | 0/100 |
| Severity | LOW |
| Recommendation | CAUTION |

## Components (1)

| File | Type | Lines | Executable |
|------|------|-------|------------|
| `SKILL.md` | markdown | 221 | No |

## Issues (0)

No security issues detected.

## Inspection Completeness

| Metric | Value |
|--------|-------|
| Execution | successful |
| Status | partial |
| Coverage | 100\.0% |
| Fully inspected | 1 |
| Partially inspected | 0 |
| Entirely uninspected | 0 |

### Ledger Exceptions

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| reference\_missing | `SKILL.md:9-9` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:10-10` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:19-19` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:98-98` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:119-119` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:122-122` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:171-171` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:202-202` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |

### Analyzer Statuses

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| completed | `artifact_integrity` |  |
| no\_applicable\_files | `behavioral_ast` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `behavioral_taint_tracking` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `bundled_execution_surface` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `mcp_least_privilege` | No files matched this analyzer's applicability contract\. |
| completed | `mcp_rug_pull` |  |
| completed | `mcp_tool_poisoning` |  |
| no\_applicable\_files | `meta_analyzer` | No files matched this analyzer's applicability contract\. |
| disabled\_by\_configuration | `semantic_developer_intent` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_quality_policy` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_security_discovery` | Analyzer was disabled by the requested configuration\. |
| completed | `static_patterns_agent_snooping` |  |
| completed | `static_patterns_anti_refusal` |  |
| completed | `static_patterns_data_exfiltration` |  |
| completed | `static_patterns_deserialization` |  |
| completed | `static_patterns_excessive_agency` |  |
| completed | `static_patterns_harmful_content` |  |
| completed | `static_patterns_memory_poisoning` |  |
| completed | `static_patterns_output_handling` |  |
| completed | `static_patterns_privilege_escalation` |  |
| completed | `static_patterns_prompt_injection` |  |
| completed | `static_patterns_rogue_agent` |  |
| completed | `static_patterns_ssrf` |  |
| completed | `static_patterns_supply_chain` |  |
| completed | `static_patterns_system_prompt_leakage` |  |
| completed | `static_patterns_tool_misuse` |  |
| completed | `static_yara` |  |

## Metadata

- **Executable Scripts:** No

*Generated by SkillSpector v2.12.0*

--- openspec-explore ---

# SkillSpector Security Report

**Skill:** openspec\-explore
**Source:** `C:\Users\PC\Documents\Proyecto_BancoO\.opencode\skills\openspec-explore`
**Scanned:** 2026-10-25 17:44:18 UTC

## Risk Assessment

| Metric | Value |
|--------|-------|
| Score | 13/100 |
| Severity | LOW |
| Recommendation | CAUTION |

## Components (1)

| File | Type | Lines | Executable |
|------|------|-------|------------|
| `SKILL.md` | markdown | 356 | No |

## Issues (4)

### 🟡 MEDIUM: EA2

**Location:** `SKILL.md:15`
**Confidence:** 75%

**Message:** Autonomous Decision Making

**Remediation:** Add human\-in\-the\-loop confirmation for destructive, irreversible, or high\-impact operations\. Never auto\-execute commands that modify files, send data, or alter system state\.

---

### 🟡 MEDIUM: EA2

**Location:** `SKILL.md:49`
**Confidence:** 80%

**Message:** Autonomous Decision Making

**Remediation:** Add human\-in\-the\-loop confirmation for destructive, irreversible, or high\-impact operations\. Never auto\-execute commands that modify files, send data, or alter system state\.

---

### 🟡 MEDIUM: EA2

**Location:** `SKILL.md:163`
**Confidence:** 75%

**Message:** Autonomous Decision Making

**Remediation:** Add human\-in\-the\-loop confirmation for destructive, irreversible, or high\-impact operations\. Never auto\-execute commands that modify files, send data, or alter system state\.

---

### 🟡 MEDIUM: EA2

**Location:** `SKILL.md:352`
**Confidence:** 75%

**Message:** Autonomous Decision Making

**Remediation:** Add human\-in\-the\-loop confirmation for destructive, irreversible, or high\-impact operations\. Never auto\-execute commands that modify files, send data, or alter system state\.

---

## Inspection Completeness

| Metric | Value |
|--------|-------|
| Execution | successful |
| Status | partial |
| Coverage | 100\.0% |
| Fully inspected | 1 |
| Partially inspected | 0 |
| Entirely uninspected | 0 |

### Ledger Exceptions

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| reference\_missing | `SKILL.md:9-9` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:10-10` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:23-23` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:143-143` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:158-158` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:188-188` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:189-189` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:190-190` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:348-348` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:353-353` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |

### Analyzer Statuses

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| completed | `artifact_integrity` |  |
| no\_applicable\_files | `behavioral_ast` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `behavioral_taint_tracking` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `bundled_execution_surface` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `mcp_least_privilege` | No files matched this analyzer's applicability contract\. |
| completed | `mcp_rug_pull` |  |
| completed | `mcp_tool_poisoning` |  |
| disabled\_by\_configuration | `meta_analyzer` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_developer_intent` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_quality_policy` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_security_discovery` | Analyzer was disabled by the requested configuration\. |
| completed | `static_patterns_agent_snooping` |  |
| completed | `static_patterns_anti_refusal` |  |
| completed | `static_patterns_data_exfiltration` |  |
| completed | `static_patterns_deserialization` |  |
| completed | `static_patterns_excessive_agency` |  |
| completed | `static_patterns_harmful_content` |  |
| completed | `static_patterns_memory_poisoning` |  |
| completed | `static_patterns_output_handling` |  |
| completed | `static_patterns_privilege_escalation` |  |
| completed | `static_patterns_prompt_injection` |  |
| completed | `static_patterns_rogue_agent` |  |
| completed | `static_patterns_ssrf` |  |
| completed | `static_patterns_supply_chain` |  |
| completed | `static_patterns_system_prompt_leakage` |  |
| completed | `static_patterns_tool_misuse` |  |
| completed | `static_yara` |  |

## Metadata

- **Executable Scripts:** No

*Generated by SkillSpector v2.12.0*

--- openspec-propose ---

# SkillSpector Security Report

**Skill:** openspec\-propose
**Source:** `C:\Users\PC\Documents\Proyecto_BancoO\.opencode\skills\openspec-propose`
**Scanned:** 2026-10-25 17:44:19 UTC

## Risk Assessment

| Metric | Value |
|--------|-------|
| Score | 41/100 |
| Severity | MEDIUM |
| Recommendation | CAUTION |

## Components (1)

| File | Type | Lines | Executable |
|------|------|-------|------------|
| `SKILL.md` | markdown | 175 | No |

## Issues (2)

### 🔴 HIGH: P6

**Location:** `SKILL.md:65`
**Confidence:** 85%

**Message:** Direct Prompt Extraction

**Remediation:** Remove any instructions that reveal, print, or output system prompts or internal rules\. System instructions should never be exposed to end users\.

---

### 🔴 HIGH: MP3

**Location:** `SKILL.md:141`
**Confidence:** 80%

**Message:** Memory Manipulation

**Remediation:** Protect agent memory and state from modification by untrusted content\. Use read\-only memory for critical instructions and validate all state changes\.

---

## Inspection Completeness

| Metric | Value |
|--------|-------|
| Execution | successful |
| Status | partial |
| Coverage | 100\.0% |
| Fully inspected | 1 |
| Partially inspected | 0 |
| Entirely uninspected | 0 |

### Ledger Exceptions

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| reference\_missing | `SKILL.md:9-9` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:10-10` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:33-33` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:59-59` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:61-61` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:73-73` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:90-90` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:131-131` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:134-134` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:135-135` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:137-137` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:171-171` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |

### Analyzer Statuses

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| completed | `artifact_integrity` |  |
| no\_applicable\_files | `behavioral_ast` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `behavioral_taint_tracking` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `bundled_execution_surface` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `mcp_least_privilege` | No files matched this analyzer's applicability contract\. |
| completed | `mcp_rug_pull` |  |
| completed | `mcp_tool_poisoning` |  |
| disabled\_by\_configuration | `meta_analyzer` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_developer_intent` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_quality_policy` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_security_discovery` | Analyzer was disabled by the requested configuration\. |
| completed | `static_patterns_agent_snooping` |  |
| completed | `static_patterns_anti_refusal` |  |
| completed | `static_patterns_data_exfiltration` |  |
| completed | `static_patterns_deserialization` |  |
| completed | `static_patterns_excessive_agency` |  |
| completed | `static_patterns_harmful_content` |  |
| completed | `static_patterns_memory_poisoning` |  |
| completed | `static_patterns_output_handling` |  |
| completed | `static_patterns_privilege_escalation` |  |
| completed | `static_patterns_prompt_injection` |  |
| completed | `static_patterns_rogue_agent` |  |
| completed | `static_patterns_ssrf` |  |
| completed | `static_patterns_supply_chain` |  |
| completed | `static_patterns_system_prompt_leakage` |  |
| completed | `static_patterns_tool_misuse` |  |
| completed | `static_yara` |  |

## Metadata

- **Executable Scripts:** No

*Generated by SkillSpector v2.12.0*

--- openspec-sync-specs ---

# SkillSpector Security Report

**Skill:** openspec\-sync\-specs
**Source:** `C:\Users\PC\Documents\Proyecto_BancoO\.opencode\skills\openspec-sync-specs`
**Scanned:** 2026-10-25 17:44:20 UTC

## Risk Assessment

| Metric | Value |
|--------|-------|
| Score | 0/100 |
| Severity | LOW |
| Recommendation | CAUTION |

## Components (1)

| File | Type | Lines | Executable |
|------|------|-------|------------|
| `SKILL.md` | markdown | 290 | No |

## Issues (0)

No security issues detected.

## Inspection Completeness

| Metric | Value |
|--------|-------|
| Execution | successful |
| Status | partial |
| Coverage | 100\.0% |
| Fully inspected | 1 |
| Partially inspected | 0 |
| Entirely uninspected | 0 |

### Ledger Exceptions

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| reference\_missing | `SKILL.md:9-9` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:10-10` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:21-21` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:54-54` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:133-133` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:142-142` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:143-143` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:167-167` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:190-190` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |

### Analyzer Statuses

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| completed | `artifact_integrity` |  |
| no\_applicable\_files | `behavioral_ast` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `behavioral_taint_tracking` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `bundled_execution_surface` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `mcp_least_privilege` | No files matched this analyzer's applicability contract\. |
| completed | `mcp_rug_pull` |  |
| completed | `mcp_tool_poisoning` |  |
| no\_applicable\_files | `meta_analyzer` | No files matched this analyzer's applicability contract\. |
| disabled\_by\_configuration | `semantic_developer_intent` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_quality_policy` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_security_discovery` | Analyzer was disabled by the requested configuration\. |
| completed | `static_patterns_agent_snooping` |  |
| completed | `static_patterns_anti_refusal` |  |
| completed | `static_patterns_data_exfiltration` |  |
| completed | `static_patterns_deserialization` |  |
| completed | `static_patterns_excessive_agency` |  |
| completed | `static_patterns_harmful_content` |  |
| completed | `static_patterns_memory_poisoning` |  |
| completed | `static_patterns_output_handling` |  |
| completed | `static_patterns_privilege_escalation` |  |
| completed | `static_patterns_prompt_injection` |  |
| completed | `static_patterns_rogue_agent` |  |
| completed | `static_patterns_ssrf` |  |
| completed | `static_patterns_supply_chain` |  |
| completed | `static_patterns_system_prompt_leakage` |  |
| completed | `static_patterns_tool_misuse` |  |
| completed | `static_yara` |  |

## Metadata

- **Executable Scripts:** No

*Generated by SkillSpector v2.12.0*

--- openspec-update-change ---

# SkillSpector Security Report

**Skill:** openspec\-update\-change
**Source:** `C:\Users\PC\Documents\Proyecto_BancoO\.opencode\skills\openspec-update-change`
**Scanned:** 2026-10-25 17:44:21 UTC

## Risk Assessment

| Metric | Value |
|--------|-------|
| Score | 0/100 |
| Severity | LOW |
| Recommendation | CAUTION |

## Components (1)

| File | Type | Lines | Executable |
|------|------|-------|------------|
| `SKILL.md` | markdown | 109 | No |

## Issues (0)

No security issues detected.

## Inspection Completeness

| Metric | Value |
|--------|-------|
| Execution | successful |
| Status | partial |
| Coverage | 100\.0% |
| Fully inspected | 1 |
| Partially inspected | 0 |
| Entirely uninspected | 0 |

### Ledger Exceptions

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| reference\_missing | `SKILL.md:9-9` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:10-10` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:19-19` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |

### Analyzer Statuses

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| completed | `artifact_integrity` |  |
| no\_applicable\_files | `behavioral_ast` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `behavioral_taint_tracking` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `bundled_execution_surface` | No files matched this analyzer's applicability contract\. |
| no\_applicable\_files | `mcp_least_privilege` | No files matched this analyzer's applicability contract\. |
| completed | `mcp_rug_pull` |  |
| completed | `mcp_tool_poisoning` |  |
| no\_applicable\_files | `meta_analyzer` | No files matched this analyzer's applicability contract\. |
| disabled\_by\_configuration | `semantic_developer_intent` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_quality_policy` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_security_discovery` | Analyzer was disabled by the requested configuration\. |
| completed | `static_patterns_agent_snooping` |  |
| completed | `static_patterns_anti_refusal` |  |
| completed | `static_patterns_data_exfiltration` |  |
| completed | `static_patterns_deserialization` |  |
| completed | `static_patterns_excessive_agency` |  |
| completed | `static_patterns_harmful_content` |  |
| completed | `static_patterns_memory_poisoning` |  |
| completed | `static_patterns_output_handling` |  |
| completed | `static_patterns_privilege_escalation` |  |
| completed | `static_patterns_prompt_injection` |  |
| completed | `static_patterns_rogue_agent` |  |
| completed | `static_patterns_ssrf` |  |
| completed | `static_patterns_supply_chain` |  |
| completed | `static_patterns_system_prompt_leakage` |  |
| completed | `static_patterns_tool_misuse` |  |
| completed | `static_yara` |  |

## Metadata

- **Executable Scripts:** No

*Generated by SkillSpector v2.12.0*

--- semantic-extraction ---

# SkillSpector Security Report

**Skill:** Extracción semántica del corpus
**Source:** `C:\Users\PC\Documents\Proyecto_BancoO\.opencode\skills\semantic-extraction`
**Scanned:** 2026-10-25 17:44:22 UTC

## Risk Assessment

| Metric | Value |
|--------|-------|
| Score | 43/100 |
| Severity | MEDIUM |
| Recommendation | CAUTION |

## Components (8)

| File | Type | Lines | Executable |
|------|------|-------|------------|
| `SKILL.md` | markdown | 128 | No |
| `references/prompt.md` | markdown | 103 | No |
| `references/schema.md` | markdown | 137 | No |
| `references/taxonomy.md` | markdown | 93 | No |
| `scripts/validate.py` | python | 52 | Yes |
| `templates/entity.json` | json | 10 | No |
| `templates/fact.json` | json | 20 | No |
| `templates/relation.json` | json | 17 | No |

## Issues (4)

### 🔴 HIGH: AE1

**Location:** `SKILL.md:23`
**Confidence:** 100%

**Message:** Referenced artifact was not completely inspected

**Remediation:** Review the reported expression and analyzer's parsing limitation; correct the scanner if it misinterprets valid source, then rerun the scan\. Keep required references; incomplete analysis is not proof of malicious evasion\.

**Evidence:**
- **reasons:** `[{'reason_code': 'static_parse_limit', 'message': "A security-relevant expression exceeded a bounded static parser's span limit.", 'phase': 'static', 'analyzers': ['static_patterns_tool_misuse']}]`
- **target\_disposition:** `partial`
- **target\_path:** `references/schema.md`

---

### 🔴 HIGH: AE1

**Location:** `SKILL.md:112`
**Confidence:** 100%

**Message:** Referenced artifact was not completely inspected

**Remediation:** Review the reported expression and analyzer's parsing limitation; correct the scanner if it misinterprets valid source, then rerun the scan\. Keep required references; incomplete analysis is not proof of malicious evasion\.

**Evidence:**
- **reasons:** `[{'reason_code': 'static_parse_limit', 'message': "A security-relevant expression exceeded a bounded static parser's span limit.", 'phase': 'static', 'analyzers': ['static_patterns_tool_misuse']}]`
- **target\_disposition:** `partial`
- **target\_path:** `references/schema.md`

---

### 🔴 HIGH: AE1

**Location:** `SKILL.md:123`
**Confidence:** 100%

**Message:** Referenced artifact was not completely inspected

**Remediation:** Review the reported expression and analyzer's parsing limitation; correct the scanner if it misinterprets valid source, then rerun the scan\. Keep required references; incomplete analysis is not proof of malicious evasion\.

**Evidence:**
- **reasons:** `[{'reason_code': 'static_parse_limit', 'message': "A security-relevant expression exceeded a bounded static parser's span limit.", 'phase': 'static', 'analyzers': ['static_patterns_tool_misuse']}]`
- **target\_disposition:** `partial`
- **target\_path:** `references/schema.md`

---

### 🔴 HIGH: AE1

**Location:** `SKILL.md:125`
**Confidence:** 100%

**Message:** Referenced artifact was not completely inspected

**Remediation:** Review the reported expression and analyzer's parsing limitation; correct the scanner if it misinterprets valid source, then rerun the scan\. Keep required references; incomplete analysis is not proof of malicious evasion\.

**Evidence:**
- **reasons:** `[{'reason_code': 'static_parse_limit', 'message': "A security-relevant expression exceeded a bounded static parser's span limit.", 'phase': 'static', 'analyzers': ['static_patterns_tool_misuse']}]`
- **target\_disposition:** `partial`
- **target\_path:** `references/prompt.md`

---

## Inspection Completeness

| Metric | Value |
|--------|-------|
| Execution | successful |
| Status | partial |
| Coverage | 50\.0% |
| Fully inspected | 4 |
| Partially inspected | 4 |
| Entirely uninspected | 0 |

### Ledger Exceptions

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| reference\_missing | `SKILL.md:22-22` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:40-40` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:55-55` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:63-63` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:64-64` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:117-117` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:119-119` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:127-127` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:128-128` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| static\_parse\_limit | `references/prompt.md` | A security\-relevant expression exceeded a bounded static parser's span limit\. |
| static\_parse\_limit | `references/schema.md` | A security\-relevant expression exceeded a bounded static parser's span limit\. |
| static\_parse\_limit | `templates/fact.json` | A security\-relevant expression exceeded a bounded static parser's span limit\. |
| static\_parse\_limit | `templates/relation.json` | A security\-relevant expression exceeded a bounded static parser's span limit\. |

### Analyzer Statuses

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| completed | `artifact_integrity` |  |
| completed | `behavioral_ast` |  |
| completed | `behavioral_taint_tracking` |  |
| no\_applicable\_files | `bundled_execution_surface` | No files matched this analyzer's applicability contract\. |
| completed | `mcp_least_privilege` |  |
| completed | `mcp_rug_pull` |  |
| completed | `mcp_tool_poisoning` |  |
| no\_applicable\_files | `meta_analyzer` | No files matched this analyzer's applicability contract\. |
| completed | `reference_coverage` |  |
| disabled\_by\_configuration | `semantic_developer_intent` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_quality_policy` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_security_discovery` | Analyzer was disabled by the requested configuration\. |
| completed | `static_patterns_agent_snooping` |  |
| completed | `static_patterns_anti_refusal` |  |
| completed | `static_patterns_data_exfiltration` |  |
| completed | `static_patterns_deserialization` |  |
| completed | `static_patterns_excessive_agency` |  |
| completed | `static_patterns_harmful_content` |  |
| completed | `static_patterns_memory_poisoning` |  |
| completed | `static_patterns_output_handling` |  |
| completed | `static_patterns_privilege_escalation` |  |
| completed | `static_patterns_prompt_injection` |  |
| completed | `static_patterns_rogue_agent` |  |
| completed | `static_patterns_ssrf` |  |
| completed | `static_patterns_supply_chain` |  |
| completed | `static_patterns_system_prompt_leakage` |  |
| degraded | `static_patterns_tool_misuse` |  |
| completed | `static_yara` |  |

### Limitations

- Analyzer static\_patterns\_tool\_misuse status: degraded\.

## Metadata

- **Executable Scripts:** Yes

*Generated by SkillSpector v2.12.0*

--- Recursive Risk Assessment ---

Maximum score: 43/100

Severity: MEDIUM

Recommendation: CAUTION

--- Recursive Inspection Completeness ---

Status: partial

- One or more recursive skill scans were incomplete.


--- boveda-rag (7 de noviembre de 2026) ---

# SkillSpector Security Report

**Skill:** boveda\-rag
**Source:** `C:\Users\PC\Documents\Proyecto_BancoO\.opencode\skills\boveda-rag`
**Scanned:** 2026-11-07 18:02:05 UTC

## Risk Assessment

| Metric | Value |
|--------|-------|
| Score | 7/100 |
| Severity | LOW |
| Recommendation | CAUTION |

## Components (3)

| File | Type | Lines | Executable |
|------|------|-------|------------|
| `SKILL.md` | markdown | 201 | No |
| `scripts/medir_recuperacion.py` | python | 571 | Yes |
| `scripts/validar_indice.py` | python | 297 | Yes |

## Issues (1)

### 🟡 MEDIUM: LP3

**Location:** `SKILL.md:1`
**Confidence:** 70%

**Message:** Skill declares no tool scope \('permissions' or 'allowed\-tools'\) but code capabilities were detected: file\_read, file\_write, network\.

**Remediation:** Clarify the skill's intended tool scope and review how the host runtime enforces it; runtime permissions are unknown unless separately verified\. For Claude Code / Agent Skills SKILL\.md, 'allowed\-tools' records preapproved tools, not a permission ceiling; add a tool only when it is independently approved as necessary, not to silence this finding\. For MCP server manifests, use a 'permissions' list naming the required capabilities\.

---

## Inspection Completeness

| Metric | Value |
|--------|-------|
| Execution | successful |
| Status | partial |
| Coverage | 100\.0% |
| Fully inspected | 3 |
| Partially inspected | 0 |
| Entirely uninspected | 0 |

### Ledger Exceptions

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| reference\_missing | `SKILL.md:29-29` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:30-30` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:31-31` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:34-34` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:37-37` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:38-38` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:39-39` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:41-41` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:42-42` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:45-45` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:47-47` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:48-48` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:51-51` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:52-52` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:53-53` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:55-55` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:63-63` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:64-64` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:85-85` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:112-112` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:115-115` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:118-118` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:123-123` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:138-138` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:139-139` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:142-142` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:144-144` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:145-145` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:147-147` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:165-165` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:166-166` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:192-192` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:193-193` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:194-194` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |
| reference\_missing | `SKILL.md:198-198` | A local path\-like reference does not match any bundled artifact, such as a file the skill writes at runtime\. |

### Analyzer Statuses

| Reason / Status | Location | Details |
|-----------------|----------|---------|
| completed | `artifact_integrity` |  |
| completed | `behavioral_ast` |  |
| completed | `behavioral_taint_tracking` |  |
| no\_applicable\_files | `bundled_execution_surface` | No files matched this analyzer's applicability contract\. |
| completed | `mcp_least_privilege` |  |
| completed | `mcp_rug_pull` |  |
| completed | `mcp_tool_poisoning` |  |
| disabled\_by\_configuration | `meta_analyzer` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_developer_intent` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_quality_policy` | Analyzer was disabled by the requested configuration\. |
| disabled\_by\_configuration | `semantic_security_discovery` | Analyzer was disabled by the requested configuration\. |
| completed | `static_patterns_agent_snooping` |  |
| completed | `static_patterns_anti_refusal` |  |
| completed | `static_patterns_data_exfiltration` |  |
| completed | `static_patterns_deserialization` |  |
| completed | `static_patterns_excessive_agency` |  |
| completed | `static_patterns_harmful_content` |  |
| completed | `static_patterns_memory_poisoning` |  |
| completed | `static_patterns_output_handling` |  |
| completed | `static_patterns_privilege_escalation` |  |
| completed | `static_patterns_prompt_injection` |  |
| completed | `static_patterns_rogue_agent` |  |
| completed | `static_patterns_ssrf` |  |
| completed | `static_patterns_supply_chain` |  |
| completed | `static_patterns_system_prompt_leakage` |  |
| completed | `static_patterns_tool_misuse` |  |
| completed | `static_yara` |  |

## Metadata

- **Executable Scripts:** Yes

*Generated by SkillSpector v2.12.0*
