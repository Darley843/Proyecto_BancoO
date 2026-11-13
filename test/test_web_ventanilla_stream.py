"""Pruebas estáticas del streaming en la app web: `app.js` y la Ventanilla.

No abren un navegador: revisan que la red viva en `app.js`, que la Ventanilla
pinte el avance con `crearTexto` y que el corte de conexión termine en el error
de siempre, con el hilo conservado.
"""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "app" / "web"


def leer(relativa: str) -> str:
    """Lee un archivo de `app/web/` como texto."""
    return (WEB / relativa).read_text(encoding="utf-8")


def bloque_funcion(codigo: str, nombre: str) -> str:
    """Devuelve el bloque de una función de nivel superior del archivo."""
    inicio = codigo.index(f"function {nombre}(")
    fin = codigo.index("\n}\n", inicio) + 3
    return codigo[inicio:fin]


def test_app_expone_pedir_en_vivo_con_la_ruta_sse() -> None:
    """`app.js` comparte `pedirEnVivo` y conoce la ruta `/api/preguntar/stream`."""
    app = leer("app.js")
    assert 'preguntar: "/api/preguntar/stream"' in app
    assert "  pedirEnVivo,\n" in app
    funcion = bloque_funcion(app, "pedirEnVivo")
    assert '"text/event-stream"' in funcion
    assert "AbortController" in funcion
    assert "return pedir(nombre, opciones);" in funcion


def test_pedir_en_vivo_vuelve_a_la_ruta_clasica_solo_si_no_existe() -> None:
    """El respaldo a `pedir` se usa en la maqueta o con 404/405, nunca tras un error."""
    funcion = bloque_funcion(leer("app.js"), "pedirEnVivo")
    assert 'estado.modo === "ejemplo"' in funcion
    assert "respuesta.status === 404 || respuesta.status === 405" in funcion
    assert funcion.count("return pedir(nombre, opciones);") == 2


def test_lectura_del_stream_reparte_etapas_final_y_error() -> None:
    """El lector distingue `etapa`, `final` y `error`, y un corte lanza error."""
    app = leer("app.js")
    leer_eventos = bloque_funcion(app, "leerEventos")
    procesar = bloque_funcion(app, "procesarBloques")
    assert "getReader()" in leer_eventos
    assert 'new TextDecoder("utf-8")' in leer_eventos
    assert "throw new Error(MENSAJE_CORTE);" in leer_eventos
    assert "alRecibir();" in leer_eventos
    for evento in ('"etapa"', '"final"', '"error"'):
        assert f"evento.tipo === {evento}" in procesar
    assert "Se perdió la conexión con la sucursal" in app


def test_el_tiempo_limite_cuenta_desde_el_ultimo_dato() -> None:
    """Cada trozo recibido reinicia la espera: un turno largo no se corta."""
    funcion = bloque_funcion(leer("app.js"), "pedirEnVivo")
    assert "const reiniciarEspera = () =>" in funcion
    assert "leerEventos(respuesta, alAvanzar, reiniciarEspera)" in funcion
    assert "window.clearTimeout(espera);" in funcion


def test_ventanilla_pide_en_vivo_y_pinta_el_avance() -> None:
    """La Ventanilla usa `pedirEnVivo` y no hace `fetch` por su cuenta."""
    codigo = leer("vistas/ventanilla.js")
    pedir = bloque_funcion(codigo, "pedirTurno")
    assert 'app.pedirEnVivo("preguntar", { cuerpo }, alAvanzar)' in pedir
    assert 'app.pedir("preguntar", { cuerpo })' in pedir
    assert "fetch(" not in codigo
    assert "innerHTML" not in codigo
    for etapa in ("reformulando", "router", "buscando", "redactando"):
        assert f"{etapa}:" in codigo
    paso = bloque_funcion(codigo, "crearPaso")
    assert "crearTexto(" in paso


def test_el_error_conserva_el_hilo_y_limpia_el_avance() -> None:
    """Tras un corte se muestra el error de siempre y el avance se vacía."""
    enviar = bloque_funcion(leer("vistas/ventanilla.js"), "enviarSecuencia")
    error = bloque_funcion(leer("vistas/ventanilla.js"), "mostrarError")
    assert "mostrarError(" in enviar
    assert "reiniciarAvance(vistaActual);" in enviar.split("finally", 1)[1]
    assert "El hilo se conserva" in error
    assert "Reintentar" in error


def test_el_comprobante_muestra_el_recorrido() -> None:
    """El comprobante guarda las etapas terminadas como «Recorrido del turno»."""
    codigo = leer("vistas/ventanilla.js")
    assert 'etapas: avance.filter((etapa) => etapa.estado === "hecho")' in codigo
    assert "Recorrido del turno" in bloque_funcion(codigo, "pintarComprobante")


def test_estilos_del_avance() -> None:
    """El avance tiene estilos con variables y respeta el movimiento reducido."""
    css = leer("estilos.css")
    for clase in (
        ".ventanilla__avance",
        ".ventanilla__paso--hecho::before",
        ".ventanilla__paso--en-curso::before",
        "@keyframes ventanilla-latido",
    ):
        assert clase in css
    reducido = css.split("@media (prefers-reduced-motion: reduce)")
    assert any(".ventanilla__paso--en-curso::before" in parte[:200] for parte in reducido[1:])
