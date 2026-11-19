"""Pruebas de la extracción de tasas y de la validación de usura (sin red).

El PDF vive en Bronze y no se versiona, así que la extracción se prueba con un
texto de muestra que reproduce la maquetación del PDF: tablas «desde/hasta»,
notas de vigencia, mora, comisiones, seguros y tablas variables que deben
quedar fuera.

Las consultas `tasa_vigente` y `tasas_producto` se prueban sobre tablas Gold
temporales: no abren red, no leen la Bóveda y parten siempre de las tasas fijas.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from banco_occidente_corpus.tablero.tasas import (
    FilaTasa,
    TablaIncompleta,
    TasaFueraDeRango,
    TasaIncoherente,
    TasaNoDisponible,
    TasaSobreUsura,
    Usura,
    UsuraSinCertificar,
    cargar_config_tasas,
    cargar_tabla,
    describir_tasa,
    es_spread,
    escribir_tabla,
    etiqueta_banda,
    fecha_legible,
    filas_desde_texto,
    leer_tabla,
    montos_en_texto,
    sin_montos,
    tasa_vigente,
    tasas_fijas,
    tasas_producto,
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
#: Fecha de consulta fija: dentro de la vigencia y sin depender del día de la corrida.
FECHA_CONSULTA = date(2026, 11, 16)
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


def test_tipo_tasa_distingue_spreads_de_tasas(filas_muestra: list[FilaTasa]) -> None:
    """Cada fila declara si es tasa fija o spread, y el JSONL lo conserva."""
    ipc = [fila for fila in filas_muestra if fila.segmento == "IPC"]
    ibr = [fila for fila in filas_muestra if fila.segmento == "IBR a 30 días"]
    assert ipc and ibr
    assert {fila.tipo_tasa for fila in ipc} == {"spread_ipc"}
    assert {fila.tipo_tasa for fila in ibr} == {"spread_ibr"}
    assert all(
        fila.tipo_tasa == "fija"
        for fila in filas_muestra
        if fila.segmento not in {"IPC", "IBR a 30 días"}
    )
    assert sum(1 for fila in filas_muestra if es_spread(fila)) == 8

    crudo = [fila.como_dict() for fila in filas_muestra]
    assert {fila["tipo_tasa"] for fila in crudo} == {"fija", "spread_ipc", "spread_ibr"}


def test_las_consultas_de_tasa_dejan_fuera_los_spreads(filas_muestra: list[FilaTasa]) -> None:
    """`tasas_fijas` es el punto de partida de toda consulta de «la tasa»."""
    fijas = tasas_fijas(filas_muestra)
    assert len(fijas) == len(filas_muestra) - 8
    assert all(fila.tipo_tasa == "fija" for fila in fijas)
    assert any(fila.producto == "cdt" for fila in fijas)


def test_usura_no_valida_los_spreads(filas_muestra: list[FilaTasa]) -> None:
    """Un spread sobre IPC o IBR no es crédito y no se compara con la usura."""
    sin_excepciones = Usura(
        tasa_ea=Decimal("0.2834"),
        vigencia_desde=date(2026, 11, 1),
        vigencia_hasta=date(2026, 11, 30),
        fuente="https://www.superfinanciera.gov.co/",
        resolucion="Resolución 1707 de 2026",
        exceptuados=frozenset(),
    )
    spread_ipc = _buscar(filas_muestra, "cdt", "IPC", 360).model_copy(
        update={"tasa_ea_desde": Decimal("0.99"), "tasa_ea_hasta": Decimal("0.99")}
    )
    spread_ibr = _buscar(filas_muestra, "cdt", "IBR a 30 días", 360).model_copy(
        update={"tasa_ea_desde": Decimal("0.99"), "tasa_ea_hasta": Decimal("0.99")}
    )
    validar_usura([spread_ipc, spread_ibr], sin_excepciones)

    fija = _buscar(filas_muestra, "libre_inversion").model_copy(
        update={"tasa_ea_hasta": Decimal("0.99")}
    )
    with pytest.raises(TasaSobreUsura):
        validar_usura([fija], sin_excepciones)


def test_coherencia_no_evalua_los_spreads(filas_muestra: list[FilaTasa]) -> None:
    """Un spread no tiene M.V. y no entra en la equivalencia M.V./E.A."""
    spread = _buscar(filas_muestra, "cdt", "IPC", 360).model_copy(
        update={"tasa_mv_desde": Decimal("0.50"), "tasa_mv_hasta": Decimal("0.50")}
    )
    validar_coherencia_tasas([spread])


def test_los_spreads_se_muestran_como_puntos_sobre_el_indice(filas_muestra: list[FilaTasa]) -> None:
    """La presentación distingue «IPC + puntos» e «IBR + puntos» de una tasa."""
    assert describir_tasa(_buscar(filas_muestra, "cdt", "IPC", 360)) == "IPC + 3,20 puntos"
    assert describir_tasa(_buscar(filas_muestra, "cdt", "IBR a 30 días", 1080)) == (
        "IBR + 0,35 puntos"
    )
    assert describir_tasa(_buscar(filas_muestra, "libre_inversion")) == "20,56–28,17 % E.A."
    assert describir_tasa(_buscar(filas_muestra, "tarjeta_credito", "Pesos")) == "28,19 % E.A."


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
    assert {fila.tipo_tasa for fila in filas if fila.producto == "cdt"} == {
        "fija",
        "spread_ipc",
        "spread_ibr",
    }
    assert sum(1 for fila in filas if es_spread(fila)) == 8
    validar_filas(filas)
    validar_usura(filas, config.usura)
    validar_coherencia_tasas(filas)


# ---------------------------------------------------------------------------
# Consulta determinista de la tasa vigente (tarea 3.5)
# ---------------------------------------------------------------------------

#: URL del PDF de tasas en las tablas temporales de las consultas.
URL_TASAS = "https://www.bancodeoccidente.com.co/documents/d/guest/tasas-personas-bdo"
#: Vigencia de la tabla de prueba por defecto.
VIGENCIA = ("2026-11-01", "2026-11-30")


def fila_consulta(
    producto: str,
    *,
    segmento: str | None = None,
    desde: str = "0.2056",
    hasta: str = "0.2817",
    tipo_tasa: str = "fija",
    plazo_dias: int | None = None,
    vigencia: tuple[str, str] = VIGENCIA,
    mensual: tuple[str, str] | None = None,
) -> FilaTasa:
    """Construye una fila de la tabla Gold para las pruebas de consulta."""
    return FilaTasa(
        producto=producto,
        segmento=segmento,
        tipo_tasa=tipo_tasa,
        plazo_dias=plazo_dias,
        tasa_ea_desde=Decimal(desde),
        tasa_ea_hasta=Decimal(hasta),
        tasa_mv_desde=None if mensual is None else Decimal(mensual[0]),
        tasa_mv_hasta=None if mensual is None else Decimal(mensual[1]),
        vigencia_desde=date.fromisoformat(vigencia[0]),
        vigencia_hasta=date.fromisoformat(vigencia[1]),
        fuente=URL_TASAS,
        sha256_pdf=SHA_EJEMPLO,
        fecha_extraccion=FECHA,
    )


def publicar(raiz: Path, nombre: str, filas: list[FilaTasa]) -> Path:
    """Escribe una tabla Gold de la vigencia en `raiz` y devuelve su ruta."""
    destino = raiz / nombre
    escribir_tabla(destino, filas)
    return destino


def test_tasa_vigente_de_un_solo_segmento(tmp_path: Path) -> None:
    """Con una sola fila devuelve su rango, su vigencia y su fuente."""
    publicar(
        tmp_path,
        "tasas-personas-2026-11.jsonl",
        [fila_consulta("libre_inversion", mensual=("0.0157", "0.0209"))],
    )

    tasa = tasa_vigente("libre_inversion", FECHA_CONSULTA, raiz=tmp_path)

    assert (tasa.tasa_ea_desde, tasa.tasa_ea_hasta) == (Decimal("0.2056"), Decimal("0.2817"))
    assert (tasa.tasa_mv_desde, tasa.tasa_mv_hasta) == (Decimal("0.0157"), Decimal("0.0209"))
    assert tasa.segmento is None
    assert (tasa.vigencia_desde, tasa.vigencia_hasta) == (date(2026, 11, 1), date(2026, 11, 30))
    assert tasa.fuente == URL_TASAS
    assert tasa.sha256_pdf == SHA_EJEMPLO
    assert tasa.fecha_extraccion == FECHA


def test_tasa_vigente_envuelve_los_segmentos_sin_promediar(tmp_path: Path) -> None:
    """Con varios segmentos devuelve el desde más bajo y el hasta más alto."""
    publicar(
        tmp_path,
        "tasas-personas-2026-11.jsonl",
        [
            fila_consulta("libranza", segmento="Libre inversión", desde="0.1539", hasta="0.2431"),
            fila_consulta("libranza", segmento="Compra de cartera", desde="0.1471", hasta="0.2343"),
            fila_consulta("libranza", segmento="Retanqueo", desde="0.143", hasta="0.23"),
        ],
    )

    tasa = tasa_vigente("libranza", FECHA_CONSULTA, raiz=tmp_path)

    assert (tasa.tasa_ea_desde, tasa.tasa_ea_hasta) == (Decimal("0.143"), Decimal("0.2431"))
    assert tasa.segmento is None
    assert tasa.tasa_mv_desde is None and tasa.tasa_mv_hasta is None


def test_tasas_producto_conserva_las_filas_por_segmento(tmp_path: Path) -> None:
    """La evidencia por segmento se conserva y se devuelve ordenada."""
    publicar(
        tmp_path,
        "tasas-personas-2026-11.jsonl",
        [
            fila_consulta("libranza", segmento="Libre inversión", desde="0.1539", hasta="0.2431"),
            fila_consulta("libranza", segmento="Retanqueo", desde="0.143", hasta="0.23"),
        ],
    )

    filas = tasas_producto("Libranza", FECHA_CONSULTA, raiz=tmp_path)

    assert [(fila.segmento, fila.tasa_ea_hasta) for fila in filas] == [
        ("Libre inversión", Decimal("0.2431")),
        ("Retanqueo", Decimal("0.23")),
    ]


def test_la_consulta_elige_la_vigencia_mas_reciente(tmp_path: Path) -> None:
    """Dos tablas con vigencias distintas no se mezclan: gana la más reciente."""
    publicar(
        tmp_path,
        "tasas-personas-2026-10.jsonl",
        [
            fila_consulta(
                "libre_inversion",
                desde="0.18",
                hasta="0.25",
                vigencia=("2026-10-01", "2026-10-31"),
            )
        ],
    )
    publicar(
        tmp_path,
        "tasas-personas-2026-11.jsonl",
        [fila_consulta("libre_inversion")],
    )

    reciente = tasa_vigente("libre_inversion", FECHA_CONSULTA, raiz=tmp_path)
    octubre = tasa_vigente("libre_inversion", date(2026, 10, 15), raiz=tmp_path)

    assert reciente.tasa_ea_desde == Decimal("0.2056")
    assert reciente.vigencia_desde == date(2026, 11, 1)
    assert octubre.tasa_ea_desde == Decimal("0.18")
    assert octubre.vigencia_desde == date(2026, 10, 1)


def test_la_consulta_fuera_de_vigencia_usa_la_mas_reciente_y_avisa(
    tmp_path: Path,
) -> None:
    """Una fecha que ninguna vigencia contiene usa la más reciente y lo advierte."""
    publicar(tmp_path, "tasas-personas-2026-11.jsonl", [fila_consulta("libre_inversion")])

    tasa = tasa_vigente("libre_inversion", date(2026, 12, 15), raiz=tmp_path)

    assert tasa.vigencia_desde == date(2026, 11, 1)
    assert tasa.tasa_ea_desde == Decimal("0.2056")
    assert tasa.vigencia_vencida is True


def test_la_consulta_dentro_de_vigencia_no_avisa(tmp_path: Path) -> None:
    """Con una fecha que la vigencia contiene, la alerta queda apagada."""
    publicar(tmp_path, "tasas-personas-2026-11.jsonl", [fila_consulta("libre_inversion")])

    tasa = tasa_vigente("libre_inversion", FECHA_CONSULTA, raiz=tmp_path)

    assert tasa.vigencia_vencida is False


def test_la_consulta_sin_producto_responde_tasa_no_disponible(tmp_path: Path) -> None:
    """Un producto que no está en la tabla no se inventa."""
    publicar(tmp_path, "tasas-personas-2026-11.jsonl", [fila_consulta("libre_inversion")])

    with pytest.raises(TasaNoDisponible) as error:
        tasa_vigente("credito_rotativo", FECHA_CONSULTA, raiz=tmp_path)

    assert "credito_rotativo" in str(error.value)


def test_las_consultas_parten_de_las_tasas_fijas(tmp_path: Path) -> None:
    """Un spread sobre IPC no es «la tasa» del CDT y no entra en las consultas."""
    publicar(
        tmp_path,
        "tasas-personas-2026-11.jsonl",
        [
            fila_consulta(
                "cdt", segmento="$100 MM - 499 MM", desde="0.119", hasta="0.119", plazo_dias=360
            ),
            fila_consulta(
                "cdt",
                segmento="IPC",
                desde="0.032",
                hasta="0.032",
                tipo_tasa="spread_ipc",
                plazo_dias=360,
            ),
            fila_consulta(
                "cdt",
                segmento="IBR a 30 días",
                desde="0.002",
                hasta="0.002",
                tipo_tasa="spread_ibr",
                plazo_dias=360,
            ),
        ],
    )

    tasa = tasa_vigente("cdt", FECHA_CONSULTA, raiz=tmp_path)
    filas = tasas_producto("cdt", FECHA_CONSULTA, raiz=tmp_path)

    assert (tasa.tasa_ea_desde, tasa.tasa_ea_hasta) == (Decimal("0.119"), Decimal("0.119"))
    assert [fila.segmento for fila in filas] == ["$100 MM - 499 MM"]
    assert not any(es_spread(fila) for fila in filas)


def test_un_valor_fuera_de_rango_se_descarta_y_se_informa(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Una tasa negativa o mayor que 100 % no se corrige: se descarta con aviso."""
    ruta = tmp_path / "tasas-personas-2026-11.jsonl"
    crudas = [
        fila_consulta("libre_inversion").como_dict(),
        {**fila_consulta("compra_cartera").como_dict(), "tasa_ea_desde": -0.1},
        {**fila_consulta("libranza").como_dict(), "tasa_ea_hasta": 1.2},
    ]
    ruta.write_text(
        "".join(json.dumps(fila, ensure_ascii=False) + "\n" for fila in crudas),
        encoding="utf-8",
    )

    with caplog.at_level("WARNING"):
        filas = cargar_tabla(ruta)

    assert [fila.producto for fila in filas] == ["libre_inversion"]
    assert "fuera de rango" in caplog.text


