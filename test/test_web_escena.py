"""Pruebas sin navegador de la pantalla de la escena «Pana vs. el gota a gota».

Comprueban que los turnos de ejemplo cumplen el contrato `TurnoEscena`
(`openspec/changes/demo-gota-a-gota/design.md`, decisión 1), que sus cifras
cuadran con las fórmulas de Don Gota, con el motor del diagnóstico y con
``config/tasas.toml``, y que la página se sirve y no carga nada de internet.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "app" / "web"
ESCENA = WEB / "escena"

PERSONAJES = {"pana", "don_gota", "joven", "agente_joven", "agente_banco", "auditor", "invitado"}
#: El invitado escribe por WhatsApp y va solo en subtítulo: no tiene voz ni retrato.
PERSONAJES_CON_VOZ = PERSONAJES - {"invitado"}
ORIGENES = {"guion_fijo", "motor", "llm", "reglas", "entrada_voz", "canal"}
TIPOS_FUENTE = {"config", "gold", "motor", "calculo_gota", "usura", "guion", "documento"}
UNIDADES = {"pesos", "porcentaje_ea", "porcentaje", "meses", "dias", "veces"}
SEMAFOROS = {None, "verde", "amarillo", "rojo"}
VEREDICTOS = {"conforme", "con_observaciones", "objeta"}
CAMPOS = {
    "id",
    "orden",
    "personaje",
    "texto",
    "subtitulo",
    "cifras",
    "escenario",
    "origen",
    "hallazgos",
}


def _datos() -> dict[str, Any]:
    """Lee la escena de ejemplo completa."""
    return json.loads((ESCENA / "turnos-ejemplo.json").read_text(encoding="utf-8"))


def _turnos() -> list[dict[str, Any]]:
    """Lee los turnos de ejemplo."""
    return _datos()["turnos"]


def _cifras() -> dict[str, Decimal]:
    """Junta todas las cifras por la referencia de su fuente (la última gana)."""
    return {c["fuente"]["referencia"]: Decimal(c["valor"]) for t in _turnos() for c in t["cifras"]}


def test_cada_turno_cumple_el_contrato() -> None:
    """Campos exactos de TurnoEscena y valores dentro de los conjuntos del contrato."""
    turnos = _turnos()
    assert [t["orden"] for t in turnos] == list(range(len(turnos)))
    assert len({t["id"] for t in turnos}) == len(turnos)
    for turno in turnos:
        ident = turno["id"]
        assert set(turno) == CAMPOS, ident
        assert turno["personaje"] in PERSONAJES, ident
        assert turno["origen"] in ORIGENES, ident
        assert turno["texto"].strip(), ident
        assert isinstance(turno["hallazgos"], list), ident
        if turno["escenario"] is not None:
            assert turno["escenario"]["semaforo"] in SEMAFOROS, ident
        for cifra in turno["cifras"]:
            assert set(cifra) == {"etiqueta", "valor", "valor_legible", "unidad", "fuente"}, ident
            assert cifra["unidad"] in UNIDADES, ident
            assert cifra["fuente"]["tipo"] in TIPOS_FUENTE, ident
            assert cifra["fuente"]["referencia"], ident
            Decimal(cifra["valor"])


def test_el_veredicto_va_aparte_y_sin_colores() -> None:
    """El veredicto del auditor es conforme/con_observaciones/objeta, nunca un color."""
    veredicto = _datos()["veredicto"]
    assert veredicto["veredicto"] in VEREDICTOS
    assert set(veredicto["turnos_revisados"]) == {t["id"] for t in _turnos()}


def test_el_ejemplo_cumple_el_contrato_de_python() -> None:
    """Si ya está escena/contratos.py (#174), cada turno lo valida con Pydantic."""
    contratos = pytest.importorskip("banco_occidente_corpus.escena.contratos")
    for turno in _turnos():
        contratos.TurnoEscena.model_validate(turno)
    contratos.VeredictoAuditor.model_validate(_datos()["veredicto"])


def test_los_cinco_que_hablan_aparecen() -> None:
    """El ejemplo recorre a los personajes con voz y cierra el auditor."""
    turnos = _turnos()
    assert {t["personaje"] for t in turnos} == PERSONAJES_CON_VOZ
    assert turnos[-1]["personaje"] == "auditor"


def test_don_gota_nunca_sale_de_un_modelo() -> None:
    """Regla del diseño: Don Gota siempre es guion_fijo, nunca llm."""
    assert all(t["origen"] == "guion_fijo" for t in _turnos() if t["personaje"] == "don_gota")


def test_los_agentes_no_dicen_cifras() -> None:
    """Los turnos del modelo no escriben números: las cifras van en `cifras`."""
    for turno in _turnos():
        if turno["origen"] == "llm":
            assert not re.search(r"\d", turno["texto"]), turno["id"]


def test_cifras_de_don_gota_siguen_el_diseno() -> None:
    """Fórmulas del design.md §2: 20 % mensual, ciclo de 30 días, 36 renovaciones."""
    cifras = _cifras()
    monto = cifras["escena.gota#monto"]
    mensual = cifras["config/escena.toml#gota.tasa_mensual"]
    assert cifras["config/escena.toml#gota.meses_horizonte"] == 36
    assert cifras["escena.gota#total_ciclo"] == monto + monto * mensual
    assert cifras["escena.gota#cuota_diaria"] == (monto + monto * mensual) / 30
    assert cifras["escena.gota#total_pagado_horizonte"] == monto + monto * mensual * 36
    assert float(cifras["escena.gota#tasa_ea"]) == pytest.approx(
        float((1 + mensual) ** 12 - 1), abs=1e-4
    )


def test_cifras_del_banco_salen_del_motor() -> None:
    """Cuota, total y tasa del banco son los del motor con la tasa máxima publicada."""
    from datetime import date

    from banco_occidente_corpus.canal.contratos import EntradaDiagnostico
    from banco_occidente_corpus.diagnostico.motor import calcular

    cifras = _cifras()
    entrada = EntradaDiagnostico.model_validate(
        {
            "producto": "libre_inversion",
            "vinculacion": "empleado",
            "ingreso_mensual": Decimal(1_500_000),
            "gastos_mensuales": Decimal(750_000),
            "cuotas_deudas": Decimal(0),
            "monto_credito": cifras["diagnostico.motor#entrada.monto_credito"],
            "plazo_meses": 36,
            "rango_usado": {},
        }
    )
    resultado = calcular(entrada, hoy=date(2026, 11, 27))
    assert cifras["diagnostico.motor#cuota_mensual.hasta"] == resultado.cuota_mensual.hasta
    assert cifras["diagnostico.motor#total_pagado.hasta"] == resultado.total_pagado.hasta
    assert cifras["diagnostico.motor#tasa_ea.hasta"] == resultado.tasa_ea.hasta
    assert resultado.semaforo == _turnos()[-1]["escenario"]["semaforo"]


def test_el_ejemplo_se_declara_ejemplo() -> None:
    """El JSON dice que es maquetación y que lo reemplaza make escena-proyectada."""
    descripcion = _datos()["descripcion"]
    assert "EJEMPLO DE MAQUETACIÓN" in descripcion
    assert "make escena-proyectada" in descripcion


def test_cifras_del_banco_usan_la_usura_y_quedan_debajo() -> None:
    """La usura de ejemplo es la de config/tasas.toml y la TEA del banco no la pasa."""
    with (RAIZ / "config" / "tasas.toml").open("rb") as fh:
        usura = Decimal(str(tomllib.load(fh)["usura"]["tasa_ea"]))
    cifras = _cifras()
    assert cifras["config/tasas.toml#usura.tasa_ea"] == usura
    assert cifras["diagnostico.motor#tasa_ea.hasta"] <= usura < cifras["escena.gota#tasa_ea"]


def test_la_pagina_carga_sus_archivos_locales() -> None:
    """escena.html usa su CSS y su JS, sin URLs externas."""
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    assert 'href="escena/escena.css"' in html
    assert 'src="escena/escena.js"' in html
    for archivo in (WEB / "escena.html", *ESCENA.glob("*.*")):
        texto = archivo.read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)=["']https?://""", texto), archivo.name
        assert "innerHTML" not in texto, archivo.name


