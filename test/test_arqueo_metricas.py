"""Pruebas sin red de las metricas del Arqueo de la fase 2."""

from __future__ import annotations

import unicodedata
from typing import Any

import pytest

from banco_occidente_corpus.arqueo.metricas import (
    ALFA,
    TARIFAS_DEEPSEEK_FLASH,
    TARIFAS_DEEPSEEK_FLASH_PICO,
    ResumenUso,
    Tarifas,
    acierta_terminos,
    citas_correctas,
    exactitud,
    hit_at_k,
    intervalo_wilson,
    mcnemar,
    mrr,
    p_minimo_mcnemar,
    resumen_uso,
)

URL_A = "https://www.bancodeoccidente.com.co/ayuda"
URL_B = "https://www.bancodeoccidente.com.co/quienes-somos"
URL_C = "https://www.bancodeoccidente.com.co/tarifas"
URL_D = "https://www.bancodeoccidente.com.co/seguros"
URL_X = "https://ejemplo.com/otra"
URL_Y = "https://ejemplo.com/tercera"


def _registro(
    entrada: int,
    salida: int,
    cache: int,
    segundos: float,
    *,
    error: str = "",
) -> dict[str, Any]:
    """Arma un registro con la forma de ``resultados.jsonl``."""
    return {
        "metricas": {
            "uso": {
                "input_tokens": entrada,
                "output_tokens": salida,
                "input_token_details": {"cache_read": cache},
            },
            "respuesta": {"finish_reason": "stop"},
        },
        "segundos": segundos,
        "error": error,
    }


def test_tarifas_del_modelo_tienen_valle_y_pico() -> None:
    """Las tarifas valle y pico coinciden con las consultadas."""
    # Arrange
    valle = Tarifas(entrada=0.15, cache=0.003, salida=0.60)
    pico = Tarifas(entrada=0.30, cache=0.006, salida=1.20)

    # Act
    tarifas_valle = TARIFAS_DEEPSEEK_FLASH
    tarifas_pico = TARIFAS_DEEPSEEK_FLASH_PICO

    # Assert
    assert tarifas_valle == valle
    assert tarifas_pico == pico


def test_hit_at_k_y_mrr_con_las_posiciones_verificadas() -> None:
    """Con posiciones 1, 3, ausente y 2, hit@5 y MRR coinciden con el ejemplo."""
    # Arrange
    recuperadas = [
        [URL_A, URL_X],
        [URL_X, URL_Y, URL_B],
        [URL_X, URL_Y],
        [URL_X, URL_C],
        [URL_X],
    ]
    esperadas = [[URL_A], [URL_B], [URL_D], [URL_C], []]

    # Act
    hit = hit_at_k(recuperadas, esperadas, k=5)
    rango = mrr(recuperadas, esperadas, k=5)

    # Assert
    assert hit is not None
    assert rango is not None
    assert hit == pytest.approx(0.75)
    assert rango == pytest.approx(11 / 24)
    assert round(hit, 2) == 0.75
    assert round(rango, 4) == 0.4583


def test_hit_at_k_respeta_el_corte_k() -> None:
    """Una URL en la posicion 6 no cuenta con k=5, pero si con k=6."""
    # Arrange
    recuperadas = [[URL_X, "u2", "u3", "u4", "u5", URL_A]]
    esperadas = [[URL_A]]

    # Act
    hit_cinco = hit_at_k(recuperadas, esperadas, k=5)
    hit_seis = hit_at_k(recuperadas, esperadas, k=6)
    rango_cinco = mrr(recuperadas, esperadas, k=5)
    rango_seis = mrr(recuperadas, esperadas, k=6)

    # Assert
    assert hit_cinco == 0.0
    assert rango_cinco == 0.0
    assert hit_seis == 1.0
    assert rango_seis == pytest.approx(1 / 6)


def test_hit_at_k_compara_urls_exactamente() -> None:
    """Una barra final o un cambio de mayusculas no cuentan como la misma URL."""
    # Arrange
    recuperadas = [[URL_A + "/", URL_A.upper()]]
    esperadas = [[URL_A]]

    # Act
    hit = hit_at_k(recuperadas, esperadas, k=5)

    # Assert
    assert hit == 0.0


def test_hit_at_k_y_mrr_sin_preguntas_evaluables_devuelven_none() -> None:
    """Las preguntas con esperadas vacia se excluyen; sin ninguna, no hay metrica."""
    # Arrange
    recuperadas = [[URL_A], []]
    esperadas = [[], []]

    # Act
    hit = hit_at_k(recuperadas, esperadas)
    rango = mrr(recuperadas, esperadas)

    # Assert
    assert hit is None
    assert rango is None


