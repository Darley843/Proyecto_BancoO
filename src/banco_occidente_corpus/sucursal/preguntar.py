"""Servicio de `POST /api/preguntar`: grafo perezoso, caché, gasto y modo demo.

El grafo y sus dependencias (recuperador, filas del Tablero, modelo, clasificador y
canal) se construyen la primera vez que se pregunta, nunca al importar `app.py`.
La caché se consulta antes de clasificar y solo para preguntas que no son de
seguimiento, de modo que un acierto no gasta una reformulación. El gasto se suma
cuando el modelo informó tokens, aunque la respuesta termine en la frase fija; en
ese caso el turno también cuenta como uso de modelo y no se guarda en la caché
para no tapar una mejora del índice. En modo demo no se crea el chat model, no se
escribe gasto y no se cachea nada.

Limitación conocida: el gasto cuenta solo los tokens de `redactar`. La reformulación
y la clasificación de dudas también llaman al modelo y el grafo todavía no expone su
uso; para contarlos, `DependenciasGrafo` debería recibir un `registrar_uso` que los
nodos invocaran con `extraer_metricas`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel

from ..asistente.contexto_prompt import CanalOficial, ContextoAusente, cargar_contexto
from ..asistente.metricas import leer_uso
from ..asistente.modelo import FaltaApiKey, crear_modelo_para
from ..asistente.validacion import es_sin_datos, sanear_pregunta
from ..boveda.recuperador import crear_recuperador
from ..boveda.tipos import Recuperador
from ..config import Config
from ..contexto import RutasContexto
from ..tablero.tipos import leer_filas, ruta_tablero
from .ajustes import ConfiguracionSucursal, tope_efectivo
from .costo import CacheRespuestas, GastoDiario, costo_de_uso, tarifas_para
from .digiturno import (
    ContadorTurnos,
    cargar_configuracion_digiturno,
    clasificador_deepseek,
    clasificar,
)
from .grafo import (
    DependenciasGrafo,
    crear_grafo,
    es_seguimiento,
    registrar_turno,
    responder_turno,
    tablero_responde_sin_modelo,
)

#: Logger del servicio; nunca recibe la pregunta, la respuesta ni el `thread_id`.
LOGGER = logging.getLogger(__name__)

#: Ruta del índice de la Bóveda dentro de `data/boveda/`.
RUTA_INDICE = "data/boveda/indice.json"
#: Ruta del `checkpointer` de la memoria conversacional.
RUTA_MEMORIA = "data/asistente/memoria.sqlite"
#: Ruta de la caché de respuestas.
RUTA_CACHE = "data/asistente/cache.sqlite"
#: Rutas que puede tomar un turno, en el orden en que se prueban en la caché.
RUTAS: tuple[str, ...] = ("boveda", "tablero", "rechazo")
#: Letra del turno a ruta descriptiva del contrato JSON.
RUTA_POR_LETRA: dict[str, str] = {"B": "boveda", "T": "tablero", "X": "rechazo"}
#: Campos del cuerpo que se guarda en la caché, sin los volátiles del turno.
CAMPOS_PAYLOAD: frozenset[str] = frozenset(
    {
        "turno",
        "ruta",
        "motivo",
        "uso_modelo",
        "reformulada",
        "respuesta",
        "fuentes",
        "tokens_entrada",
        "tokens_salida",
        "tokens_cache",
        "costo_usd",
    }
)
#: Caracteres del fragmento principal que se muestran en una respuesta demo.
LARGO_DEMO = 400
#: Mensaje único para una pregunta que queda vacía después de sanearla.
MENSAJE_PREGUNTA_VACIA = "La pregunta está vacía: escribe qué quieres consultar."


class ErrorSucursal(Exception):
    """Error con código estable para el cuerpo `{"error": {codigo, mensaje}}`."""

    def __init__(self, estado_http: int, codigo: str, mensaje: str) -> None:
        """Guarda el estado HTTP, el código y el mensaje que verá el frontend."""
        super().__init__(mensaje)
        self.estado_http = estado_http
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass(frozen=True, slots=True)
class PiezasGrafo:
    """Dependencias y grafo compilados que el servicio construye una sola vez."""

    dependencias: DependenciasGrafo
    grafo: Any


def leer_indice(config: Config) -> dict[str, Any] | None:
    """Lee `data/boveda/indice.json` si existe y es un objeto JSON.

    Args:
        config: configuración con la raíz del proyecto.

    Returns:
        El contenido del índice o None si falta o no se puede leer.
    """
    ruta = config.paths.root / RUTA_INDICE
    if not ruta.exists():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return datos if isinstance(datos, dict) else None


def indice_listo(config: Config) -> bool:
    """Indica si la Bóveda tiene índice y al menos un fragmento indexado."""
    datos = leer_indice(config)
    if datos is None:
        return False
    try:
        return int(datos.get("fragmentos", 0)) > 0
    except (TypeError, ValueError):
        return False


def ruta_de_letra(letra: str) -> str:
    """Convierte la letra del turno en la ruta descriptiva del contrato JSON."""
    return RUTA_POR_LETRA.get(letra, "boveda")


def requiere_modelo(
    pregunta: str,
    dependencias: DependenciasGrafo,
    *,
    con_historial: bool = False,
) -> bool:
    """Estima si un turno necesitará el modelo, sin gastar una llamada.

    Es una réplica deliberada de las reglas del grafo: solo hay reformulación con
    historial y pregunta de seguimiento (`es_seguimiento`), el digiturno se
    evalúa sin clasificador y el Tablero responde sin modelo cuando la plantilla
    puede cubrir las filas (1–3 o del mismo concepto, hasta 10). Si esas reglas
    cambian en `grafo.py` o en `digiturno.py`, esta función debe actualizarse con
    ellas; si no, el tope podría bloquear preguntas que el grafo responde gratis
    o dejar pasar preguntas que sí gastan.

    Args:
        pregunta: pregunta saneada del cliente.
        dependencias: piezas construidas del grafo.
        con_historial: True si el hilo ya tiene mensajes en el `checkpointer`.

    Returns:
        True si el turno puede llamar a DeepSeek; False si las reglas y el
        Tablero lo resuelven sin modelo.
    """
    if con_historial and es_seguimiento(pregunta):
        return True
    turno = clasificar(
        pregunta,
        configuracion=dependencias.configuracion_digiturno,
        permitidos=dependencias.permitidos,
        clasificador=None,
        contador=ContadorTurnos(),
    )
    if turno.letra == "X":
        return False
    if turno.letra == "T":
        return not tablero_responde_sin_modelo(dependencias.filas, pregunta)
    return True


def fuentes_de_boveda(
    fragmentos: Sequence[Mapping[str, Any]],
    citadas: Sequence[str] | None = (),
) -> list[dict[str, Any]]:
    """Arma las fuentes numeradas desde los fragmentos del estado.

    Args:
        fragmentos: fragmentos recuperados, en el orden en que los vio el modelo.
        citadas: URL citadas en la respuesta; se conserva su número original. Si
            es None se devuelven todos los fragmentos (respuesta de demostración).

    Returns:
        Una lista de objetos `{n, titulo, url, seccion, tipo, similitud}`.
    """
    permitidas = None if citadas is None else {url for url in citadas if url}
    fuentes: list[dict[str, Any]] = []
    for indice, fragmento in enumerate(fragmentos, start=1):
        url = str(fragmento.get("url", ""))
        if permitidas is not None and url not in permitidas:
            continue
        fuentes.append(
            {
                "n": indice,
                "titulo": str(fragmento.get("titulo", "")),
                "url": url,
                "seccion": str(fragmento.get("seccion", "")),
                "tipo": str(fragmento.get("tipo", "pagina")),
                "similitud": round(float(fragmento.get("puntaje", 0.0)), 4),
            }
        )
    return fuentes


def fuentes_de_tablero(filas: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Arma las fuentes del Tablero, una por URL única y sin similitud.

    Args:
        filas: filas del Tablero que sostienen la respuesta con plantilla.

    Returns:
        Una lista de objetos `{n, titulo, url, seccion, tipo, similitud}` con
        `similitud` en None porque la búsqueda de filas no tiene puntaje.
    """
    fuentes: list[dict[str, Any]] = []
    vistas: set[str] = set()
    for fila in filas:
        url = str(fila.get("fuente", ""))
        if not url or url in vistas:
            continue
        vistas.add(url)
        origen = str(fila.get("origen", ""))
        fuentes.append(
            {
                "n": len(fuentes) + 1,
                "titulo": str(fila.get("concepto", "")),
                "url": url,
                "seccion": "otros",
                "tipo": "pdf" if origen == "tarifario" else "pagina",
                "similitud": None,
            }
        )
    return fuentes