def test_ids_que_usa_el_js_existen_en_el_html() -> None:
    """Cada porId("...") de escena.js tiene su elemento en escena.html."""
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    codigo = (ESCENA / "escena.js").read_text(encoding="utf-8")
    fijos = set(re.findall(r'porId\("([a-z-]+)"\)', codigo))
    assert fijos
    for identificador in fijos:
        assert f'id="{identificador}"' in html, identificador


def test_el_contrato_js_declara_los_mismos_conjuntos() -> None:
    """contrato.js usa los mismos personajes, orígenes, fuentes, unidades y veredictos."""
    codigo = (ESCENA / "contrato.js").read_text(encoding="utf-8")
    for valor in PERSONAJES | ORIGENES | TIPOS_FUENTE | UNIDADES | VEREDICTOS:
        assert f'"{valor}"' in codigo, valor
    origenes = re.search(r"export const ORIGENES = Object\.freeze\(\[(.*?)\]\);", codigo, re.S)
    assert origenes
    assert set(re.findall(r'"([a-z_]+)"', origenes.group(1))) == ORIGENES


def test_cada_personaje_tiene_rostro_con_boca() -> None:
    """rostros.js dibuja a todos los del contrato (respaldo) y escena.js usa los retratos."""
    codigo = (ESCENA / "rostros.js").read_text(encoding="utf-8")
    bloque = re.search(r"const DIBUJOS = Object\.freeze\(\{(.*?)\}\);", codigo, re.S)
    assert bloque
    claves = set(re.findall(r"^\s*([a-z_]+)(?::|,)", bloque.group(1), re.M))
    assert claves == PERSONAJES
    assert codigo.count('class: "escena__boca"') == len(PERSONAJES)
    assert "retrato(personaje)" in (ESCENA / "escena.js").read_text(encoding="utf-8")