@pytest.mark.parametrize("k", [0, -1])
def test_hit_at_k_y_mrr_exigen_k_positivo(k: int) -> None:
    """k debe ser mayor que cero en hit@k y en MRR."""
    # Arrange
    recuperadas = [[URL_A]]
    esperadas = [[URL_A]]

    # Act / Assert
    with pytest.raises(ValueError):
        hit_at_k(recuperadas, esperadas, k=k)
    with pytest.raises(ValueError):
        mrr(recuperadas, esperadas, k=k)


def test_hit_at_k_y_mrr_exigen_listas_del_mismo_largo() -> None:
    """Las listas paralelas deben tener el mismo numero de preguntas."""
    # Arrange
    recuperadas = [[URL_A]]
    esperadas: list[list[str]] = []

    # Act / Assert
    with pytest.raises(ValueError):
        hit_at_k(recuperadas, esperadas)
    with pytest.raises(ValueError):
        mrr(recuperadas, esperadas)


def test_mrr_usa_la_primera_url_esperada_que_aparece() -> None:
    """Si hay varias esperadas, cuenta la que aparece primero en recuperadas."""
    # Arrange
    recuperadas = [[URL_X, URL_C, URL_B]]
    esperadas = [[URL_B, URL_C]]

    # Act
    rango = mrr(recuperadas, esperadas, k=5)

    # Assert
    assert rango == pytest.approx(1 / 2)


def test_acierta_terminos_ignora_mayusculas() -> None:
    """Cada grupo se satisface con una alternativa, sin distinguir mayusculas."""
    # Arrange
    respuesta = "Radica la QUEJA en el PQR y llama al 018000."
    terminos = [["pqr", "queja"], ["018000"]]

    # Act
    acierto = acierta_terminos(respuesta, terminos)

    # Assert
    assert acierto is True


def test_acierta_terminos_exige_todos_los_grupos() -> None:
    """Si falta una alternativa de un grupo, el resultado es False."""
    # Arrange
    respuesta = "Radica la queja en el PQR."
    terminos = [["pqr"], ["018000"]]

    # Act
    acierto = acierta_terminos(respuesta, terminos)

    # Assert
    assert acierto is False


def test_acierta_terminos_sin_terminos_devuelve_none() -> None:
    """Sin grupos no hay nada que evaluar."""
    # Arrange
    respuesta = "Cualquier respuesta."
    terminos: list[list[str]] = []

    # Act
    acierto = acierta_terminos(respuesta, terminos)

    # Assert
    assert acierto is None


def test_acierta_terminos_quita_tildes_en_respuesta_y_terminos() -> None:
    """«petición» y «peticion» coinciden, también con el término descompuesto."""
    # Arrange
    respuesta = "La petición se radica por el canal oficial."
    termino_descompuesto = unicodedata.normalize("NFD", "petición")

    # Act
    sin_tilde = acierta_terminos(respuesta, [["peticion"]])
    descompuesto = acierta_terminos(respuesta, [[termino_descompuesto]])

    # Assert
    assert sin_tilde is True
    assert descompuesto is True


def test_acierta_terminos_iguala_linea_con_tilde_en_los_dos_sentidos() -> None:
    """«LÍNEA» y «linea» coinciden tanto en la respuesta como en el término."""
    # Assert
    assert acierta_terminos("LÍNEA de atención al cliente", [["linea"]]) is True
    assert acierta_terminos("linea de atencion al cliente", [["LÍNEA"]]) is True


def test_exactitud_ignora_none() -> None:
    """Los None no cuentan; True y False si."""
    # Arrange
    aciertos: list[bool | None] = [True, False, None, True]

    # Act
    valor = exactitud(aciertos)

    # Assert
    assert valor == pytest.approx(2 / 3)


def test_exactitud_sin_casos_evaluables_devuelve_none() -> None:
    """Sin valores True/False no hay proporcion que calcular."""
    # Arrange
    vacios: list[bool | None] = []
    solo_none: list[bool | None] = [None, None]

    # Act
    sin_casos = exactitud(vacios)
    con_none = exactitud(solo_none)

    # Assert
    assert sin_casos is None
    assert con_none is None


def test_citas_correctas_solo_mira_preguntas_con_esperadas() -> None:
    """Cuenta las preguntas con esperadas no vacia y alguna cita coincidente."""
    # Arrange
    citadas = [[URL_A], [URL_X, URL_B], [URL_X], []]
    esperadas = [[URL_A], [URL_B], [URL_Y], []]

    # Act
    valor = citas_correctas(citadas, esperadas)

    # Assert
    assert valor == pytest.approx(2 / 3)


