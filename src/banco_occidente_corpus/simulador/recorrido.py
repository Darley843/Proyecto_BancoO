"""Recorrido de punta a punta del canal con las personas sintéticas (tarea 7.2).

Firma las conversaciones del simulador y las entrega al webhook real
(``canal.webhook``) dentro del mismo proceso, con el ``TestClient`` de FastAPI:
no abre puertos ni hace red. Cada mensaje recorre la misma cadena que en la
app (firma, extracción, despachador, consentimiento, entrevista, motor, comité
y tarjeta) y la respuesta la registra ``EnviadorFalso``: nada sale por WhatsApp.

A cada persona se le envía:

1. «hola» y el botón **Acepto** del aviso de la Ley 1581;
2. los turnos de su guion (``data/evaluacion/personas_sinteticas.json``);
3. «¿Y si lo pago en 60 meses?»;
4. «olvida mis datos»;
5. otra vez el primer mensaje, como haría Meta al reintentar.

Y se verifica que:

- cada turno recibe una sola respuesta y el reintento no produce otra;
- el diagnóstico llega con texto y tarjeta, y con el semáforo esperado;
- el rojo ofrece hablar con un asesor y los textos de inyección no sacan a la
  entrevista de su guion;
- la revocación borra la entrevista, el resultado y los casos;
- el número no aparece en ningún archivo de la base.

El grafo de preguntas se reemplaza por una ruta D fija: la clasificación real
del Digiturno se prueba aparte y aquí solo importa el canal. Sin
``DEEPSEEK_API_KEY`` el comité no se convoca y amarillo y rojo llegan con el
diagnóstico, igual que en la app. El App Secret y la sal son ficticios y solo
viven en este proceso; la base se crea en una carpeta temporal que se borra al
terminar.

Uso: ``make simular`` o ``uv run python -m banco_occidente_corpus.simulador``.
Las pruebas viven en ``test/test_simulador_recorrido.py``.
"""

from __future__ import annotations

import argparse
import gc
import logging
import os
import sqlite3
import tempfile
import unicodedata
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel

from banco_occidente_corpus.canal.cola import ColaMensajes
from banco_occidente_corpus.canal.configuracion import ConfiguracionCanal
from banco_occidente_corpus.canal.consentimiento import MaquinaConsentimiento
from banco_occidente_corpus.canal.contratos import MensajeEntrante
from banco_occidente_corpus.canal.despachador import Despachador, RespuestaGrafo
from banco_occidente_corpus.canal.entrevista import (
    TEXTO_NO_ENTENDI,
    TEXTO_SIN_TASA,
    EntrevistaCanal,
)
from banco_occidente_corpus.canal.envio import EnviadorFalso
from banco_occidente_corpus.canal.identidad import calcular_usuario_id
from banco_occidente_corpus.canal.webhook import crear_router_canal
from banco_occidente_corpus.config import PROJECT_ROOT
from banco_occidente_corpus.pana.tarjetas import TITULO_SEMAFORO
from banco_occidente_corpus.simulador.payloads import enviar_a_webhook
from banco_occidente_corpus.simulador.personas import (
    Persona,
    SemaforoEsperado,
    Turno,
    cargar_personas,
    conversacion,
)

#: Guiones de las personas sintéticas del proyecto.
RUTA_PERSONAS: Path = PROJECT_ROOT / "data" / "evaluacion" / "personas_sinteticas.json"

#: App Secret ficticio: solo firma dentro de este proceso.
SECRETO_SIMULADO = "secreto-del-simulador"

#: Sal ficticia para las huellas de los números simulados.
SAL_SIMULADA = "sal-del-simulador"

#: Ruta real del webhook del canal.
RUTA_WEBHOOK = "/webhooks/whatsapp"

#: Turnos del canal antes del guion: saludo y aceptación del aviso.
PREAMBULO: tuple[Turno, ...] = (
    Turno(tipo="texto", valor="hola"),
    Turno(tipo="boton", valor="consentimiento.acepto", titulo="Acepto"),
)

#: Turnos del canal después del guion: «¿Y si…?» y revocación.
CIERRE: tuple[Turno, ...] = (
    Turno(tipo="texto", valor="¿Y si lo pago en 60 meses?"),
    Turno(tipo="texto", valor="olvida mis datos"),
)

#: Texto fijo del grafo cuando la pregunta no es de diagnóstico.
TEXTO_GRAFO = "Respuesta del grafo de preguntas (simulada)."

