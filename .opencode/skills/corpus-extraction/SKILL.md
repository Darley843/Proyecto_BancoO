---
name: Corpus Banco de Occidente
description: Extrae, refresca y valida el corpus web de Banco de Occidente con el pipeline Medallion (Bronze/Silver/Gold) de este repositorio. Úsala para capturar el sitio, regenerar Gold, medir la cobertura del checklist del Taller 1 o diagnosticar fallos de scraping.
---

# Corpus Banco de Occidente

Skill del proyecto para operar el corpus sin romper el estándar. El corpus vive
en **este mismo repositorio** (`data/gold/` se versiona); no se crea un repo
aparte.

## Cuándo usarla

- Hay que capturar o refrescar el sitio `https://www.bancodeoccidente.com.co`.
- Hay que regenerar Silver/Gold tras cambiar el limpiador o la clasificación.
- Hay que revisar la cobertura de las 24 casillas del Taller 1.
- El scraping falla (403, 404 en masa, HTML sin texto) y hay que diagnosticar.

No la uses para inventar contenido ni para saltarte `robots.txt`.

## Reglas duras

1. **`uv` es el único gestor.** Nada de `pip` ni `requirements.txt`.
2. **`robots.txt` manda.** No tocar `/portaltransaccional/`, `/icbs-web/`,
   `/AjaxTx`, `/wps/` ni `/*!ut/p*`.
3. **Cortesía:** 1.5 s entre peticiones + pausa de 10 s cada 50. No bajar el
   `delay` para "terminar rápido".
4. **Identificación:** UA de navegador + header `From` con
   `darley.idarraga@uao.edu.co`. El WAF responde 403 a UA declarados bot.
5. **Bronze no se edita a mano.** Se regenera Silver y Gold con
   `make clean && make extract && make gold`.
6. **Gold es el entregable** y sí se versiona en este repo.

## Flujo

```bash
make doctor     # red + robots.txt + estado de las capas
make discover   # expande 210 sitemaps -> data/raw/urls.jsonl
make fetch      # Bronze (reanudable; no repite lo ya bajado)
make extract    # Silver (trafilatura + fallback)
make gold       # Gold (frontmatter + corpus.jsonl)
make stats      # _INDICE.md con la cobertura
make status     # 196 URLs / Bronze / Silver / Gold
make docs       # PDFs: balances, informes, gobierno -> Gold
make videos     # YouTube: subtítulos -> transcripción Gold
```

Para una corrida completa: `make all`. Para empaquetar el entregable:
`make deliver`.

Antes de dar por terminado:

```bash
make check      # ruff + ty + pytest
uv run python .opencode/skills/corpus-extraction/scripts/healthcheck.py
```

## Diagnóstico rápido

| Síntoma | Causa probable | Acción |
|---|---|---|
| `doctor` da 403 | UA de bot o VPN | Revisar `config/site.toml`; usar red colombiana |
| Muchos 404 en `fetch` | Rutas `/w/` sin normalizar | Verificar `discover.normalize_url()` |
| Silver con texto vacío | Página que exige JavaScript | `make browser` y `fetch --browser` |
| Gold con duplicados | Redirecciones al mismo contenido | Es esperado: se descartan por hash |
| `_INDICE.md` con 0 % | Gold vacío o rutas rotas | `make status` y revisar `data/gold/corpus.jsonl` |

## Criterios de aceptación

- `data/gold/pages/*.md` con `fuente`, `titulo`, `seccion`, `fecha_captura`,
  `tokens`, `hash`.
- `data/gold/corpus.jsonl` sin ids duplicados y con archivo existente.
- `_INDICE.md` con cobertura y evidencia citada.
- `make check` en verde.

## Referencias

- `references/pipeline.md` — arquitectura, contrato de Gold y límites.
- `docs/FUENTES.md` — inventario de fuentes y hallazgos del sitio.
- `CONSTITUTION.md` — verdad central del proyecto.
- `docs/ESTANDAR.md` — trazabilidad regla de la clase → código.
