"""Pruebas de Pana y sus tarjetas: sin red, sin disco y sin datos personales."""

from __future__ import annotations

import io
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from banco_occidente_corpus.pana import (
    AVISO,
    EXPRESIONES,
    DatosDiagnostico,
    DatosEscenario,
    FotoEscenario,
    dibujar_pana,
    foto_de_perfil,
    tarjeta_diagnostico,
    tarjeta_escenario,
    texto_diagnostico,
    texto_escenario,
)
from banco_occidente_corpus.pana.__main__ import (
    EJEMPLO_DIAGNOSTICO,
    EJEMPLO_ESCENARIO,
    guardar_muestras,
)
from banco_occidente_corpus.pana.tarjetas import (
    LADO,
    PESO_MAXIMO,
    TITULO_SEMAFORO,
    monto_corto,
    pesos,
    porcentaje,
    rango_pesos,
)

RAIZ = Path(__file__).resolve().parents[1]
"""Raíz del repositorio."""

PAQUETE = RAIZ / "src" / "banco_occidente_corpus" / "pana"
"""Carpeta del paquete de Pana."""

FIRMA_PNG = b"\x89PNG\r\n\x1a\n"
"""Primeros bytes de todo PNG."""


def _diagnostico(**cambios: object) -> DatosDiagnostico:
    """Crea un diagnóstico de prueba con cambios opcionales.

    Args:
        **cambios: campos que se reemplazan en el ejemplo.

    Returns:
        Diagnóstico validado.
    """
    return DatosDiagnostico(**(EJEMPLO_DIAGNOSTICO.model_dump() | cambios))


def _abrir(png: bytes) -> Image.Image:
    """Abre un PNG desde bytes.

    Args:
        png: bytes de la imagen.

    Returns:
        La imagen cargada.
    """
    return Image.open(io.BytesIO(png))


@pytest.mark.parametrize("semaforo", ["verde", "amarillo", "rojo"])
def test_tarjeta_diagnostico_es_png_cuadrado_y_liviano(semaforo: str) -> None:
    """La tarjeta del diagnóstico es un PNG de 1080 × 1080 de menos de 1 MB."""
    png = tarjeta_diagnostico(_diagnostico(semaforo=semaforo))

    assert png.startswith(FIRMA_PNG)
    assert len(png) < PESO_MAXIMO
    assert _abrir(png).size == (LADO, LADO)


def test_tarjeta_escenario_es_png_cuadrado_y_liviano() -> None:
    """La tarjeta «¿Y si…?» es un PNG de 1080 × 1080 de menos de 1 MB."""
    png = tarjeta_escenario(EJEMPLO_ESCENARIO)

    assert png.startswith(FIRMA_PNG)
    assert len(png) < PESO_MAXIMO
    assert _abrir(png).size == (LADO, LADO)


def test_el_color_de_la_tarjeta_sigue_el_semaforo() -> None:
    """La luz del semáforo cambia de color con el resultado."""
    centro_luz = (190, 545)
    verde = _abrir(tarjeta_diagnostico(_diagnostico(semaforo="verde"))).getpixel(centro_luz)
    rojo = _abrir(tarjeta_diagnostico(_diagnostico(semaforo="rojo"))).getpixel(centro_luz)

    assert verde == (79, 154, 106)
    assert rojo == (200, 85, 61)


def test_misma_entrada_misma_imagen() -> None:
    """Con la fuente del repositorio, la tarjeta sale igual en cada corrida."""
    assert tarjeta_diagnostico(EJEMPLO_DIAGNOSTICO) == tarjeta_diagnostico(EJEMPLO_DIAGNOSTICO)


def test_texto_del_diagnostico_lleva_los_mismos_datos() -> None:
    """El texto trae semáforo, cuota, tasa con vigencia y fuente, y el aviso."""
    texto = texto_diagnostico(EJEMPLO_DIAGNOSTICO)

    for pieza in (
        TITULO_SEMAFORO["amarillo"],
        "$150.000 – $170.000",
        "1,9 % mensual",
        "Tablero de tasas",
        "nov. 2026",
        "Portátil",
        "24 meses",
        AVISO,
    ):
        assert pieza in texto, pieza


