"""App Streamlit del asistente: capa delgada sobre ``banco_occidente_corpus.asistente``.

La app no contiene reglas de negocio: solo pinta, cachea y delega. El modelo se
invoca unicamente al pulsar un boton; ``st.cache_resource`` guarda el contexto y
un modelo por tarea, y ``st.cache_data`` guarda las respuestas por pregunta y
version. Los resultados con errores de contrato no se guardan, y una pregunta
con datos personales se responde sin llamar al modelo y sin entrar en la cache.

Se ejecuta con ``make app`` (``uv run streamlit run app/streamlit_app.py``).
"""

from __future__ import annotations

import time
from typing import Any

import streamlit as st
from langchain_core.language_models import BaseChatModel

from banco_occidente_corpus.asistente.contexto_prompt import (
    ContextoAusente,
    ContextoPrompt,
    cargar_contexto,
)
from banco_occidente_corpus.asistente.manifest import (
    ManifestAusente,
    MetadatosContexto,
    cargar_metadatos,
    fecha_version_contexto,
)
from banco_occidente_corpus.asistente.metricas import formatear_metricas
from banco_occidente_corpus.asistente.modelo import (
    MODELO_POR_DEFECTO,
    FaltaApiKey,
    api_key_desde_entorno,
    crear_modelo_para,
)
from banco_occidente_corpus.asistente.prompts import (
    VERSION_POR_DEFECTO,
    versiones_disponibles,
)
from banco_occidente_corpus.asistente.servicio import (
    PROMPT_SIN_MODELO,
    ResultadoFAQ,
    ResultadoQA,
    ResultadoResumen,
    detectar_pii_pregunta,
    ejecutar_faq,
    ejecutar_pregunta,
    ejecutar_resumen,
    respuesta_pii,
)

AVISO = (
    "Responde solo con información pública del sitio del Banco de Occidente; "
    "no reemplaza la asesoría oficial"
)

_CLAVE_PREGUNTA = "resultado_pregunta"
_CLAVE_FAQ = "resultado_faq"
_CLAVE_RESUMEN = "resultado_resumen"
_MARCAS_VISTAS = "marcas_vistas"

#: Margen para distinguir un calculo recien hecho de uno servido por la cache.
_MARGEN_RECIENTE = 2.0


class _SinCachear(Exception):
    """Resultado con errores: se propaga para que no quede en la cache de la app.

    Streamlit no guarda el resultado de una funcion cacheada que lanza: el
    siguiente clic en Generar vuelve a llamar al modelo.
    """

    def __init__(self, resultado: Any) -> None:
        self.resultado = resultado
        self.marca = time.time()
        super().__init__("resultado con errores de validacion")


# --------------------------------------------------------------------- cache


@st.cache_resource(show_spinner=False)
def _contexto() -> ContextoPrompt:
    """Carga una sola vez el contexto consolidado de ``data/contexto``."""
    return cargar_contexto()


@st.cache_resource(show_spinner=False)
def _metadatos() -> MetadatosContexto:
    """Carga una sola vez los tokens del manifest."""
    return cargar_metadatos()


@st.cache_resource(show_spinner=False)
def _modelo(tarea: str, nombre: str) -> BaseChatModel:
    """Crea una vez el modelo de cada tarea, con su temperatura y su tope."""
    return crear_modelo_para(tarea, modelo=nombre)


@st.cache_data(ttl=600, show_spinner=False)
def _fecha_version() -> str | None:
    """Fecha del commit que versiono el contexto (consulta git como maximo cada 10 min)."""
    return fecha_version_contexto()


@st.cache_data(max_entries=64, show_spinner=False)
def _pregunta(
    nombre: str,
    version: str,
    tokens: int,
    versionada: str | None,
    pregunta: str,
) -> tuple[ResultadoQA, float]:
    """Respuesta de Q&A cacheada por modelo, version, contexto y pregunta."""
    resultado = ejecutar_pregunta(
        _modelo("qa", nombre),
        version,
        pregunta,
        contexto=_contexto(),
    )
    return resultado, time.time()


