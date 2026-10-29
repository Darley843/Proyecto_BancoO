"""Pestaña «Scraping»: pipeline por etapas, métricas y captura en vivo.

Capa delgada de la app: solo pinta, cachea y delega. Las cifras salen de
``banco_occidente_corpus.panel`` (lectura de disco, sin red) y la captura de
``banco_occidente_corpus.live_capture`` (que usa ``net.HttpClient`` y
``robots.txt``). Aquí no hay reglas de negocio ni peticiones propias.
"""

from __future__ import annotations

import streamlit as st

from banco_occidente_corpus.config import Config, load_config
from banco_occidente_corpus.live_capture import (
    DEFAULT_SAMPLE,
    DiscoveryAudit,
    LiveCapture,
    LiveStage,
    audit_discovery,
    check_queue_robots,
    new_workdir,
    run_capture,
    select_urls,
)
from banco_occidente_corpus.net import HttpClient
from banco_occidente_corpus.panel import (
    CorpusMetrics,
    PipelineSummary,
    Stage,
    corpus_metrics,
    pipeline_summary,
    queue_urls_file,
)

_CLAVE_CAPTURA = "captura_en_vivo"
_CLAVE_ROBOTS = "robots_de_la_cola"
_CLAVE_AUDITORIA = "auditoria_descubrimiento"

#: Coste medido de la auditoría completa (210 sitemaps con la pausa de 1,5 s).
_AUDIT_HINT = (
    "Tarda unos 7 min: es una petición por sitemap con la pausa de cortesía "
    "(210 sitemaps, 409,8 s en la última medición). No escribe nada."
)

_ICONOS = {"ok": "OK", "warning": "AVISO", "error": "ERROR"}


# --------------------------------------------------------------------- caché


@st.cache_data(ttl=60, show_spinner=False)
def _resumen() -> PipelineSummary:
    """Etapas del pipeline y deduplicación, cacheadas un minuto."""
    return pipeline_summary(load_config())


@st.cache_data(ttl=60, show_spinner=False)
def _metricas() -> CorpusMetrics:
    """Cifras del corpus y del contexto, cacheadas un minuto."""
    return corpus_metrics(load_config())


# ---------------------------------------------------------------- secciones


def _tarjeta(numero: int, etapa: Stage) -> None:
    """Pinta una etapa con su conteo, su explicación y sus notas."""
    with st.container(border=True):
        st.markdown(f"**{numero}. {etapa.title}**")
        st.caption(etapa.hint)
        if etapa.metrics:
            columnas = st.columns(len(etapa.metrics))
            for columna, metrica in zip(columnas, etapa.metrics, strict=False):
                columna.metric(metrica.label, metrica.value)
        if etapa.note:
            st.info(etapa.note)
        if etapa.warning:
            st.warning(etapa.warning)


def _robots_de_la_cola(config: Config) -> None:
    """Chequeo barato: una sola petición a robots.txt para toda la cola."""
    st.caption(
        "Comprobación barata: una sola petición a robots.txt para toda la cola, "
        "sin descargar ninguna página."
    )
    if st.button("Verificar robots.txt de la cola", key="boton_robots"):
        with st.spinner("Consultando robots.txt..."):
            try:
                with HttpClient(config) as cliente:
                    check = check_queue_robots(config, cliente)
            except Exception as exc:  # la app no debe caerse por un fallo de red
                st.error(f"No se pudo consultar robots.txt ({type(exc).__name__}).")
            else:
                st.session_state[_CLAVE_ROBOTS] = check
    check = st.session_state.get(_CLAVE_ROBOTS)
    if check is not None:
        estado = "disponible" if check.robots_found else "no disponible (se asume permitido)"
        st.caption(
            f"robots.txt {estado}: {len(check.allowed)} URLs permitidas y "
            f"{len(check.blocked)} bloqueadas de la cola."
        )


def _etapas(config: Config, resumen: PipelineSummary) -> None:
    """Pinta las cinco etapas en orden, con el chequeo de robots tras Descubrir."""
    for numero, etapa in enumerate(resumen.stages, start=1):
        _tarjeta(numero, etapa)
        if etapa.key == "discover":
            _robots_de_la_cola(config)


