# ============================================================================
#  Corpus web - Banco de Occidente
#  Pipeline Medallion: Bronze -> Silver -> Gold
#
#  Todo pasa por uv: no hace falta activar el entorno a mano.
#  Uso: make help
#
#  Las tareas con logica viven en scripts/tasks.py para que funcione igual
#  en Windows (PowerShell/cmd) y en macOS/Linux, sin grep, awk ni rm.
# ============================================================================

.DEFAULT_GOAL := help
.DELETE_ON_ERROR:

UV ?= uv
CORPUS ?= $(UV) run corpus
TASKS ?= $(UV) run python scripts/tasks.py
LIMIT ?=
DELAY ?=
MSG ?= corpus: actualiza el pipeline
REPO ?= Proyecto_BancoO
OWNER ?= Darley843
GIT_USER ?= Darley843
GIT_EMAIL ?= darley.idarraga@uao.edu.co
GIT_REMOTE ?= https://github.com/$(OWNER)/$(REPO).git

# ---------------------------------------------------------------------------
#  Ayuda
# ---------------------------------------------------------------------------

.PHONY: help
help: ## Muestra esta ayuda
	@$(TASKS) help

# ---------------------------------------------------------------------------
#  Entorno
# ---------------------------------------------------------------------------

.PHONY: init
init: ## Crea el entorno: Python, dependencias y hooks
	$(UV) python install
	$(UV) sync --all-extras
	$(UV) run pre-commit install
	@echo.
	@echo Listo. Siguiente paso: make doctor

.PHONY: sync
sync: ## Sincroniza el entorno con uv.lock
	$(UV) sync --all-extras

.PHONY: lock
lock: ## Regenera uv.lock
	$(UV) lock

.PHONY: add
add: ## Anade una dependencia (make add PKG=httpx)
	$(UV) add $(PKG)

.PHONY: add-dev
add-dev: ## Anade una dependencia de desarrollo (make add-dev PKG=pytest)
	$(UV) add --dev $(PKG)

.PHONY: browser
browser: ## Instala Chromium para paginas con JavaScript
	$(UV) sync --extra browser
	$(UV) run playwright install chromium

# ---------------------------------------------------------------------------
#  Pipeline
# ---------------------------------------------------------------------------

.PHONY: discover
discover: ## Lee robots.txt y sitemap.xml y arma la lista de URLs
	$(CORPUS) discover $(if $(DELAY),--delay $(DELAY),)

.PHONY: fetch
fetch: ## Descarga el HTML crudo (Bronze)
	$(CORPUS) fetch $(if $(LIMIT),--limit $(LIMIT),) $(if $(DELAY),--delay $(DELAY),)

.PHONY: extract
extract: ## Limpia el HTML a Markdown (Silver)
	$(CORPUS) extract

.PHONY: gold
gold: ## Anade metadatos y genera corpus.jsonl (Gold)
	$(CORPUS) gold

.PHONY: chunks
chunks: ## Segmenta Gold en chunks por encabezado (capa Knowledge)
	$(CORPUS) chunks

.PHONY: knowledge
knowledge: chunks ## Valida entidades/hechos/relaciones y escribe el indice
	$(CORPUS) knowledge

.PHONY: docs
docs: ## Inventaria, descarga y extrae PDFs (balances, informes, gobierno)
	$(CORPUS) docs all

.PHONY: docs-finanzas
docs-finanzas: ## Descarga el historico completo de estados financieros
	$(CORPUS) docs fetch --tipo financiero --priority-max 3 --max-mb 600

.PHONY: videos
videos: ## Lista el canal, descarga subtitulos y transcribe a Gold
	$(CORPUS) videos all

.PHONY: media
media: docs videos ## Documentos PDF + videos de YouTube

.PHONY: noticias
noticias: ## Hechos oficiales y prensa curada a Gold (independiente del pipeline)
	$(CORPUS) noticias

.PHONY: repetidos
repetidos: ## Mide bloques repetidos en Gold y escribe _REPETIDOS.md (sin red)
	$(CORPUS) repetidos

