"""Pruebas de las herramientas de lectura y cálculo del agente `pana`."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from banco_occidente_corpus.escena import en_vivo, ficha_entrega
from banco_occidente_corpus.herramientas import lectura

RESPUESTAS = [
    "objetivo.libre_inversion",
    "vinculacion.empleado",
    "ingresos.DE_3M_A_5M",
    "gastos.DE_1M_A_2M",
    "cuotas.NINGUNA",
    "monto.DE_5M_A_10M",
    "plazo.36",
]

RESPUESTAS_VEHICULO = [
    "objetivo.vehiculo_nuevo",
    "vinculacion.empleado",
    "ingresos.DE_3M_A_5M",
    "gastos.DE_1M_A_2M",
    "cuotas.NINGUNA",
    "monto.DE_30M_A_60M",
    "plazo.48",
]


def test_consultar_tasa_lee_el_tablero() -> None:
    """La tasa vigente se devuelve con su fuente y su vigencia."""
    salida = lectura.consultar_tasa("libre inversión")
    assert salida.ok
    assert salida.datos["producto"] == "libre_inversion"
    assert salida.datos["resumen"]["fuente"]


def test_verificar_usura_compara_contra_el_limite_certificado() -> None:
    """Una tasa por encima de la usura se marca con su exceso en puntos."""
    salida = lectura.verificar_usura(0.35)
    assert salida.ok
    assert salida.datos["excede"] is True
    assert salida.datos["exceso_puntos"] == 6.66
    assert salida.datos["fuente"].startswith("https://")


def test_calcular_prestamo_gota_no_usa_modelo() -> None:
    """El gota a gota sale de la aritmética de la escena."""
    salida = lectura.calcular_prestamo_gota(1_000_000)
    assert salida.ok
    assert Decimal(str(salida.datos["interes_mensual"])) == Decimal("200000")
    assert Decimal(str(salida.datos["cuota_diaria"])) == Decimal("40000")
    assert "20 % mensual" in str(salida.datos["resumen"])


def test_diagnosticar_capacidad_devuelve_el_resultado_del_motor() -> None:
    """El diagnóstico se arma con las respuestas y el monto exacto del invitado."""
    salida = lectura.diagnosticar_capacidad(RESPUESTAS, monto=7_500_000)
    assert salida.ok
    resultado = salida.datos["resultado"]
    assert resultado["entrada"]["producto"] == "libre_inversion"
    assert resultado["semaforo"] in {"verde", "amarillo", "rojo"}


def test_comparar_escenario_no_modifica_el_original() -> None:
    """El «¿Y si…?» devuelve su tendencia y el escenario separado."""
    salida = lectura.comparar_escenario(RESPUESTAS, "plazo_meses", 60)
    assert salida.ok
    comparacion = salida.datos["comparacion"]
    assert comparacion["tendencia"] in {"mejora", "igual", "empeora"}
    assert comparacion["thread_escenario"].endswith(":esc")


def test_negociar_opcion_sin_modelo_es_determinista(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin modelo, la mesa se recorre con reglas y termina en máximo 4 turnos."""
    monkeypatch.setenv("SUCURSAL_DEMO", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    salida = lectura.negociar_opcion(RESPUESTAS)
    assert salida.ok
    assert 1 <= len(salida.datos["turnos"]) <= 4
    assert salida.datos["veredicto"]["veredicto"] in {
        "conforme",
        "con_observaciones",
        "objeta",
    }


def test_generar_ficha_opcion_tiene_texto_equivalente() -> None:
    """La ficha siempre trae su texto, sin depender de la imagen."""
    salida = lectura.generar_ficha_opcion(RESPUESTAS)
    assert salida.ok
    assert "Libre inversión" in str(salida.datos["texto"])
    assert int(salida.datos["png_bytes"]) > 0


def test_responder_sobre_proyecto_cita_la_fuente() -> None:
    """El corpus del proyecto se cita como `ruta#ancla`."""
    salida = lectura.responder_sobre_proyecto("¿cómo hicieron el RAG híbrido?")
    assert salida.ok
    assert int(salida.datos["total"]) >= 1
    fragmento = salida.datos["fragmentos"][0]
    assert "#" in str(fragmento["fuente"])
    assert len(str(fragmento["texto"]).split()) <= 41


def test_buscar_en_documentos_traduce_el_error_del_indice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si la Bóveda no está, la herramienta devuelve un error explicable."""

    def falso(pregunta: str, k: int = 5) -> dict[str, object]:
        """Devuelve el error fijo del índice ausente."""
        return {"error": {"codigo": "indice_ausente", "mensaje": "falta el índice"}}

    monkeypatch.setattr(lectura, "buscar_en_boveda", falso)
    salida = lectura.buscar_en_documentos("requisitos de ahorro")
    assert not salida.ok
    assert salida.error is not None
    assert salida.error.codigo == "indice_ausente"


def test_consultar_tarifas_lee_el_csv_del_tablero() -> None:
    """El Tablero responde con filas exactas y su fuente."""
    salida = lectura.consultar_tarifas("cheque de gerencia", limite=2)
    assert salida.ok
    filas = salida.datos["filas"]
    assert filas
    assert "fuente" in filas[0]


def test_clasificar_y_auditar_son_deterministas() -> None:
    """El Digiturno y el auditor no necesitan modelo."""
    turno = lectura.clasificar_pregunta("¿cuál es la tasa de libre inversión?")
    assert turno.ok
    assert turno.datos["letra"] == "T"

    auditor = lectura.auditar_respuesta("Tu crédito está aprobado y te lo garantizo.")
    assert auditor.ok
    assert auditor.datos["conforme"] is False
    assert auditor.datos["veredicto"] == "objeta"


def test_calcular_prestamo_gota_trae_cifras_legibles() -> None:
    """Con $2.000.000 la tasa E.A. se copia como 791,61 % y no como 7,916 %."""
    salida = lectura.calcular_prestamo_gota(2_000_000)
    assert salida.ok
    datos = salida.datos
    assert datos["tasa_ea_legible"] == "791,61 % E.A."
    assert datos["cuota_diaria_legible"] == "$80.000"
    assert datos["total_pagado_horizonte_legible"] == "$16.400.000"
    assert "791,61 % E.A." in datos["cifras_permitidas"]
    assert datos["metadatos"]["version_formula"] == "gota-v1"
    texto = json.dumps(
        {clave: valor for clave, valor in datos.items() if clave != "metadatos"},
        ensure_ascii=False,
    )
    assert "gota-v1" not in texto


def test_comparar_gota_banco_trae_las_tasas_legibles() -> None:
    """La comparación entrega la tasa del gota y la del banco sin ambigüedad."""
    salida = lectura.comparar_gota_banco(2_000_000, RESPUESTAS)
    assert salida.ok
    comparacion = salida.datos["comparacion"]
    assert comparacion["tasa_ea_gota_legible"] == "791,61 % E.A."
    assert comparacion["tasa_ea_banco_legible"].endswith("% E.A.")
    assert comparacion["usura_ea_legible"] == "28,34 % E.A."
    assert "$16.400.000" in salida.datos["cifras_permitidas"]


def test_consultar_tasa_y_simular_cuota_traen_texto_legible() -> None:
    """Los rangos de tasa y cuota llevan su `valor_legible` y sus permitidas."""
    tasa = lectura.consultar_tasa("libre inversión")
    assert tasa.ok
    assert tasa.datos["resumen"]["tasa_ea_desde_legible"].endswith("% E.A.")
    assert tasa.datos["resumen"]["valor_legible"].endswith("% E.A.")
    assert any("% E.A." in cifra for cifra in tasa.datos["cifras_permitidas"])

    cuota = lectura.simular_cuota("libre inversión", 15_000_000, 48)
    assert cuota.ok
    assert cuota.datos["tasa_ea"]["valor_legible"].endswith("% E.A.")
    assert cuota.datos["tasa_mensual"]["valor_legible"].endswith("% mensual")
    assert cuota.datos["cuota_mensual"]["valor_legible"].startswith("$")
    assert "version_formula" not in cuota.datos
    assert cuota.datos["metadatos"]["version_formula"]


def test_verificar_usura_trae_las_tasas_legibles() -> None:
    """La usura y su exceso se leen en la misma escala que la tasa de entrada."""
    salida = lectura.verificar_usura(7.9161)
    assert salida.ok
    assert salida.datos["tasa_ea_legible"] == "791,61 % E.A."
    assert salida.datos["usura_ea_legible"] == "28,34 % E.A."
    assert salida.datos["exceso_puntos_legible"] == "763,27 puntos porcentuales"


def test_auditar_respuesta_objeta_la_tasa_mal_escalada() -> None:
    """«7.916% E.A.» no está respaldado por la cifra legible de la herramienta."""
    salida = lectura.auditar_respuesta(
        "Don Gota cobra 7.916% E.A.",
        cifras_permitidas=["791,61 % E.A."],
    )
    assert salida.ok
    assert salida.datos["veredicto"] == "objeta"
    assert any("cifra_inventada" in hallazgo for hallazgo in salida.datos["hallazgos"])


def test_auditar_respuesta_objeta_un_monto_fuera_de_las_permitidas() -> None:
    """«$2.400.000 al mes» se objeta cuando solo está permitido el pago diario."""
    salida = lectura.auditar_respuesta(
        "Pagarías $2.400.000 al mes solo para no crecer la deuda.",
        cifras_permitidas=["$80.000"],
    )
    assert salida.ok
    assert salida.datos["veredicto"] == "objeta"
    assert any("cifra_inventada" in hallazgo for hallazgo in salida.datos["hallazgos"])


def test_auditar_respuesta_acepta_las_cifras_legibles_de_la_herramienta() -> None:
    """La respuesta que copia `valor_legible` queda conforme."""
    calculo = lectura.calcular_prestamo_gota(2_000_000)
    salida = lectura.auditar_respuesta(
        "Don Gota cobra 791,61 % E.A. y la cuota diaria es $80.000.",
        cifras_permitidas=calculo.datos["cifras_permitidas"],
    )
    assert salida.ok
    assert salida.datos["veredicto"] == "conforme"


# --- Escena en vivo: las herramientas publican sus turnos -----------------------


@pytest.fixture
def escena_viva(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Enciende el interruptor y manda la lista a una carpeta temporal."""
    monkeypatch.setenv("ESCENA_EN_VIVO", "1")
    ruta = tmp_path / "escena" / "en_vivo.jsonl"
    monkeypatch.setattr(en_vivo, "RUTA_EN_VIVO", ruta)
    monkeypatch.setattr(ficha_entrega, "RUTA_ENTREGA", tmp_path / "escena" / "ficha_entrega.json")
    monkeypatch.setattr(lectura, "_ULTIMA_FICHA_PUBLICADA", None)
    return ruta


def _publicados(ruta: Path) -> list[dict[str, object]]:
    """Lee todos los turnos publicados en la lista temporal."""
    registros, _ = en_vivo.leer_turnos(0, limite=1000, ruta=ruta)
    return [dict(registro) for registro in registros]


def _turnos(registros: list[dict[str, object]]) -> list[dict[str, object]]:
    """Extrae los turnos de los registros de la lista."""
    return [dict(registro["turno"]) for registro in registros]  # type: ignore[arg-type]


def test_calcular_prestamo_gota_publica_cuatro_turnos_de_don_gota(escena_viva: Path) -> None:
    """Don Gota deja sus cuatro turnos con origen de herramienta."""
    salida = lectura.calcular_prestamo_gota(1_000_000)
    assert salida.ok

    registros = _publicados(escena_viva)
    assert len(registros) == 4
    assert all(registro["origen"] == "herramienta" for registro in registros)
    turnos = _turnos(registros)
    assert [turno["personaje"] for turno in turnos] == ["don_gota"] * 4
    assert [turno["orden"] for turno in turnos] == [1, 2, 3, 4]
    assert [int(registro["seq"]) for registro in registros] == sorted(
        int(registro["seq"]) for registro in registros
    )


def test_comparar_gota_banco_publica_tres_turnos_de_pana(escena_viva: Path) -> None:
    """La comparación deja golpe, tasa y ley como turnos de Pana."""
    salida = lectura.comparar_gota_banco(1_000_000, RESPUESTAS)
    assert salida.ok

    turnos = _turnos(_publicados(escena_viva))
    assert len(turnos) == 3
    assert [turno["personaje"] for turno in turnos] == ["pana"] * 3
    assert [turno["orden"] for turno in turnos] == [8, 9, 10]


def test_negociar_opcion_publica_solo_los_dos_agentes(
    escena_viva: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La negociación publica de uno a cuatro turnos de los dos agentes."""
    monkeypatch.setenv("SUCURSAL_DEMO", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    salida = lectura.negociar_opcion(RESPUESTAS)
    assert salida.ok

    turnos = _turnos(_publicados(escena_viva))
    assert 1 <= len(turnos) <= 4
    assert {turno["personaje"] for turno in turnos} <= {"agente_joven", "agente_banco"}


def test_auditar_respuesta_publica_el_turno_del_auditor(escena_viva: Path) -> None:
    """Aun cuando objeta, el veredicto es parte de la escena."""
    salida = lectura.auditar_respuesta("Tu crédito está aprobado y te lo garantizo.")
    assert salida.ok
    assert salida.datos["veredicto"] == "objeta"

    turnos = _turnos(_publicados(escena_viva))
    assert len(turnos) == 1
    assert turnos[0]["personaje"] == "auditor"
    assert turnos[0]["orden"] == 90
    assert turnos[0]["origen"] == "reglas"


def test_el_turno_publicado_del_auditor_trae_los_hallazgos(escena_viva: Path) -> None:
    """Con una promesa de aprobación el turno publicado no dice «conforme»."""
    salida = lectura.auditar_respuesta("Tu crédito está aprobado y te lo garantizo.")
    assert salida.ok
    assert salida.datos["veredicto"] == "objeta"

    turnos = _turnos(_publicados(escena_viva))
    assert len(turnos) == 1
    assert turnos[0]["hallazgos"]
    assert "conforme" not in str(turnos[0]["texto"])


def test_el_turno_publicado_del_auditor_limpio_sigue_conforme(escena_viva: Path) -> None:
    """Un texto limpio publica el veredicto conforme y sin hallazgos."""
    salida = lectura.auditar_respuesta("Todo tiene su fuente y cada frase está sustentada.")
    assert salida.ok
    assert salida.datos["veredicto"] == "conforme"

    turnos = _turnos(_publicados(escena_viva))
    assert len(turnos) == 1
    assert turnos[0]["hallazgos"] == []
    assert "conforme" in str(turnos[0]["texto"])


def test_el_cambio_de_veredicto_no_se_oculta_como_turno_repetido(escena_viva: Path) -> None:
    """Pasar de conforme a objeta publica un turno nuevo, no lo descarta."""
    conforme = lectura.auditar_respuesta("Todo tiene su fuente y cada frase está sustentada.")
    objeta = lectura.auditar_respuesta("Tu crédito está aprobado y te lo garantizo.")
    assert conforme.datos["veredicto"] == "conforme"
    assert objeta.datos["veredicto"] == "objeta"

    turnos = _turnos(_publicados(escena_viva))
    assert len(turnos) == 2
    assert turnos[0]["hallazgos"] == []
    assert "conforme" in str(turnos[0]["texto"])
    assert turnos[1]["hallazgos"]
    assert "conforme" not in str(turnos[1]["texto"])


def test_generar_ficha_opcion_publica_un_turno_de_pana(escena_viva: Path) -> None:
    """La ficha viaja como texto equivalente, nunca como PNG en la lista."""
    salida = lectura.generar_ficha_opcion(RESPUESTAS)
    assert salida.ok

    turnos = _turnos(_publicados(escena_viva))
    assert len(turnos) == 1
    assert turnos[0]["personaje"] == "pana"
    assert turnos[0]["id"] == "vivo.ficha.v1"
    assert turnos[0]["subtitulo"] == "Ficha de la opción"
    assert turnos[0]["texto"] == salida.datos["texto"]


def test_generar_ficha_opcion_cierra_con_la_opcion_elegida_y_sus_cifras(
    escena_viva: Path,
) -> None:
    """El cierre corto no repite la otra opción y el auditor queda conforme."""
    salida = lectura.generar_ficha_opcion(RESPUESTAS_VEHICULO, monto=30_000_000, opcion="A")
    assert salida.ok
    mensaje = salida.datos["mensaje_listo"]
    assert "Elegiste la opción A" in mensaje
    assert "Ya te envié la ficha por WhatsApp" in mensaje
    assert "es orientativo" in mensaje.lower()
    assert "Opción B" not in mensaje
    assert salida.datos["texto"] not in mensaje
    auditoria = lectura.auditar_respuesta(
        mensaje,
        cifras_permitidas=salida.datos["cifras_permitidas"],
    )
    assert auditoria.datos["veredicto"] == "conforme"


def test_el_turno_de_la_ficha_trae_el_escenario_de_la_opcion_elegida(
    escena_viva: Path,
) -> None:
    """El panel de cifras recibe el plazo, la cuota y el total de la opción A."""
    salida = lectura.generar_ficha_opcion(RESPUESTAS_VEHICULO, monto=30_000_000, opcion="A")
    assert salida.ok

    turnos = _turnos(_publicados(escena_viva))
    assert len(turnos) == 1
    escenario = turnos[0]["escenario"]
    assert isinstance(escenario, dict)
    assert escenario["plazo_meses"] == 60
    assert escenario["cuota_mensual"] == salida.datos["escenario"]["cuota_mensual"]
    etiquetas = {cifra["etiqueta"] for cifra in turnos[0]["cifras"]}  # type: ignore[union-attr]
    assert {"plazo", "cuota mensual", "total pagado"} <= etiquetas


def test_los_pasos_de_la_entrevista_traen_el_mensaje_listo() -> None:
    """Cada paso trae la pregunta con sus opciones para copiar sin reescribir."""
    pasos = [
        ["objetivo.libre_inversion"],
        ["objetivo.libre_inversion", "vinculacion.empleado"],
        [
            "objetivo.libre_inversion",
            "vinculacion.empleado",
            "ingresos.DE_3M_A_5M",
        ],
        [
            "objetivo.libre_inversion",
            "vinculacion.empleado",
            "ingresos.DE_3M_A_5M",
            "gastos.DE_1M_A_2M",
        ],
        [
            "objetivo.libre_inversion",
            "vinculacion.empleado",
            "ingresos.DE_3M_A_5M",
            "gastos.DE_1M_A_2M",
            "cuotas.NINGUNA",
        ],
        [
            "objetivo.libre_inversion",
            "vinculacion.empleado",
            "ingresos.DE_3M_A_5M",
            "gastos.DE_1M_A_2M",
            "cuotas.NINGUNA",
            "monto.DE_5M_A_10M",
        ],
    ]
    for respuestas in pasos:
        salida = lectura.diagnosticar_capacidad(respuestas)
        assert salida.ok
        assert salida.datos["estado"] == "faltan_datos"
        mensaje = salida.datos["mensaje_listo"]
        assert salida.datos["pregunta"] in mensaje
        if salida.datos["opciones"]:
            primera = salida.datos["opciones"][0]
            assert f"{primera['letra']}. {primera['etiqueta']}" in mensaje


def test_el_diagnostico_completo_trae_resumen_y_cifras_permitidas() -> None:
    """El resumen copia A y B y sus cifras cubren el cierre y la ficha."""
    salida = lectura.diagnosticar_capacidad(RESPUESTAS_VEHICULO, monto=30_000_000)
    assert salida.ok
    resumen = salida.datos["resumen_escena"]
    mensaje = resumen["mensaje_listo"]
    assert "Opción A:" in mensaje
    assert "Opción B:" in mensaje
    assert "Responde A o B." in mensaje
    permitidas = resumen["cifras_permitidas"]
    assert "$880.294" in permitidas
    assert "$760.808" in permitidas
    assert "19,49 % E.A." in permitidas
    assert "1,49 % M.V." in permitidas
    assert salida.datos["mensaje_listo"] == mensaje
    assert salida.datos["cifras_permitidas"] == permitidas
    auditoria = lectura.auditar_respuesta(mensaje, cifras_permitidas=permitidas)
    assert auditoria.datos["veredicto"] == "conforme"


def test_apagado_las_herramientas_no_publican(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Sin el interruptor no se crea la carpeta de la escena en vivo."""
    monkeypatch.delenv("ESCENA_EN_VIVO", raising=False)
    ruta = tmp_path / "escena" / "en_vivo.jsonl"
    monkeypatch.setattr(en_vivo, "RUTA_EN_VIVO", ruta)

    assert lectura.calcular_prestamo_gota(1_000_000).ok
    assert lectura.comparar_gota_banco(1_000_000, RESPUESTAS).ok
    assert lectura.auditar_respuesta("Don Gota cobra 20 % mensual.").ok
    assert lectura.generar_ficha_opcion(RESPUESTAS).ok

    assert not ruta.parent.exists()


def test_un_error_de_la_herramienta_no_publica(escena_viva: Path) -> None:
    """Si la herramienta devuelve error, la lista queda vacía."""
    salida = lectura.comparar_gota_banco(1_000_000, ["respuesta.invalida"])
    assert not salida.ok
    assert _publicados(escena_viva) == []


def test_si_la_publicacion_falla_la_herramienta_responde_igual(
    escena_viva: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La publicación es un efecto lateral: un fallo no cambia el sobre."""

    def fallar(*_args: object, **_kwargs: object) -> tuple[int, ...]:
        raise OSError("disco lleno")

    monkeypatch.setattr(lectura, "publicar_turnos", fallar)
    salida = lectura.calcular_prestamo_gota(1_000_000)

    assert salida.ok
    assert salida.datos["cuota_diaria_legible"] == "$40.000"


# --- El diagnóstico completo sigue solo con la escena ---------------------------


def test_diagnostico_completo_publica_la_escena_en_orden_y_devuelve_el_resumen(
    escena_viva: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La misma llamada deja la escena en orden y las opciones A y B en el resumen."""
    monkeypatch.setenv("SUCURSAL_DEMO", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    salida = lectura.diagnosticar_capacidad(RESPUESTAS, monto=7_500_000)
    assert salida.ok
    assert "resultado" in salida.datos

    resumen = salida.datos["resumen_escena"]
    assert resumen["avisos"] == []
    assert resumen["gota"]["monto_legible"] == "$7.500.000"
    assert resumen["gota"]["tasa_ea_legible"] == "791,61 % E.A."
    assert resumen["gota"]["total_legible"] == "$61.500.000"
    assert resumen["comparacion"]["tasa_ea_banco_legible"].endswith("% E.A.")
    assert resumen["comparacion"]["total_banco_legible"].startswith("$")
    assert [opcion["letra"] for opcion in resumen["opciones"]] == ["A", "B"]
    for opcion in resumen["opciones"]:
        assert opcion["cuota_mensual_legible"].startswith("$")
        assert opcion["plazo_legible"].endswith("meses")
        assert opcion["total_pagado_legible"].startswith("$")

    registros = _publicados(escena_viva)
    turnos = _turnos(registros)
    assert [registro["origen"] for registro in registros] == ["herramienta"] * len(registros)
    seqs = [int(registro["seq"]) for registro in registros]
    assert seqs == sorted(seqs)

    assert turnos[0]["personaje"] == "pana"
    assert turnos[0]["id"] == "pana.diagnostico.v1"
    assert [turno["personaje"] for turno in turnos[1:5]] == ["don_gota"] * 4
    assert [turno["personaje"] for turno in turnos[5:8]] == ["pana"] * 3
    assert turnos[8:]
    assert {turno["personaje"] for turno in turnos[8:]} <= {"agente_joven", "agente_banco"}


def test_diagnostico_incompleto_no_publica_la_escena_continua(escena_viva: Path) -> None:
    """Sin monto exacto o con respuestas parciales no se publica nada de la escena."""
    sin_monto = lectura.diagnosticar_capacidad(RESPUESTAS)
    assert sin_monto.ok
    assert sin_monto.datos["estado"] == "faltan_datos"
    assert "resumen_escena" not in sin_monto.datos
    assert _publicados(escena_viva) == []

    parcial = lectura.diagnosticar_capacidad(["objetivo.libre_inversion"])
    assert parcial.ok
    assert parcial.datos["estado"] == "faltan_datos"
    assert "resumen_escena" not in parcial.datos
    assert _publicados(escena_viva) == []


def test_si_la_negociacion_falla_el_diagnostico_se_devuelve_igual(
    escena_viva: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un fallo de la negociación deja el diagnóstico, Don Gota y la comparación."""
    monkeypatch.setenv("SUCURSAL_DEMO", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    def fallar(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("fallo simulado de la negociación")

    monkeypatch.setattr(lectura, "negociar_opcion", fallar)
    with caplog.at_level("WARNING"):
        salida = lectura.diagnosticar_capacidad(RESPUESTAS, monto=7_500_000)

    assert salida.ok
    assert "resultado" in salida.datos
    resumen = salida.datos["resumen_escena"]
    assert lectura.AVISO_NEGOCIACION in resumen["avisos"]
    assert "opciones" not in resumen
    assert "gota" in resumen and "comparacion" in resumen
    assert "aviso negociacion" in caplog.text

    turnos = _turnos(_publicados(escena_viva))
    assert turnos[0]["id"] == "pana.diagnostico.v1"
    assert [turno["personaje"] for turno in turnos[1:5]] == ["don_gota"] * 4