def test_cada_personaje_tiene_retrato_liviano() -> None:
    """Hay un retrato .webp por personaje con voz y ninguno pesa más de 60 KB."""
    retratos = {archivo.stem: archivo for archivo in (ESCENA / "rostros").glob("*.webp")}
    assert set(retratos) == PERSONAJES_CON_VOZ
    for nombre, archivo in retratos.items():
        assert archivo.stat().st_size < 60_000, nombre
        assert archivo.read_bytes()[8:12] == b"WEBP", nombre


def _anfitrion() -> str:
    """Lee el módulo del anfitrión."""
    return (ESCENA / "anfitrion.js").read_text(encoding="utf-8")


def test_la_presentacion_presenta_a_cada_agente_en_orden() -> None:
    """Pana abre y cierra; en medio se presentan Don Gota, los agentes y el auditor."""
    bloque = re.search(
        r"export const INTRODUCCION = Object\.freeze\(\s*\[(.*?)\]\.map", _anfitrion(), re.S
    )
    assert bloque
    turnos = re.findall(
        r'turnoSimple\(\s*"([a-z_]+)",\s*"(.*?)",\s*"([a-z_]+)",?\s*\)', bloque.group(1), re.S
    )
    assert [p for p, _, _ in turnos] == [
        "pana",
        "pana",
        "don_gota",
        "agente_joven",
        "agente_banco",
        "auditor",
        "pana",
    ]
    assert all(origen == "guion_fijo" for _, _, origen in turnos)
    assert "actividad práctica" in turnos[0][1]
    assert "preguntas" in turnos[-1][1]


def test_la_respuesta_de_las_artistas_es_fija_y_menciona_al_profe() -> None:
    """Karol G y Shakira tienen respuesta fija de reglas, sin pasar por el modelo."""
    codigo = _anfitrion()
    assert re.search(r"/karol \?g\\b\|shakira\|bichota/", codigo)
    respuesta = re.search(r"artistas:\s*\"(.*?)\"", codigo, re.S)
    assert respuesta
    assert "profesor Jan" in respuesta.group(1)
    assert "nada que ver con nuestro proyecto" in respuesta.group(1)
    assert "también" in respuesta.group(1)