def test_la_tabla_normaliza_la_coma_decimal(tmp_path: Path) -> None:
    """Una tabla con «0,2056» se lee como el decimal 0,2056 y no se rechaza."""
    ruta = tmp_path / "tasas-personas-2026-11.jsonl"
    cruda = {
        **fila_consulta("libre_inversion").como_dict(),
        "tasa_ea_desde": "0,2056",
        "tasa_ea_hasta": "0,2817",
    }
    ruta.write_text(json.dumps(cruda) + "\n", encoding="utf-8")

    filas = cargar_tabla(ruta)

    assert len(filas) == 1
    assert filas[0].tasa_ea_desde == Decimal("0.2056")
    assert filas[0].tasa_ea_hasta == Decimal("0.2817")


def test_la_consulta_funciona_offline_sobre_la_tabla_gold() -> None:
    """La consulta lee la tabla Gold local; la suite bloquea cualquier socket."""
    config = cargar_config_tasas()

    tasa = tasa_vigente("Libre inversión", FECHA_CONSULTA)
    filas = tasas_producto("libranza", FECHA_CONSULTA)

    assert tasa.fuente == config.fuente
    assert tasa.sha256_pdf == config.sha256
    assert tasa.vigencia_desde == config.vigencia_desde
    assert tasa.vigencia_vencida is False
    assert tasa_vigente("Libre inversión", FECHA_CONSULTA) == tasa
    assert len(filas) == 3