#: Consultas de las tablas que la revocación debe dejar sin filas de la persona.
CONTEOS_REVOCADOS: dict[str, str] = {
    "entrevistas": "SELECT COUNT(*) FROM entrevistas WHERE usuario_id = ?",
    "resultados_diagnostico": "SELECT COUNT(*) FROM resultados_diagnostico WHERE usuario_id = ?",
    "casos": "SELECT COUNT(*) FROM casos WHERE usuario_id = ?",
}

#: Lo que se espera cuando la persona no tiene semáforo de crédito.
SIN_SEMAFORO = "ahorro"


@dataclass
class ColaInmediata(ColaMensajes):
    """Cola que atiende cada mensaje en el momento, sin hilo trabajador.

    En la app, el webhook responde 200 y un hilo procesa el turno después. Aquí
    el turno se procesa dentro de la misma petición para saber qué respuesta
    produjo cada mensaje; el registro, la deduplicación y el despachador son los
    mismos.
    """

    procesar: Callable[[MensajeEntrante], None] | None = None

    def encolar(self, mensaje: MensajeEntrante) -> bool:
        """Procesa el mensaje de inmediato.

        Args:
            mensaje: mensaje ya registrado y deduplicado por el despachador.

        Returns:
            ``True`` si se procesó; ``False`` si todavía no hay despachador.
        """
        if self.procesar is None:
            return False
        self.procesar(mensaje)
        return True