@st.cache_data(max_entries=8, show_spinner=False)
def _faq(nombre: str, tokens: int, versionada: str | None) -> tuple[ResultadoFAQ, float]:
    """FAQ cacheada; si la validacion falla no se guarda."""
    resultado = ejecutar_faq(_modelo("faq", nombre), contexto=_contexto())
    if resultado.faq is None:
        raise _SinCachear(resultado)
    return resultado, time.time()


@st.cache_data(max_entries=8, show_spinner=False)
def _resumen(
    nombre: str,
    tema: str,
    tokens: int,
    versionada: str | None,
) -> tuple[ResultadoResumen, float]:
    """Resumen cacheado; si la validacion falla no se guarda."""
    resultado = ejecutar_resumen(_modelo("resumen", nombre), tema, contexto=_contexto())
    if resultado.resumen is None:
        raise _SinCachear(resultado)
    return resultado, time.time()


# ---------------------------------------------------------------- presentacion


def _recien_calculada(marca: float) -> bool:
    """Indica si la marca se creo en esta ejecucion y no viene de la cache."""
    if _MARCAS_VISTAS not in st.session_state:
        st.session_state[_MARCAS_VISTAS] = set()
    vistas: set[float] = st.session_state[_MARCAS_VISTAS]
    if marca in vistas:
        return False
    vistas.add(marca)
    return (time.time() - marca) < _MARGEN_RECIENTE


def _leyenda_tiempo(segundos: float, desde_cache: bool) -> str:
    """Tiempo de generacion o aviso de que la respuesta vino de la cache."""
    if desde_cache:
        return "desde la caché de la app"
    return f"Tiempo de generación: {segundos:.1f} s"


def _formatear_fecha(fecha: str | None) -> str:
    """Recorta la fecha ISO de git para mostrarla en la barra lateral."""
    if not fecha:
        return "no disponible"
    return fecha[:16].replace("T", " ")


def _detalles(
    *,
    prompt: str,
    modelo: str,
    segundos: float,
    desde_cache: bool,
    avisos: tuple[str, ...],
    metricas: dict[str, Any],
    texto_crudo: str | None = None,
    errores: tuple[str, ...] = (),
    nota_crudo: str = "",
) -> None:
    """Desplegable con prompt, avisos, metricas y respuesta cruda."""
    with st.expander("Detalles técnicos"):
        if prompt == PROMPT_SIN_MODELO:
            st.caption("Prompt: sin modelo (la pregunta contiene datos personales).")
        else:
            st.caption(f"Prompt: {prompt} | Modelo: {modelo}")
        if prompt != PROMPT_SIN_MODELO:
            st.caption(_leyenda_tiempo(segundos, desde_cache))
        if errores:
            st.markdown("**Errores de validación**")
            st.code("\n".join(errores))
        st.markdown("**Avisos de validación**")
        st.code(", ".join(avisos) if avisos else "ninguno")
        st.markdown("**Métricas**")
        st.code(formatear_metricas(metricas) or "no disponibles")
        if texto_crudo:
            st.markdown("**Respuesta cruda del modelo**")
            st.code(texto_crudo)
        elif nota_crudo:
            st.caption(nota_crudo)


def _mostrar_pregunta(resultado: ResultadoQA, desde_cache: bool, modelo: str) -> None:
    """Pinta la respuesta de Q&A con su fuente y sus detalles tecnicos."""
    st.markdown(resultado.respuesta.texto)
    if resultado.respuesta.fuente:
        st.link_button("Abrir la fuente", resultado.respuesta.fuente)
    if resultado.prompt == PROMPT_SIN_MODELO:
        st.caption("Sin llamada al modelo: la pregunta contiene datos personales.")
    else:
        st.caption(_leyenda_tiempo(resultado.segundos, desde_cache))
    _detalles(
        prompt=resultado.prompt,
        modelo=modelo,
        segundos=resultado.segundos,
        desde_cache=desde_cache,
        avisos=resultado.respuesta.avisos,
        metricas=resultado.respuesta.metricas,
        texto_crudo=resultado.respuesta.texto_crudo,
    )