def test_los_montos_de_la_pregunta_se_leen_en_pesos() -> None:
    """«200 millones», «500 mil» y «$5.000.000» son montos; el plazo no."""
    assert montos_en_texto("un CDT por 200 millones") == [200_000_000]
    assert montos_en_texto("un CDT por $5.000.000") == [5_000_000]
    assert montos_en_texto("un CDT por 500 mil") == [500_000]
    assert montos_en_texto("un CDT a 360 días") == []
    assert montos_en_texto("un CDT a 2 años") == []


def test_la_pregunta_sin_montos_conserva_el_plazo() -> None:
    """Quitar el monto deja intactos el producto y el plazo de la pregunta."""
    assert sin_montos("CDT a 360 días por 200 millones") == "cdt a 360 dias por"
    assert sin_montos("CDT por $5.000.000 a 2 años") == "cdt por a 2 anos"


def test_las_bandas_se_muestran_con_etiquetas_legibles() -> None:
    """La etiqueta visible traduce el texto del PDF y no lo reescribe en Gold."""
    assert etiqueta_banda("$500M- $99 MM") == "De $500 mil a $99 millones"
    assert etiqueta_banda("$100 MM - 499 MM") == "De $100 a $499 millones"
    assert etiqueta_banda("$500 MM - 10.000 MM") == "De $500 millones a $10.000 millones"
    assert etiqueta_banda("De 0 a $5.000.000") == "De 0 a $5.000.000"


def test_la_fecha_se_escribe_en_espanol() -> None:
    """La alerta de vigencia nombra el día y el mes, no la fecha ISO."""
    assert fecha_legible(date(2026, 11, 18)) == "18 de noviembre de 2026"
    assert fecha_legible(date(2026, 11, 4)) == "4 de noviembre de 2026"
