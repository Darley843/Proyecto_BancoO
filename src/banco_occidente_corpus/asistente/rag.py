"""RAG del asistente: fragmentos citados, validación de citas y adaptador.

El prompt v2 recibe los fragmentos recuperados entre ``<fragmentos>`` y
``</fragmentos>``, numerados ``[n]``. La respuesta cita cada dato con su número
y cierra con una lista ``Fuentes:`` con las URL exactas de los fragmentos
citados. Este módulo arma ese bloque, valida las citas y reutiliza las
comprobaciones atómicas de :mod:`banco_occidente_corpus.asistente.validacion`
para la frase fija, las cifras, la fuga del prompt, la PII y el tope de
palabras. No hace peticiones de red ni escribe en el corpus.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from ..boveda.tipos import Fragmento
from .contexto_prompt import CanalOficial
from .metricas import extraer_metricas
from .prompts import Prompt
from .validacion import (
    FRASE_SIN_DATOS,
    LIMITE_QA,
    cifras_duras,
    cifras_inventadas,
    detectar_fuga_prompt,
    detectar_pii,
    es_sin_datos,
    extraer_urls_texto,
    limitar_resumen,
    limpiar_respuesta,
    mensaje_pii,
    respuesta_sin_datos,
    sanear_pregunta,
    separar_fuentes,
    texto_de_contenido,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

_ETIQUETA_FRAGMENTOS = re.compile(r"<\s*(?P<cierre>/?)\s*fragmentos\s*>", re.IGNORECASE)
_CITA = re.compile(r"\[(\d+)\]")

#: Avisos que obligan a reemplazar la respuesta por la frase fija.
_BLOQUEANTES = ("sin_citas", "cita_inexistente", "fuente_inventada")


@dataclass(frozen=True, slots=True)
class RespuestaCitas:
    """Respuesta de v2 validada, con las fuentes usadas y sus avisos."""

    texto: str
    fuentes: tuple[str, ...] = ()
    sin_datos: bool = False
    avisos: tuple[str, ...] = ()
    metricas: dict[str, Any] = field(default_factory=dict)
    texto_crudo: str | None = None


@dataclass(frozen=True, slots=True)
class _AnalisisCitas:
    """Resultado interno de revisar citas, bloque Fuentes: y URL."""

    citas: tuple[int, ...]
    usadas: tuple[str, ...]
    urls_fuentes: tuple[str, ...]
    avisos: tuple[str, ...]


def _neutralizar(texto: str) -> str:
    """Convierte las etiquetas de fragmentos en texto que no cierra el bloque."""
    return _ETIQUETA_FRAGMENTOS.sub(lambda match: f"‹{match.group('cierre')}fragmentos›", texto)


def formatear_fragmentos(fragmentos: Sequence[Fragmento]) -> str:
    """Arma el bloque ``<fragmentos>`` numerado que recibe el prompt v2.

    Cada fragmento conserva su título, su sección y su línea ``Fuente:`` para
    que el número ``[n]`` sea rastreable. El texto se neutraliza para que un
    fragmento no pueda cerrar el bloque y colar instrucciones fuera de él.
    """
    bloques = [
        "\n".join(
            (
                f"[{indice}] {_neutralizar(fragmento.titulo)}",
                f"Sección: {_neutralizar(fragmento.seccion)}",
                f"Fuente: {fragmento.url}",
                "",
                _neutralizar(fragmento.texto),
            )
        )
        for indice, fragmento in enumerate(fragmentos, start=1)
    ]
    cuerpo = "\n\n".join(bloques)
    if not cuerpo:
        return "<fragmentos>\n</fragmentos>"
    return f"<fragmentos>\n{cuerpo}\n</fragmentos>"


def _analizar_citas(texto: str, fragmentos: Sequence[Fragmento]) -> _AnalisisCitas:
    """Revisa citas, bloque ``Fuentes:`` y correspondencia exacta de URL."""
    cuerpo, bloque = separar_fuentes(texto)
    citas = tuple(dict.fromkeys(int(numero) for numero in _CITA.findall(cuerpo)))
    usadas = tuple(
        dict.fromkeys(
            fragmentos[numero - 1].url for numero in citas if 1 <= numero <= len(fragmentos)
        )
    )
    urls_fuentes = extraer_urls_texto(bloque)

    avisos: list[str] = []
    if not citas:
        avisos.append("sin_citas")
    avisos.extend(
        f"cita_inexistente: [{numero}]" for numero in citas if not 1 <= numero <= len(fragmentos)
    )
    if not urls_fuentes:
        avisos.append("sin_fuentes")
    else:
        disponibles = {fragmento.url for fragmento in fragmentos}
        for url in urls_fuentes:
            if url not in disponibles:
                avisos.append(f"fuente_inventada: {url}")
            elif url not in usadas:
                avisos.append(f"fuente_no_citada: {url}")

    return _AnalisisCitas(
        citas=citas,
        usadas=usadas,
        urls_fuentes=urls_fuentes,
        avisos=tuple(avisos),
    )


def avisos_citas(texto: str, fragmentos: Sequence[Fragmento]) -> list[str]:
    """Lista los avisos de citas y fuentes sin decidir el fallback.

    Códigos: ``sin_citas``, ``cita_inexistente: [n]``, ``sin_fuentes``,
    ``fuente_inventada: <url>`` y ``fuente_no_citada: <url>``. Un rechazo con
    la frase fija no exige citas y devuelve una lista vacía.
    """
    if es_sin_datos(texto):
        return []
    return list(_analizar_citas(texto, fragmentos).avisos)


def validar_citas(
    texto: str,
    fragmentos: Sequence[Fragmento],
    *,
    canal: CanalOficial | None = None,
) -> RespuestaCitas:
    """Valida las citas de v2 y devuelve el texto corregido o el fallback.

    ``sin_citas``, ``cita_inexistente`` y ``fuente_inventada`` bloquean y
    devuelven la frase fija con el canal oficial. ``sin_fuentes`` no bloquea:
    se arma la lista con las URL de los fragmentos citados. ``fuente_no_citada``
    tampoco bloquea: se quita esa URL de la lista. Las URL se comparan
    exactamente, sin ignorar la barra final.
    """
    if es_sin_datos(texto):
        return RespuestaCitas(texto=texto, sin_datos=True)

    analisis = _analizar_citas(texto, fragmentos)
    if any(aviso.startswith(_BLOQUEANTES) for aviso in analisis.avisos):
        return RespuestaCitas(
            texto=respuesta_sin_datos(canal),
            fuentes=(canal.url,) if canal and canal.url else (),
            sin_datos=True,
            avisos=analisis.avisos,
        )

    fuentes = analisis.usadas
    avisos = list(analisis.avisos)
    if "sin_fuentes" in avisos or any(aviso.startswith("fuente_no_citada") for aviso in avisos):
        cuerpo, _ = separar_fuentes(texto)
        lineas = "\n".join(f"- {url}" for url in fuentes)
        texto = f"{cuerpo}\n\nFuentes:\n{lineas}"

    return RespuestaCitas(
        texto=texto,
        fuentes=fuentes,
        sin_datos=False,
        avisos=tuple(avisos),
    )


def _cuerpo_sin_citas(texto: str) -> str:
    """Cuerpo de la respuesta sin marcadores ``[n]`` ni bloque ``Fuentes:``."""
    cuerpo, _ = separar_fuentes(texto)
    return _CITA.sub(" ", cuerpo)


@dataclass(frozen=True, slots=True)
class ContextoRag:
    """Adapta los fragmentos de la Bóveda a las comprobaciones atómicas de v1."""

    fragmentos: tuple[Fragmento, ...]
    canal: CanalOficial | None = None

    @property
    def texto(self) -> str:
        """Texto agregado de los fragmentos; define las cifras permitidas."""
        return "\n\n".join(fragmento.texto for fragmento in self.fragmentos)

    @property
    def urls(self) -> frozenset[str]:
        """URLs exactas de los fragmentos recuperados."""
        return frozenset(fragmento.url for fragmento in self.fragmentos)

    @property
    def permitidos(self) -> tuple[str, ...]:
        """Teléfonos públicos del canal oficial, exentos del filtro de PII."""
        return self.canal.telefonos if self.canal else ()

    def mensajes(self, prompt: Prompt, pregunta: str) -> list[BaseMessage]:
        """Arma sistema (fragmentos + reglas) y humano (recordatorio + pregunta)."""
        sistema = f"{formatear_fragmentos(self.fragmentos)}\n\n{prompt.sistema}"
        partes = [f"<pregunta>\n{pregunta}\n</pregunta>"]
        if prompt.recordatorio:
            partes.insert(0, f"<reglas_clave>\n{prompt.recordatorio}\n</reglas_clave>")
        return [SystemMessage(content=sistema), HumanMessage(content="\n\n".join(partes))]

    def _fallback(
        self,
        avisos: Sequence[str],
        metricas: dict[str, Any] | None = None,
        crudo: str | None = None,
    ) -> RespuestaCitas:
        """Respuesta segura con la frase fija y el canal oficial."""
        return RespuestaCitas(
            texto=respuesta_sin_datos(self.canal),
            fuentes=(self.canal.url,) if self.canal and self.canal.url else (),
            sin_datos=True,
            avisos=tuple(avisos),
            metricas=metricas or {},
            texto_crudo=crudo,
        )

    def validar(
        self,
        crudo: str,
        metricas: dict[str, Any] | None = None,
    ) -> RespuestaCitas:
        """Valida citas, cifras, fuga, PII y tope sobre la salida del modelo."""
        metricas = metricas or {}
        texto = limpiar_respuesta(crudo)
        if not texto or es_sin_datos(texto):
            return self._fallback(("sin_datos",), metricas, crudo)

        texto, recortado = limitar_resumen(texto, LIMITE_QA)
        resultado = validar_citas(texto, self.fragmentos, canal=self.canal)
        if resultado.sin_datos:
            return self._fallback(resultado.avisos, metricas, crudo)

        texto = resultado.texto
        if cifras_inventadas(
            _cuerpo_sin_citas(texto),
            cifras_contexto=cifras_duras(self.texto),
        ):
            return self._fallback(("cifra_inventada",), metricas, crudo)
        if detectar_fuga_prompt(texto):
            return self._fallback(("fuga_prompt",), metricas, crudo)
        if detectar_pii(texto, permitidos=self.permitidos):
            return self._fallback(("pii_en_respuesta",), metricas, crudo)

        avisos = list(resultado.avisos)
        if recortado:
            avisos.append("recortado")
        if FRASE_SIN_DATOS.casefold() in texto.casefold():
            avisos.append("parcial")

        return RespuestaCitas(
            texto=texto,
            fuentes=resultado.fuentes,
            sin_datos=False,
            avisos=tuple(avisos),
            metricas=metricas,
            texto_crudo=crudo,
        )

    def responder(
        self,
        modelo: BaseChatModel,
        prompt: Prompt,
        pregunta: str,
    ) -> RespuestaCitas:
        """Responde con los fragmentos y valida la salida antes de devolverla."""
        if not self.fragmentos:
            return self._fallback(("sin_fragmentos",))

        pregunta_limpia = sanear_pregunta(pregunta)
        deteccion = detectar_pii(pregunta_limpia, permitidos=self.permitidos)
        if deteccion:
            return RespuestaCitas(
                texto=mensaje_pii(deteccion.categoria, self.canal),
                fuentes=(self.canal.url,) if self.canal and self.canal.url else (),
                sin_datos=False,
                avisos=("pii_bloqueada",),
            )

        respuesta = modelo.invoke(self.mensajes(prompt, pregunta_limpia))
        return self.validar(
            texto_de_contenido(respuesta.content),
            extraer_metricas(respuesta),
        )
