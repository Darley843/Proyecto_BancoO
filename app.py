"""Arranque de la Sucursal 1965: API y app web en un solo servidor local.

``uv run python app.py`` equivale a ``make app``: levanta uvicorn en
``http://127.0.0.1:8000`` y sirve los archivos de ``app/web/`` (OpenSpec
``sucursal-1965``, decisión 15). Escucha solo en ``127.0.0.1``: nunca abre un
host público.

La API (``/api/...``) se registra en :func:`crear_app` **antes** de montar los
estáticos, porque el montaje en ``/`` atiende todo lo que no haya reclamado una
ruta anterior. Expone estado, Tablero, Bóveda, pipeline, Arqueo, Vestíbulo,
las voces de la escena, ``POST /api/preguntar`` y ``GET /health``: el grafo y sus dependencias se
construyen en la primera pregunta, nunca al importar este módulo.

La app web vive en ``app/web/`` y consume la API; la lógica del asistente está en
``asistente/`` y el grafo de la sucursal en ``sucursal/``.
"""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from banco_occidente_corpus.arqueo.latencia import con_latencia, ruta_por_defecto
from banco_occidente_corpus.asistente.contexto_prompt import cargar_contexto
from banco_occidente_corpus.boveda.mapa import ServicioMapa
from banco_occidente_corpus.canal.almacen import (
    hay_mensaje_desde,
    marcar_procesando_como_error,
)
from banco_occidente_corpus.canal.cola import ColaMensajes
from banco_occidente_corpus.canal.configuracion import cargar_configuracion_canal
from banco_occidente_corpus.canal.consentimiento import MaquinaConsentimiento
from banco_occidente_corpus.canal.despachador import Despachador, RespuestaGrafo
from banco_occidente_corpus.canal.entrevista import EntrevistaCanal
from banco_occidente_corpus.canal.envio import (
    Enviador,
    EnviadorFalso,
    EnviadorMeta,
    ErrorEnvio,
)
from banco_occidente_corpus.canal.escena_vivo import EscenaVivo
from banco_occidente_corpus.canal.openclaw import ClienteOpenClaw, cliente_desde_entorno
from banco_occidente_corpus.canal.webhook import crear_router_canal
from banco_occidente_corpus.config import Config, load_config
from banco_occidente_corpus.escena.api import crear_router_escena
from banco_occidente_corpus.escena.api_en_vivo import crear_router_en_vivo
from banco_occidente_corpus.escena.recursos import crear_router_recursos
from banco_occidente_corpus.herramientas.api import crear_router_herramientas
from banco_occidente_corpus.sucursal.ajustes import (
    ConfiguracionSucursal,
    cargar_configuracion_sucursal,
)
from banco_occidente_corpus.sucursal.api import (
    SaludRespuesta,
    crear_router,
    salud_operativa,
)
from banco_occidente_corpus.sucursal.costo import CacheRespuestas, GastoDiario
from banco_occidente_corpus.sucursal.grafo import responder_turno
from banco_occidente_corpus.sucursal.perfil import borrar_perfil_en
from banco_occidente_corpus.sucursal.preguntar import (
    RUTA_PERFIL,
    PiezasGrafo,
    construir_piezas,
)
from banco_occidente_corpus.sucursal.transmision import cerrar_transmisiones
from banco_occidente_corpus.voz.api import crear_router_voz
from banco_occidente_corpus.voz.sintesis import (
    VozEscena,
    cargar_configuracion_voz,
    crear_voz,
    modelos_disponibles,
)

HOST = "127.0.0.1"
PUERTO = 8000
#: Segundos que uvicorn espera a las conexiones abiertas al recibir Ctrl + C.
ESPERA_APAGADO_SEGUNDOS = 5
RAIZ = Path(__file__).resolve().parent
CARPETA_WEB = RAIZ / "app" / "web"
#: Rutas que siguen públicas cuando la petición llega por el túnel de Cloudflare.
RUTAS_PUBLICAS = frozenset({"/webhooks/whatsapp", "/health"})
#: Hosts que identifican una petición local, incluido el de ``TestClient``.
HOSTS_LOCALES = frozenset({"127.0.0.1", "localhost", "::1", "testserver"})
#: Cabeceras que añade Cloudflare a toda petición que entra por el túnel.
CABECERAS_DE_TUNEL = ("cf-ray", "cf-connecting-ip", "x-forwarded-for")


def _host_local(cabecera: str) -> bool:
    """Indica si la cabecera ``Host`` nombra este equipo.

    Args:
        cabecera: valor de ``Host``, con o sin puerto.

    Returns:
        ``True`` para ``127.0.0.1``, ``localhost``, ``::1`` y ``testserver``.
    """
    valor = cabecera.strip().lower()
    if valor.startswith("["):
        nombre = valor.split("]", 1)[0][1:]
    elif valor.count(":") == 1:
        nombre = valor.split(":", 1)[0]
    else:
        nombre = valor
    return nombre in HOSTS_LOCALES


