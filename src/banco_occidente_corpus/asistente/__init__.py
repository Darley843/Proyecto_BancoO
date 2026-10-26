"""Asistente Q&A del corpus: preguntas, FAQ y resumen con DeepSeek.

El subpaquete es autocontenido: consume ``data/contexto/contexto_banco.md`` y
``config/prompts/``, y se ejecuta con
``uv run python -m banco_occidente_corpus.asistente`` sin pasar por el CLI del
pipeline. No escribe en Bronze, Silver ni Gold.
"""

from __future__ import annotations

__all__: list[str] = []