def _metricas_del_corpus(datos: CorpusMetrics) -> None:
    """Resume el corpus, sus secciones y los descartes con su motivo."""
    st.subheader("Métricas del corpus")
    st.caption(f"Sitio: {datos.site_url}")

    primera = st.columns(4)
    primera[0].metric("Páginas Gold", f"{datos.gold_pages:,}")
    primera[1].metric("Tokens Gold", f"{datos.gold_tokens:,}")
    primera[2].metric("Documentos PDF", f"{datos.pdf:,}")
    primera[3].metric("Vídeos transcritos", f"{datos.videos:,}")

    segunda = st.columns(4)
    segunda[0].metric("Tokens del corpus", f"{datos.total_tokens:,}")
    segunda[1].metric("Chunks web", f"{datos.chunks_web:,}")
    segunda[2].metric("Contexto (páginas)", f"{datos.context_pages:,}")
    segunda[3].metric("Contexto (tokens)", f"{datos.context_tokens:,}")
    if datos.checklist is not None:
        encontrados, total, porcentaje = datos.checklist
        st.caption(
            f"Checklist del Taller 1: {encontrados}/{total} ({porcentaje:.0f} %) - heurística."
        )

    if datos.sections:
        st.markdown("**Documentos por sección**")
        st.dataframe(
            [{"Sección": item.label, "Documentos": item.value} for item in datos.sections],
            hide_index=True,
        )

    if datos.drops:
        st.markdown("**Descartes del contexto con su motivo**")
        st.dataframe(
            [{"Motivo": drop.reason, "Páginas": drop.count} for drop in datos.drops],
            hide_index=True,
        )
        st.caption(
            "Sale de data/contexto/manifest.json: son descartes del contexto, no del descubrimiento."
        )
    for aviso in datos.warnings:
        st.warning(aviso)
    with st.expander("Fuentes de estas cifras"):
        st.code("\n".join(datos.sources) or "sin fuentes")


def _deduplicacion(resumen: PipelineSummary) -> None:
    """Muestra umbrales y bloques repetidos leídos de ``_REPETIDOS.md``."""
    reporte = resumen.repetitions
    if reporte is None:
        return
    st.subheader("Detalle de deduplicación")
    st.dataframe(
        [
            {
                "Umbral (páginas)": fila.threshold,
                "Líneas cubiertas": fila.covered,
                "Total": fila.total,
                "Porcentaje": f"{fila.percentage:.1f} %",
            }
            for fila in reporte.thresholds
        ],
        hide_index=True,
    )
    st.caption(
        f"Contenido único: {reporte.unique_global:.1f} % global y "
        f"{reporte.unique_average:.1f} % de promedio por página. "
        "La deduplicación de Gold solo mide: no borra contenido."
    )
    if reporte.blocks:
        with st.expander(f"Top {len(reporte.blocks)} de bloques repetidos"):
            st.dataframe(
                [
                    {
                        "Tamaño": bloque.size,
                        "Páginas": bloque.pages,
                        "Bloque": bloque.text,
                        "Ejemplos": bloque.examples,
                    }
                    for bloque in reporte.blocks
                ],
                hide_index=True,
            )


# ------------------------------------------------------------ captura en vivo


def _ejecutar_captura(config: Config, urls: list[str]) -> None:
    """Corre la captura en vivo mostrando cada etapa en un ``st.status``."""
    with st.status("Captura en vivo en una carpeta temporal", expanded=True) as estado:

        def al_terminar_etapa(etapa: LiveStage) -> None:
            """Escribe el resultado de la etapa y actualiza el estado."""
            st.write(f"[{_ICONOS.get(etapa.state, 'INFO')}] **{etapa.title}**: {etapa.detail}")
            estado.update(label=f"{etapa.title}: {etapa.detail}", state="running")

        try:
            resultado = run_capture(
                config,
                urls,
                workdir=new_workdir(),
                on_stage=al_terminar_etapa,
            )
        except Exception as exc:  # la app no debe caerse por un fallo de red
            estado.update(label="La captura no se pudo completar", state="error")
            st.error(f"La captura falló ({type(exc).__name__}). Revisa el detalle de las etapas.")
            return

        if resultado.error:
            estado.update(label="Captura detenida", state="error")
        else:
            estado.update(label="Captura completa", state="complete")

    st.session_state[_CLAVE_CAPTURA] = resultado


def _mostrar_captura(resultado: LiveCapture) -> None:
    """Enseña el resultado de la captura y el frontmatter de la página Gold."""
    if resultado.error:
        st.error(resultado.error)
    else:
        st.success(f"{len(resultado.corpus)} documentos Gold generados en una carpeta temporal.")
    if resultado.blocked:
        st.caption(f"Bloqueadas por robots.txt: {', '.join(resultado.blocked)}")
    if resultado.stages:
        st.dataframe(
            [
                {
                    "Etapa": etapa.title,
                    "Resultado": etapa.detail,
                    "Estado": _ICONOS.get(etapa.state, etapa.state),
                }
                for etapa in resultado.stages
            ],
            hide_index=True,
        )
    st.caption(f"Carpeta temporal de la corrida: {resultado.workdir}")
    if resultado.frontmatter_text:
        st.markdown("**Frontmatter de la página Gold generada**")
        st.code(resultado.frontmatter_text, language="yaml")
        if resultado.page_path is not None:
            st.caption(f"Archivo: {resultado.page_path}")
        with st.expander("Cuerpo Gold (primeras 40 líneas)"):
            st.code(resultado.body_excerpt, language="markdown")