@asynccontextmanager
async def _ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
    """Suelta las transmisiones abiertas cuando la app se apaga.

    uvicorn espera a las conexiones abiertas antes de llegar aquí, así que el
    corte de un stream vivo lo acota ``timeout_graceful_shutdown``; este cierre
    cubre el apagado en proceso (pruebas, uso embebido) y no deja colas con
    consumidores pendientes.

    Args:
        _: la app que arranca o se apaga; no se usa.

    Yields:
        El control durante toda la vida del servidor.
    """
    yield
    cerrar_transmisiones()


def _telefonos_publicos() -> tuple[str, ...]:
    """Teléfonos del canal oficial, para que el detector de PII no los marque.

    Returns:
        Los teléfonos públicos del bloque de atención al cliente, o ``()`` si
        el contexto todavía no se generó (``make contexto``).
    """
    try:
        contexto = cargar_contexto()
    except Exception:
        return ()
    if contexto.canal is None:
        return ()
    return contexto.canal.telefonos


def crear_app(
    carpeta_web: Path = CARPETA_WEB,
    *,
    config: Config | None = None,
    ajustes: ConfiguracionSucursal | None = None,
    cache: CacheRespuestas | None = None,
    piezas: Callable[[], PiezasGrafo] | None = None,
    mapa_boveda: ServicioMapa | None = None,
    voz: VozEscena | None = None,
) -> FastAPI:
    """Crea la app FastAPI de la sucursal y monta la app web en ``/``.

    ``carpeta_web`` se puede cambiar en las pruebas para servir otra carpeta;
    ``config``, ``ajustes``, ``cache``, ``piezas``, ``mapa_boveda`` y ``voz``
    permiten inyectar rutas, topes, un grafo simulado, un mapa y unas voces sin
    tocar la red ni los modelos de Piper.
    """
    configuracion = config or load_config()
    parametros = ajustes or cargar_configuracion_sucursal()
    gasto = GastoDiario(configuracion.paths.root / "data/asistente/gasto.sqlite")

    canal = cargar_configuracion_canal()
    sal = os.getenv("WHATSAPP_ID_SALT", "").strip()
    ruta_canal = configuracion.paths.root / "data/asistente/whatsapp.sqlite"
    ruta_latencias = ruta_por_defecto(configuracion.paths.root)
    config_voz = cargar_configuracion_voz()
    if voz is not None:
        voces, voces_disponibles = voz, None
    else:
        voces = crear_voz(config_voz, configuracion.paths.root)
        voces_disponibles = modelos_disponibles(config_voz, configuracion.paths.root)
    cola = ColaMensajes()
    despachador: Despachador | None = None
    motor_openclaw: ClienteOpenClaw | None = None

    if sal:
        motor_openclaw = cliente_desde_entorno(
            user_agent=configuracion.site.user_agent,
            remitente=configuracion.site.contact,
        )
        maquina = MaquinaConsentimiento(
            ruta_canal,
            version=canal.version_aviso,
            retencion_dias=canal.retencion_dias,
            borrar_perfil=partial(borrar_perfil_en, configuracion.paths.root / RUTA_PERFIL),
        )
        entrevista = EntrevistaCanal(
            ruta_canal,
            ttl_minutos=canal.entrevista_ttl_minutos,
            ruta_latencias=ruta_latencias,
        )
        # El aviso promete plazos de conservación: se cumplen al arrancar.
        maquina.purgar_casos_vencidos()
        entrevista.purgar_vencidos()

        def puede_responder(usuario_id: str) -> bool:
            """Autoriza la respuesta del evento dentro de la ventana de Meta.

            Args:
                usuario_id: huella HMAC del destinatario.

            Returns:
                ``True`` solo si el modo evento sigue vigente y esa huella
                escribió dentro de la ventana de servicio.
            """
            if not canal.evento.vigente():
                return False
            limite = canal.evento.limite_respuesta()
            return hay_mensaje_desde(ruta_canal, usuario_id, limite)

        def fabrica_enviador(usuario_id: str, destino: str) -> Enviador:
            """Devuelve el enviador falso o el cliente real de Meta."""
            if canal.modo != "real":
                return EnviadorFalso(ruta_canal)
            token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
            phone = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
            if not token or not phone:
                raise ErrorEnvio("faltan credenciales de Meta para el modo real")
            return EnviadorMeta(
                usuario_id=usuario_id,
                destino=destino,
                phone_number_id=phone,
                token=token,
                user_agent=configuracion.site.user_agent,
                remitente=configuracion.site.contact,
                huellas=canal.huellas,
                version_api=canal.version_api,
                puede_responder=puede_responder,
            )

        piezas_canal: list[PiezasGrafo] = []
        candado = threading.Lock()

        def obtener_piezas() -> PiezasGrafo:
            """Construye el grafo la primera vez que llega un mensaje."""
            if piezas is not None:
                return piezas()
            with candado:
                if not piezas_canal:
                    piezas_canal.append(construir_piezas(configuracion, parametros))
                return piezas_canal[0]

        def responder(pregunta: str, thread_id: str, perfil: str) -> RespuestaGrafo:
            """Entrega una pregunta al grafo y devuelve su respuesta y su ruta."""
            actuales = obtener_piezas()
            estado = responder_turno(
                actuales.grafo,
                actuales.dependencias,
                pregunta,
                thread_id,
                perfil,
            )
            return RespuestaGrafo(
                texto=str(estado.get("respuesta") or ""),
                avisos=tuple(str(aviso) for aviso in estado.get("avisos") or ()),
            )

        despachador = Despachador(
            config=canal,
            sal=sal,
            ruta_almacen=ruta_canal,
            maquina=maquina,
            cola=cola,
            crear_enviador=fabrica_enviador,
            responder=responder,
            motor=motor_openclaw.responder if motor_openclaw is not None else None,
            entrevista=entrevista,
            escena=EscenaVivo(
                ttl_minutos=canal.escena_ttl_minutos,
                permitidos=_telefonos_publicos(),
            ),
        )

    @asynccontextmanager
    async def ciclo(_: FastAPI) -> AsyncIterator[None]:
        """Arranca y detiene el trabajador del canal con la app."""
        if despachador is not None:
            marcar_procesando_como_error(ruta_canal)
            cola.iniciar(con_latencia("webhook", despachador.procesar, ruta=ruta_latencias))
        try:
            yield
        finally:
            if despachador is not None:
                cola.detener()
            if motor_openclaw is not None:
                motor_openclaw.cerrar()
            cerrar_transmisiones()

    app = FastAPI(
        title="Sucursal 1965",
        description="Asistente de conocimiento sobre Banco de Occidente (proyecto TAAML, UAO).",
        lifespan=ciclo,
    )
    app.include_router(
        crear_router(
            configuracion,
            parametros,
            gasto,
            cache=cache,
            piezas=piezas,
            mapa_boveda=mapa_boveda,
        )
    )
    app.include_router(
        crear_router_voz(voces, voces_disponibles, None if voz else config_voz.personajes)
    )
    app.include_router(crear_router_canal(despachador.recibir if despachador is not None else None))
    app.include_router(crear_router_escena(canal=despachador))
    app.include_router(crear_router_en_vivo())
    app.include_router(crear_router_recursos())
    app.include_router(crear_router_herramientas())

    @app.get("/health", response_model=SaludRespuesta, tags=["salud"])
    def salud(response: Response) -> SaludRespuesta:
        """Responde el chequeo de salud en la raíz, como esperan los monitores.

        Va en ``/`` y no en ``/api`` a propósito: es la ruta que prueban los
        monitores y la que se consulta al arrancar. Devuelve 200 cuando hay
        índice o se está en demo, y 503 cuando la Sucursal no puede responder.

        Args:
            response: respuesta de FastAPI, para fijar el estado HTTP.

        Returns:
            El estado operativo mínimo, sin red, sin claves ni datos de clientes.
        """
        estado = salud_operativa(configuracion, parametros)
        response.status_code = 200 if estado.estado == "ok" else 503
        return estado

    @app.middleware("http")
    async def solo_webhook_por_tunel(
        request: Request,
        siguiente: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Acota la superficie pública cuando la petición llega por el túnel.

        El túnel rápido de Cloudflare publica todo el origen y la API no tiene
        autenticación. Por eso, si la petición no es local, solo pasan el
        webhook —que ya valida token y firma— y ``/health``; el resto responde
        ``404`` para no confirmar qué rutas existen. Se considera local una
        petición con ``Host`` de loopback y sin cabeceras de Cloudflare, que el
        túnel no puede quitar.

        Args:
            request: petición entrante.
            siguiente: siguiente paso de la cadena de FastAPI.

        Returns:
            La respuesta de la ruta o un ``404`` para las rutas no públicas.
        """
        if request.url.path in RUTAS_PUBLICAS:
            return await siguiente(request)
        por_tunel = any(cabecera in request.headers for cabecera in CABECERAS_DE_TUNEL)
        if not por_tunel and _host_local(request.headers.get("host", "")):
            return await siguiente(request)
        return JSONResponse({"detail": "ruta no pública"}, status_code=404)

    app.mount("/", StaticFiles(directory=carpeta_web, html=True), name="web")
    return app


app = crear_app()


def main() -> None:
    """Levanta uvicorn en ``127.0.0.1:8000`` con la app de la sucursal.

    Fija ``timeout_graceful_shutdown`` para que Ctrl + C cierre aunque quede una
    ventana con el streaming SSE abierto: las transmisiones se cortan en el
    apagado y, si alguna no responde, uvicorn sale igual tras la espera.
    """
    print(f"Sucursal 1965 abierta en http://{HOST}:{PUERTO}  (Ctrl + C para cerrar)")
    uvicorn.run(
        app,
        host=HOST,
        port=PUERTO,
        timeout_graceful_shutdown=ESPERA_APAGADO_SEGUNDOS,
    )


if __name__ == "__main__":
    main()
