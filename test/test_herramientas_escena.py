"""Pruebas sin red de los esquemas de la escena completa del agente `pana`.

Cubren los cuatro hallazgos de la traza: los ids canónicos del diagnóstico en el
esquema y en el error, la negociación sin `modo_demo`, la usura sin tope y el
alcance declarado de `responder_sobre_proyecto`.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from banco_occidente_corpus.herramientas import catalogo, estado, lectura
from banco_occidente_corpus.herramientas.esquemas import (
    BLOQUES_ENTREVISTA,
    CATALOGO_ENTREVISTA,
    NegociarOpcionEntrada,
    VerificarUsuraEntrada,
)
from banco_occidente_corpus.herramientas.servidor import crear_servidor

RESPUESTAS = [
    "objetivo.libre_inversion",
    "vinculacion.empleado",
    "ingresos.DE_3M_A_5M",
    "gastos.DE_1M_A_2M",
    "cuotas.NINGUNA",
    "monto.DE_5M_A_10M",
    "plazo.36",
]

RESPUESTAS_HASTA_5M = [
    *RESPUESTAS[:5],
    "monto.HASTA_5M",
    "plazo.36",
]

RESPUESTAS_VEHICULO = [
    "objetivo.vehiculo_nuevo",
    "vinculacion.empleado",
    "ingresos.DE_3M_A_5M",
    "gastos.DE_1M_A_2M",
    "cuotas.NINGUNA",
    "monto.DE_30M_A_60M",
    "plazo.36",
]

CON_RESPUESTAS = (
    "diagnosticar_capacidad",
    "comparar_escenario",
    "convocar_comite",
    "comparar_gota_banco",
    "negociar_opcion",
    "generar_ficha_opcion",
    "generar_tarjeta_pana",
)


def _respuestas_del_esquema(nombre: str) -> dict[str, Any]:
    """Devuelve el campo `respuestas` del JSON Schema de una herramienta."""
    herramienta = catalogo.por_nombre(nombre)
    assert herramienta is not None
    esquema = herramienta.entrada.model_json_schema()
    return dict(esquema["properties"]["respuestas"])


def test_esquema_de_respuestas_expone_bloques_y_valores() -> None:
    """Todas las herramientas con entrevista publican bloques, ids y un ejemplo."""
    for nombre in CON_RESPUESTAS:
        campo = _respuestas_del_esquema(nombre)
        assert "objetivo.libre_inversion" in campo["description"]
        assert "plazo.36" in campo["description"]
        assert "cuota_trasladar" in campo["description"]
        assert campo["items"]["enum"] == [
            ident for ids in CATALOGO_ENTREVISTA.values() for ident in ids
        ]
        assert campo["examples"][0][0] == "objetivo.libre_inversion"


def test_esquema_de_respuestas_trae_la_etiqueta_de_cada_id() -> None:
    """Cada id canónico viaja con su etiqueta legible y su letra por bloque."""
    campo = _respuestas_del_esquema("diagnosticar_capacidad")
    assert "Entre $500 mil y $5 millones" in campo["description"]
    assert campo["etiquetas"]["monto.HASTA_5M"] == "Entre $500 mil y $5 millones"
    assert campo["etiquetas"]["objetivo.libre_inversion"] == "Libre inversión"

    monto = campo["opciones"]["monto"]
    assert monto["pregunta"] == "¿Cuánto dinero necesitas?"
    assert monto["opciones"][0] == {
        "letra": "A",
        "id": "monto.HASTA_5M",
        "etiqueta": "Entre $500 mil y $5 millones",
    }
    assert campo["opciones"]["plazo"]["opciones"][2] == {
        "letra": "C",
        "id": "plazo.36",
        "etiqueta": "36 meses",
    }


def test_el_mcp_expone_los_ids_en_la_firma_de_la_herramienta() -> None:
    """El esquema que ve el modelo sale de la firma, con enum y descripción."""

    async def caso() -> None:
        servidor = crear_servidor()
        herramientas = {
            herramienta.name: herramienta for herramienta in await servidor.list_tools()
        }
        campo = herramientas["diagnosticar_capacidad"].input_schema["properties"]["respuestas"]
        assert "objetivo.libre_inversion" in campo["description"]
        assert "monto.DE_5M_A_10M" in campo["items"]["enum"]
        assert "libre inversión a la tasa máxima" in (
            herramientas["comparar_gota_banco"].description or ""
        )

    asyncio.run(caso())


def test_error_de_entrevista_trae_campos_y_valores_validos() -> None:
    """Un id inventado o un bloque faltante devuelven el catálogo para corregir."""
    inventado = lectura.diagnosticar_capacidad(["objetivo.libre_inversion", "monto.rango_2"])
    assert not inventado.ok
    assert inventado.error is not None
    assert inventado.error.codigo == "entrada_invalida"
    assert inventado.datos["campos"][:5] == [
        "objetivo",
        "vinculacion",
        "ingresos",
        "gastos",
        "cuotas",
    ]
    assert "monto.rango_2" in inventado.datos["no_reconocidas"]
    assert "ingresos.DE_3M_A_5M" in inventado.datos["valores_validos"]["ingresos"]
    assert inventado.datos["ejemplo"] == RESPUESTAS
    opciones = inventado.datos["opciones"]
    assert opciones["monto"]["opciones"][0] == {
        "letra": "A",
        "id": "monto.HASTA_5M",
        "etiqueta": "Entre $500 mil y $5 millones",
    }
    assert opciones["cuotas"]["opciones"][0]["etiqueta"] == "No tengo cuotas"

    incompleta = lectura.diagnosticar_capacidad(
        ["objetivo.libre_inversion", "vinculacion.empleado"]
    )
    assert incompleta.ok
    assert incompleta.datos["estado"] == "faltan_datos"
    assert incompleta.datos["bloque"] == "ingresos"
    assert incompleta.datos["opciones"] == BLOQUES_ENTREVISTA["ingresos"]["opciones"]

    tarjeta = estado.generar_tarjeta_pana(["monto.rango_2"])
    assert not tarjeta.ok
    assert tarjeta.error is not None
    assert tarjeta.error.codigo == "entrada_invalida"
    assert tarjeta.datos["valores_validos"]["plazo"]


def test_entrevista_la_conduce_diagnosticar_capacidad() -> None:
    """Sin respuestas, la herramienta devuelve la primera pregunta y sus opciones."""
    salida = lectura.diagnosticar_capacidad([])
    assert salida.ok
    assert salida.error is None
    assert salida.datos["estado"] == "faltan_datos"
    assert salida.datos["bloque"] == "objetivo"
    assert salida.datos["pregunta"] == BLOQUES_ENTREVISTA["objetivo"]["pregunta"]
    assert salida.datos["opciones"] == BLOQUES_ENTREVISTA["objetivo"]["opciones"]
    assert salida.datos["opciones"][0]["letra"] == "A"
    assert salida.datos["opciones"][0]["id"].startswith("objetivo.")


def test_entrevista_pide_el_monto_exacto_despues_del_rango() -> None:
    """Con el bloque de monto respondido y sin `monto`, pide el monto exacto."""
    salida = lectura.diagnosticar_capacidad(RESPUESTAS_HASTA_5M)
    assert salida.ok
    assert salida.datos["estado"] == "faltan_datos"
    assert salida.datos["bloque"] == "monto_exacto"
    assert salida.datos["campo"] == "monto"
    assert salida.datos["rango"] == "monto.HASTA_5M"
    assert salida.datos["etiqueta"] == "Entre $500 mil y $5 millones"
    assert salida.datos["limites"] == {"desde": 500_000, "hasta": 5_000_000}
    assert salida.datos["opciones"] == []


def test_diagnostico_usa_el_monto_exacto_en_todo_el_recorrido() -> None:
    """Con todas las respuestas y monto=2.000.000, el motor calcula sobre 2 M."""
    salida = lectura.diagnosticar_capacidad(RESPUESTAS_HASTA_5M, monto=2_000_000)
    assert salida.ok
    entrada = salida.datos["resultado"]["entrada"]
    assert Decimal(str(entrada["monto_credito"])) == Decimal("2000000")
    assert entrada["rango_usado"]["monto"] == "monto.HASTA_5M"

    escenario = lectura.comparar_escenario(
        RESPUESTAS_HASTA_5M,
        "plazo_meses",
        60,
        monto=2_000_000,
    )
    assert escenario.ok
    assert Decimal(str(escenario.datos["escenario"]["entrada"]["monto_credito"])) == Decimal(
        "2000000"
    )

    tarjeta = estado.generar_tarjeta_pana(RESPUESTAS_HASTA_5M, monto=2_000_000)
    assert tarjeta.ok
    assert "$2 millones" in str(tarjeta.datos["texto"])


def test_negociar_opcion_usa_las_respuestas_y_no_acepta_modo_demo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El modo demo lo decide el servidor; la mesa sale de las respuestas dadas."""
    assert "modo_demo" not in NegociarOpcionEntrada.model_fields
    with pytest.raises(ValidationError):
        NegociarOpcionEntrada.model_validate({"respuestas": RESPUESTAS, "modo_demo": True})

    monkeypatch.setenv("SUCURSAL_DEMO", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    salida = lectura.negociar_opcion(RESPUESTAS)
    assert salida.ok
    escenarios = salida.datos["escenarios"]
    base = next(escenario for escenario in escenarios if escenario["codigo"] == "base")
    assert Decimal(str(base["monto"])) == Decimal("7500000")
    assert Decimal(str(base["monto"])) != Decimal("4000000")
    assert any("modo demo" in nota for nota in salida.datos["registro"])


def test_verificar_usura_acepta_tasas_sobre_cien_por_ciento() -> None:
    """El 791,61 % E.A. del gota a gota se acepta en fracción o en porcentaje."""
    fraccion = lectura.verificar_usura(7.9161)
    porcentaje = lectura.verificar_usura(791.61)
    declarado = lectura.verificar_usura(791.61, unidad="porcentaje")
    for salida in (fraccion, porcentaje, declarado):
        assert salida.ok
        assert salida.datos["excede"] is True
        assert salida.datos["tasa_ea_pct"] == 791.61

    assert fraccion.datos["unidad_interpretada"] == "fraccion"
    assert porcentaje.datos["unidad_interpretada"] == "porcentaje"
    assert declarado.datos["unidad_interpretada"] == "porcentaje"
    assert Decimal(str(fraccion.datos["exceso_puntos"])) == Decimal("763.27")

    certificada = lectura.verificar_usura(0.2834)
    assert certificada.ok
    assert certificada.datos["excede"] is False
    assert lectura.verificar_usura(28.34, unidad="porcentaje").datos["tasa_ea"] == 0.2834

    esquema = VerificarUsuraEntrada.model_json_schema()["properties"]
    assert "porcentaje" in esquema["tasa_ea"]["description"]
    assert "fracción" in esquema["tasa_ea"]["description"]
    assert "exclusiveMaximum" not in esquema["tasa_ea"]
    assert esquema["unidad"]["anyOf"][0]["enum"] == ["fraccion", "porcentaje"]


def test_negociar_opcion_usa_el_monto_exacto_del_invitado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con `monto`, la mesa se arma sobre el monto exacto y no sobre el rango."""
    monkeypatch.setenv("SUCURSAL_DEMO", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    por_rango = lectura.negociar_opcion(RESPUESTAS_HASTA_5M)
    exacto = lectura.negociar_opcion(RESPUESTAS_HASTA_5M, monto=2_000_000)
    assert por_rango.ok and exacto.ok

    def base(salida: Any) -> Decimal:
        escenario = next(e for e in salida.datos["escenarios"] if e["codigo"] == "base")
        return Decimal(str(escenario["monto"]))

    assert base(por_rango) == Decimal("4000000")
    assert base(exacto) == Decimal("2000000")

    herramienta = catalogo.por_nombre("negociar_opcion")
    assert herramienta is not None
    monto = herramienta.entrada.model_json_schema()["properties"]["monto"]
    assert "calcular_prestamo_gota" in monto["description"]
    assert "límites" in monto["description"]


def test_monto_fuera_del_rango_devuelve_entrada_invalida_con_los_limites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un monto que no cabe en el rango elegido no se usa y explica los límites."""
    monkeypatch.setenv("SUCURSAL_DEMO", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    negociacion = lectura.negociar_opcion(RESPUESTAS_HASTA_5M, monto=6_000_000)
    assert not negociacion.ok
    assert negociacion.error is not None
    assert negociacion.error.codigo == "entrada_invalida"
    assert negociacion.datos["rango"] == "monto.HASTA_5M"
    assert negociacion.datos["limites"] == {"desde": 500_000, "hasta": 5_000_000}

    ficha = lectura.generar_ficha_opcion(RESPUESTAS_HASTA_5M, monto=6_000_000)
    assert not ficha.ok
    assert ficha.error is not None
    assert ficha.error.codigo == "entrada_invalida"
    assert ficha.datos["limites"] == {"desde": 500_000, "hasta": 5_000_000}


def test_generar_ficha_opcion_usa_el_monto_exacto_del_invitado() -> None:
    """La ficha con `monto` muestra el monto exacto y una cuota menor."""
    por_rango = lectura.generar_ficha_opcion(RESPUESTAS_HASTA_5M)
    exacto = lectura.generar_ficha_opcion(RESPUESTAS_HASTA_5M, monto=2_000_000)
    assert por_rango.ok and exacto.ok
    assert "$4 millones" in str(por_rango.datos["texto"])
    assert "$2 millones" in str(exacto.datos["texto"])

    cuota_rango = Decimal(str(por_rango.datos["cuota_mensual"]["hasta"]))
    cuota_exacta = Decimal(str(exacto.datos["cuota_mensual"]["hasta"]))
    assert cuota_exacta < cuota_rango


def test_responder_sobre_proyecto_declara_su_alcance() -> None:
    """La herramienta dice que no sirve para crédito, tasas ni diagnóstico."""
    herramienta = catalogo.por_nombre("responder_sobre_proyecto")
    assert herramienta is not None
    descripcion = herramienta.entrada.model_json_schema()["properties"]["pregunta"]["description"]
    assert "Solo sirve para eso" in descripcion
    assert "no para preguntas de crédito" in descripcion
    assert "tasas" in descripcion and "diagnóstico" in descripcion

    docstring = lectura.responder_sobre_proyecto.__doc__ or ""
    assert "no para preguntas de crédito" in docstring

    fuera = lectura.responder_sobre_proyecto("¿cuál es la tasa de libre inversión?")
    assert fuera.error is not None
    assert fuera.error.codigo == "fuera_del_corpus"


def test_comparar_gota_banco_usa_siempre_libre_inversion() -> None:
    """Aunque la entrevista nombre otro producto, el banco se compara en libre inversión."""
    libre = lectura.comparar_gota_banco(2_000_000, RESPUESTAS)
    vehiculo = lectura.comparar_gota_banco(2_000_000, RESPUESTAS_VEHICULO)
    assert libre.ok and vehiculo.ok
    assert (
        vehiculo.datos["comparacion"]["tasa_ea_banco"]
        == libre.datos["comparacion"]["tasa_ea_banco"]
    )
    assert (
        vehiculo.datos["comparacion"]["tasa_ea_banco_legible"]
        == libre.datos["comparacion"]["tasa_ea_banco_legible"]
    )


def test_comparar_gota_banco_declara_el_producto_en_su_descripcion() -> None:
    """La herramienta avisa que la escena compara con libre inversión a la tasa máxima."""
    docstring = lectura.comparar_gota_banco.__doc__ or ""
    assert "libre inversión a la tasa máxima" in docstring
    assert "aunque las respuestas nombren otro producto" in docstring

    herramienta = catalogo.por_nombre("comparar_gota_banco")
    assert herramienta is not None
    assert "libre inversión a la tasa máxima" in (herramienta.funcion.__doc__ or "")


def test_agents_de_pana_declara_el_alcance_y_cabe_en_el_presupuesto() -> None:
    """AGENTS.md excluye esas dos herramientas, exige copiar cifras y sigue bajo 4.000."""
    texto = Path("openclaw/workspace/pana/AGENTS.md").read_text(encoding="utf-8")
    frase = (
        "Durante la entrevista y la escena no uso responder_sobre_proyecto ni buscar_en_documentos"
    )
    assert frase in texto
    assert "Copio las cifras tal como vienen en `valor_legible`" in texto
    assert "nunca hago cuentas propias ni convierto unidades" in texto
    assert "Antes de enviar cualquier mensaje con cifras, lo reviso con" in texto
    assert "`auditar_respuesta`" in texto
    assert "`cifras_permitidas`" in texto
    compacto = " ".join(texto.split())
    assert "con las opciones exactas del esquema, con sus letras; no invento rangos" in compacto
    assert "En la escena el producto es libre inversión" in compacto
    assert len(texto) < 4000
