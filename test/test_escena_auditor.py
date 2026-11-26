"""Pruebas del auditor de la escena: reglas, veredicto sin colores y cierres.

Los turnos limpios salen del código real: Don Gota de `escena.gota` y Pana de
`escena.comparacion`, contra una tabla Gold temporal y una usura de prueba. Las
reglas se prueban mutando esos turnos, así cada regla tiene un caso que la
dispara y la escena original sigue conforme. Ninguna prueba usa red ni modelo.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from banco_occidente_corpus.canal.contratos import EntradaDiagnostico
from banco_occidente_corpus.escena.auditor import (
    ALTERNATIVAS_FORMALES,
    ETIQUETA_VEREDICTO,
    REGLAS,
    REGLAS_ALTAS,
    REGLAS_MEDIAS,
    auditar_escena,
    auditar_negociacion,
    auditar_turno,
    cierre_pana,
    crear_auditor_negociacion,
    etiqueta_veredicto,
    permite_cierre_favorable,
    turno_auditor,
    veredicto_desde_hallazgos,
)
from banco_occidente_corpus.escena.comparacion import (
    alertas_comparacion,
    comparar_gota_banco,
    turnos_pana_comparacion,
)
from banco_occidente_corpus.escena.contratos import (
    EscenarioEscena,
    FuenteCifra,
    HallazgoEscena,
    TurnoEscena,
    VeredictoAuditor,
)
from banco_occidente_corpus.escena.gota import (
    calcular_prestamo_gota,
    cargar_config_gota,
    turnos_don_gota,
)
from banco_occidente_corpus.escena.negociacion import negociar
from banco_occidente_corpus.tablero.tasas import (
    ConfiguracionTasas,
    FilaTasa,
    cargar_config_tasas,
    escribir_tabla,
)

#: Vigencia de la tabla Gold de prueba.
VIGENCIA_DESDE = date(2026, 11, 1)
VIGENCIA_HASTA = date(2026, 11, 30)
#: Fecha fija de consulta, dentro de la vigencia.
FECHA_CONSULTA = date(2026, 11, 16)
#: Huella del PDF de tasas de la vigencia.
SHA_EJEMPLO = "989be43a0ed19eb33e2057cd01c1ae612b6f15544eaaf41af6348846a6ff1b7f"
#: URL de la fuente de las tasas.
FUENTE = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"
#: Colores del semáforo; ninguno puede ser un veredicto.
COLORES = ("verde", "amarillo", "rojo")


def _fila(producto: str, desde: str, hasta: str) -> FilaTasa:
    """Construye una fila de la tabla Gold de prueba.

    Args:
        producto: clave canónica del producto.
        desde: tasa E.A. mínima publicada.
        hasta: tasa E.A. máxima publicada.

    Returns:
        La fila lista para escribir la tabla.
    """
    return FilaTasa(
        producto=producto,
        tipo_tasa="fija",
        tasa_ea_desde=Decimal(desde),
        tasa_ea_hasta=Decimal(hasta),
        vigencia_desde=VIGENCIA_DESDE,
        vigencia_hasta=VIGENCIA_HASTA,
        fuente=FUENTE,
        sha256_pdf=SHA_EJEMPLO,
        fecha_extraccion=VIGENCIA_DESDE,
    )


@pytest.fixture()
def raiz_tasas(tmp_path: Path) -> Path:
    """Crea una tabla Gold temporal con libre inversión y compra de cartera."""
    escribir_tabla(
        tmp_path / "tasas-personas-2026-11.jsonl",
        [
            _fila("libre_inversion", "0.2056", "0.2817"),
            _fila("compra_cartera", "0.1746", "0.2817"),
        ],
    )
    return tmp_path


def _config_usura(tmp_path: Path, tasa: str) -> ConfiguracionTasas:
    """Carga una usura de prueba sin tocar `config/tasas.toml`.

    Args:
        tmp_path: carpeta temporal de la prueba.
        tasa: tasa E.A. de usura; ``0.0`` significa sin certificar.

    Returns:
        La configuración de tasas de prueba.
    """
    ruta = tmp_path / f"tasas-{tasa}.toml"
    ruta.write_text(
        "\n".join(
            (
                "[usura]",
                f"tasa_ea = {tasa}",
                'vigencia_desde = "2026-11-01"',
                'vigencia_hasta = "2026-11-30"',
                'fuente = "https://www.superfinanciera.gov.co/"',
                'resolucion = "Resolución 1707 de 2026"',
                'exceptuados = ["vivienda", "ahorro", "cdt"]',
                "",
            )
        ),
        encoding="utf-8",
    )
    return cargar_config_tasas(ruta)


def _entrada(
    ingreso: int = 3_000_000,
    gastos: int = 1_000_000,
    deudas: int = 0,
    monto: int = 1_000_000,
) -> EntradaDiagnostico:
    """Perfil ficticio para el motor del diagnóstico.

    Args:
        ingreso: ingreso mensual, en pesos.
        gastos: gastos fijos mensuales, en pesos.
        deudas: cuotas actuales de deudas, en pesos.
        monto: monto del crédito, en pesos.

    Returns:
        La entrada validada del diagnóstico.
    """
    return EntradaDiagnostico(
        producto="libre_inversion",
        vinculacion="empleado",
        ingreso_mensual=Decimal(ingreso),
        gastos_mensuales=Decimal(gastos),
        cuotas_deudas=Decimal(deudas),
        monto_credito=Decimal(monto),
        plazo_meses=36,
    )


def _escena_base(raiz: Path, tmp_path: Path, usura: str = "0.2834") -> list[TurnoEscena]:
    """Turnos reales de Don Gota y de la comparación de Pana.

    Args:
        raiz: tabla Gold temporal.
        tmp_path: carpeta temporal para la usura.
        usura: tasa de usura de prueba.

    Returns:
        Los cuatro turnos de Don Gota seguidos de los tres de Pana.
    """
    config = cargar_config_gota()
    prestamo = calcular_prestamo_gota(Decimal("1000000"), config=config)
    comparacion = comparar_gota_banco(
        prestamo,
        _entrada(),
        raiz=raiz,
        config_tasas=_config_usura(tmp_path, usura),
        hoy=FECHA_CONSULTA,
    )
    return [
        *turnos_don_gota(prestamo, "verde_empleado", config=config),
        *turnos_pana_comparacion(comparacion),
    ]


def _turno(escena: list[TurnoEscena], ident: str) -> TurnoEscena:
    """Busca un turno por id.

    Args:
        escena: turnos de la escena.
        ident: id del turno.

    Returns:
        El turno buscado.
    """
    return next(turno for turno in escena if turno.id == ident)


def _escenario(semaforo: str) -> EscenarioEscena:
    """Escenario de la mesa con el semáforo indicado.

    Args:
        semaforo: color que dejó el motor.

    Returns:
        El escenario `base` de prueba.
    """
    return EscenarioEscena(
        codigo="base",
        descripcion="El crédito que pediste a 36 meses",
        producto="libre_inversion",
        monto=Decimal("30000000"),
        plazo_meses=36,
        semaforo=semaforo,
        aceptable=semaforo != "rojo",
        ofertable=True,
    )


def _codigos(hallazgos: tuple[HallazgoEscena, ...]) -> set[str]:
    """Códigos de un conjunto de hallazgos.

    Args:
        hallazgos: hallazgos del auditor.

    Returns:
        Sus códigos.
    """
    return {hallazgo.codigo for hallazgo in hallazgos}


# --- Escena limpia ---------------------------------------------------------


def test_la_escena_real_de_don_gota_y_pana_queda_conforme(raiz_tasas: Path, tmp_path: Path) -> None:
    """Los turnos que produce el código no disparan ninguna regla."""
    escena = _escena_base(raiz_tasas, tmp_path)

    veredicto = auditar_escena(escena)

    assert veredicto.veredicto == "conforme"
    assert veredicto.hallazgos == ()
    assert veredicto.turnos_revisados == tuple(turno.id for turno in escena)
    assert veredicto.reglas == REGLAS
    assert veredicto.alternativas == ()


def test_el_articulo_305_y_el_anio_de_la_vigencia_no_son_cifras_inventadas(
    raiz_tasas: Path, tmp_path: Path
) -> None:
    """El turno de la ley cita el artículo y la vigencia sin falsos positivos."""
    ley = _turno(_escena_base(raiz_tasas, tmp_path), "pana.ley.v1")

    assert "305" in ley.texto
    assert auditar_turno(ley) == ()


# --- Una regla alta por caso -------------------------------------------------

#: Mutaciones sobre la oferta de Don Gota y la regla que cada una debe disparar.
MUTACIONES_GOTA: tuple[tuple[str, Callable[[TurnoEscena], TurnoEscena]], ...] = (
    (
        "cifra_inventada",
        lambda turno: turno.model_copy(update={"texto": f"{turno.texto} Y otros $2.500.000."}),
    ),
    (
        "fuente_ausente",
        lambda turno: turno.model_copy(
            update={
                "cifras": (
                    turno.cifras[0].model_copy(
                        update={"fuente": FuenteCifra(tipo="motor", referencia="me lo inventé")}
                    ),
                    *turno.cifras[1:],
                )
            }
        ),
    ),
    (
        "fuente_ausente",
        lambda turno: turno.model_copy(
            update={
                "cifras": (
                    turno.cifras[0].model_copy(update={"valor": Decimal("999")}),
                    *turno.cifras[1:],
                )
            }
        ),
    ),
    (
        "promesa_aprobacion",
        lambda turno: turno.model_copy(update={"texto": f"{turno.texto} Te lo apruebo ya."}),
    ),
    (
        "dato_personal",
        lambda turno: turno.model_copy(
            update={"texto": f"{turno.texto} Escríbeme a ana.prueba@ejemplo.com."}
        ),
    ),
)


@pytest.mark.parametrize(("regla", "mutar"), MUTACIONES_GOTA)
def test_cada_regla_alta_se_dispara_y_la_escena_objeta(
    regla: str,
    mutar: Callable[[TurnoEscena], TurnoEscena],
    raiz_tasas: Path,
    tmp_path: Path,
) -> None:
    """Una mutación en la oferta de Don Gota hace objetar la escena completa."""
    escena = _escena_base(raiz_tasas, tmp_path)
    escena[0] = mutar(escena[0])

    veredicto = auditar_escena(escena)

    assert regla in _codigos(veredicto.hallazgos)
    assert veredicto.veredicto == "objeta"
    assert veredicto.alternativas == ALTERNATIVAS_FORMALES
    assert all(
        hallazgo.turno_id == escena[0].id
        for hallazgo in veredicto.hallazgos
        if hallazgo.codigo == regla
    )


def test_pana_que_recomienda_el_gota_a_gota_hace_objetar(raiz_tasas: Path, tmp_path: Path) -> None:
    """Si Pana recomienda el gota a gota, el hallazgo es alto."""
    escena = _escena_base(raiz_tasas, tmp_path)
    golpe = _turno(escena, "pana.golpe.v1")
    escena[escena.index(golpe)] = golpe.model_copy(
        update={"texto": f"{golpe.texto} Te recomiendo el gota a gota."}
    )

    veredicto = auditar_escena(escena)

    assert "recomienda_gota" in _codigos(veredicto.hallazgos)
    assert veredicto.veredicto == "objeta"


def test_don_gota_esta_exento_de_recomendar_el_gota_pero_no_de_lo_demas(
    raiz_tasas: Path, tmp_path: Path
) -> None:
    """Don Gota puede ofrecer el gota a gota, pero no prometer ni inventar cifras."""
    oferta = _escena_base(raiz_tasas, tmp_path)[0]
    assert oferta.personaje == "don_gota"

    se_ofrece = oferta.model_copy(update={"texto": f"{oferta.texto} Te recomiendo el gota a gota."})
    promete = oferta.model_copy(update={"texto": f"{oferta.texto} Queda garantizado."})

    assert auditar_turno(se_ofrece) == ()
    assert "promesa_aprobacion" in _codigos(auditar_turno(promete))


def test_el_texto_del_invitado_no_se_audita_como_si_fuera_pana() -> None:
    """El invitado puede escribir cifras y preguntar por una aprobación."""
    turno = TurnoEscena(
        id="canal.invitado.v1",
        orden=0,
        personaje="invitado",
        texto="¿Me lo aprueban? Son $2.500.000 y ya está aprobado.",
        origen="canal",
    )

    assert auditar_turno(turno) == ()


def test_el_invitado_sigue_sujeto_a_la_regla_de_datos_personales() -> None:
    """Eximir el texto del invitado no desactiva la revisión de PII."""
    turno = TurnoEscena(
        id="canal.invitado.v1",
        orden=0,
        personaje="invitado",
        texto="¿Me lo aprueban? Escríbeme a ana.prueba@ejemplo.com.",
        origen="canal",
    )

    assert "dato_personal" in _codigos(auditar_turno(turno))


@pytest.mark.parametrize(
    "texto",
    [
        "El escenario queda en verde. La decisión final es del banco, por sus canales oficiales.",
        "Esta opción es sostenible y cabe con holgura. La decisión final es del banco, por sus "
        "canales oficiales.",
    ],
)
def test_el_banco_no_puede_cambiar_el_color_del_motor(texto: str) -> None:
    """Nombrar otro color o dar por sostenible un rojo es `semaforo_alterado`."""
    turno = TurnoEscena(
        id="negociacion.agente_banco.2.v1",
        orden=12,
        personaje="agente_banco",
        texto=texto,
        escenario=_escenario("rojo"),
        origen="llm",
    )

    assert "semaforo_alterado" in _codigos(auditar_turno(turno))


def test_decir_que_un_rojo_no_cabe_no_es_un_hallazgo() -> None:
    """«No cabe en tu capacidad» sobre un rojo es lo correcto."""
    turno = TurnoEscena(
        id="negociacion.agente_banco.2.v1",
        orden=12,
        personaje="agente_banco",
        texto="No cabe en tu capacidad. La decisión final es del banco, por sus canales oficiales.",
        escenario=_escenario("rojo"),
        origen="reglas",
    )

    assert auditar_turno(turno) == ()


# --- Negaciones -------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "dispara"),
    [
        ("Todavía no está aprobado: lo decide el banco.", False),
        ("Sin papeles y rápido. Queda garantizado.", True),
        ("No te conviene el gota a gota.", False),
        ("Es mejor el banco que Don Gota.", False),
        ("Mejor con Don Gota, es más rápido.", True),
    ],
)
def test_la_negacion_vale_solo_dentro_de_la_misma_oracion(texto: str, dispara: bool) -> None:
    """Una negación anterior al punto no desactiva una promesa de la oración siguiente."""
    turno = TurnoEscena(
        id="pana.prueba.v1", orden=1, personaje="pana", texto=texto, origen="reglas"
    )

    hallazgos = _codigos(auditar_turno(turno))

    assert bool(hallazgos & {"promesa_aprobacion", "recomienda_gota"}) is dispara


@pytest.mark.parametrize(
    ("texto", "regla", "dispara"),
    [
        ("Sin duda está aprobado.", "promesa_aprobacion", True),
        ("No solo está aprobado, también es barato.", "promesa_aprobacion", True),
        ("No te preocupes: te lo aprueban.", "promesa_aprobacion", True),
        ("Sin duda te lo apruebo.", "promesa_aprobacion", True),
        ("Ya es tuyo.", "promesa_aprobacion", True),
        ("No te lo apruebo yo: decide el banco.", "promesa_aprobacion", False),
        ("Este resultado no es una aprobación.", "promesa_aprobacion", False),
        ("Ninguna opción está garantizada.", "promesa_aprobacion", False),
        ("Ve donde el gota a gota, es más rápido.", "recomienda_gota", True),
        ("Ándate donde Don Gota.", "recomienda_gota", True),
        ("Vete a donde el gota a gota.", "recomienda_gota", True),
        ("No vaya donde el gota a gota.", "recomienda_gota", False),
        ("No, te recomiendo el gota a gota.", "recomienda_gota", True),
    ],
)
def test_la_escena_niega_igual_que_el_comite(texto: str, regla: str, dispara: bool) -> None:
    """«Sin duda» y «no solo» no niegan; la negación vale en la misma cláusula, sin cruzar comas."""
    turno = TurnoEscena(
        id="pana.prueba.v1", orden=1, personaje="pana", texto=texto, origen="reglas"
    )

    assert (regla in _codigos(auditar_turno(turno))) is dispara


# --- Observaciones medias ----------------------------------------------------


def test_la_usura_sin_certificar_deja_observaciones(raiz_tasas: Path, tmp_path: Path) -> None:
    """Sin usura certificada la escena no puede quedar conforme."""
    escena = _escena_base(raiz_tasas, tmp_path, usura="0.0")
    config = cargar_config_gota()
    prestamo = calcular_prestamo_gota(Decimal("1000000"), config=config)
    alertas = alertas_comparacion(
        comparar_gota_banco(
            prestamo,
            _entrada(),
            raiz=raiz_tasas,
            config_tasas=_config_usura(tmp_path, "0.0"),
            hoy=FECHA_CONSULTA,
        )
    )

    veredicto = auditar_escena(escena, alertas=alertas)

    assert _codigos(veredicto.hallazgos) == {"usura_sin_certificar"}
    assert veredicto.veredicto == "con_observaciones"


@pytest.mark.parametrize("alerta", ["tasa_no_disponible", "vigencia_vencida"])
def test_las_alertas_del_motor_son_observaciones(alerta: str) -> None:
    """Una alerta de la tasa queda como observación media."""
    veredicto = auditar_escena([], alertas=[alerta])

    assert _codigos(veredicto.hallazgos) == {alerta}
    assert veredicto.veredicto == "con_observaciones"


def test_el_nucleo_sin_negociacion_queda_con_observaciones(
    raiz_tasas: Path, tmp_path: Path
) -> None:
    """Si se exigía la negociación y no hay turnos de los agentes, se observa."""
    veredicto = auditar_escena(_escena_base(raiz_tasas, tmp_path), exigir_negociacion=True)

    assert _codigos(veredicto.hallazgos) == {"sin_negociacion"}
    assert veredicto.veredicto == "con_observaciones"


def test_sin_acuerdo_ofrece_las_alternativas_formales() -> None:
    """Una negociación sin acuerdo queda con observaciones y con alternativas."""
    veredicto = auditar_negociacion([], [_escenario("rojo")], None)

    assert {"sin_acuerdo", "sin_negociacion"} <= _codigos(veredicto.hallazgos)
    assert veredicto.veredicto == "con_observaciones"
    assert veredicto.alternativas == ALTERNATIVAS_FORMALES


def test_un_perfil_rojo_recibe_alternativas_aunque_el_auditor_este_conforme() -> None:
    """Con el semáforo en rojo Pana ofrece alternativas aunque no haya hallazgos."""
    veredicto = auditar_escena([], semaforo="rojo")

    assert veredicto.veredicto == "conforme"
    assert veredicto.alternativas == ALTERNATIVAS_FORMALES


# --- Veredicto sin colores (4.3) --------------------------------------------


def test_la_gravedad_define_el_veredicto() -> None:
    """Alta → objeta; solo medias → con observaciones; ninguna → conforme."""
    alta = HallazgoEscena(codigo="cifra_inventada", detalle="x", gravedad="alta")
    media = HallazgoEscena(codigo="sin_acuerdo", detalle="x", gravedad="media")

    assert veredicto_desde_hallazgos([alta, media]) == "objeta"
    assert veredicto_desde_hallazgos([media]) == "con_observaciones"
    assert veredicto_desde_hallazgos([]) == "conforme"
    assert set(REGLAS_ALTAS).isdisjoint(REGLAS_MEDIAS)


@pytest.mark.parametrize("color", COLORES)
def test_el_veredicto_no_acepta_colores(color: str) -> None:
    """Un color del semáforo no es un veredicto del auditor."""
    with pytest.raises(ValidationError):
        VeredictoAuditor(veredicto=color, hallazgos=(), turnos_revisados=(), reglas=())


def test_la_etiqueta_del_veredicto_no_usa_colores() -> None:
    """La pantalla recibe una etiqueta distinta del semáforo del crédito."""
    for veredicto, etiqueta in ETIQUETA_VEREDICTO.items():
        modelo = VeredictoAuditor(veredicto=veredicto, hallazgos=(), turnos_revisados=(), reglas=())
        assert etiqueta_veredicto(modelo) == etiqueta
        assert not any(color in etiqueta.casefold() for color in COLORES)


def test_objeta_bloquea_el_cierre_favorable() -> None:
    """Con `objeta` la UI no habilita el cierre verde."""
    objeta = VeredictoAuditor(veredicto="objeta", hallazgos=(), turnos_revisados=(), reglas=())
    conforme = VeredictoAuditor(veredicto="conforme", hallazgos=(), turnos_revisados=(), reglas=())

    assert permite_cierre_favorable(objeta) is False
    assert permite_cierre_favorable(conforme) is True


# --- Cierres de Pana y turno del auditor (4.4) --------------------------------


@pytest.mark.parametrize("veredicto", ["conforme", "con_observaciones", "objeta"])
@pytest.mark.parametrize("con_alternativas", [False, True])
def test_los_cierres_pasan_su_propio_auditor(veredicto: str, con_alternativas: bool) -> None:
    """Los cierres de Pana y del auditor no prometen, no recomiendan el gota y son cortos."""
    modelo = VeredictoAuditor(
        veredicto=veredicto,
        hallazgos=(),
        turnos_revisados=(),
        reglas=REGLAS,
        alternativas=ALTERNATIVAS_FORMALES if con_alternativas else (),
    )

    for turno in (cierre_pana(modelo, orden=20), turno_auditor(modelo, orden=19)):
        assert auditar_turno(turno) == ()
        assert turno.origen == "reglas"
        assert turno.cifras == ()
        assert len(turno.texto.split()) <= 40
        assert not any(color in turno.texto.casefold() for color in COLORES)


def test_si_el_auditor_objeta_pana_ofrece_las_alternativas_formales() -> None:
    """`objeta` cierra con microcrédito, cooperativas y entidades vigiladas."""
    objeta = VeredictoAuditor(
        veredicto="objeta",
        hallazgos=(),
        turnos_revisados=(),
        reglas=REGLAS,
        alternativas=ALTERNATIVAS_FORMALES,
    )

    cierre = cierre_pana(objeta, orden=20)

    assert cierre.personaje == "pana"
    for alternativa in ALTERNATIVAS_FORMALES:
        assert alternativa in cierre.texto


def test_un_cierre_conforme_recuerda_que_decide_el_banco() -> None:
    """Sin alternativas, Pana recuerda que es orientativo y que decide el banco."""
    conforme = VeredictoAuditor(veredicto="conforme", hallazgos=(), turnos_revisados=(), reglas=())

    cierre = cierre_pana(conforme, orden=20)

    assert "orientativo" in cierre.texto
    assert "la decisión final es del banco, por sus canales oficiales." in cierre.texto
    assert not any(alternativa in cierre.texto for alternativa in ALTERNATIVAS_FORMALES)


# --- Integración con la negociación (#178) -----------------------------------


@pytest.mark.parametrize(
    ("perfil", "veredicto", "con_alternativas"),
    [
        (_entrada(5_000_000, 2_000_000, 0, 10_000_000), "conforme", False),
        (_entrada(3_000_000, 1_200_000, 0, 25_000_000), "conforme", False),
        (_entrada(2_000_000, 1_500_000, 0, 30_000_000), "con_observaciones", True),
    ],
    ids=["verde", "amarillo", "rojo"],
)
def test_el_auditor_inyectado_revisa_la_negociacion_real(
    perfil: EntradaDiagnostico,
    veredicto: str,
    con_alternativas: bool,
    raiz_tasas: Path,
) -> None:
    """La negociación determinista pasa el auditor sin falsos positivos."""
    resultado = negociar(
        perfil,
        auditor=crear_auditor_negociacion(),
        entorno={"SUCURSAL_DEMO": "1"},
        hoy=FECHA_CONSULTA,
        raiz=raiz_tasas,
    )

    final = resultado.negociacion.veredicto
    assert final.veredicto == veredicto
    assert not any(hallazgo.gravedad == "alta" for hallazgo in final.hallazgos)
    assert bool(final.alternativas) is con_alternativas
    assert final.turnos_revisados == tuple(turno.id for turno in resultado.negociacion.turnos)


# --- Fuentes de documento ----------------------------------------------------


@pytest.mark.parametrize(
    ("referencia", "valida"),
    [
        ("README.md#arquitectura", True),
        ("AGENTS.md#reglas", True),
        ("CONSTITUTION.md#base-de-datos-vectorial", True),
        ("docs/ARQUEO.md#metricas", True),
        ("docs/CONSTITUTION-curso-TAAML.md#rubrica", True),
        ("CONSTITUTION.md", False),
        ("SECRETOS.md#clave", False),
        ("src/README.md#arquitectura", False),
        ("data/noticias/README.md#fuentes", False),
        ("docs/../config/secretos.md#clave", False),
    ],
)
def test_las_fuentes_de_documento_aceptan_los_archivos_de_la_raiz(
    referencia: str, valida: bool
) -> None:
    """README, AGENTS y CONSTITUTION de la raíz citan como documento; otras rutas no."""
    config = cargar_config_gota()
    prestamo = calcular_prestamo_gota(Decimal(1_000_000), config=config)
    oferta = turnos_don_gota(prestamo, config=config)[0]
    cifra = oferta.cifras[0].model_copy(
        update={"fuente": FuenteCifra(tipo="documento", referencia=referencia)}
    )
    turno = oferta.model_copy(update={"cifras": (cifra, *oferta.cifras[1:])})

    codigos = {hallazgo.codigo for hallazgo in auditar_turno(turno)}

    assert ("fuente_ausente" not in codigos) is valida
