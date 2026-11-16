"""Pruebas de los contratos Pydantic del canal y del diagnóstico.

Cubren lo que la tarea 1.2 del cambio ``corresponsal-whatsapp`` exige: un payload
válido construye el modelo y un campo extra, un rol inválido o un plazo fuera de
rango fallan. Además se fijan los límites de WhatsApp (4.096 caracteres y tres
botones) y el orden de ``RangoDecimal``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from banco_occidente_corpus.canal.contratos import (
    BotonCanal,
    CasoAsesor,
    EntradaDiagnostico,
    MensajeEntrante,
    PerfilUsuario,
    RangoDecimal,
    RespuestaCanal,
    ResultadoDiagnostico,
)

AHORA = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
"""Marca de tiempo fija de las pruebas, para que todo sea determinista."""


def _mensaje(**cambios: Any) -> MensajeEntrante:
    """Construye un mensaje entrante válido con los cambios pedidos."""
    datos: dict[str, Any] = {
        "id_mensaje": "wamid.SIM123",
        "remitente": "57000000001",
        "texto": "hola",
        "recibido_en": AHORA,
    }
    datos.update(cambios)
    return MensajeEntrante(**datos)


def _entrada(**cambios: Any) -> EntradaDiagnostico:
    """Construye una entrada de diagnóstico válida con los cambios pedidos."""
    datos: dict[str, Any] = {
        "producto": "libre_inversion",
        "ingreso_mensual": Decimal("5000000"),
        "gastos_mensuales": Decimal("2000000"),
        "cuotas_deudas": Decimal("300000"),
        "monto_credito": Decimal("10000000"),
        "plazo_meses": 36,
    }
    datos.update(cambios)
    return EntradaDiagnostico(**datos)


def _resultado(**cambios: Any) -> ResultadoDiagnostico:
    """Construye un resultado de diagnóstico válido con los cambios pedidos."""
    datos: dict[str, Any] = {
        "entrada": _entrada(),
        "tasa_ea": RangoDecimal(desde=Decimal("18.50"), hasta=Decimal("24.90")),
        "tasa_mensual": RangoDecimal(desde=Decimal("1.43"), hasta=Decimal("1.87")),
        "cuota_mensual": RangoDecimal(desde=Decimal("380000"), hasta=Decimal("410000")),
        "total_intereses": RangoDecimal(desde=Decimal("3000000"), hasta=Decimal("4000000")),
        "total_pagado": RangoDecimal(desde=Decimal("13000000"), hasta=Decimal("14000000")),
        "razon_endeudamiento": Decimal("0.28"),
        "capacidad_pago": Decimal("700000"),
        "semaforo": "verde",
        "recomendaciones": ["El plazo elegido deja una cuota cómoda."],
        "fuente_tasa": "https://www.bancodeoccidente.com.co/tasas",
        "vigencia_tasa_desde": date(2026, 11, 1),
        "vigencia_tasa_hasta": date(2026, 11, 30),
        "sha256_pdf": "a" * 64,
        "umbrales": {"verde": Decimal("0.30"), "amarillo": Decimal("0.40")},
        "aviso": "Orientativo, no es una aprobación de crédito.",
    }
    datos.update(cambios)
    return ResultadoDiagnostico(**datos)


def test_mensaje_valido_construye_el_modelo() -> None:
    """Un payload completo del webhook se normaliza sin tocar sus valores."""
    mensaje = _mensaje()

    assert mensaje.id_mensaje == "wamid.SIM123"
    assert mensaje.tipo == "texto"
    assert mensaje.id_boton is None


def test_mensaje_con_campo_extra_falla() -> None:
    """``extra="forbid"`` corta un campo que el contrato no declara."""
    with pytest.raises(ValidationError):
        _mensaje(inesperado="x")


def test_mensaje_con_texto_vacio_falla() -> None:
    """WhatsApp no entrega textos vacíos y el contrato tampoco los acepta."""
    with pytest.raises(ValidationError):
        _mensaje(texto="")


def test_mensaje_de_4096_caracteres_pasa_y_4097_falla() -> None:
    """El límite de WhatsApp es inclusivo en 4.096 caracteres."""
    assert len(_mensaje(texto="x" * 4096).texto) == 4096
    with pytest.raises(ValidationError):
        _mensaje(texto="x" * 4097)


def test_remitente_demasiado_corto_falla() -> None:
    """Un remitente de menos de 8 caracteres no es un número E.164."""
    with pytest.raises(ValidationError):
        _mensaje(remitente="123")


def test_respuesta_admite_tres_botones_y_rechaza_cuatro() -> None:
    """WhatsApp permite como máximo tres respuestas rápidas."""
    tres = [BotonCanal(id=f"b{i}", titulo=f"Opción {i}") for i in range(3)]
    respuesta = RespuestaCanal(
        usuario_id="u" * 32,
        id_mensaje_origen="wamid.SIM123",
        texto="¿Qué quieres hacer?",
        tipo="botones",
        botones=tres,
    )

    assert len(respuesta.botones) == 3
    with pytest.raises(ValidationError):
        RespuestaCanal(
            usuario_id="u" * 32,
            id_mensaje_origen="wamid.SIM123",
            texto="¿Qué quieres hacer?",
            botones=[*tres, BotonCanal(id="b4", titulo="Otra")],
        )


def test_titulo_de_boton_de_21_caracteres_falla() -> None:
    """El título visible de un botón no pasa de 20 caracteres."""
    with pytest.raises(ValidationError):
        BotonCanal(id="asesor", titulo="x" * 21)


def test_respuesta_sin_texto_falla() -> None:
    """Toda respuesta del canal necesita texto para el usuario."""
    with pytest.raises(ValidationError):
        RespuestaCanal(
            usuario_id="u" * 32,
            id_mensaje_origen="wamid.SIM123",
            texto="",
        )


def test_perfil_por_defecto_es_cliente_sin_consentimiento() -> None:
    """Un perfil nuevo nace como cliente y sin consentimiento registrado."""
    perfil = PerfilUsuario(usuario_id="u" * 32)

    assert perfil.rol == "cliente"
    assert perfil.consentimiento is False
    assert perfil.version_consentimiento == ""


def test_rol_invalido_falla() -> None:
    """Solo existen los roles ``cliente`` y ``asesor``."""
    with pytest.raises(ValidationError):
        PerfilUsuario(usuario_id="u" * 32, rol="admin")


def test_plazo_fuera_de_rango_falla() -> None:
    """El plazo del diagnóstico vive entre 6 y 120 meses."""
    with pytest.raises(ValidationError):
        _entrada(plazo_meses=5)
    with pytest.raises(ValidationError):
        _entrada(plazo_meses=121)


def test_rango_invertido_falla() -> None:
    """``RangoDecimal`` exige ``desde <= hasta``."""
    with pytest.raises(ValidationError):
        RangoDecimal(desde=Decimal("24.90"), hasta=Decimal("18.50"))


def test_rango_de_un_solo_valor_pasa() -> None:
    """Un producto con una sola tasa se representa con extremos iguales."""
    rango = RangoDecimal(desde=Decimal("18.50"), hasta=Decimal("18.50"))

    assert rango.desde == rango.hasta


def test_resultado_valido_sobrevive_la_ida_y_vuelta_json() -> None:
    """El resultado se puede guardar y releer sin perder precisión ni campos."""
    resultado = _resultado()

    recuperado = ResultadoDiagnostico.model_validate_json(resultado.model_dump_json())

    assert recuperado == resultado
    assert recuperado.entrada.plazo_meses == 36


def test_semaforo_fuera_de_los_tres_colores_falla() -> None:
    """El semáforo solo admite verde, amarillo o rojo."""
    with pytest.raises(ValidationError):
        _resultado(semaforo="azul")


def test_caso_asesor_nace_pendiente_y_sin_resultado() -> None:
    """Un caso directo no arrastra diagnóstico ni datos del cliente."""
    caso = CasoAsesor(
        id_caso="caso-1",
        usuario_id="u" * 32,
        motivo="solicitud_directa",
        semaforo="amarillo",
        creado_en=AHORA,
    )

    assert caso.estado == "pendiente"
    assert caso.origen == "diagnostico"
    assert caso.resultado is None