.PHONY: all
all: ## Pipeline completo: discover -> fetch -> extract -> gold -> stats
	$(CORPUS) all $(if $(LIMIT),--limit $(LIMIT),) $(if $(DELAY),--delay $(DELAY),)

.PHONY: demo
demo: ## Prueba el pipeline con una pagina local (sin red)
	$(UV) run python scripts/demo_offline.py

.PHONY: deliver
deliver: gold stats pack ## Genera Gold, el indice y el ZIP del entregable
	@echo Paquete listo en dist/

# ---------------------------------------------------------------------------
#  Calidad y diagnostico
# ---------------------------------------------------------------------------

.PHONY: doctor
doctor: ## Verifica red, robots.txt y estado de las capas
	$(CORPUS) doctor

.PHONY: status
status: ## Cuenta URLs, Bronze, Silver y Gold
	$(CORPUS) status

.PHONY: stats
stats: ## Resumen del corpus y cobertura del checklist
	$(CORPUS) stats --write

.PHONY: test
test: ## Ejecuta las pruebas
	$(UV) run pytest

.PHONY: cov
cov: ## Pruebas con cobertura
	$(UV) run pytest --cov=banco_occidente_corpus --cov-report=term-missing

.PHONY: lint
lint: ## Revisa estilo y errores con ruff
	$(UV) run ruff check .

.PHONY: fmt
fmt: ## Formatea el codigo con ruff
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

.PHONY: typecheck
typecheck: ## Verifica tipos con ty
	$(UV) run ty check src

.PHONY: check
check: lint typecheck test ## Lint + tipos + pruebas

.PHONY: ci
ci: check demo ## Lo mismo que corre GitHub Actions

.PHONY: pre-commit
pre-commit: ## Corre los hooks sobre todos los archivos
	$(UV) run pre-commit run --all-files

.PHONY: health
health: ## Verifica integridad de Bronze/Silver/Gold y el contrato de Gold
	$(UV) run python .opencode/skills/corpus-extraction/scripts/healthcheck.py

.PHONY: pack
pack: ## Empaqueta Gold en dist/ para entregar
	$(TASKS) pack

.PHONY: clean
clean: ## Borra Silver y Gold (conserva el crudo)
	$(CORPUS) clean

.PHONY: clean-all
clean-all: ## Borra todas las capas, incluido el crudo
	$(CORPUS) clean --hard

.PHONY: clean-env
clean-env: ## Borra .venv y las caches
	$(TASKS) clean-env

# ---------------------------------------------------------------------------
#  Git y GitHub
# ---------------------------------------------------------------------------

.PHONY: identity
identity: ## Fija user.name y user.email del repositorio
	$(TASKS) identity --user $(GIT_USER) --email $(GIT_EMAIL)

.PHONY: whoami
whoami: ## Muestra la identidad de Git y el remoto
	$(TASKS) whoami

.PHONY: remote
remote: ## Configura origin (make remote OWNER=... REPO=...)
	$(TASKS) remote --url $(GIT_REMOTE)

.PHONY: git-init
git-init: identity ## Inicializa el repositorio local y hace el primer commit
	git init -b main
	git add -A
	git commit -m "chore: corpus Banco de Occidente con pipeline Medallion"

.PHONY: commit
commit: ## Guarda cambios (make commit MSG="...")
	git add -A
	git commit -m "$(MSG)"

.PHONY: push
push: ## Sube a origin/main
	git push -u origin main

.PHONY: repo
repo: ## Crea el repositorio en GitHub (requiere GITHUB_TOKEN con scope repo)
	$(TASKS) repo --repo $(REPO) --owner $(OWNER)

.PHONY: constitution
constitution: ## Descarga la CONSTITUTION del repo (requiere GITHUB_TOKEN)
	$(TASKS) constitution --repo $(REPO) --owner $(OWNER)

# ---------------------------------------------------------------------------
#  Atajos
# ---------------------------------------------------------------------------

.PHONY: setup
setup: init doctor ## init + doctor