def test_fuera_de_tema_dice_que_no_tiene_informacion() -> None:
    """Lo que no es del proyecto recibe la frase fija y la pregunta tiene tope."""
    codigo = _anfitrion()
    assert "No tengo información sobre eso" in codigo
    assert "export const LARGO_MAXIMO = 300;" in codigo
    assert '"/api/escena/introduccion"' in codigo
    assert '"/api/escena/pregunta"' in codigo
    assert "JSON.stringify({ pregunta:" in codigo


def test_el_rechazo_del_servidor_cede_ante_la_ficha_local() -> None:
    """Si el servidor solo rechaza, la pantalla prueba antes su ficha local."""
    anfitrion = (ESCENA / "anfitrion.js").read_text(encoding="utf-8")
    bloque = re.search(r"SIN_RESPUESTA_DEL_SERVIDOR = Object\.freeze\(\[(.*?)\]\)", anfitrion)
    assert bloque is not None
    ids = set(re.findall(r'"([a-z0-9_.]+)"', bloque.group(1)))
    assert ids == {"pana.pregunta.rechazo.v1", "pana.pregunta.respaldo.v1"}
    servidor = RAIZ / "src" / "banco_occidente_corpus" / "escena" / "pregunta.py"
    if servidor.exists():
        codigo = servidor.read_text(encoding="utf-8")
        for id_turno in ids:
            assert f'id="{id_turno}"' in codigo, id_turno


def test_la_ficha_local_responde_cuentame_del_proyecto() -> None:
    """El respaldo del navegador no deja «cuéntame del proyecto» sin respuesta.

    La entrada general va al final para no tapar las respuestas específicas
    que también mencionan el proyecto.
    """
    bloque = re.search(r"const FICHA = Object\.freeze\(\[(.*?)\]\);", _anfitrion(), re.S)
    assert bloque is not None
    claves = re.findall(r"claves: \[(.*?)\]", bloque.group(1))
    assert claves
    ultima = claves[-1]
    assert '"proyecto"' in ultima
    assert '"sucursal 1965"' in ultima
    assert "Se llama Sucursal 1965" in bloque.group(1)


def test_el_panel_de_recursos_trae_repositorio_whatsapp_y_diagramas() -> None:
    """El panel de la tecla G ofrece el QR del repositorio y los seis diagramas."""
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    assert re.search(r'<aside[^>]*id="escena-recursos"[^>]*\bhidden\b', html)
    assert 'id="escena-ver-recursos"' in html
    assert 'id="escena-repositorio"' in html
    assert 'id="escena-repositorio-qr"' in html
    assert 'src="/api/escena/repositorio/qr.png"' in html
    assert 'id="escena-whatsapp-qr"' in html
    for nombre in (
        "arquitectura",
        "datos",
        "canal",
        "diagnostico",
        "agente-openclaw",
        "despliegue-openclaw",
    ):
        assert f'href="/diagramas/{nombre}.html"' in html, nombre
    recurso = (ESCENA / "recursos.js").read_text(encoding="utf-8")
    assert '"/api/escena/repositorio"' in recurso
    assert '"/api/escena/whatsapp"' in recurso
    assert "wa.me" not in recurso
    assert not re.search(r"\d{10,}", recurso)
    codigo = (ESCENA / "escena.js").read_text(encoding="utf-8")
    assert 'tecla === "g"' in codigo


def test_el_microfono_de_la_entrada_habla_con_la_api() -> None:
    """La entrada del voluntario (V) manda lo que oye a /api/escena/hablar."""
    codigo = (ESCENA / "captura.js").read_text(encoding="utf-8")
    assert '"/api/escena/hablar"' in codigo
    assert "void enviar();" in codigo
    assert "JSON.stringify({ texto })" in codigo
    assert "ESPERA_HABLAR_MS" in codigo
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    assert 'id="captura-microfono"' in html
    assert 'id="captura-pana"' in html
    assert 'id="captura-pana-estado"' in html