def construir_piezas(
    config: Config,
    ajustes: ConfiguracionSucursal,
    *,
    crear_modelo_chat: Callable[[], BaseChatModel] | None = None,
    crear_recuperador_boveda: Callable[[], Recuperador] | None = None,
    ruta_memoria: Path | None = None,
) -> PiezasGrafo:
    """Construye dependencias y grafo una sola vez, sin red si se inyectan dobles.

    El modelo se crea antes que el recuperador para que la falta de
    `DEEPSEEK_API_KEY` falle sin intentar hablar con Ollama ni con Chroma.

    Args:
        config: configuración con las rutas del corpus.
        ajustes: configuración de la Sucursal (tope, TTL y modo demo).
        crear_modelo_chat: fábrica alternativa del chat model; por defecto
            `crear_modelo_para("qa")`.
        crear_recuperador_boveda: fábrica alternativa del recuperador; por
            defecto el híbrido real sobre el índice `base`.
        ruta_memoria: archivo SQLite del `checkpointer`; por defecto el de la
            Ventanilla (`data/asistente/memoria.sqlite`). La evaluación v2 usa
            uno propio para no mezclar sus hilos con la conversación real.

    Returns:
        Las piezas listas para atender preguntas.

    Raises:
        FaltaApiKey: fuera de demo, si no hay `DEEPSEEK_API_KEY` en el entorno.
    """
    modelo: BaseChatModel | None = None
    clasificador = None
    if not ajustes.demo:
        fabrica_modelo = crear_modelo_chat or _crear_modelo_qa
        modelo = fabrica_modelo()
        clasificador = clasificador_deepseek(modelo)

    fabrica_recuperador = crear_recuperador_boveda or _fabrica_recuperador(config)
    dependencias = DependenciasGrafo(
        recuperador=fabrica_recuperador(),
        filas=leer_filas(ruta_tablero(config)),
        modelo=modelo,
        clasificador=clasificador,
        canal=_cargar_canal(config),
        configuracion_digiturno=cargar_configuracion_digiturno(),
        contador=ContadorTurnos(),
    )
    grafo = crear_grafo(dependencias, ruta_memoria or config.paths.root / RUTA_MEMORIA)
    return PiezasGrafo(dependencias=dependencias, grafo=grafo)


