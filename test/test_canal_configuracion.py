"""Pruebas de la configuración del canal y del diagnóstico.

La configuración no guarda secretos: los tokens viven en el entorno. Estas
pruebas fijan eso y comprueban que las huellas autorizadas son hexadecimales,
que el catálogo de productos y los umbrales están completos, y que los rangos de
la entrevista conservan los ids y los valores de cálculo del guion.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from banco_occidente_corpus.config import PROJECT_ROOT

RUTA_WHATSAPP = PROJECT_ROOT / "config" / "whatsapp.toml"
"""Configuración del canal, versionada y sin secretos."""

RUTA_DIAGNOSTICO = PROJECT_ROOT / "config" / "diagnostico.toml"
"""Umbrales del semáforo y catálogo de productos del diagnóstico."""

PATRON_HUELLA = re.compile(r"^[0-9a-f]{64}$")
"""Huella HMAC-SHA256 en hexadecimal minúscula."""

PATRON_TELEFONO = re.compile(r"\d{10,}")
"""Secuencia de diez o más dígitos: un número en claro, no una versión."""

CLAVES_PROHIBIDAS = ("token", "secret", "clave", "salt")
"""Fragmentos que delatan un secreto guardado en la configuración."""

IDS_POR_CLAVE = {
    "ingresos": {
        "ingresos.MENOS_2M",
        "ingresos.DE_2M_A_3M",
        "ingresos.DE_3M_A_5M",
        "ingresos.DE_5M_A_8M",
        "ingresos.DE_8M_A_12M",
        "ingresos.MAS_12M",
    },
    "gastos": {
        "gastos.MENOS_1M",
        "gastos.DE_1M_A_2M",
        "gastos.DE_2M_A_3M",
        "gastos.DE_3M_A_5M",
        "gastos.MAS_5M",
    },
    "cuotas": {
        "cuotas.NINGUNA",
        "cuotas.MENOS_500K",
        "cuotas.DE_500K_A_1M",
        "cuotas.DE_1M_A_2M",
        "cuotas.DE_2M_A_3M",
        "cuotas.MAS_3M",
    },
    "cuota_trasladar": {
        "cuota_trasladar.MENOS_500K",
        "cuota_trasladar.DE_500K_A_1M",
        "cuota_trasladar.DE_1M_A_2M",
        "cuota_trasladar.DE_2M_A_3M",
        "cuota_trasladar.MAS_3M",
    },
    "monto": {
        "monto.HASTA_5M",
        "monto.DE_5M_A_10M",
        "monto.DE_10M_A_20M",
        "monto.DE_20M_A_50M",
        "monto.MAS_50M",
    },
    "monto_vehiculo": {
        "monto.DE_30M_A_60M",
        "monto.DE_60M_A_100M",
        "monto.MAS_100M",
    },
    "monto_vivienda": {
        "monto.DE_100M_A_200M",
        "monto.DE_200M_A_350M",
        "monto.MAS_350M",
    },
    "plazo": {
        "plazo.12",
        "plazo.24",
        "plazo.36",
        "plazo.48",
        "plazo.60",
        "plazo.72",
    },
    "plazo_vivienda": {
        "plazo.120",
        "plazo.180",
        "plazo.240",
    },
}
"""Ids canónicos del guion de la entrevista, por bloque de rango."""


def _cargar(ruta: Path) -> dict[str, Any]:
    """Carga un TOML del proyecto como diccionario."""
    with ruta.open("rb") as archivo:
        return dict(tomllib.load(archivo))


def _claves(datos: dict[str, Any]) -> list[str]:
    """Recorre el TOML y devuelve todas las claves, sin repetir."""
    encontradas: list[str] = []
    for clave, valor in datos.items():
        encontradas.append(clave)
        if isinstance(valor, dict):
            encontradas.extend(_claves(dict(valor)))
    return encontradas


def _rangos() -> dict[str, dict[str, Any]]:
    """Indexa los rangos de la entrevista por su clave."""
    return {rango["clave"]: rango for rango in _cargar(RUTA_DIAGNOSTICO)["rango"]}


def _opciones(rango: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Indexa las opciones de un rango por su id canónico."""
    return {opcion["id"]: opcion for opcion in rango["opcion"]}


def test_whatsapp_no_guarda_secretos_ni_numeros_en_claro() -> None:
    """El TOML del canal no lleva tokens, sal ni teléfonos en claro."""
    datos = _cargar(RUTA_WHATSAPP)
    sin_huellas = {clave: valor for clave, valor in datos.items() if clave != "autorizados"}

    sospechosas = [
        clave for clave in _claves(datos) if any(p in clave.casefold() for p in CLAVES_PROHIBIDAS)
    ]

    assert sospechosas == []
    assert PATRON_TELEFONO.search(json.dumps(sin_huellas, ensure_ascii=False)) is None