def _captura_en_vivo(config: Config) -> None:
    """Sección con la selección de URLs y el botón de captura."""
    st.subheader("Captura en vivo")
    cola = queue_urls_file(config)
    if not cola:
        st.warning("No hay cola de URLs en data/raw/urls.jsonl: ejecuta make discover.")
        return

    st.caption(
        "Ejecuta capturar, extraer, deduplicar y Gold sobre las URLs elegidas en una "
        "carpeta temporal. Consulta robots.txt, usa la pausa de 1,5 s de net.py y no "
        "escribe nada en data/."
    )
    elegidas = st.multiselect(
        "URLs de la cola (máximo 3)",
        options=cola,
        default=select_urls(config, limit=DEFAULT_SAMPLE),
        max_selections=DEFAULT_SAMPLE,
        key="urls_captura_vivo",
    )
    if st.button(
        "Ejecutar captura en vivo",
        type="primary",
        disabled=not elegidas,
        key="boton_captura_vivo",
    ):
        _ejecutar_captura(config, elegidas)

    resultado = st.session_state.get(_CLAVE_CAPTURA)
    if isinstance(resultado, LiveCapture):
        _mostrar_captura(resultado)


def _auditoria(config: Config) -> None:
    """Auditoría completa del descubrimiento, opcional por su duración."""
    st.caption(
        "La auditoría completa del descubrimiento se ofrece aparte porque tarda "
        "minutos y no es parte del flujo de la pestaña."
    )
    with st.expander("Auditoría opcional: descubrimiento completo"):
        st.caption(_AUDIT_HINT)
        if st.button("Auditar descubrimiento", key="boton_auditoria"):
            with st.spinner("Leyendo robots.txt y sitemaps con la pausa de cortesía..."):
                try:
                    with HttpClient(config) as cliente:
                        auditoria = audit_discovery(config, cliente)
                except Exception as exc:  # la app no debe caerse por un fallo de red
                    st.error(f"La auditoría falló ({type(exc).__name__}).")
                else:
                    st.session_state[_CLAVE_AUDITORIA] = auditoria
        auditoria = st.session_state.get(_CLAVE_AUDITORIA)
        if isinstance(auditoria, DiscoveryAudit):
            _mostrar_auditoria(auditoria)


def _mostrar_auditoria(auditoria: DiscoveryAudit) -> None:
    """Resume sitemaps, robots y descartes de la auditoría completa."""
    columnas = st.columns(4)
    columnas[0].metric("Sitemaps leídos", f"{auditoria.sitemaps_read:,}")
    columnas[1].metric("URLs capturables", f"{auditoria.urls:,}")
    columnas[2].metric("Documentos", f"{auditoria.documents:,}")
    columnas[3].metric("Duración", f"{auditoria.seconds:.1f} s")
    if auditoria.sitemaps_failed:
        st.caption(f"Sitemaps fallidos: {auditoria.sitemaps_failed:,}.")
    st.caption(
        "robots.txt "
        + ("encontrado" if auditoria.robots_found else "no disponible")
        + (
            f"; Crawl-delay declarado: {auditoria.crawl_delay} s"
            if auditoria.crawl_delay
            else "; sin Crawl-delay declarado (la pausa de 1,5 s es del proyecto)"
        )
    )
    if auditoria.skipped:
        st.dataframe(
            [{"Motivo": motivo, "URLs": cuenta} for motivo, cuenta in auditoria.skipped],
            hide_index=True,
        )
    else:
        st.caption("Sin descartes en esta corrida.")


# ------------------------------------------------------------------- entrada


def render_tab_scraping() -> None:
    """Pinta la pestaña completa: etapas, métricas, deduplicación y captura."""
    config = load_config()
    st.subheader("Pipeline del corpus (Medallion)")
    columnas = st.columns([4, 1])
    columnas[0].caption(
        "Cada etapa lee su propio artefacto en disco; Refrescar vuelve a leerlos "
        "sin tocar el corpus."
    )
    if columnas[1].button("Refrescar cifras", key="boton_refrescar"):
        _resumen.clear()
        _metricas.clear()
    resumen = _resumen()
    datos = _metricas()
    _etapas(config, resumen)
    _metricas_del_corpus(datos)
    _deduplicacion(resumen)
    _captura_en_vivo(config)
    _auditoria(config)
    with st.expander("Fuentes de las etapas"):
        st.code("\n".join(resumen.sources) or "sin fuentes")
        st.caption(
            "Bronze y Silver no se versionan; Gold sí. Por eso sus conteos pueden "
            "diferir sin que haya un error."
        )
