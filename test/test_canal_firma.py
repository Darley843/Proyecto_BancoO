"""Pruebas de la firma ``X-Hub-Signature-256`` (sin red).

El vector fijo se calculó una vez con HMAC-SHA256; si cambia, la prueba debe
fallar aunque el código se "autocalcule" la firma con la misma función.
"""

from __future__ import annotations

from banco_occidente_corpus.canal.firma import calcular_firma, firma_valida

CUERPO = b'{"object":"whatsapp_business_account"}'
"""Cuerpo exacto que Meta habría enviado."""

SECRETO = "s3creto-de-prueba"
"""App Secret ficticio de la prueba."""

FIRMA = "sha256=919b73c6c03d35c9c285ea495eac819f464cbf06d2abd19237598bb4b0e78033"
"""Firma conocida de ``CUERPO`` con ``SECRETO``."""


def test_firma_conocida() -> None:
    """El HMAC coincide con el vector fijo y con el prefijo de Meta."""
    assert calcular_firma(CUERPO, SECRETO) == FIRMA
    assert firma_valida(CUERPO, FIRMA, SECRETO) is True


def test_cuerpo_alterado_no_valida() -> None:
    """Cambiar un byte después de firmar invalida la cabecera."""
    assert firma_valida(CUERPO + b" ", FIRMA, SECRETO) is False


def test_cabecera_ausente_no_valida() -> None:
    """Sin cabecera no hay nada que comparar."""
    assert firma_valida(CUERPO, None, SECRETO) is False


def test_otro_esquema_no_valida() -> None:
    """Solo se acepta el prefijo ``sha256=``."""
    assert firma_valida(CUERPO, FIRMA.replace("sha256=", "sha1="), SECRETO) is False


def test_secreto_vacio_no_valida() -> None:
    """Un secreto vacío no puede validar nada."""
    assert firma_valida(CUERPO, FIRMA, "") is False
