"""Interfaz compartida del publicador (`docs/ESCENA_EN_VIVO.md`, §7).

El canal y la app consumen ``publicar_turnos`` y ``leer_turnos`` sin abrir la
lista por su cuenta. La implementacion vive en `en_vivo`, que es el unico
modulo que toca `data/escena/en_vivo.jsonl`.
"""

from __future__ import annotations

from .en_vivo import leer_turnos, publicar_turnos

__all__ = ["leer_turnos", "publicar_turnos"]