def test_el_microfono_escucha_en_espanol_de_colombia_con_respaldo() -> None:
    """Un solo resultado en es-CO; sin reconocimiento se escribe la pregunta."""
    codigo = (ESCENA / "microfono.js").read_text(encoding="utf-8")
    assert 'instancia.lang = "es-CO";' in codigo
    assert "instancia.continuous = false;" in codigo
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    assert 'id="escena-pregunta-texto"' in html
    assert 'id="escena-microfono"' in html


def test_los_pasos_empiezan_en_presentacion_y_terminan_en_preguntas() -> None:
    """contrato.js agrega la presentación al inicio y las preguntas al final."""
    codigo = (ESCENA / "contrato.js").read_text(encoding="utf-8")
    bloque = re.search(r"export const PASOS = Object\.freeze\(\[(.*?)\]\);", codigo, re.S)
    assert bloque
    pasos = re.findall(r'"([^"]+)"', bloque.group(1))
    assert pasos[0] == "Presentación"
    assert pasos[-1] == "Preguntas"
    assert len(pasos) == 8


@pytest.mark.parametrize(
    "ruta",
    [
        "/escena.html",
        "/escena/escena.js",
        "/escena/contrato.js",
        "/escena/rostros.js",
        "/escena/rostros/pana.webp",
        "/escena/escena.css",
        "/escena/turnos-ejemplo.json",
        "/escena/anfitrion.js",
        "/escena/microfono.js",
        "/escena/respaldo.js",
        "/escena/traza.js",
    ],
)
def test_la_app_sirve_la_escena(ruta: str) -> None:
    """Los archivos de la escena se sirven como estáticos."""
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    app = FastAPI()
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
    assert TestClient(app).get(ruta).status_code == 200


def test_la_trazabilidad_empieza_oculta_y_se_abre_con_la_t() -> None:
    """El panel del facilitador no se ve al cargar y tiene su tecla y su botón."""
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    assert re.search(r'<aside[^>]*id="escena-traza"[^>]*\bhidden\b', html)
    assert 'id="escena-ver-traza"' in html
    codigo = (ESCENA / "escena.js").read_text(encoding="utf-8")
    assert 'tecla === "t"' in codigo
    assert 'tecla === "n"' in codigo


def test_el_resumen_de_la_traza_busca_las_tres_tasas_por_su_fuente() -> None:
    """Usura, tasa del banco y del gota se reconocen por el tipo de fuente."""
    traza = (ESCENA / "traza.js").read_text(encoding="utf-8")
    for nombre in ("Usura", "Tasa del banco", "Tasa del gota", "Veredicto del auditor"):
        assert f'"{nombre}"' in traza
    assert 'c.fuente?.tipo === "usura"' in traza
    assert 'c.fuente?.tipo === "calculo_gota"' in traza


def test_el_respaldo_solo_usa_session_storage_y_con_try() -> None:
    """La escena guardada vive en la pestaña y nunca rompe la página."""
    respaldo = (ESCENA / "respaldo.js").read_text(encoding="utf-8")
    assert "localStorage" not in respaldo
    usos = respaldo.count("globalThis.sessionStorage")
    assert usos >= 3
    assert respaldo.count("try {") == 3
    for archivo in ESCENA.glob("*.js"):
        if archivo.name != "respaldo.js":
            assert "sessionStorage" not in archivo.read_text(encoding="utf-8"), archivo.name


def test_el_nucleo_deja_a_don_gota_pana_y_el_auditor() -> None:
    """El núcleo local no incluye la negociación ni al voluntario."""
    respaldo = (ESCENA / "respaldo.js").read_text(encoding="utf-8")
    personajes = re.search(r"PERSONAJES_NUCLEO = Object\.freeze\(\[(.*?)\]\)", respaldo)
    assert personajes is not None
    assert set(re.findall(r'"([a-z_]+)"', personajes.group(1))) == {"don_gota", "pana", "auditor"}
    codigo = (ESCENA / "escena.js").read_text(encoding="utf-8")
    assert '"/api/escena/proyectado"' in codigo
    assert "?modo=nucleo" in codigo