def test_texto_del_escenario_lleva_los_dos_lados() -> None:
    """El texto del «¿Y si…?» trae ambos plazos, cuotas, colores y el aviso."""
    texto = texto_escenario(EJEMPLO_ESCENARIO)

    for pieza in (
        "¿Y si lo pagas en 36 meses?",
        "24 meses: $150.000 – $170.000",
        "36 meses: $110.000 – $125.000",
        "(amarillo)",
        "(verde)",
        "no cambió",
        AVISO,
    ):
        assert pieza in texto, pieza


def test_el_aviso_dice_que_es_un_proyecto_academico() -> None:
    """El aviso aclara que Pana no es del banco y que no aprueba créditos."""
    assert "proyecto académico" in AVISO
    assert "no del Banco de Occidente" in AVISO
    assert "no es una aprobación" in AVISO


@pytest.mark.parametrize(
    "producto",
    ["Portátil 3001234567", "Moto +57 300 123 4567", "CC 1.234.567.890", "Llamar al 310-555-1234"],
)
def test_rechaza_telefonos_y_documentos_en_el_texto(producto: str) -> None:
    """Un texto con 7 o más dígitos seguidos no entra en la tarjeta."""
    with pytest.raises(ValidationError, match="teléfono"):
        _diagnostico(producto=producto)


def test_rechaza_telefono_en_la_pregunta_del_escenario() -> None:
    """La regla también aplica a la pregunta del «¿Y si…?»."""
    datos = EJEMPLO_ESCENARIO.model_dump() | {"pregunta": "¿Y si llamo al 3001234567?"}
    with pytest.raises(ValidationError, match="teléfono"):
        DatosEscenario(**datos)


@pytest.mark.parametrize("campo", ["nombre", "telefono", "usuario_id", "documento"])
def test_no_hay_campos_para_datos_personales(campo: str) -> None:
    """Los modelos rechazan cualquier campo extra, como nombre o teléfono."""
    with pytest.raises(ValidationError):
        _diagnostico(**{campo: "dato"})


def test_rechaza_rango_de_cuota_invertido() -> None:
    """La cuota mínima no puede ser mayor que la máxima."""
    with pytest.raises(ValidationError, match="cuota_min"):
        _diagnostico(cuota_min=Decimal(200_000), cuota_max=Decimal(100_000))
    with pytest.raises(ValidationError, match="cuota_min"):
        FotoEscenario(plazo_meses=12, semaforo="verde", cuota_min=Decimal(9), cuota_max=Decimal(1))