def _mostrar_faq(resultado: ResultadoFAQ, desde_cache: bool, modelo: str) -> None:
    """Pinta las diez preguntas frecuentes, cada una con fuente y detalles."""
    if resultado.faq is None:
        st.error("La FAQ generada no cumplió el contrato de validación. Vuelve a intentarlo.")
        _detalles(
            prompt=resultado.prompt,
            modelo=modelo,
            segundos=resultado.segundos,
            desde_cache=desde_cache,
            avisos=(),
            metricas=resultado.metricas,
            errores=resultado.errores,
            nota_crudo="La respuesta cruda del modelo solo se conserva en Q&A (--verbose).",
        )
        return

    st.caption(_leyenda_tiempo(resultado.segundos, desde_cache))
    for indice, item in enumerate(resultado.faq.preguntas, 1):
        st.markdown(f"**{indice}. {item.pregunta.strip()}**")
        st.markdown(item.respuesta.strip())
        st.markdown(f"[Fuente]({item.fuente.url.strip()})")
        _detalles(
            prompt=resultado.prompt,
            modelo=modelo,
            segundos=resultado.segundos,
            desde_cache=desde_cache,
            avisos=(),
            metricas=resultado.metricas,
            texto_crudo=item.model_dump_json(indent=2),
            nota_crudo="Salida estructurada validada del modelo.",
        )


def _mostrar_resumen(resultado: ResultadoResumen, desde_cache: bool, modelo: str) -> None:
    """Pinta el resumen con sus fuentes y sus detalles tecnicos."""
    if resultado.resumen is None:
        st.error("El resumen no cumplió el contrato de validación. Vuelve a intentarlo.")
        _detalles(
            prompt=resultado.prompt,
            modelo=modelo,
            segundos=resultado.segundos,
            desde_cache=desde_cache,
            avisos=(),
            metricas=resultado.metricas,
            errores=resultado.errores,
            nota_crudo="La respuesta cruda del modelo solo se conserva en Q&A (--verbose).",
        )
        return

    st.markdown(resultado.resumen.texto)
    for url in resultado.resumen.fuentes:
        st.markdown(f"- [{url}]({url})")
    st.caption(_leyenda_tiempo(resultado.segundos, desde_cache))
    _detalles(
        prompt=resultado.prompt,
        modelo=modelo,
        segundos=resultado.segundos,
        desde_cache=desde_cache,
        avisos=resultado.resumen.avisos,
        metricas=resultado.resumen.metricas,
        nota_crudo=(
            "La respuesta cruda del modelo solo se conserva en Q&A (--verbose); "
            "arriba está el texto validado."
        ),
    )


# --------------------------------------------------------------------- arranque


st.set_page_config(page_title="Asistente del corpus - Banco de Occidente", layout="wide")

st.title("Asistente del Banco de Occidente")
st.info(AVISO)

try:
    contexto = _contexto()
except ContextoAusente as exc:
    st.error(str(exc))
    st.stop()

tokens = 0
try:
    metadatos = _metadatos()
    tokens = metadatos.tokens
except ManifestAusente as exc:
    metadatos = MetadatosContexto(
        tokens=0,
        max_tokens=0,
        tokens_metodo="",
        paginas_incluidas=0,
    )
    st.sidebar.warning(str(exc))

fecha = _fecha_version()
versionada = fecha

hay_clave = True
try:
    api_key_desde_entorno()
except FaltaApiKey as exc:
    hay_clave = False
    st.error("Falta la clave de la API del modelo: los botones quedan deshabilitados.")
    st.code(str(exc))

