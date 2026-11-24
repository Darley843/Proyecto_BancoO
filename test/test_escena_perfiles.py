"""Pruebas de los perfiles seguros de la escena (tarea 4.5).

Los perfiles reales de `config/escena.toml` se validan contra el motor con una
tabla Gold temporal, así las pruebas no dependen de la fecha ni de la red. Los
errores de estructura se prueban con archivos TOML temporales.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from banco_occidente_corpus.escena.auditor import auditar_escena, crear_auditor_negociacion
from banco_occidente_corpus.escena.comparacion import comparar_gota_banco, turnos_pana_comparacion
from banco_occidente_corpus.escena.gota import (
    calcular_prestamo_gota,
    cargar_config_gota,
    turnos_don_gota,
)
from banco_occidente_corpus.escena.negociacion import negociar
from banco_occidente_corpus.escena.perfiles import (
    PREGUNTAS,
    RUTA_CONFIG,
    cargar_perfiles,
    entrada_del_perfil,
    opciones_escena,
    perfil_seguro,
    perfiles_seguros,
)
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

#: Perfil válido para armar archivos de prueba.
PERFIL_VERDE = """
[[perfiles]]
id = "verde_{n}"
personaje = "Estudiante que trabaja medio tiempo"
proposito = "Comprar un computador para estudiar"
monto = 4000000
letras = {{ monto = "A", ingresos = "B", gastos = "A", deudas = "A" }}
esperado = "verde"
"""


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
    raiz = tmp_path / "gold"
    raiz.mkdir()
    escribir_tabla(
        raiz / "tasas-personas-2026-11.jsonl",
        [
            _fila("libre_inversion", "0.2056", "0.2817"),
            _fila("compra_cartera", "0.1746", "0.2817"),
        ],
    )
    return raiz


@pytest.fixture()
def config_usura(tmp_path: Path) -> ConfiguracionTasas:
    """Carga una usura de prueba sin tocar `config/tasas.toml`."""
    ruta = tmp_path / "tasas.toml"
    ruta.write_text(
        "\n".join(
            (
                "[usura]",
                "tasa_ea = 0.2834",
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


def _escena_toml(tmp_path: Path, cuerpo: str) -> Path:
    """Escribe un `escena.toml` de prueba.

    Args:
        tmp_path: carpeta temporal.
        cuerpo: contenido del archivo.

    Returns:
        La ruta del archivo.
    """
    ruta = tmp_path / "escena.toml"
    ruta.write_text(cuerpo, encoding="utf-8")
    return ruta


def _con_dos_validos(perfil: str) -> str:
    """Rodea un perfil de prueba con dos perfiles válidos (el mínimo es tres).

    Args:
        perfil: tabla `[[perfiles]]` que se prueba.

    Returns:
        El contenido del archivo con tres perfiles.
    """
    return PERFIL_VERDE.format(n=1) + PERFIL_VERDE.format(n=2) + perfil


# --- Opciones A–F ----------------------------------------------------------


def test_las_letras_salen_de_la_entrevista_del_diagnostico() -> None:
    """A es la primera opción del rango y deudas usa el rango `cuotas`."""
    opciones = opciones_escena()

    assert tuple(opciones) == PREGUNTAS
    assert [op.letra for op in opciones["monto"]] == ["A", "B", "C", "D", "E"]
    assert opciones["monto"][0].opcion_id == "monto.HASTA_5M"
    assert len(opciones["ingresos"]) == 6
    assert opciones["deudas"][0].opcion_id == "cuotas.NINGUNA"
    assert opciones["deudas"][0].valor == 0
    assert opciones["monto"][3].contiene(Decimal("28000000"))
    assert not opciones["monto"][3].contiene(Decimal("60000000"))


# --- Perfiles del demo ----------------------------------------------------------


def test_los_perfiles_del_demo_coinciden_con_el_motor(raiz_tasas: Path) -> None:
    """Los perfiles de `config/escena.toml` son válidos y cubren los tres colores."""
    perfiles = cargar_perfiles(hoy=FECHA_CONSULTA, raiz=raiz_tasas)

    assert 3 <= len(perfiles) <= 5
    assert all(perfil.valido for perfil in perfiles), [p.motivo for p in perfiles]
    assert {perfil.esperado for perfil in perfiles} == {"verde", "amarillo", "rojo"}
    for perfil in perfiles:
        assert perfil.obtenido == perfil.esperado
        assert perfil.perfil.confirmado is True
        assert [r.pregunta for r in perfil.perfil.respuestas] == list(PREGUNTAS)


def test_el_perfil_por_defecto_es_el_amarillo(raiz_tasas: Path) -> None:
    """Sin id, el modo seguro usa `[seguro] por_defecto`."""
    perfil = perfil_seguro(hoy=FECHA_CONSULTA, raiz=raiz_tasas)

    assert perfil.monto_calculo == Decimal("28000000")
    assert entrada_del_perfil(perfil).monto_credito == Decimal("28000000")


def test_un_color_distinto_al_motor_no_se_usa_en_modo_seguro(
    raiz_tasas: Path, tmp_path: Path
) -> None:
    """Si el motor no confirma el color, el perfil queda fuera del modo seguro."""
    mal = PERFIL_VERDE.format(n=3).replace('esperado = "verde"', 'esperado = "rojo"')
    ruta = _escena_toml(tmp_path, _con_dos_validos(mal))

    perfiles = cargar_perfiles(ruta, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    malo = next(perfil for perfil in perfiles if perfil.id == "verde_3")

    assert malo.valido is False
    assert malo.obtenido == "verde"
    assert "espera rojo" in malo.motivo
    assert "verde_3" not in {
        perfil.id for perfil in perfiles_seguros(ruta, hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    }
    with pytest.raises(ValueError, match="no se usa en modo seguro"):
        perfil_seguro("verde_3", ruta, hoy=FECHA_CONSULTA, raiz=raiz_tasas)


def test_sin_tasa_ningun_perfil_se_usa(tmp_path: Path) -> None:
    """Si el motor no encuentra la tasa, no se promete ningún color."""
    vacia = tmp_path / "sin_tasas"
    vacia.mkdir()

    assert perfiles_seguros(hoy=FECHA_CONSULTA, raiz=vacia) == ()
    with pytest.raises(ValueError, match=r"ningún perfil seguro|no se usa"):
        perfil_seguro(hoy=FECHA_CONSULTA, raiz=vacia)


@pytest.mark.parametrize(
    ("cambio", "mensaje"),
    [
        (('monto = "A"', 'monto = "F"'), "no existe"),
        (("monto = 4000000", "monto = 9000000"), "no cae en la opción"),
        (("Estudiante que trabaja medio tiempo", "Escríbeme a ana@ejemplo.com"), "no puede"),
        (("para estudiar", "para estudiar en dos mil veintiséis 2026"), "no puede"),
        (('esperado = "verde"', 'esperado = "ambar"'), "no es un color"),
        (('id = "verde_3"', 'id = "verde_1"'), "repetido"),
    ],
)
def test_un_perfil_mal_escrito_falla_al_cargar(
    cambio: tuple[str, str], mensaje: str, raiz_tasas: Path, tmp_path: Path
) -> None:
    """Letras, montos, textos con datos, colores e ids se validan al cargar."""
    antes, despues = cambio
    perfil = PERFIL_VERDE.format(n=3).replace(antes, despues, 1)
    ruta = _escena_toml(tmp_path, _con_dos_validos(perfil))

    with pytest.raises(ValueError, match=mensaje):
        cargar_perfiles(ruta, hoy=FECHA_CONSULTA, raiz=raiz_tasas)


@pytest.mark.parametrize("cantidad", [2, 6])
def test_la_escena_necesita_entre_tres_y_cinco_perfiles(
    cantidad: int, raiz_tasas: Path, tmp_path: Path
) -> None:
    """El diseño pide de tres a cinco perfiles."""
    cuerpo = "".join(PERFIL_VERDE.format(n=n) for n in range(cantidad))
    ruta = _escena_toml(tmp_path, cuerpo)

    with pytest.raises(ValueError, match="entre 3 y 5"):
        cargar_perfiles(ruta, hoy=FECHA_CONSULTA, raiz=raiz_tasas)


def test_los_textos_de_los_perfiles_del_demo_no_llevan_datos_personales() -> None:
    """El archivo real no trae teléfonos, correos ni documentos en los perfiles."""
    texto = RUTA_CONFIG.read_text(encoding="utf-8")

    assert "@" not in texto.split("[[perfiles]]", 1)[1]


# --- El modo seguro ejecuta el auditor ------------------------------------------


def test_el_modo_seguro_pasa_por_el_auditor(
    raiz_tasas: Path, config_usura: ConfiguracionTasas
) -> None:
    """Don Gota y Pana con cada perfil seguro pasan el auditor sin hallazgos altos."""
    config = cargar_config_gota()
    for seguro in perfiles_seguros(hoy=FECHA_CONSULTA, raiz=raiz_tasas):
        perfil = seguro.perfil
        prestamo = calcular_prestamo_gota(perfil.monto_calculo, config=config)
        comparacion = comparar_gota_banco(
            prestamo,
            entrada_del_perfil(perfil),
            raiz=raiz_tasas,
            config_tasas=config_usura,
            hoy=FECHA_CONSULTA,
        )
        turnos = [
            *turnos_don_gota(prestamo, seguro.id, config=config),
            *turnos_pana_comparacion(comparacion),
        ]

        veredicto = auditar_escena(turnos, semaforo=seguro.obtenido)

        assert not any(h.gravedad == "alta" for h in veredicto.hallazgos), seguro.id
        assert bool(veredicto.alternativas) is (seguro.obtenido == "rojo")


def test_los_perfiles_seguros_negocian_como_el_diseno(raiz_tasas: Path) -> None:
    """Verde recomienda, amarillo pasa a verde, rojo cierra sin acuerdo y el auditor no objeta."""
    seguros = {
        seguro.id: seguro for seguro in perfiles_seguros(hoy=FECHA_CONSULTA, raiz=raiz_tasas)
    }

    resultados = {
        ident: negociar(
            seguro.perfil,
            auditor=crear_auditor_negociacion(semaforo=seguro.obtenido),
            entorno={"SUCURSAL_DEMO": "1"},
            hoy=FECHA_CONSULTA,
            raiz=raiz_tasas,
        )
        for ident, seguro in seguros.items()
    }

    assert resultados["verde_computador"].acuerdo is not None
    assert resultados["verde_computador"].acuerdo.semaforo == "verde"
    assert resultados["amarillo_negocio"].acuerdo is not None
    assert resultados["amarillo_negocio"].acuerdo.semaforo == "verde"
    assert resultados["rojo_moto"].acuerdo is None
    for resultado in resultados.values():
        veredicto = resultado.negociacion.veredicto
        assert veredicto.veredicto != "objeta"
        assert not any(h.gravedad == "alta" for h in veredicto.hallazgos)