def test_citas_correctas_compara_urls_exactamente() -> None:
    """Una barra final no coincide con la URL esperada."""
    # Arrange
    citadas = [[URL_A + "/"]]
    esperadas = [[URL_A]]

    # Act
    valor = citas_correctas(citadas, esperadas)

    # Assert
    assert valor == 0.0


def test_citas_correctas_sin_preguntas_evaluables_devuelve_none() -> None:
    """Sin esperadas no hay proporcion que calcular."""
    # Arrange
    citadas = [[URL_A], []]
    esperadas = [[], []]

    # Act
    valor = citas_correctas(citadas, esperadas)

    # Assert
    assert valor is None


def test_resumen_uso_agrega_tokens_costo_y_tiempo() -> None:
    """Suma y promedia tokens, costo y tiempo de los registros validos."""
    # Arrange
    registros = [
        _registro(entrada=1000, salida=100, cache=400, segundos=2.0),
        _registro(entrada=3000, salida=300, cache=600, segundos=4.0),
    ]

    # Act
    resumen = resumen_uso(registros)

    # Assert
    assert resumen.registros == 2
    assert resumen.errores == 0
    assert resumen.entrada_total == 4000
    assert resumen.entrada_promedio == 2000.0
    assert resumen.salida_total == 400
    assert resumen.salida_promedio == 200.0
    assert resumen.cache_total == 1000
    assert resumen.cache_promedio == 500.0
    assert resumen.costo_usd_total == pytest.approx(0.000693)
    assert resumen.costo_usd_promedio == pytest.approx(0.0003465)
    assert resumen.tiempo_promedio == pytest.approx(3.0)
    assert resumen.tiempo_maximo == pytest.approx(4.0)


def test_resumen_uso_excluye_registros_con_error() -> None:
    """Un registro con error no suma tokens, costo ni tiempo; se cuenta aparte."""
    # Arrange
    registros = [
        _registro(entrada=1000, salida=100, cache=400, segundos=2.0),
        _registro(
            entrada=9000,
            salida=900,
            cache=900,
            segundos=90.0,
            error="timeout",
        ),
    ]

    # Act
    resumen = resumen_uso(registros)

    # Assert
    assert resumen.registros == 1
    assert resumen.errores == 1
    assert resumen.entrada_total == 1000
    assert resumen.salida_total == 100
    assert resumen.cache_total == 400
    assert resumen.costo_usd_total == pytest.approx(0.0001512)
    assert resumen.tiempo_promedio == pytest.approx(2.0)
    assert resumen.tiempo_maximo == pytest.approx(2.0)


def test_resumen_uso_sin_registros_validos_devuelve_ceros() -> None:
    """Si todos los registros tienen error, los totales quedan en cero."""
    # Arrange
    registros = [
        _registro(entrada=1000, salida=100, cache=400, segundos=2.0, error="fallo"),
        _registro(entrada=2000, salida=200, cache=500, segundos=3.0, error="timeout"),
    ]

    # Act
    resumen = resumen_uso(registros)

    # Assert
    assert resumen == ResumenUso(errores=2)


def test_resumen_uso_sin_registros_devuelve_ceros() -> None:
    """Una lista vacia produce un resumen en cero."""
    # Arrange
    registros: list[dict[str, Any]] = []

    # Act
    resumen = resumen_uso(registros)

    # Assert
    assert resumen == ResumenUso()


def test_resumen_uso_usa_el_respaldo_crudo() -> None:
    """Si no hay uso normalizado, leer_uso toma token_usage del proveedor."""
    # Arrange
    registros = [
        {
            "metricas": {
                "respuesta": {
                    "token_usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 10,
                        "prompt_cache_hit_tokens": 40,
                    }
                }
            },
            "segundos": 1.0,
            "error": "",
        }
    ]

    # Act
    resumen = resumen_uso(registros)

    # Assert
    assert resumen.entrada_total == 100
    assert resumen.salida_total == 10
    assert resumen.cache_total == 40
    assert resumen.costo_usd_total == pytest.approx(0.00001512)


def test_resumen_uso_permite_tarifas_de_pico() -> None:
    """Las tarifas de pico se pueden pasar explicitamente."""
    # Arrange
    registros = [_registro(entrada=1000, salida=100, cache=400, segundos=2.0)]

    # Act
    resumen = resumen_uso(registros, tarifas=TARIFAS_DEEPSEEK_FLASH_PICO)

    # Assert
    assert resumen.costo_usd_total == pytest.approx(0.0003024)


def test_mcnemar_ejemplo_verificado() -> None:
    """Con b=2 y c=9, la p exacta de dos colas es 134/2048."""
    # Arrange
    aciertos_v1 = [True, True] + [False] * 9
    aciertos_v2 = [False, False] + [True] * 9

    # Act
    resultado = mcnemar(aciertos_v1, aciertos_v2)

    # Assert
    assert resultado.b == 2
    assert resultado.c == 9
    assert resultado.n == 11
    assert resultado.p == pytest.approx(134 / 2048)
    assert round(resultado.p, 4) == 0.0654


