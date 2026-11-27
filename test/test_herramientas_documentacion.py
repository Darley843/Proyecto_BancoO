"""`docs/HERRAMIENTAS.md` se genera desde el catálogo y no puede desactualizarse."""

from __future__ import annotations

from pathlib import Path

import pytest

from banco_occidente_corpus.herramientas import catalogo, documentacion

#: Documento versionado que valida el profesor.
RUTA = Path("docs/HERRAMIENTAS.md")


def test_el_bloque_generado_coincide_con_el_catalogo() -> None:
    """Si cambia una herramienta y no se regenera el documento, la prueba falla."""
    contenido = RUTA.read_text(encoding="utf-8")
    assert documentacion.bloque_generado(contenido) == documentacion.render_markdown(
        catalogo.CATALOGO
    )


def test_el_documento_conserva_las_secciones_manuales() -> None:
    """Las dos secciones escritas a mano siguen en el documento."""
    contenido = RUTA.read_text(encoding="utf-8")
    assert "## Herramientas de OpenClaw" in contenido
    assert "## Control de la alucinación" in contenido
    assert "PR #215" in contenido
    assert "make traza" in contenido
    assert "motor" in contenido


def test_las_veinte_herramientas_tienen_ficha_completa() -> None:
    """Cada entrada declara dueña, uso, límite, salida, fuente, módulo y confirmación."""
    assert len(catalogo.CATALOGO) == 20
    assert len(set(catalogo.nombres())) == 20
    for herramienta in catalogo.CATALOGO:
        ficha = herramienta.documentacion
        assert ficha.para_que.strip()
        assert ficha.cuando_no.strip()
        assert ficha.devuelve.strip()
        assert ficha.fuente.strip()
        assert ficha.modulo.strip()
        assert ficha.confirmacion.strip()


def test_auditar_respuesta_exige_una_sola_auditoria_con_cifras_permitidas() -> None:
    """La ficha del catálogo deja claro que la auditoría es única y con cifras."""
    herramienta = catalogo.por_nombre("auditar_respuesta")
    assert herramienta is not None
    ficha = herramienta.documentacion
    texto = " ".join(f"{ficha.para_que} {ficha.cuando_no}".split())
    assert "una sola vez por mensaje" in texto
    assert "`cifras_permitidas` es obligatorio" in texto
    assert "devolvieron las herramientas usadas" in texto
    assert "No audites dos veces el mismo texto" in texto


def test_markdown_imprime_el_bloque(capsys: pytest.CaptureFixture[str]) -> None:
    """`--markdown` imprime solo el bloque, sin la tabla de consola."""
    assert catalogo.main(["--markdown"]) == 0
    salida = capsys.readouterr().out.strip()
    assert salida == documentacion.render_markdown(catalogo.CATALOGO)
    assert "Total: 20 herramientas. Usa --json" not in salida


def test_salida_actualiza_el_bloque_y_respeta_lo_manual(tmp_path: Path) -> None:
    """`--salida` reemplaza el bloque y deja intactas las secciones a mano."""
    ruta = tmp_path / "HERRAMIENTAS.md"
    ruta.write_text(
        "# Prueba\n\n"
        f"{documentacion.MARCA_INICIO}\n\n"
        "viejo\n\n"
        f"{documentacion.MARCA_FIN}\n\n"
        "## Sección manual\n\nNo se toca.\n",
        encoding="utf-8",
    )
    assert catalogo.main(["--markdown", "--salida", str(ruta)]) == 0
    contenido = ruta.read_text(encoding="utf-8")
    assert documentacion.bloque_generado(contenido) == documentacion.render_markdown(
        catalogo.CATALOGO
    )
    assert "## Sección manual" in contenido
    assert "No se toca." in contenido
    assert "\nviejo\n" not in contenido


def test_salida_sin_ruta_falla() -> None:
    """La opción no adivina el destino si falta el argumento."""
    assert catalogo.main(["--markdown", "--salida"]) == 2