class ServicioPreguntas:
    """Atiende una pregunta con el grafo, la caché, el gasto y el modo demo."""

    def __init__(
        self,
        config: Config,
        ajustes: ConfiguracionSucursal,
        gasto: GastoDiario,
        *,
        cache: CacheRespuestas | None = None,
        piezas: Callable[[], PiezasGrafo] | None = None,
        usar_cache: bool = True,
    ) -> None:
        """Guarda las dependencias y deja la construcción para la primera pregunta.

        Args:
            config: configuración con las rutas del corpus.
            ajustes: configuración de la Sucursal.
            gasto: acumulado diario del gasto del modelo.
            cache: caché alternativa; por defecto la de `data/asistente/`.
            piezas: fábrica alternativa para las pruebas; por defecto
                `construir_piezas`.
            usar_cache: False desactiva la caché por completo (ni consulta ni
                guarda). La evaluación v2 lo usa para no reutilizar respuestas
                de una corrida anterior.
        """
        self._config = config
        self._ajustes = ajustes
        self._gasto = gasto
        self._cache = cache
        self._fabrica = piezas
        self._usar_cache = usar_cache
        self._construidas: PiezasGrafo | None = None
        self._candado = threading.Lock()

    def piezas(self) -> PiezasGrafo:
        """Devuelve las piezas, construyéndolas la primera vez que se piden."""
        if self._construidas is not None:
            return self._construidas
        with self._candado:
            if self._construidas is None:
                self._construidas = (
                    self._fabrica()
                    if self._fabrica is not None
                    else construir_piezas(self._config, self._ajustes)
                )
        return self._construidas

    def cache(self) -> CacheRespuestas:
        """Devuelve la caché, creándola la primera vez que se necesita."""
        if self._cache is None:
            self._cache = CacheRespuestas(
                self._config.paths.root / RUTA_CACHE,
                self._ajustes.cache_ttl_segundos,
            )
        return self._cache

    def preguntar(self, pregunta: str, thread_id: str) -> dict[str, Any]:
        """Responde una pregunta y devuelve el cuerpo JSON del contrato.

        Args:
            pregunta: texto del cliente.
            thread_id: identificador de la conversación que envía la Ventanilla.

        Returns:
            El diccionario con los catorce campos de `PreguntarRespuesta`.

        Raises:
            ErrorSucursal: con 422 si falta la pregunta o el hilo, 429 si el tope
                bloquea una ruta con modelo y 503 si falta el índice o la clave.
        """
        inicio = time.perf_counter()
        limpia = self._sanear(pregunta)
        hilo = thread_id.strip()
        if not hilo:
            raise ErrorSucursal(
                422,
                "thread_id_ausente",
                "Falta thread_id: la Ventanilla necesita identificar el hilo.",
            )
        if not indice_listo(self._config):
            raise ErrorSucursal(
                503,
                "indice_no_listo",
                "La Bóveda no tiene índice: ejecuta `make indice` y vuelve a intentarlo.",
            )

        piezas = self._piezas_o_error()
        version = piezas.dependencias.prompt.nombre

        if self._usar_cache and not self._ajustes.demo and not es_seguimiento(limpia):
            guardado = self._buscar_en_cache(limpia, version)
            if guardado is not None:
                return self._desde_cache(guardado, piezas, limpia, hilo, inicio)

        self._comprobar_tope(limpia, piezas, hilo)
        estado = responder_turno(piezas.grafo, piezas.dependencias, limpia, hilo)
        return self._mapear(estado, piezas, limpia, hilo, version, inicio)

    @staticmethod
    def _sanear(pregunta: str) -> str:
        """Sanea la pregunta y traduce el texto vacío a un 422 del contrato."""
        try:
            limpia = sanear_pregunta(pregunta)
        except ValueError as error:
            raise ErrorSucursal(422, "pregunta_vacia", MENSAJE_PREGUNTA_VACIA) from error
        if not limpia:
            raise ErrorSucursal(422, "pregunta_vacia", MENSAJE_PREGUNTA_VACIA)
        return limpia

    def _piezas_o_error(self) -> PiezasGrafo:
        """Construye las piezas y traduce la falta de clave a un 503."""
        try:
            return self.piezas()
        except FaltaApiKey as error:
            LOGGER.warning("evento=sin_clave codigo=%s", type(error).__name__)
            raise ErrorSucursal(
                503,
                "sin_clave",
                "Falta DEEPSEEK_API_KEY: define la clave o arranca con SUCURSAL_DEMO=1.",
            ) from error

    def _comprobar_tope(self, pregunta: str, piezas: PiezasGrafo, thread_id: str) -> None:
        """Devuelve 429 si el gasto del día ya alcanzó el tope y hace falta modelo."""
        if self._ajustes.demo:
            return
        con_historial = self._hilo_con_historial(piezas, thread_id)
        if not requiere_modelo(pregunta, piezas.dependencias, con_historial=con_historial):
            return
        tope = self._tope()
        if self._gasto.hoy()[0] < tope:
            return
        raise ErrorSucursal(
            429,
            "tope_alcanzado",
            "Se alcanzó el tope diario de gasto del modelo "
            f"({tope:.2f} USD). Las respuestas de la Bóveda volverán mañana "
            "o se puede ajustar SUCURSAL_TOPE_USD.",
        )

    def _hilo_con_historial(self, piezas: PiezasGrafo, thread_id: str) -> bool:
        """Indica si el hilo ya tiene mensajes guardados en el `checkpointer`."""
        try:
            estado = piezas.grafo.get_state({"configurable": {"thread_id": thread_id}})
        except Exception:
            return True
        valores = getattr(estado, "values", None) or {}
        mensajes = valores.get("messages") if isinstance(valores, Mapping) else None
        return bool(mensajes)

    def _tope(self) -> float:
        """Devuelve el tope efectivo del día, traduciendo una config inválida."""
        try:
            return tope_efectivo(self._ajustes)
        except ValueError as error:
            raise ErrorSucursal(500, "configuracion_invalida", str(error)) from error

    def _buscar_en_cache(self, pregunta: str, version: str) -> dict[str, Any] | None:
        """Busca la respuesta en las tres rutas posibles sin gastar una llamada."""
        cache = self.cache()
        for ruta in RUTAS:
            guardado = cache.obtener(CacheRespuestas.clave(pregunta, ruta, version))
            if guardado is not None and set(guardado) == CAMPOS_PAYLOAD:
                return guardado
        return None

    def _guardar_en_cache(self, clave: str, payload: Mapping[str, Any]) -> None:
        """Guarda el cuerpo de un turno con modelo; la caché no debe romper la respuesta."""
        try:
            self.cache().guardar(clave, payload)
        except OSError as error:
            LOGGER.warning("evento=cache_no_guardada codigo=%s", type(error).__name__)

    def _desde_cache(
        self,
        guardado: Mapping[str, Any],
        piezas: PiezasGrafo,
        pregunta: str,
        thread_id: str,
        inicio: float,
    ) -> dict[str, Any]:
        """Devuelve un acierto con ticket nuevo, costo cero y el turno en memoria."""
        datos = dict(guardado)
        datos["turno_numero"] = piezas.dependencias.contador.siguiente()
        datos["tiempo_s"] = round(time.perf_counter() - inicio, 3)
        datos["cache"] = True
        datos["tokens_entrada"] = 0
        datos["tokens_salida"] = 0
        datos["tokens_cache"] = 0
        datos["costo_usd"] = 0.0
        try:
            registrar_turno(piezas.grafo, pregunta, str(datos["respuesta"]), thread_id)
        except Exception as error:
            LOGGER.warning("evento=historial_no_actualizado codigo=%s", type(error).__name__)
        self._registrar_turno_log(datos, inicio)
        return datos

    def _mapear(
        self,
        estado: Mapping[str, Any],
        piezas: PiezasGrafo,
        pregunta: str,
        thread_id: str,
        version: str,
        inicio: float,
    ) -> dict[str, Any]:
        """Convierte el estado del grafo en el cuerpo JSON del contrato.

        El modelo puede gastar tokens y aun así terminar en la frase fija: si
        `leer_uso` informa tokens de entrada o de salida, el turno cuenta como
        uso de modelo, se cobra y no se guarda en la caché.
        """
        turno = estado.get("turno") or {}
        letra = str(turno.get("letra", "B"))
        ruta = ruta_de_letra(letra)
        uso = estado.get("uso") or {}
        detalle = leer_uso(uso)
        tokens_entrada = detalle.entrada or 0
        tokens_salida = detalle.salida or 0
        uso_modelo = bool(uso.get("uso_modelo", False)) or tokens_entrada > 0 or tokens_salida > 0
        reformulada = str(estado.get("reformulada") or "")
        fragmentos = list(estado.get("fragmentos") or [])
        respuesta = str(estado.get("respuesta", ""))

        if self._ajustes.demo and letra == "B" and fragmentos:
            principal = _fragmento_principal(fragmentos)
            respuesta = _respuesta_demo(principal)
            fuentes = fuentes_de_boveda([principal], None)
        elif letra == "X":
            fuentes = []
        elif letra == "T":
            fuentes = fuentes_de_tablero(list(estado.get("filas") or []))
        else:
            fuentes = fuentes_de_boveda(fragmentos, list(estado.get("fuentes") or []))

        payload: dict[str, Any] = {
            "turno": letra,
            "ruta": ruta,
            "motivo": str(turno.get("motivo", "")),
            "uso_modelo": uso_modelo,
            "reformulada": reformulada if reformulada != pregunta else None,
            "respuesta": respuesta,
            "fuentes": fuentes,
            "tokens_entrada": tokens_entrada,
            "tokens_salida": tokens_salida,
            "tokens_cache": detalle.cache or 0,
            "costo_usd": 0.0,
        }
        if uso_modelo and not self._ajustes.demo:
            costo, tokens = costo_de_uso(uso, tarifas_para(datetime.now(UTC)))
            payload["costo_usd"] = round(costo, 6)
            self._gasto.sumar(costo, tokens)
            if self._usar_cache and letra != "X" and not es_sin_datos(respuesta):
                clave = CacheRespuestas.clave(reformulada or pregunta, ruta, version)
                self._guardar_en_cache(clave, payload)

        salida = dict(payload)
        salida["turno_numero"] = int(turno.get("numero", 0))
        salida["tiempo_s"] = round(time.perf_counter() - inicio, 3)
        salida["cache"] = False
        self._registrar_turno_log(salida, inicio)
        return salida

    def _registrar_turno_log(self, datos: Mapping[str, Any], inicio: float) -> None:
        """Anota un turno sin la pregunta, la respuesta ni el hilo."""
        LOGGER.info(
            "evento=pregunta_atendida turno=%s ruta=%s uso_modelo=%s cache=%s ms=%d",
            datos.get("turno", ""),
            datos.get("ruta", ""),
            datos.get("uso_modelo", False),
            datos.get("cache", False),
            int((time.perf_counter() - inicio) * 1000),
        )