@dataclass
class ResultadoPersona:
    """Lo que produjo el recorrido de una persona y lo que falló."""

    persona: str
    esperado: str
    obtenido: str
    comite: bool
    escenario: str
    fallas: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Indica si la persona pasó todas las verificaciones."""
        return not self.fallas


def _normalizar(texto: str) -> str:
    """Pasa a minúsculas y quita las tildes para comparar intenciones."""
    descompuesto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def grafo_ruta_d(pregunta: str, _thread_id: str, _perfil: str) -> RespuestaGrafo:
    """Doble del grafo de preguntas: la ruta D para el diagnóstico.

    Args:
        pregunta: texto que llegó al grafo.
        _thread_id: hilo del usuario; no se usa.
        _perfil: huella del perfil; no se usa.

    Returns:
        El aviso ``diagnostico`` si la pregunta pide el diagnóstico o la
        capacidad de pago; en otro caso, un texto fijo sin ruta especial.
    """
    normalizada = _normalizar(pregunta)
    if "diagnostico" in normalizada or "alcanza" in normalizada:
        return RespuestaGrafo(texto=TEXTO_GRAFO, avisos=("diagnostico",))
    return RespuestaGrafo(texto=TEXTO_GRAFO)


@contextmanager
def _secreto_simulado() -> Generator[None]:
    """Fija el App Secret ficticio solo durante el recorrido y lo restaura."""
    anterior = os.environ.get("WHATSAPP_APP_SECRET")
    os.environ["WHATSAPP_APP_SECRET"] = SECRETO_SIMULADO
    try:
        yield
    finally:
        if anterior is None:
            os.environ.pop("WHATSAPP_APP_SECRET", None)
        else:
            os.environ["WHATSAPP_APP_SECRET"] = anterior


def _semaforo_en(texto: str) -> str:
    """Deduce el resultado que muestra el texto del diagnóstico.

    Args:
        texto: texto que acompañó a la tarjeta.

    Returns:
        ``verde``, ``amarillo`` o ``rojo`` según el título; ``ahorro`` si es la
        tarjeta de ahorro, ``sin_tasa`` si no hubo tasa y ``desconocido`` si no
        se reconoce.
    """
    for color, titulo in TITULO_SEMAFORO.items():
        if titulo in texto:
            return str(color)
    if texto == TEXTO_SIN_TASA:
        return SemaforoEsperado.SIN_TASA.value
    if "Cuenta de ahorros" in texto or "CDT" in texto:
        return SIN_SEMAFORO
    return "desconocido"


def _filas_de(ruta: Path, usuario_id: str) -> dict[str, int]:
    """Cuenta las filas de la persona en las tablas que borra la revocación."""
    conexion = sqlite3.connect(str(ruta))
    try:
        return {
            tabla: int(conexion.execute(consulta, (usuario_id,)).fetchone()[0])
            for tabla, consulta in CONTEOS_REVOCADOS.items()
        }
    finally:
        conexion.close()


def _numero_en_la_base(carpeta: Path, numero: str) -> bool:
    """Busca los bytes del número en todos los archivos de la base."""
    buscado = numero.encode("utf-8")
    return any(
        buscado in archivo.read_bytes() for archivo in carpeta.iterdir() if archivo.is_file()
    )


def _verificar(
    persona: Persona,
    tramos: Sequence[Sequence[tuple[str, str]]],
) -> ResultadoPersona:
    """Compara lo que recibió la persona con lo que espera su guion.

    Args:
        persona: persona sintética con su resultado esperado.
        tramos: lo que registró el enviador falso por cada turno, en orden.

    Returns:
        El resultado de la persona con las fallas encontradas.
    """
    fallas: list[str] = []
    for posicion, tramo in enumerate(tramos, start=1):
        textos = [valor for tipo, valor in tramo if tipo == "texto"]
        if len(textos) != 1:
            fallas.append(f"el turno {posicion} recibió {len(textos)} respuestas")

    inicio = len(PREAMBULO)
    diagnostico = tramos[inicio + len(persona.turnos) - 1]
    texto = next((valor for tipo, valor in diagnostico if tipo == "texto"), "")
    esperado_enum = persona.esperado.semaforo
    esperado = esperado_enum.value if esperado_enum is not None else SIN_SEMAFORO
    obtenido = _semaforo_en(texto)
    if obtenido != esperado:
        fallas.append(f"se esperaba «{esperado}» y llegó «{obtenido}»")
    if esperado_enum is not SemaforoEsperado.SIN_TASA and all(
        tipo != "imagen" for tipo, _ in diagnostico
    ):
        fallas.append("el diagnóstico llegó sin tarjeta")
    if persona.esperado.deriva_asesor and "asesor" not in texto.casefold():
        fallas.append("el rojo no ofreció hablar con un asesor")

    if persona.esperado.bloquea_inyeccion:
        for indice, turno in enumerate(persona.turnos[1:], start=1):
            if turno.tipo != "texto":
                continue
            respuesta = next(
                (valor for tipo, valor in tramos[inicio + indice] if tipo == "texto"), ""
            )
            if TEXTO_NO_ENTENDI not in respuesta:
                fallas.append(f"el texto del turno {inicio + indice + 1} salió del guion")

    escenario = tramos[inicio + len(persona.turnos)]
    return ResultadoPersona(
        persona=persona.id,
        esperado=esperado,
        obtenido=obtenido,
        comite="comité" in texto.casefold(),
        escenario="tarjeta" if any(tipo == "imagen" for tipo, _ in escenario) else "texto",
        fallas=fallas,
    )


def recorrer(
    personas: Sequence[Persona],
    carpeta: Path,
    *,
    modelo: BaseChatModel | None = None,
    hoy: datetime | None = None,
    raiz: Path | None = None,
) -> list[ResultadoPersona]:
    """Recorre el canal con cada persona y verifica lo que recibe.

    Args:
        personas: personas sintéticas a simular.
        carpeta: carpeta vacía donde se crea la base del canal.
        modelo: modelo del comité; ``None`` usa el de la app (DeepSeek si hay
            clave en la sesión).
        hoy: fecha de las tasas; ``None`` usa la de hoy.
        raiz: carpeta alternativa de la tabla Gold de tasas, para las pruebas.

    Returns:
        Un resultado por persona, en el mismo orden.
    """
    ruta = carpeta / "whatsapp.sqlite"
    huellas = {
        persona.id: calcular_usuario_id(persona.numero, SAL_SIMULADA) for persona in personas
    }
    enviadores: dict[str, EnviadorFalso] = {}

    def crear_enviador(usuario_id: str, _destino: str) -> EnviadorFalso:
        """Un enviador falso por persona, para separar lo que recibe cada una."""
        if usuario_id not in enviadores:
            enviadores[usuario_id] = EnviadorFalso(ruta)
        return enviadores[usuario_id]

    cola = ColaInmediata()
    despachador = Despachador(
        config=ConfiguracionCanal(huellas=tuple(huellas.values())),
        sal=SAL_SIMULADA,
        ruta_almacen=ruta,
        maquina=MaquinaConsentimiento(ruta),
        cola=cola,
        crear_enviador=crear_enviador,
        responder=grafo_ruta_d,
        entrevista=EntrevistaCanal(ruta, modelo=modelo, hoy=hoy, raiz=raiz),
    )
    cola.procesar = despachador.procesar
    aplicacion = FastAPI()
    aplicacion.include_router(crear_router_canal(despachador.recibir))

    resultados: list[ResultadoPersona] = []
    with _secreto_simulado(), TestClient(aplicacion) as cliente:
        for persona in personas:
            usuario_id = huellas[persona.id]
            enviador = crear_enviador(usuario_id, persona.numero)
            payloads = conversacion(persona, preambulo=PREAMBULO, cierre=CIERRE)
            tramos: list[list[tuple[str, str]]] = []
            rechazos = 0
            for payload in payloads:
                antes = len(enviador.registro)
                respuesta = enviar_a_webhook(cliente, payload, SECRETO_SIMULADO, ruta=RUTA_WEBHOOK)
                rechazos += int(respuesta.status_code != 200)
                tramos.append(list(enviador.registro[antes:]))

            antes = len(enviador.registro)
            enviar_a_webhook(cliente, payloads[0], SECRETO_SIMULADO, ruta=RUTA_WEBHOOK)
            repetidos = len(enviador.registro) - antes

            resultado = _verificar(persona, tramos)
            if rechazos:
                resultado.fallas.append(f"el webhook rechazó {rechazos} mensajes")
            if repetidos:
                resultado.fallas.append("el reintento de Meta produjo otra respuesta")
            restantes = {tabla: n for tabla, n in _filas_de(ruta, usuario_id).items() if n}
            if restantes:
                resultado.fallas.append(f"la revocación dejó filas en {sorted(restantes)}")
            if _numero_en_la_base(carpeta, persona.numero):
                resultado.fallas.append("el número quedó en la base")
            resultados.append(resultado)
    return resultados


def informe(resultados: Sequence[ResultadoPersona], *, con_clave: bool) -> str:
    """Escribe el resumen del recorrido para la consola.

    Args:
        resultados: resultados por persona.
        con_clave: si la sesión tiene ``DEEPSEEK_API_KEY`` (no se muestra).

    Returns:
        Tabla por persona, las fallas y una línea de cierre.
    """
    lineas = [
        f"Recorrido del canal con {len(resultados)} personas (enviador falso, sin WhatsApp real)",
        "Comité: "
        + (
            "con DEEPSEEK_API_KEY en la sesión, amarillo y rojo lo convocan."
            if con_clave
            else "sin DEEPSEEK_API_KEY, amarillo y rojo llegan con el diagnóstico."
        ),
        "",
        f"{'Persona':<22}{'Esperado':<11}{'Obtenido':<11}{'Comité':<8}{'¿Y si…?':<10}Resultado",
    ]
    for resultado in resultados:
        lineas.append(
            f"{resultado.persona:<22}{resultado.esperado:<11}{resultado.obtenido:<11}"
            f"{'sí' if resultado.comite else 'no':<8}{resultado.escenario:<10}"
            f"{'OK' if resultado.ok else 'FALLA'}"
        )
    fallidas = [resultado for resultado in resultados if not resultado.ok]
    for resultado in fallidas:
        lineas.append("")
        lineas.append(f"{resultado.persona}:")
        lineas.extend(f"  - {falla}" for falla in resultado.fallas)
    lineas.append("")
    aprobadas = len(resultados) - len(fallidas)
    lineas.append(
        f"Todo en orden: {aprobadas} de {len(resultados)} personas."
        if not fallidas
        else f"Con fallas: {aprobadas} de {len(resultados)} personas pasaron."
    )
    return "\n".join(lineas)


def main(argv: Sequence[str] | None = None) -> int:
    """Ejecuta el recorrido desde la consola.

    Args:
        argv: argumentos; por defecto los de la línea de comandos.

    Returns:
        0 si todas las personas pasan, 1 si alguna falla y 2 si los argumentos
        no son válidos.
    """
    lector = argparse.ArgumentParser(
        prog="python -m banco_occidente_corpus.simulador",
        description="Recorre el canal de WhatsApp con las personas sintéticas, sin red.",
    )
    lector.add_argument(
        "--solo",
        action="append",
        default=[],
        metavar="ID",
        help="Simula solo esta persona (se puede repetir).",
    )
    lector.add_argument(
        "--registro",
        action="store_true",
        help="Muestra los avisos internos del canal.",
    )
    argumentos = lector.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if argumentos.registro else logging.CRITICAL,
        format="%(levelname)s %(name)s: %(message)s",
    )

    personas = cargar_personas(RUTA_PERSONAS)
    if argumentos.solo:
        disponibles = {persona.id for persona in personas}
        desconocidas = sorted(set(argumentos.solo) - disponibles)
        if desconocidas:
            print(f"Personas desconocidas: {', '.join(desconocidas)}")
            print(f"Disponibles: {', '.join(sorted(disponibles))}")
            return 2
        personas = tuple(persona for persona in personas if persona.id in argumentos.solo)

    with tempfile.TemporaryDirectory(
        prefix="simulador-canal-", ignore_cleanup_errors=True
    ) as temporal:
        resultados = recorrer(personas, Path(temporal))
        gc.collect()

    print(informe(resultados, con_clave=bool(os.getenv("DEEPSEEK_API_KEY", "").strip())))
    return 0 if all(resultado.ok for resultado in resultados) else 1
