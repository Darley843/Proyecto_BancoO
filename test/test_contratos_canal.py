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
    PESO_MAXIMO_IMAGEN,
    BotonCanal,
    CasoAsesor,
    EntradaDiagnostico,
    MensajeEntrante,
    PerfilUsuario,
    RangoDecimal,
    RespuestaCanal,
    ResultadoDiagnostico,
    TasaCaptacion,
    TramoTasa,
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
        "vinculacion": "empleado",
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
        "umbrales": {
            "verde_hasta": Decimal("0.30"),
            "amarillo_hasta": Decimal("0.40"),
            "vivienda_hasta": Decimal("0.30"),
        },
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


def _respuesta_imagen(**cambios: Any) -> RespuestaCanal:
    """Construye una respuesta con tarjeta y los cambios pedidos."""
    datos: dict[str, Any] = {
        "usuario_id": "u" * 32,
        "id_mensaje_origen": "wamid.SIM123",
        "texto": "Tu diagnóstico",
        "tipo": "imagen",
        "imagen": b"\x89PNG\r\n\x1a\n",
    }
    datos.update(cambios)
    return RespuestaCanal(**datos)


def test_respuesta_de_imagen_conserva_el_texto_y_oculta_los_bytes() -> None:
    """La tarjeta acompaña al texto y sus bytes no aparecen en la represión."""
    png = b"PNGDATOS-SECRETOS"

    respuesta = _respuesta_imagen(imagen=png)

    assert respuesta.texto == "Tu diagnóstico"
    assert respuesta.imagen == png
    assert "PNGDATOS" not in repr(respuesta)


def test_respuesta_de_imagen_sin_png_falla() -> None:
    """El tipo imagen exige el PNG para poder enviarlo."""
    with pytest.raises(ValidationError):
        _respuesta_imagen(imagen=None)


def test_png_con_tipo_distinto_de_imagen_falla() -> None:
    """Un PNG suelto en una respuesta de texto no se envía por accidente."""
    with pytest.raises(ValidationError):
        _respuesta_imagen(tipo="texto")


def test_respuesta_de_imagen_no_admite_botones() -> None:
    """La tarjeta acompaña al texto; no reemplaza a los botones."""
    with pytest.raises(ValidationError):
        _respuesta_imagen(botones=[BotonCanal(id="asesor", titulo="Asesor")])


def test_imagen_de_un_megabyte_o_mas_falla() -> None:
    """El contrato corta el PNG que llega al límite antes de salir a la red."""
    with pytest.raises(ValidationError):
        _respuesta_imagen(imagen=b"x" * PESO_MAXIMO_IMAGEN)


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
    """El plazo del diagnóstico vive entre 6 y 240 meses (vivienda)."""
    with pytest.raises(ValidationError):
        _entrada(plazo_meses=5)
    with pytest.raises(ValidationError):
        _entrada(plazo_meses=241)


def test_plazo_largo_de_vivienda_pasa() -> None:
    """Los plazos de vivienda del guion (180 y 240 meses) caben en el contrato."""
    assert _entrada(plazo_meses=180).plazo_meses == 180
    assert _entrada(plazo_meses=240).plazo_meses == 240


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


def test_producto_fuera_del_diagnostico_falla() -> None:
    """Solo los siete objetivos de docs/DIAGNOSTICO.md son válidos."""
    with pytest.raises(ValidationError):
        _entrada(producto="tarjeta_credito")
    with pytest.raises(ValidationError):
        _entrada(producto="credito_rotativo")


def test_vinculacion_invalida_falla() -> None:
    """La libranza depende de una vinculación conocida."""
    with pytest.raises(ValidationError):
        _entrada(vinculacion="desempleado")


def test_credito_sin_monto_o_sin_plazo_falla() -> None:
    """Un producto de crédito exige monto y plazo para simular."""
    with pytest.raises(ValidationError):
        _entrada(monto_credito=None)
    with pytest.raises(ValidationError):
        _entrada(plazo_meses=None)


