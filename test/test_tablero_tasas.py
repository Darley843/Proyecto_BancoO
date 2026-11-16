"""Pruebas de la extracción de tasas y de la validación de usura (sin red).

El PDF vive en Bronze y no se versiona, así que la extracción se prueba con un
texto de muestra que reproduce la maquetación del PDF: tablas «desde/hasta»,
notas de vigencia, mora, comisiones, seguros y tablas variables que deben
quedar fuera.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from banco_occidente_corpus.tablero.tasas import (
    FilaTasa,
    TablaIncompleta,
    TasaFueraDeRango,
    TasaIncoherente,
    TasaSobreUsura,
    Usura,
    UsuraSinCertificar,
    cargar_config_tasas,
    escribir_tabla,
    filas_desde_texto,
    leer_tabla,
    validar_coherencia_tasas,
    validar_filas,
    validar_usura,
)

#: Texto de muestra que imita la extracción de `pypdfium2`.
FIXTURE: Path = Path(__file__).parent / "fixtures" / "tasas-personas-muestra.txt"
#: Huella de ejemplo con el largo del PDF real.
SHA_EJEMPLO = "989be43a0ed19eb33e2057cd01c1ae612b6f15544eaaf41af6348846a6ff1b7f"
#: Fecha de extracción de las pruebas.
FECHA = date(2026, 11, 16)
#: Productos del alcance que el PDF debe publicar.
PRODUCTOS_ESPERADOS = {
    "libre_inversion",
    "compra_cartera",
    "credito_rotativo",
    "libranza",
    "vehiculo_nuevo",
    "vehiculo_usado",
    "vivienda",
    "tarjeta_credito",
    "ahorro",
    "cdt",
}


@pytest.fixture()
def texto_muestra() -> str:
    """Devuelve el texto de muestra del PDF de tasas."""
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture()
def filas_muestra(texto_muestra: str) -> list[FilaTasa]:
    """Extrae las filas del texto de muestra con la vigencia de la fuente."""
    config = cargar_config_tasas()
    return filas_desde_texto(
        texto_muestra,
        fuente=config.fuente,
        sha256_pdf=SHA_EJEMPLO,
        fecha_extraccion=FECHA,
        vigencia_desde=config.vigencia_desde,
        vigencia_hasta=config.vigencia_hasta,
    )


def _buscar(
    filas: list[FilaTasa],
    producto: str,
    segmento: str | None = None,
    plazo_dias: int | None = None,
) -> FilaTasa:
    """Devuelve la única fila de un producto, segmento y plazo, o falla."""
    encontradas = [
        fila
        for fila in filas
        if fila.producto == producto and fila.segmento == segmento and fila.plazo_dias == plazo_dias
    ]
    assert len(encontradas) == 1, f"{producto}/{segmento}/{plazo_dias}: {len(encontradas)} filas"
    return encontradas[0]


def test_extrae_los_diez_productos(filas_muestra: list[FilaTasa]) -> None:
    """La tabla publica los diez productos del alcance una sola vez por segmento."""
    assert {fila.producto for fila in filas_muestra} == PRODUCTOS_ESPERADOS
    assert len(filas_muestra) == 53
    claves = [(fila.producto, fila.segmento, fila.plazo_dias) for fila in filas_muestra]
    assert len(claves) == len(set(claves))


def test_conserva_los_rangos_publicados(filas_muestra: list[FilaTasa]) -> None:
    """Los extremos E.A. y M.V. se copian del PDF, sin redondear ni invertir."""
    libre = _buscar(filas_muestra, "libre_inversion")
    assert (libre.tasa_ea_desde, libre.tasa_ea_hasta) == (Decimal("0.2056"), Decimal("0.2817"))
    assert (libre.tasa_mv_desde, libre.tasa_mv_hasta) == (Decimal("0.0157"), Decimal("0.0209"))

    cartera = _buscar(filas_muestra, "compra_cartera")
    assert (cartera.tasa_ea_desde, cartera.tasa_ea_hasta) == (Decimal("0.1746"), Decimal("0.2817"))

    rotativo = _buscar(filas_muestra, "credito_rotativo", "Compra de cartera")
    assert (rotativo.tasa_ea_desde, rotativo.tasa_ea_hasta) == (
        Decimal("0.1746"),
        Decimal("0.2727"),
    )
    assert (rotativo.tasa_mv_desde, rotativo.tasa_mv_hasta) == (
        Decimal("0.0135"),
        Decimal("0.0203"),
    )

    nuevo = _buscar(filas_muestra, "vehiculo_nuevo", "Persona natural")
    assert (nuevo.tasa_ea_desde, nuevo.tasa_ea_hasta) == (Decimal("0.1949"), Decimal("0.1949"))
    assert (nuevo.tasa_mv_desde, nuevo.tasa_mv_hasta) == (Decimal("0.0149"), Decimal("0.0149"))

    usada = _buscar(filas_muestra, "vivienda", "Crédito hipotecario")
    assert (usada.tasa_ea_desde, usada.tasa_ea_hasta) == (Decimal("0.1517"), Decimal("0.1854"))


def test_libranza_conserva_sus_tres_segmentos(filas_muestra: list[FilaTasa]) -> None:
    """La libranza se publica por segmento y no se colapsa en una sola fila."""
    segmentos = {
        fila.segmento: (fila.tasa_ea_desde, fila.tasa_ea_hasta)
        for fila in filas_muestra
        if fila.producto == "libranza"
    }
    assert segmentos == {
        "Libre inversión": (Decimal("0.1539"), Decimal("0.2431")),
        "Compra de cartera": (Decimal("0.1471"), Decimal("0.2343")),
        "Retanqueo": (Decimal("0.143"), Decimal("0.23")),
    }


def test_tarjeta_publica_pesos_y_dolares_sin_inventar_mv(filas_muestra: list[FilaTasa]) -> None:
    """La tarjeta conserva las dos monedas y deja la M.V. vacía: el PDF da n.v."""
    tarjetas = [fila for fila in filas_muestra if fila.producto == "tarjeta_credito"]
    assert len(tarjetas) == 2
    pesos = _buscar(filas_muestra, "tarjeta_credito", "Pesos")
    dolares = _buscar(filas_muestra, "tarjeta_credito", "Dólares")
    assert pesos.tasa_ea_desde == pesos.tasa_ea_hasta == Decimal("0.2819")
    assert dolares.tasa_ea_desde == dolares.tasa_ea_hasta == Decimal("0.2374")
    assert pesos.tasa_mv_desde is None and pesos.tasa_mv_hasta is None


def test_excluye_mora_comisiones_seguros_y_tablas_variables(filas_muestra: list[FilaTasa]) -> None:
    """Mora, comisiones, seguros, sobregiro y KUBO no entran en la tabla de tasas."""
    tasas = {fila.tasa_ea_desde for fila in filas_muestra} | {
        fila.tasa_ea_hasta for fila in filas_muestra
    }
    for ajena in ("0.10", "0.0769", "0.003910", "0.00011753"):
        assert Decimal(ajena) not in tasas
    assert all("mora" not in fila.producto for fila in filas_muestra)


def test_producto_ausente_no_se_inventa() -> None:
    """Si el PDF no publica una tabla, no aparece una fila con una tasa inventada."""
    texto = (
        "Tasas de Captación Cuenta de Ahorros\n"
        "Montos Tasa % ( E.A)\n"
        "De 0 a $5.000.000 0,01%\n"
        "*Vigencia del 01 al 30 de Noviembre de 2026\n"
        "KUBO\n"
    )
    filas = filas_desde_texto(
        texto,
        fuente="https://www.bancodeoccidente.com.co/tarifas",
        sha256_pdf=SHA_EJEMPLO,
        fecha_extraccion=FECHA,
        vigencia_desde=date(2026, 11, 1),
        vigencia_hasta=date(2026, 11, 30),
    )
    assert {fila.producto for fila in filas} == {"ahorro"}
    assert len(filas) == 1


def test_tabla_ilegible_no_publica_una_tabla_incompleta(texto_muestra: str) -> None:
    """Un renglón al que le falta una columna frena la publicación."""
    roto = texto_muestra.replace(
        "Tasa E.A 15,39% 24,31% 14,71% 23,43% 14,30% 23,00%",
        "Tasa E.A 15,39% 24,31% 14,71% 23,43% 14,30%",
    )
    config = cargar_config_tasas()
    with pytest.raises(TablaIncompleta) as error:
        filas_desde_texto(
            roto,
            fuente=config.fuente,
            sha256_pdf=SHA_EJEMPLO,
            fecha_extraccion=FECHA,
            vigencia_desde=config.vigencia_desde,
            vigencia_hasta=config.vigencia_hasta,
        )
    assert error.value.codigo == "tabla_incompleta"


def test_cabecera_cambiada_no_se_interpreta_a_ciegas(texto_muestra: str) -> None:
    """Si la cabecera deja de nombrar las columnas, el bloque no se publica."""
    roto = texto_muestra.replace(
        "TIPO DE LIBRE INVERSIÓN COMPRA DE CARTERA RETANQUEO",
        "TIPO DE TASA COLUMNA A COLUMNA B COLUMNA C",
    )
    config = cargar_config_tasas()
    with pytest.raises(TablaIncompleta):
        filas_desde_texto(
            roto,
            fuente=config.fuente,
            sha256_pdf=SHA_EJEMPLO,
            fecha_extraccion=FECHA,
            vigencia_desde=config.vigencia_desde,
            vigencia_hasta=config.vigencia_hasta,
        )


def test_escribir_tabla_reescribe_la_vigencia_sin_duplicar(
    filas_muestra: list[FilaTasa], tmp_path: Path
) -> None:
    """Dos extracciones de la misma vigencia dejan una sola tabla completa."""
    destino = tmp_path / "tasas-personas-2026-11.jsonl"
    assert escribir_tabla(destino, filas_muestra) == 53
    primero = destino.read_bytes()

    nueva_huella = "a" * 64
    actualizadas = [fila.model_copy(update={"sha256_pdf": nueva_huella}) for fila in filas_muestra]
    assert escribir_tabla(destino, actualizadas) == 53
    segunda = destino.read_bytes()

    assert len(segunda.splitlines()) == 53
    assert b'"sha256_pdf": "a' in segunda
    assert segunda != primero
    leidas = leer_tabla(destino)
    assert len(leidas) == 53
    assert {fila.sha256_pdf for fila in leidas} == {nueva_huella}


def test_validar_filas_rechaza_rangos_imposibles(filas_muestra: list[FilaTasa]) -> None:
    """Un rango invertido o una tasa mayor que 100 % no se publica."""
    invertida = filas_muestra[0].model_copy(update={"tasa_ea_desde": Decimal("0.5")})
    with pytest.raises(TasaFueraDeRango) as error:
        validar_filas([invertida])
    assert error.value.codigo == "tasa_fuera_de_rango"

    enorme = filas_muestra[0].model_copy(update={"tasa_ea_hasta": Decimal("1.2")})
    with pytest.raises(TasaFueraDeRango):
        validar_filas([enorme])


def test_usura_acepta_la_tabla_del_periodo(filas_muestra: list[FilaTasa]) -> None:
    """Ninguna tasa de crédito del período supera la usura certificada."""
    usura = cargar_config_tasas().usura
    validar_filas(filas_muestra)
    validar_usura(filas_muestra, usura)


def test_usura_rechaza_una_tasa_sobre_el_techo(filas_muestra: list[FilaTasa]) -> None:
    """Una tasa de crédito por encima de la usura produce `tasa_sobre_usura`."""
    usura = cargar_config_tasas().usura
    sobre = _buscar(filas_muestra, "libre_inversion").model_copy(
        update={"tasa_ea_hasta": Decimal("0.30")}
    )
    with pytest.raises(TasaSobreUsura) as error:
        validar_usura([sobre], usura)
    assert error.value.codigo == "tasa_sobre_usura"
    assert "libre_inversion" in str(error.value)


def test_usura_con_centinela_bloquea_la_publicacion(filas_muestra: list[FilaTasa]) -> None:
    """El centinela 0,0 significa «sin certificar» y detiene la publicación."""
    sin_certificar = Usura(
        tasa_ea=Decimal("0"),
        vigencia_desde=date(2026, 11, 1),
        vigencia_hasta=date(2026, 11, 30),
        fuente="https://www.superfinanciera.gov.co/",
        resolucion="",
        exceptuados=frozenset({"vivienda", "ahorro", "cdt"}),
    )
    with pytest.raises(UsuraSinCertificar) as error:
        validar_usura(filas_muestra, sin_certificar)
    assert error.value.codigo == "usura_sin_certificar"


def test_ahorro_cdt_y_vivienda_no_se_validan_contra_la_usura(
    filas_muestra: list[FilaTasa],
) -> None:
    """Vivienda tiene modalidad propia y ahorro y CDT no son crédito."""
    usura = cargar_config_tasas().usura
    exceptuadas = [
        _buscar(filas_muestra, "ahorro", "De 0 a $5.000.000").model_copy(
            update={"tasa_ea_desde": Decimal("0.99"), "tasa_ea_hasta": Decimal("0.99")}
        ),
        _buscar(filas_muestra, "cdt", "$500M- $99 MM", 30).model_copy(
            update={"tasa_ea_desde": Decimal("0.99"), "tasa_ea_hasta": Decimal("0.99")}
        ),
        _buscar(filas_muestra, "vivienda", "Crédito hipotecario").model_copy(
            update={"tasa_ea_desde": Decimal("0.99"), "tasa_ea_hasta": Decimal("0.99")}
        ),
    ]
    validar_usura(exceptuadas, usura)

    credito = _buscar(filas_muestra, "libre_inversion").model_copy(
        update={"tasa_ea_hasta": Decimal("0.99")}
    )
    with pytest.raises(TasaSobreUsura):
        validar_usura([credito], usura)


def test_cdt_corto_se_desagrega_por_plazo_y_monto(filas_muestra: list[FilaTasa]) -> None:
    """El CDT corto publica una fila por plazo y rango de monto, sin envolver."""
    cortos = [
        fila
        for fila in filas_muestra
        if fila.producto == "cdt" and fila.segmento and fila.segmento.startswith("$")
    ]
    assert len(cortos) == 27
    assert {fila.plazo_dias for fila in cortos} == {30, 60, 90, 180, 270, 360, 540, 720, 1080}
    assert {fila.segmento for fila in cortos} == {
        "$500M- $99 MM",
        "$100 MM - 499 MM",
        "$500 MM - 10.000 MM",
    }
    assert len({(fila.segmento, fila.plazo_dias) for fila in cortos}) == 27

    treinta = _buscar(filas_muestra, "cdt", "$500 MM - 10.000 MM", 30)
    assert (treinta.tasa_ea_desde, treinta.tasa_ea_hasta) == (Decimal("0.0005"), Decimal("0.0005"))
    treinta_anios = _buscar(filas_muestra, "cdt", "$500 MM - 10.000 MM", 1080)
    assert (treinta_anios.tasa_ea_desde, treinta_anios.tasa_ea_hasta) == (
        Decimal("0.1215"),
        Decimal("0.1215"),
    )


def test_cdt_largo_se_desagrega_por_plazo_e_indice(filas_muestra: list[FilaTasa]) -> None:
    """El CDT largo conserva plazo e índice; los plazos sin tasa no se inventan."""
    largos = [
        fila
        for fila in filas_muestra
        if fila.producto == "cdt" and fila.segmento in {"IPC", "IBR a 30 días"}
    ]
    assert len(largos) == 8
    assert {fila.plazo_dias for fila in largos} == {360, 540, 720, 1080}
    assert {fila.plazo_dias for fila in largos} & {90, 180} == set()

    assert _buscar(filas_muestra, "cdt", "IPC", 360).tasa_ea_desde == Decimal("0.032")
    assert _buscar(filas_muestra, "cdt", "IPC", 1080).tasa_ea_desde == Decimal("0.039")
    assert _buscar(filas_muestra, "cdt", "IBR a 30 días", 1080).tasa_ea_desde == Decimal("0.0035")


def test_coherencia_entre_mv_y_ea(filas_muestra: list[FilaTasa]) -> None:
    """La M.V. publicada debe ser (1 + E.A.) ^ (1/12) - 1 con 0,01 puntos de tolerancia."""
    validar_coherencia_tasas(filas_muestra)

    cerca = _buscar(filas_muestra, "libre_inversion").model_copy(
        update={"tasa_mv_desde": Decimal("0.0158")}
    )
    validar_coherencia_tasas([cerca])

    lejos = _buscar(filas_muestra, "libre_inversion").model_copy(
        update={"tasa_mv_hasta": Decimal("0.0250")}
    )
    with pytest.raises(TasaIncoherente) as error:
        validar_coherencia_tasas([lejos])
    assert error.value.codigo == "tasa_incoherente"
    assert "libre_inversion" in str(error.value)


def test_config_tasas_certifica_la_usura_del_periodo() -> None:
    """`config/tasas.toml` registra la usura de consumo y ordinario de noviembre."""
    config = cargar_config_tasas()
    assert config.usura.tasa_ea == Decimal("0.2834")
    assert config.usura.vigencia_desde == date(2026, 11, 1)
    assert config.usura.vigencia_hasta == date(2026, 11, 30)
    assert "superfinanciera" in config.usura.fuente.casefold()
    assert config.usura.resolucion == "Resolución 1707 de 2026"
    assert config.usura.certificada
    assert "vivienda" in config.usura.exceptuados
    assert config.tabla.name == "tasas-personas-2026-11.jsonl"
    assert config.sha256 == SHA_EJEMPLO

    crudo = (Path(__file__).parents[1] / "config" / "tasas.toml").read_text(encoding="utf-8")
    for clave in ("token =", "api_key =", "password =", "secret ="):
        assert clave not in crudo.casefold()


def test_tabla_gold_versionada_cumple_la_usura() -> None:
    """La tabla Gold publicada recorre todas sus filas contra la usura."""
    config = cargar_config_tasas()
    filas = leer_tabla(config.tabla)
    assert filas, "falta la tabla Gold de tasas de la vigencia"
    assert {fila.producto for fila in filas} == PRODUCTOS_ESPERADOS
    assert {fila.sha256_pdf for fila in filas} == {config.sha256}
    validar_filas(filas)
    validar_usura(filas, config.usura)
    validar_coherencia_tasas(filas)