def test_las_tarjetas_no_escriben_en_disco(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Generar tarjetas y caras solo guarda en memoria, nunca en archivos."""
    original = Image.Image.save
    destinos: list[object] = []

    def save_vigilado(self: Image.Image, fp: object, *args: object, **kwargs: object) -> None:
        """Registra a dónde se guarda cada imagen.

        Args:
            self: imagen que se guarda.
            fp: destino.
            *args: argumentos posicionales de ``save``.
            **kwargs: argumentos con nombre de ``save``.
        """
        destinos.append(fp)
        original(self, fp, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Image.Image, "save", save_vigilado)
    monkeypatch.chdir(tmp_path)

    tarjeta_diagnostico(EJEMPLO_DIAGNOSTICO)
    tarjeta_escenario(EJEMPLO_ESCENARIO)
    foto_de_perfil()

    assert destinos
    assert all(isinstance(destino, io.BytesIO) for destino in destinos)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("expresion", EXPRESIONES)
def test_pana_tiene_tres_caras_con_fondo_transparente(expresion: str) -> None:
    """Cada cara es RGBA, del tamaño pedido y con esquinas transparentes."""
    cara = dibujar_pana(expresion, 256)  # type: ignore[arg-type]

    assert cara.mode == "RGBA"
    assert cara.size == (256, 256)
    assert cara.getpixel((0, 0))[3] == 0  # type: ignore[index]


def test_las_caras_son_distintas() -> None:
    """Feliz, pensativo y calma no son la misma imagen."""
    caras = {dibujar_pana(e, 128).tobytes() for e in EXPRESIONES}
    assert len(caras) == 3


def test_pana_rechaza_expresiones_y_tamanos_invalidos() -> None:
    """Una expresión desconocida o un lado muy pequeño dan error claro."""
    with pytest.raises(ValueError, match="expresión"):
        dibujar_pana("enojado", 256)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="32"):
        dibujar_pana("feliz", 16)


def test_foto_de_perfil_es_png_de_640() -> None:
    """La foto de perfil sirve para el número de prueba en Meta."""
    png = foto_de_perfil()
    assert png.startswith(FIRMA_PNG)
    assert _abrir(png).size == (640, 640)


def test_formatos_de_pesos_y_porcentajes() -> None:
    """Pesos con punto de miles, porcentaje con coma y montos en millones."""
    assert pesos(Decimal("150000.4")) == "$150.000"
    assert rango_pesos(Decimal(1000), Decimal(1000)) == "$1.000"
    assert rango_pesos(Decimal(1000), Decimal(2000)) == "$1.000 – $2.000"
    assert porcentaje(Decimal("1.9")) == "1,9 %"
    assert porcentaje(Decimal("2")) == "2 %"
    assert porcentaje(Decimal("1.875")) == "1,88 %"
    assert monto_corto(Decimal(3_000_000)) == "$3 millones"
    assert monto_corto(Decimal(2_500_000)) == "$2,5 millones"
    assert monto_corto(Decimal(1_000_000)) == "$1 millón"
    assert monto_corto(Decimal(800_000)) == "$800.000"


def test_la_fuente_libre_viene_en_el_repo_con_su_licencia() -> None:
    """DejaVu Sans y su licencia están versionadas dentro del paquete."""
    fuentes = PAQUETE / "fuentes"
    for nombre in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        assert (fuentes / nombre).stat().st_size > 100_000, nombre
    licencia = (fuentes / "LICENCIA-DejaVu.txt").read_text(encoding="utf-8")
    assert "Bitstream" in licencia
    assert "public domain" in licencia


def test_pillow_tiene_version_fija() -> None:
    """Pillow va con versión exacta para que la tarjeta salga igual en todos lados."""
    datos = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    pillow = [d for d in datos["project"]["dependencies"] if d.lower().startswith("pillow")]
    assert pillow
    assert "==" in pillow[0]


def test_muestras_se_guardan_solo_cuando_se_piden(tmp_path: Path) -> None:
    """El comando de muestras escribe la foto, las tres caras y las dos tarjetas."""
    escritos = guardar_muestras(tmp_path / "muestras")

    assert sorted(ruta.name for ruta in escritos) == [
        "pana-calma.png",
        "pana-feliz.png",
        "pana-pensativo.png",
        "pana-perfil.png",
        "tarjeta-diagnostico.png",
        "tarjeta-escenario.png",
    ]
    assert all(ruta.read_bytes().startswith(FIRMA_PNG) for ruta in escritos)


@pytest.mark.parametrize("campo", ["producto", "razon", "tasa_vigencia", "tasa_fuente"])
def test_rechaza_textos_solo_con_espacios(campo: str) -> None:
    """Un texto que solo tiene espacios no se acepta como si tuviera contenido."""
    with pytest.raises(ValidationError, match="vacío"):
        _diagnostico(**{campo: "   "})


def test_rechaza_tarjetas_de_un_mega_o_mas(monkeypatch: pytest.MonkeyPatch) -> None:
    """El tope es estricto: una tarjeta que llega a 1 MB da error."""
    import banco_occidente_corpus.pana.tarjetas as tarjetas

    peso_real = len(tarjeta_diagnostico(EJEMPLO_DIAGNOSTICO))
    monkeypatch.setattr(tarjetas, "PESO_MAXIMO", peso_real)
    with pytest.raises(RuntimeError, match="1 MB"):
        tarjetas.tarjeta_diagnostico(EJEMPLO_DIAGNOSTICO)
