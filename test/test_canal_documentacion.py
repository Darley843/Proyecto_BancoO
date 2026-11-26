"""Pruebas de la documentación operativa del canal (sin red).

Fijan que `.env.example` solo tenga marcadores, que la guía cubra arranque,
túnel, callback y modos, y que el README enlace la operación.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

VARIABLES = (
    "WHATSAPP_VERIFY_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_ID_SALT",
)

MODO = "WHATSAPP_MODO"


def test_env_example_solo_tiene_marcadores() -> None:
    """Cada variable de ejemplo usa `<...>` o un modo válido, nunca un valor real."""
    texto = (RAIZ / ".env.example").read_text(encoding="utf-8")

    for nombre in VARIABLES:
        assert re.search(rf"^{nombre}=<[^>]+>$", texto, re.MULTILINE), nombre

    assert re.search(rf"^{MODO}=(falso|real)$", texto, re.MULTILINE)


def test_env_example_no_parece_contener_secretos() -> None:
    """Ningún valor del ejemplo tiene forma de clave."""
    texto = (RAIZ / ".env.example").read_text(encoding="utf-8")

    valores = [
        linea.split("=", 1)[1]
        for linea in texto.splitlines()
        if linea and not linea.startswith("#") and "=" in linea
    ]

    assert valores
    for valor in valores:
        assert valor.startswith("<") or valor in {"falso", "real"}
        assert len(valor) < 60


def test_la_guia_cubre_arranque_tunel_callback_y_modos() -> None:
    """La guía operativa tiene los pasos que pide la tarea 2.10."""
    texto = (RAIZ / "docs" / "OPERACION_WHATSAPP.md").read_text(encoding="utf-8")

    for pieza in (
        "make app",
        "cloudflared",
        "ngrok",
        "/webhooks/whatsapp",
        "hub.verify_token",
        "WHATSAPP_ID_SALT",
        "WHATSAPP_MODO",
        "127.0.0.1",
        "X-Hub-Signature-256",
        "subscribed_apps",
        "Whatsapp Business Account",
        "falso",
        "real",
    ):
        assert pieza in texto, pieza


def test_la_guia_explica_publicar_la_app_y_la_suscripcion() -> None:
    """Los dos bloqueos reales de Meta quedan documentados."""
    texto = (RAIZ / "docs" / "OPERACION_WHATSAPP.md").read_text(encoding="utf-8")

    assert "modo Desarrollo" in texto
    assert "«Activo»" in texto
    assert "Estado verificado" in texto


def test_el_readme_enlaza_la_operacion_del_canal() -> None:
    """El README explica el canal y apunta a la guía completa."""
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")

    assert "## Canal de WhatsApp" in readme
    assert "docs/OPERACION_WHATSAPP.md" in readme
    assert ".env.example" in readme


def test_el_readme_explica_tunel_y_meta() -> None:
    """El README no se queda en el resumen: explica túnel y configuración de Meta."""
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")

    for pieza in (
        "cloudflared",
        "Whatsapp Business Account",
        "subscribed_apps",
        "WHATSAPP_MODO",
        "/webhooks/whatsapp",
        "messages",
    ):
        assert pieza in readme, pieza


def test_el_despliegue_dice_donde_va_la_url_del_tunel() -> None:
    """El despliegue señala el único campo de Meta y el arranque por ventana."""
    texto = (RAIZ / "docs" / "DESPLIEGUE_WHATSAPP.md").read_text(encoding="utf-8")

    for pieza in (
        "URL de devolución de llamada",
        "whatsapp-business/wa-settings",
        "/webhooks/whatsapp",
        "Verificar y guardar",
        "WHATSAPP_ID_SALT",
        "WHATSAPP_EVENTO",
        "..\\whatsapp-env.ps1",
        "127.0.0.1:8000",
    ):
        assert pieza in texto, pieza


def test_el_despliegue_explica_que_solo_el_webhook_es_publico() -> None:
    """El runbook dice qué rutas quedan públicas y cómo comprobarlo desde fuera."""
    texto = (RAIZ / "docs" / "DESPLIEGUE_WHATSAPP.md").read_text(encoding="utf-8")
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")

    for pieza in (
        "Qué queda público",
        "solo deja pasar",
        "/webhooks/whatsapp",
        "/health",
        "SEGURIDAD.md",
        "/api/estado",
        "404",
    ):
        assert pieza in texto, pieza
    assert "**solo** `/webhooks/whatsapp`" in readme
    assert "§3.12" in readme


def test_los_comandos_del_modulo_usan_uv() -> None:
    """Ningún comando del paquete se invoca con el Python del sistema."""
    for archivo in ("README.md", "docs/OPERACION_WHATSAPP.md"):
        texto = (RAIZ / archivo).read_text(encoding="utf-8")

        assert "uv run python -m banco_occidente_corpus.canal.identidad" in texto, archivo
        assert re.search(r"(?<!uv run )python -m banco_occidente_corpus", texto) is None, archivo


def test_la_guia_documenta_el_codigo_de_la_escena() -> None:
    """La operación explica que el comando exige el código de cuatro dígitos."""
    texto = (RAIZ / "docs" / "OPERACION_WHATSAPP.md").read_text(encoding="utf-8")

    for pieza in ("ESCENA_CODIGO", "cuatro dígitos", "ESCENA 1965"):
        assert pieza in texto, pieza


def test_la_lista_de_la_demo_enciende_la_escena_en_vivo() -> None:
    """El sábado la app arranca con la lista encendida y el código del voluntario."""
    texto = (RAIZ / "docs" / "LISTA_DEMO.md").read_text(encoding="utf-8")

    for pieza in (
        'ESCENA_EN_VIVO = "1"',
        'ESCENA_CODIGO = "XXXX"',
        "cuatro dígitos",
        "solo en la tarjeta del voluntario",
        "En vivo — esperando el primer turno",
        "no se versiona",
    ):
        assert pieza in texto, pieza


def test_la_ficha_del_presentador_ya_confirma_la_fila_de_darley() -> None:
    """La fila de P2 no vuelve a quedar marcada como pendiente de confirmar."""
    texto = (RAIZ / "docs" / "PRESENTADOR.md").read_text(encoding="utf-8")

    assert "Fila de Darley confirmada" in texto
    assert "Darley confirma su fila" not in texto