def _crear_modelo_qa() -> BaseChatModel:
    """Crea el chat model de DeepSeek con los parámetros de la tarea de Q&A."""
    return crear_modelo_para("qa")


def _fabrica_recuperador(config: Config) -> Callable[[], Recuperador]:
    """Devuelve la fábrica del recuperador híbrido real sobre el alcance base."""

    def construir() -> Recuperador:
        """Construye el recuperador con los embeddings y el índice configurados."""
        return crear_recuperador(config, "base")

    return construir


def _cargar_canal(config: Config) -> CanalOficial | None:
    """Carga el canal oficial del contexto, o None si la capa Contexto falta."""
    try:
        contexto = cargar_contexto(archivo=RutasContexto.desde(config).archivo)
    except (ContextoAusente, OSError):
        return None
    return contexto.canal


def _puntaje(fragmento: Mapping[str, Any]) -> float:
    """Lee la similitud del fragmento; un valor ausente o inválido cuenta como cero."""
    try:
        return float(fragmento.get("puntaje", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _fragmento_principal(fragmentos: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Devuelve el fragmento de mayor puntaje; ante empate conserva el primero.

    Args:
        fragmentos: fragmentos recuperados, en el orden en que los devolvió el
            recuperador (que no coincide necesariamente con el de similitud).

    Returns:
        El fragmento con el `puntaje` más alto; la lista no puede estar vacía.
    """
    return max(fragmentos, key=_puntaje)


def _respuesta_demo(fragmento: Mapping[str, Any]) -> str:
    """Arma una respuesta de demostración con el fragmento principal y su fuente.

    Args:
        fragmento: fragmento de mayor puntaje recuperado, con su texto y su URL.

    Returns:
        El extracto citado como `[1]`, la lista de fuentes y una nota de demo.
    """
    texto = " ".join(str(fragmento.get("texto", "")).split())
    extracto = texto[:LARGO_DEMO]
    if len(texto) > LARGO_DEMO:
        corte = extracto.rfind(". ")
        extracto = extracto[: corte + 1] if corte > LARGO_DEMO // 3 else extracto.rstrip() + "…"
    url = str(fragmento.get("url", ""))
    return (
        f"{extracto} [1]\n\nFuentes:\n- {url}\n\n"
        "(Modo demo: respuesta armada con el fragmento principal de la Bóveda, sin modelo.)"
    )
