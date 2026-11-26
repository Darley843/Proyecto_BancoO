"""Pruebas del contrato de la escena: modelos, fuentes y veredicto sin colores."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from banco_occidente_corpus.escena.contratos import (
    CifraEscena,
    ComparacionGota,
    EscenarioEscena,
    FuenteCifra,
    HallazgoEscena,
    TurnoEscena,
    VeredictoAuditor,
)

#: Personajes que ya existían antes del contrato de la escena en vivo.
PERSONAJES_ANTERIORES = ("pana", "don_gota", "joven", "agente_joven", "agente_banco", "auditor")
#: Orígenes que ya existían antes del contrato de la escena en vivo.
ORIGENES_ANTERIORES = ("guion_fijo", "motor", "llm", "reglas", "entrada_voz")


def _fuente() -> FuenteCifra:
    """Fuente válida para las cifras de prueba.

    Returns:
        Una fuente de configuración con referencia.
    """
    return FuenteCifra(tipo="config", referencia="config/escena.toml#gota.tasa_mensual")


def _turno(**cambios: object) -> TurnoEscena:
    """Construye un turno válido y permite cambiar un campo.

    Args:
        **cambios: campos que se sobreescriben.

    Returns:
        El turno validado.
    """
    datos: dict[str, object] = {
        "id": "pana.comparacion.v1",
        "orden": 8,
        "personaje": "pana",
        "texto": "Con Don Gota pagarías $8.200.000 en total.",
        "cifras": (
            CifraEscena(
                etiqueta="total de Don Gota",
                valor=Decimal("8200000"),
                valor_legible="$8.200.000",
                unidad="pesos",
                fuente=_fuente(),
            ),
        ),
        "escenario": EscenarioEscena(
            codigo="comparacion",
            descripcion="Mismo monto y mismo horizonte",
            producto="libre_inversion",
            monto=Decimal("1000000"),
            plazo_meses=36,
            total_pagado=Decimal("8200000"),
            total_intereses=Decimal("7200000"),
            aceptable=False,
            ofertable=False,
        ),
        "origen": "motor",
    }
    datos.update(cambios)
    return TurnoEscena.model_validate(datos)


def test_turno_valido_construye() -> None:
    """Un turno con fuente, cifras y escenario se construye sin errores."""
    turno = _turno()

    assert turno.personaje == "pana"
    assert turno.cifras[0].fuente.referencia == "config/escena.toml#gota.tasa_mensual"
    assert turno.escenario is not None and turno.escenario.codigo == "comparacion"
    assert turno.hallazgos == ()


def test_turno_del_invitado_por_el_canal_es_valido() -> None:
    """El contrato aditivo acepta al invitado de WhatsApp y el origen del canal."""
    turno = _turno(
        personaje="invitado",
        origen="canal",
        texto="¿Me lo aprueban?",
        cifras=(),
        escenario=None,
    )

    assert turno.personaje == "invitado"
    assert turno.origen == "canal"
    assert turno.texto == "¿Me lo aprueban?"


@pytest.mark.parametrize("personaje", PERSONAJES_ANTERIORES)
def test_los_personajes_anteriores_siguen_validando(personaje: str) -> None:
    """Los personajes que ya existían conservan su validez."""
    assert _turno(personaje=personaje).personaje == personaje


@pytest.mark.parametrize("origen", ORIGENES_ANTERIORES)
def test_los_origenes_anteriores_siguen_validando(origen: str) -> None:
    """Los orígenes que ya existían conservan su validez."""
    assert _turno(origen=origen).origen == origen


def test_campo_extra_falla() -> None:
    """El contrato es cerrado: un campo que no está en el diseño falla."""
    with pytest.raises(ValidationError):
        _turno(color="verde")


def test_cifra_sin_fuente_falla() -> None:
    """Toda cifra debe declarar su fuente verificable."""
    with pytest.raises(ValidationError):
        CifraEscena(
            etiqueta="total",
            valor=Decimal("8200000"),
            valor_legible="$8.200.000",
            unidad="pesos",
        )


def test_cifra_con_fuente_documento_es_valida() -> None:
    """Una cifra citada de un documento del repositorio usa `ruta#ancla`."""
    cifra = CifraEscena(
        etiqueta="monto citado en el documento",
        valor=Decimal("1000000"),
        valor_legible="$1.000.000",
        unidad="pesos",
        fuente=FuenteCifra(tipo="documento", referencia="docs/ARQUEO.md#ancla"),
    )

    assert cifra.fuente.tipo == "documento"
    assert cifra.fuente.referencia == "docs/ARQUEO.md#ancla"


@pytest.mark.parametrize("veredicto", ["conforme", "con_observaciones", "objeta"])
def test_veredicto_acepta_los_tres_valores(veredicto: str) -> None:
    """El auditor solo usa los tres veredictos del diseño."""
    modelo = VeredictoAuditor(
        veredicto=veredicto,
        hallazgos=(
            HallazgoEscena(
                codigo="fuente_ausente",
                turno_id="gota.oferta.v1",
                detalle="La cifra no cita su origen.",
                gravedad="media",
            ),
        ),
        turnos_revisados=("gota.oferta.v1",),
        reglas=("fuente_ausente",),
    )

    assert modelo.veredicto == veredicto


@pytest.mark.parametrize("color", ["verde", "amarillo", "rojo"])
def test_veredicto_rechaza_colores(color: str) -> None:
    """Un color del semáforo no es un veredicto del auditor."""
    with pytest.raises(ValidationError):
        VeredictoAuditor(veredicto=color)


def test_comparacion_sin_usura_deja_los_campos_vacios() -> None:
    """Sin usura certificada, la comparación no calcula el ratio."""
    comparacion = ComparacionGota(
        monto=Decimal("1000000"),
        plazo_meses=36,
        tasa_ea_banco=Decimal("0.2817"),
        tasa_ea_gota=Decimal("7.9161"),
        usura_ea=None,
        usura_vigencia=None,
        total_banco=Decimal("1432836"),
        total_gota=Decimal("8200000"),
        diferencia=Decimal("6767164"),
        veces_total=Decimal("5.72"),
        veces_usura=None,
        articulo_305="Código Penal, artículo 305",
        supuestos=("usura_sin_certificar",),
        fuente_usura=None,
    )

    assert comparacion.usura_ea is None
    assert comparacion.veces_usura is None
    assert comparacion.fuente_usura is None