def test_ahorro_no_lleva_monto_ni_plazo() -> None:
    """El ahorro no se simula: sin monto y sin plazo, y con ambos falla."""
    ahorro = _entrada(
        producto="ahorro",
        monto_credito=None,
        plazo_meses=None,
        cuotas_deudas=Decimal("0"),
    )

    assert ahorro.monto_credito is None
    assert ahorro.plazo_meses is None
    with pytest.raises(ValidationError):
        _entrada(producto="ahorro")
    with pytest.raises(ValidationError):
        _entrada(producto="ahorro", monto_credito=None)


def test_montos_negativos_fallan() -> None:
    """Ingreso, gastos, cuotas y cuota trasladada no admiten negativos."""
    for campo in (
        "ingreso_mensual",
        "gastos_mensuales",
        "cuotas_deudas",
        "monto_credito",
        "cuota_trasladar",
    ):
        with pytest.raises(ValidationError):
            _entrada(**{campo: Decimal("-1")})


def test_cuota_trasladar_es_opcional() -> None:
    """Solo la compra de cartera necesita la cuota que se traslada."""
    assert _entrada().cuota_trasladar is None
    assert _entrada(cuota_trasladar=Decimal("300000")).cuota_trasladar == Decimal("300000")


def test_resultado_de_ahorro_no_tiene_semaforo_ni_cuota() -> None:
    """El ahorro informa capacidad y tasas de captación, sin semáforo."""
    ahorro = _entrada(
        producto="ahorro",
        monto_credito=None,
        plazo_meses=None,
        cuotas_deudas=Decimal("0"),
    )
    resultado = _resultado(
        entrada=ahorro,
        tasa_ea=None,
        tasa_mensual=None,
        cuota_mensual=None,
        total_intereses=None,
        total_pagado=None,
        razon_endeudamiento=None,
        margen_despues_cuota=None,
        semaforo=None,
        capacidad_pago=Decimal("0"),
        fuente_tasa=None,
        vigencia_tasa_desde=None,
        vigencia_tasa_hasta=None,
        sha256_pdf=None,
    )

    assert resultado.semaforo is None
    assert resultado.cuota_mensual is None
    assert resultado.alertas == []
    assert resultado.ahorro_mensual_estimado is None


def test_alertas_solo_admiten_los_motivos_conocidos() -> None:
    """Las alertas son un conjunto cerrado y se guardan como lista."""
    resultado = _resultado(alertas=["capacidad_negativa", "vigencia_vencida"])

    assert resultado.alertas == ["capacidad_negativa", "vigencia_vencida"]
    with pytest.raises(ValidationError):
        _resultado(alertas=["otra_cosa"])


def test_tasa_captacion_separa_la_referencia_del_rango_completo() -> None:
    """El CDT lleva la referencia del monto mínimo y el detalle por plazo."""
    tasa = TasaCaptacion(
        producto="cdt",
        tasa_ea=RangoDecimal(desde=Decimal("0.0005"), hasta=Decimal("0.1205")),
        referencia="De $500 mil a $99 millones",
        rango_completo=RangoDecimal(desde=Decimal("0.0005"), hasta=Decimal("0.1215")),
        tramos=[
            TramoTasa(
                etiqueta="30 días (1 mes)",
                tasa_ea=RangoDecimal(desde=Decimal("0.0005"), hasta=Decimal("0.0005")),
            )
        ],
        vigencia_desde=date(2026, 11, 1),
        vigencia_hasta=date(2026, 11, 30),
        fuente="https://www.bancodeoccidente.com.co/tasas",
    )

    assert tasa.referencia == "De $500 mil a $99 millones"
    assert tasa.rango_completo is not None
    assert tasa.rango_completo.hasta == Decimal("0.1215")
    assert tasa.tramos[0].etiqueta == "30 días (1 mes)"


def test_tasa_captacion_rechaza_un_tramo_sin_etiqueta() -> None:
    """El tramo siempre se puede nombrar en el texto."""
    with pytest.raises(ValidationError):
        TramoTasa(
            etiqueta="",
            tasa_ea=RangoDecimal(desde=Decimal("0.01"), hasta=Decimal("0.01")),
        )


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