def test_cada_funcion_de_la_escena_tiene_jsdoc() -> None:
    """Toda función de los módulos de la escena va precedida de su comentario."""
    for archivo in ESCENA.glob("*.js"):
        texto = archivo.read_text(encoding="utf-8")
        for coincidencia in re.finditer(
            r"^(?:export )?(?:async )?function (\w+)", texto, re.MULTILINE
        ):
            previo = texto[: coincidencia.start()].rstrip()
            assert previo.endswith("*/"), f"{archivo.name}: {coincidencia.group(1)}"


# --- En vivo: el voluntario solo habla con Pana ------------------------------


def _bloque_html(html: str, inicio: str, fin: str) -> str:
    """Devuelve el trozo del HTML entre dos marcas (la primera incluida)."""
    desde = html.index(inicio)
    return html[desde : html.index(fin, desde)]


def test_en_vivo_el_panel_v_separa_el_flujo_guiado_de_la_conversacion() -> None:
    """Las tarjetas, el monto y Hablar/Enviar/Perfil seguro van en el bloque guiado."""
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    guiado = _bloque_html(html, 'id="captura-guiada"', 'id="captura-conversacion"')
    for elemento in (
        'id="captura-pregunta"',
        'id="captura-microfono"',
        'id="captura-enviar"',
        'id="captura-seguro"',
        'id="captura-confirmacion"',
    ):
        assert elemento in guiado, elemento
    conversacion = _bloque_html(html, 'id="captura-conversacion"', "</section>")
    assert 'id="captura-pana"' in conversacion
    assert 'data-texto-vivo="Toca y habla con Pana"' in conversacion
    assert 'id="captura-pana-escuche"' in conversacion
    assert "servicio externo" in conversacion
    assert 'id="captura-microfono"' not in conversacion


def test_en_vivo_el_css_oculta_el_flujo_guiado_solo_en_ese_modo() -> None:
    """Con `escena--en-vivo` se oculta el bloque guiado; fuera del modo sigue igual."""
    css = (ESCENA / "escena.css").read_text(encoding="utf-8")
    assert ".escena--en-vivo .escena__captura-guiada { display: none; }" in css
    assert ".escena:not(.escena--en-vivo) .escena__aviso--vivo { display: none; }" in css
    assert ".escena:not(.escena--en-vivo) .escena__captura-guiada" not in css


def test_en_vivo_la_captura_solo_manda_texto_a_hablar() -> None:
    """En vivo no se carga el catálogo ni se valida un monto: solo se habla con Pana."""
    codigo = (ESCENA / "captura.js").read_text(encoding="utf-8")
    alternar = codigo[codigo.index("async function alternar()") :]
    alternar = alternar[: alternar.index("\n}\n")]
    assert alternar.index("if (enVivo())") < alternar.index("cargarOpciones()")
    assert "abrirConversacion();" in alternar
    abrir = codigo[codigo.index("function abrirConversacion(") :]
    abrir = abrir[: abrir.index("\n}\n")]
    assert "cargarOpciones" not in abrir
    assert "pintarPregunta" not in abrir
    assert "Escuché: «${texto}»" in codigo
    assert "JSON.stringify({ texto })" in codigo
    assert 'classList.contains("escena--en-vivo")' in codigo
    # Al cerrar se suelta el foco para que E, P y Espacio sigan funcionando.
    assert "document.activeElement.blur()" in codigo