with st.sidebar:
    st.subheader("Configuración")
    nombre_modelo = st.selectbox("Modelo", [MODELO_POR_DEFECTO])
    versiones = versiones_disponibles("qa") or [VERSION_POR_DEFECTO]
    por_defecto = (
        versiones.index(VERSION_POR_DEFECTO)
        if VERSION_POR_DEFECTO in versiones
        else len(versiones) - 1
    )
    version_qa = st.selectbox(
        "Versión del prompt (Preguntas)",
        versiones,
        index=por_defecto,
    )
    st.caption(f"Preguntas frecuentes y Resumen usan siempre {VERSION_POR_DEFECTO}.")
    st.divider()
    st.caption(f"Contexto: {metadatos.tokens:,} tokens (tope {metadatos.max_tokens:,})")
    st.caption(f"Contexto versionado el {_formatear_fecha(fecha)}")
    st.caption(f"Páginas incluidas: {metadatos.paginas_incluidas:,}")

tab_preguntas, tab_faq, tab_resumen = st.tabs(["Preguntas", "Preguntas frecuentes", "Resumen"])

with tab_preguntas:
    st.markdown("Pregunta por productos, requisitos, tasas o canales de atención.")
    pregunta = st.text_area(
        "Tu pregunta",
        value="",
        height=100,
        placeholder="¿Qué necesito para abrir una cuenta de ahorros?",
    )
    if st.button(
        "Preguntar",
        type="primary",
        disabled=not hay_clave or not pregunta.strip(),
    ):
        deteccion = detectar_pii_pregunta(pregunta, contexto=contexto)
        if deteccion is not None:
            st.session_state[_CLAVE_PREGUNTA] = (respuesta_pii(contexto, deteccion), False)
        else:
            with st.spinner("Consultando al modelo..."):
                resultado_qa, marca_qa = _pregunta(
                    nombre_modelo,
                    version_qa,
                    tokens,
                    versionada,
                    pregunta,
                )
            st.session_state[_CLAVE_PREGUNTA] = (
                resultado_qa,
                not _recien_calculada(marca_qa),
            )

    if _CLAVE_PREGUNTA in st.session_state:
        guardado_qa, desde_cache_qa = st.session_state[_CLAVE_PREGUNTA]
        _mostrar_pregunta(guardado_qa, desde_cache_qa, nombre_modelo)

with tab_faq:
    st.markdown("Genera diez preguntas frecuentes de un cliente nuevo, cada una con su fuente.")
    if st.button("Generar", key="boton_faq", disabled=not hay_clave):
        with st.spinner("Generando las diez preguntas frecuentes..."):
            try:
                resultado_faq, marca_faq = _faq(nombre_modelo, tokens, versionada)
            except _SinCachear as exc:
                resultado_faq, marca_faq = exc.resultado, exc.marca
        st.session_state[_CLAVE_FAQ] = (
            resultado_faq,
            not _recien_calculada(marca_faq),
        )

    if _CLAVE_FAQ in st.session_state:
        guardado_faq, desde_cache_faq = st.session_state[_CLAVE_FAQ]
        _mostrar_faq(guardado_faq, desde_cache_faq, nombre_modelo)

with tab_resumen:
    st.markdown("Genera un resumen ejecutivo del corpus público, con sus fuentes.")
    if st.button("Generar", key="boton_resumen", disabled=not hay_clave):
        with st.spinner("Generando el resumen ejecutivo..."):
            try:
                resultado_resumen, marca_resumen = _resumen(
                    nombre_modelo,
                    "",
                    tokens,
                    versionada,
                )
            except _SinCachear as exc:
                resultado_resumen, marca_resumen = exc.resultado, exc.marca
        st.session_state[_CLAVE_RESUMEN] = (
            resultado_resumen,
            not _recien_calculada(marca_resumen),
        )

    if _CLAVE_RESUMEN in st.session_state:
        guardado_resumen, desde_cache_resumen = st.session_state[_CLAVE_RESUMEN]
        _mostrar_resumen(guardado_resumen, desde_cache_resumen, nombre_modelo)

st.divider()
st.caption(
    "Cada clic en un botón hace una llamada al modelo; las respuestas repetidas de la "
    "sesión se sirven desde la caché de la app."
)