def test_hay_cinco_huellas_hexadecimales() -> None:
    """Los cinco números autorizados se guardan como huellas, no como números."""
    huellas = _cargar(RUTA_WHATSAPP)["autorizados"]["huellas"]

    assert len(huellas) == 5
    assert all(PATRON_HUELLA.match(huella) for huella in huellas)
    assert len(set(huellas)) == 5


def test_modo_del_canal_es_falso_o_real() -> None:
    """El canal arranca en modo falso salvo que se pida el real."""
    assert _cargar(RUTA_WHATSAPP)["canal"]["modo"] in {"falso", "real"}


def test_umbrales_del_semaforo_estan_ordenados() -> None:
    """Verde queda por debajo de amarillo y ambos dentro de 0 y 1."""
    umbrales = _cargar(RUTA_DIAGNOSTICO)["umbrales"]

    assert 0 < umbrales["verde_hasta"] < umbrales["amarillo_hasta"] < 1


def test_catalogo_de_productos_tiene_los_diez_del_diseno() -> None:
    """El catálogo cubre los diez productos del tarifario."""
    productos = _cargar(RUTA_DIAGNOSTICO)["productos"]

    assert set(productos) == {
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
    assert all(isinstance(nombre, str) and nombre for nombre in productos.values())


def test_rangos_de_la_entrevista_tienen_los_ids_del_guion() -> None:
    """Cada bloque de rango trae exactamente los ids canónicos del guion."""
    rangos = _rangos()

    assert set(rangos) == set(IDS_POR_CLAVE)
    for clave, esperados in IDS_POR_CLAVE.items():
        assert set(_opciones(rangos[clave])) == esperados


def test_los_ids_de_las_opciones_no_se_repiten() -> None:
    """Un id identifica una sola opción en todo el archivo."""
    ids = [opcion["id"] for rango in _rangos().values() for opcion in rango["opcion"]]

    assert len(ids) == len(set(ids))


def test_valor_de_calculo_es_el_punto_medio_del_rango() -> None:
    """Con desde y hasta, el valor es el punto medio; sin extremos, el declarado."""
    for clave, rango in _rangos().items():
        if clave in {"plazo", "plazo_vivienda"}:
            continue
        for opcion in rango["opcion"]:
            desde = opcion.get("desde")
            hasta = opcion.get("hasta")
            if desde is not None and hasta is not None:
                assert opcion["valor"] == (desde + hasta) // 2, opcion["id"]
            elif hasta is not None:
                assert 0 < opcion["valor"] < hasta, opcion["id"]
            elif desde is not None:
                assert opcion["valor"] > desde, opcion["id"]
            else:
                assert opcion["valor"] == 0, opcion["id"]


def test_valores_de_calculo_ancla_del_guion() -> None:
    """Fija los valores que el equipo acordó en el guion de la entrevista."""
    valores = {
        opcion["id"]: opcion["valor"] for rango in _rangos().values() for opcion in rango["opcion"]
    }
    anclas = {
        "ingresos.DE_2M_A_3M": 2500000,
        "ingresos.DE_5M_A_8M": 6500000,
        "gastos.DE_3M_A_5M": 4000000,
        "cuotas.DE_500K_A_1M": 750000,
        "cuota_trasladar.DE_1M_A_2M": 1500000,
        "monto.DE_20M_A_50M": 35000000,
        "monto.DE_200M_A_350M": 275000000,
    }

    assert {clave: valores[clave] for clave in anclas} == anclas


def test_cuota_trasladar_repite_cuotas_sin_ninguna() -> None:
    """Trasladar deudas usa los mismos rangos que las cuotas, sin «ninguna»."""
    rangos = _rangos()
    cuotas = {
        opcion["id"].split(".", 1)[1]: opcion
        for opcion in rangos["cuotas"]["opcion"]
        if not opcion["id"].endswith("NINGUNA")
    }
    trasladar = {
        opcion["id"].split(".", 1)[1]: opcion for opcion in rangos["cuota_trasladar"]["opcion"]
    }

    assert set(trasladar) == set(cuotas)
    for sufijo, opcion in trasladar.items():
        assert opcion["valor"] == cuotas[sufijo]["valor"]


def test_plazos_coinciden_con_el_id_y_caben_en_el_guion() -> None:
    """El id `plazo.N` vale N meses y no pasa del máximo del guion (240)."""
    rangos = _rangos()
    plazos = [opcion for clave in ("plazo", "plazo_vivienda") for opcion in rangos[clave]["opcion"]]

    for opcion in plazos:
        assert opcion["valor"] == int(opcion["id"].split(".", 1)[1])
        assert 6 <= opcion["valor"] <= 240


def test_monto_y_plazo_aplican_a_objetivos_del_catalogo() -> None:
    """Cada objetivo de `aplica_a` existe en el catálogo de productos."""
    productos = set(_cargar(RUTA_DIAGNOSTICO)["productos"])

    for rango in _rangos().values():
        for objetivo in rango.get("aplica_a", []):
            assert objetivo in productos, objetivo