def test_mcnemar_sin_discordantes_da_p_uno() -> None:
    """Si no hay pares discordantes, no hay evidencia de diferencia."""
    # Arrange
    aciertos_v1 = [True, False, True]
    aciertos_v2 = [True, False, True]

    # Act
    resultado = mcnemar(aciertos_v1, aciertos_v2)

    # Assert
    assert resultado.b == 0
    assert resultado.c == 0
    assert resultado.n == 0
    assert resultado.p == 1.0


def test_mcnemar_exige_el_mismo_largo() -> None:
    """Dos versiones se comparan pregunta a pregunta."""
    # Arrange
    aciertos_v1 = [True]
    aciertos_v2: list[bool] = []

    # Act / Assert
    with pytest.raises(ValueError):
        mcnemar(aciertos_v1, aciertos_v2)


def test_mcnemar_cuenta_b_y_c_en_su_direccion() -> None:
    """b es v1 acierta y v2 falla; c es lo contrario."""
    # Arrange
    aciertos_v1 = [True, True, False]
    aciertos_v2 = [False, False, True]

    # Act
    resultado = mcnemar(aciertos_v1, aciertos_v2)

    # Assert
    assert resultado.b == 2
    assert resultado.c == 1
    assert resultado.n == 3
    assert resultado.p == 1.0


def test_mcnemar_excluye_pares_con_none() -> None:
    """Los pares con None no cuentan en b ni c, pero si en excluidos."""
    # Arrange
    aciertos_v1 = [True, None, False, True]
    aciertos_v2 = [False, True, None, True]

    # Act
    resultado = mcnemar(aciertos_v1, aciertos_v2)

    # Assert
    assert resultado.b == 1
    assert resultado.c == 0
    assert resultado.n == 1
    assert resultado.excluidos == 2
    assert resultado.p == 1.0


def test_p_minimo_mcnemar_con_cinco_pares_supera_alfa() -> None:
    """Con n=5 el reparto mas extremo da 0.0625, mayor que ALFA."""
    # Act
    minimo = p_minimo_mcnemar(5)

    # Assert
    assert ALFA == 0.05
    assert minimo == 0.0625
    assert minimo > ALFA


def test_p_minimo_mcnemar_con_seis_pares_baja_de_alfa() -> None:
    """Con n=6 el minimo ya puede ser significativo, aunque no lo sea el observado."""
    # Act
    minimo = p_minimo_mcnemar(6)

    # Assert
    assert minimo == 0.03125
    assert minimo < ALFA


def test_p_minimo_mcnemar_sin_discordantes_da_uno() -> None:
    """Sin pares discordantes no hay reparto que pueda declarar diferencia."""
    assert p_minimo_mcnemar(0) == 1.0


def test_p_minimo_mcnemar_rechaza_n_negativo() -> None:
    """El numero de pares discordantes no puede ser negativo."""
    with pytest.raises(ValueError):
        p_minimo_mcnemar(-1)


def test_intervalo_wilson_ejemplo_23_de_36() -> None:
    """El intervalo del hit@5 de 23/36 coincide con la formula de Wilson."""
    # Act
    intervalo = intervalo_wilson(23, 36)

    # Assert
    assert intervalo is not None
    assert intervalo[0] == pytest.approx(0.4758, abs=1e-4)
    assert intervalo[1] == pytest.approx(0.7752, abs=1e-4)


def test_intervalo_wilson_sin_evaluables_devuelve_none() -> None:
    """Sin preguntas evaluables no hay intervalo."""
    assert intervalo_wilson(0, 0) is None


def test_intervalo_wilson_extremos_quedan_acotados() -> None:
    """Con cero o todos los aciertos el intervalo toca 0 o 1."""
    # Act
    ninguno = intervalo_wilson(0, 10)
    todos = intervalo_wilson(10, 10)

    # Assert
    assert ninguno is not None and ninguno[0] == 0.0
    assert todos is not None and todos[1] == 1.0
    assert ninguno[0] <= 0.0 <= ninguno[1] <= 1.0
    assert todos[0] <= 1.0 <= todos[1]


def test_intervalo_wilson_rechaza_conteos_invalidos() -> None:
    """Conteos negativos o fuera de rango se rechazan."""
    with pytest.raises(ValueError):
        intervalo_wilson(-1, 10)
    with pytest.raises(ValueError):
        intervalo_wilson(11, 10)
    with pytest.raises(ValueError):
        intervalo_wilson(5, 10, confianza=1.5)