def test_al_entrar_en_vivo_se_empieza_desde_el_ultimo_turno() -> None:
    """E pide la lista desde el final; R sigue pidiendo desde el principio."""
    escena = (ESCENA / "escena.js").read_text(encoding="utf-8")
    assert "sondeo.iniciar({ desdeElFinal: true });" in escena
    assert "sondeo.reiniciar();" in escena
    envivo = (ESCENA / "envivo.js").read_text(encoding="utf-8")
    assert "sondeo.saltando = desdeElFinal;" in envivo
    assert "datos.turnos.length >= LIMITE_RUTA" in envivo


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node no está instalado")
def test_el_sondeo_desde_el_final_no_entrega_turnos_viejos() -> None:
    """Con `desdeElFinal`, la primera respuesta solo mueve el cursor; lo nuevo sí llega."""
    assert NODE
    url = (ESCENA / "envivo.js").as_uri()
    programa = f"""
const respuestas = [
  {{ turnos: [{{ seq: 5 }}, {{ seq: 6 }}], ultimo: 6 }},
  {{ turnos: [{{ seq: 7 }}], ultimo: 7 }},
];
const pedidas = [];
const recibidos = [];
let pendiente = null;
globalThis.window = {{
  setTimeout: (funcion) => {{ pendiente = funcion; return 1; }},
  clearTimeout: () => {{}},
}};
globalThis.document = {{ hidden: false, addEventListener: () => {{}} }};
globalThis.fetch = async (url) => {{
  pedidas.push(url);
  const datos = respuestas.shift() ?? {{ turnos: [], ultimo: 7 }};
  return {{ ok: true, json: async () => datos }};
}};
const {{ crearSondeo }} = await import({json.dumps(url)});
const sondeo = crearSondeo({{
  alRecibir: (registros) => recibidos.push(...registros.map((r) => r.seq)),
  alEstado: () => {{}},
}});
const esperar = () => new Promise((listo) => setImmediate(listo));
sondeo.iniciar({{ desdeElFinal: true }});
await esperar(); await esperar();
const vuelta = pendiente; pendiente = null; vuelta();
await esperar(); await esperar();
sondeo.detener();
console.log(JSON.stringify({{ pedidas, recibidos }}));
"""
    salida = subprocess.run(
        [NODE, "--input-type=module", "-e", programa],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    resultado = json.loads(salida.stdout)
    assert resultado["recibidos"] == [7]
    assert resultado["pedidas"][0].endswith("desde=0")
    assert resultado["pedidas"][1].endswith("desde=6")


# --- De la presentación a la conversación por voz con Pana -------------------


def _funcion(codigo: str, firma: str) -> str:
    """Devuelve el cuerpo de una función de un módulo JS, hasta su cierre."""
    cuerpo = codigo[codigo.index(firma) :]
    return cuerpo[: cuerpo.index("\n}\n")]


def test_la_presentacion_termina_en_el_qr_de_whatsapp() -> None:
    """Tras la invitación de Pana queda el QR con «Esperando al voluntario…»."""
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    espera = _bloque_html(html, 'id="escena-espera"', "</section>")
    assert 'id="escena-espera-qr"' in espera
    assert "Esperando al voluntario…" in espera
    assert "ESCENA" in espera
    codigo = (ESCENA / "escena.js").read_text(encoding="utf-8")
    termino = _funcion(codigo, "function terminoLaPresentacion()")
    assert "estado.largoIntroduccion - 1" in termino
    assert 'estado.modo !== "nucleo"' in termino
    reproducir = _funcion(codigo, "async function reproducir()")
    assert "terminoLaPresentacion()" in reproducir
    assert "mostrarEspera();" in reproducir
    siguiente = _funcion(codigo, "function siguiente()")
    assert "mostrarEspera();" in siguiente
    espera_js = _funcion(codigo, "function mostrarEspera()")
    assert 'ponerQrWhatsapp(porId("escena-espera-qr"))' in espera_js
    assert "vigia?.iniciar({ desdeElFinal: true });" in espera_js
    # La espera no abre el flujo guiado.
    assert "escena:captura" not in espera_js
    recursos = (ESCENA / "recursos.js").read_text(encoding="utf-8")
    assert "export async function ponerQrWhatsapp(imagen)" in recursos


def test_el_primer_turno_del_canal_activa_el_modo_conversacion() -> None:
    """El vigía de la espera pasa solo al modo conversación con un turno del canal."""
    codigo = (ESCENA / "escena.js").read_text(encoding="utf-8")
    assert "vigia = crearSondeo({ alRecibir: alVigilar" in codigo
    vigilar = _funcion(codigo, "function alVigilar(registros, ultimo)")
    assert 'registro?.origen === "canal"' in vigilar
    assert "entrarEnVivo({ registros, ultimo });" in vigilar
    entrar = _funcion(codigo, "function entrarEnVivo(")
    assert "ocultarEspera();" in entrar
    assert 'new CustomEvent("escena:conversacion")' in entrar
    assert "sondeo.iniciar({ desde: ultimo });" in entrar
    assert "recibirEnVivo(registros);" in entrar
    # La tecla E sigue forzando el modo, desde el último turno.
    assert "sondeo.iniciar({ desdeElFinal: true });" in entrar
    assert 'tecla === "e"' in codigo


def test_en_modo_conversacion_solo_se_ve_el_boton_de_pana() -> None:
    """Botón grande y «Detener la escucha»; los controles guiados quedan ocultos."""
    html = (WEB / "escena.html").read_text(encoding="utf-8")
    conversacion = _bloque_html(html, 'id="captura-conversacion"', "</section>")
    assert 'id="captura-pana-detener"' in conversacion
    css = (ESCENA / "escena.css").read_text(encoding="utf-8")
    assert ".escena--en-vivo .escena__captura-guiada { display: none; }" in css
    assert ".escena:not(.escena--en-vivo) #captura-pana-detener { display: none; }" in css
    codigo = (ESCENA / "captura.js").read_text(encoding="utf-8")
    assert 'addEventListener("escena:conversacion", empezarConversacion)' in codigo
    assert 'addEventListener("escena:fin-conversacion", terminarConversacion)' in codigo


def test_el_microfono_se_reabre_cuando_pana_termina_la_cola() -> None:
    """Al vaciarse la cola tras un turno de Pana, la captura vuelve a escuchar."""
    escena = (ESCENA / "escena.js").read_text(encoding="utf-8")
    reproducir = _funcion(escena, "async function reproducir()")
    assert "avisarColaTerminada();" in reproducir
    aviso = _funcion(escena, "function avisarColaTerminada()")
    assert "estado.indice === estado.turnos.length - 1" in aviso
    assert 'ultimo?.personaje === "pana"' in aviso
    assert 'new CustomEvent("escena:pana-termino")' in aviso
    captura = (ESCENA / "captura.js").read_text(encoding="utf-8")
    assert 'addEventListener("escena:pana-termino", reabrirMicrofono)' in captura
    reabrir = _funcion(captura, "function reabrirMicrofono()")
    assert "estado.escuchaAutomatica" in reabrir
    assert "escuchando()" in reabrir
    assert "escucharAPana();" in reabrir
    detener = _funcion(captura, "function detenerEscucha()")
    assert "estado.escuchaAutomatica = false;" in detener
    assert "detenerMicrofono();" in detener


@pytest.mark.skipif(NODE is None, reason="Node no está instalado")
def test_el_sondeo_sigue_desde_el_cursor_de_la_espera() -> None:
    """`iniciar({desde})` pide desde ese cursor y entrega lo nuevo."""
    assert NODE
    url = (ESCENA / "envivo.js").as_uri()
    programa = f"""
const pedidas = [];
globalThis.window = {{ setTimeout: () => 1, clearTimeout: () => {{}} }};
globalThis.document = {{ hidden: false, addEventListener: () => {{}} }};
globalThis.fetch = async (url) => {{
  pedidas.push(url);
  return {{ ok: true, json: async () => ({{ turnos: [], ultimo: 42 }}) }};
}};
const {{ crearSondeo }} = await import({json.dumps(url)});
const sondeo = crearSondeo({{ alRecibir: () => {{}}, alEstado: () => {{}} }});
sondeo.iniciar({{ desde: 42 }});
await new Promise((listo) => setImmediate(listo));
sondeo.detener();
console.log(JSON.stringify(pedidas));
"""
    salida = subprocess.run(
        [NODE, "--input-type=module", "-e", programa],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(salida.stdout)[0].endswith("desde=42")
