"""Herramientas de estado y de persona del agente `pana` (12–16).

Las escrituras van solo a `data/asistente/` —canal, perfil y casos— y siempre
bajo la huella HMAC del número. `olvidar_mis_datos` y `solicitar_asesor` usan
dos pasos: primero devuelven un token y después, solo con confirmación explícita,
ejecutan el borrado o abren el caso.
"""

from __future__ import annotations

import base64
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ..canal.almacen import RUTA_ALMACEN, abrir_caso, listar_casos
from ..canal.consentimiento import ESTADO_ACEPTADO, MaquinaConsentimiento
from ..pana.desde_diagnostico import tarjeta_y_texto
from ..sucursal.perfil import borrar_perfil_en
from .comun import como_json, diagnostico_de, error, ok
from .esquemas import (
    ConsultarCasoEntrada,
    GenerarTarjetaPanaEntrada,
    OlvidarMisDatosEntrada,
    RegistrarConsentimientoEntrada,
    SalidaHerramienta,
    SolicitarAsesorEntrada,
)

#: Ruta del store de perfil de la Sucursal; se puede mover con una variable.
RUTA_PERFIL: Path = Path("data/asistente/perfil.sqlite")
#: Variable de entorno para aislar la base del canal en las pruebas.
VARIABLE_CANAL: str = "CORPUS_CANAL_DB"
#: Variable de entorno para aislar el store de perfil en las pruebas.
VARIABLE_PERFIL: str = "CORPUS_PERFIL_DB"
#: Segundos que vale un token de confirmación.
VIDA_TOKEN_SEGUNDOS: float = 300.0


@dataclass(frozen=True, slots=True)
class _Pendiente:
    """Una acción destructiva esperando la confirmación de la persona."""

    accion: str
    token: str
    creado_en: float


_PENDIENTES: dict[str, _Pendiente] = {}
_CANDADO = threading.Lock()


def _ruta_canal() -> Path:
    """Devuelve la base del canal, respetando el aislamiento de pruebas."""
    return Path(os.environ.get(VARIABLE_CANAL, str(RUTA_ALMACEN)))


def _ruta_perfil() -> Path:
    """Devuelve el store de perfil, respetando el aislamiento de pruebas."""
    return Path(os.environ.get(VARIABLE_PERFIL, str(RUTA_PERFIL)))


def _maquina() -> MaquinaConsentimiento:
    """Crea la máquina de consentimiento con el borrado de perfil conectado."""
    return MaquinaConsentimiento(
        _ruta_canal(),
        borrar_perfil=lambda usuario_id: borrar_perfil_en(_ruta_perfil(), usuario_id),
    )


def _token_de(usuario_id: str, accion: str) -> str:
    """Devuelve el token vigente o crea uno nuevo para la acción pedida.

    Args:
        usuario_id: huella HMAC del número.
        accion: `olvidar_mis_datos` o `solicitar_asesor`.

    Returns:
        El token de confirmación de 16 caracteres.
    """
    with _CANDADO:
        pendiente = _PENDIENTES.get(usuario_id)
        vigente = (
            pendiente is not None
            and pendiente.accion == accion
            and time.monotonic() - pendiente.creado_en < VIDA_TOKEN_SEGUNDOS
        )
        if vigente and pendiente is not None:
            return pendiente.token
        token = uuid4().hex[:16]
        _PENDIENTES[usuario_id] = _Pendiente(accion, token, time.monotonic())
        return token


def _consumir_token(usuario_id: str, accion: str, token: str | None) -> bool:
    """Consume el token una sola vez si coincide y está vigente.

    Args:
        usuario_id: huella HMAC del número.
        accion: acción que se confirma.
        token: token que devolvió el primer paso.

    Returns:
        `True` si la confirmación es válida y quedó consumida.
    """
    if not token:
        return False
    with _CANDADO:
        pendiente = _PENDIENTES.get(usuario_id)
        valido = (
            pendiente is not None
            and pendiente.accion == accion
            and pendiente.token == token
            and time.monotonic() - pendiente.creado_en < VIDA_TOKEN_SEGUNDOS
        )
        if valido:
            del _PENDIENTES[usuario_id]
        return valido


def registrar_consentimiento(usuario_id: str, acepta: bool) -> SalidaHerramienta:
    """Registra la aceptación del aviso de la Ley 1581.

    Args:
        usuario_id: huella HMAC del número.
        acepta: confirmación explícita de la persona.

    Returns:
        El estado del consentimiento y la versión del aviso, o el rechazo.
    """
    entrada = RegistrarConsentimientoEntrada(usuario_id=usuario_id, acepta=acepta)
    if not entrada.acepta:
        return error(
            "registrar_consentimiento",
            "sin_confirmacion",
            "No se guarda nada hasta que la persona acepte el aviso.",
        )
    maquina = _maquina()
    if maquina.estado(entrada.usuario_id) != ESTADO_ACEPTADO:
        maquina.aceptar(entrada.usuario_id)
    return ok(
        "registrar_consentimiento",
        {
            "estado": maquina.estado(entrada.usuario_id),
            "version": maquina.version,
        },
    )


def olvidar_mis_datos(
    usuario_id: str,
    confirmar: bool = False,
    token: str | None = None,
) -> SalidaHerramienta:
    """Revoca el consentimiento y borra los datos del diagnóstico.

    Args:
        usuario_id: huella HMAC del número.
        confirmar: segundo paso; sin él solo se pide confirmación.
        token: token que devolvió el primer paso.

    Returns:
        El token pendiente o la confirmación del borrado una sola vez.
    """
    entrada = OlvidarMisDatosEntrada(usuario_id=usuario_id, confirmar=confirmar, token=token)
    if not entrada.confirmar:
        return ok(
            "olvidar_mis_datos",
            {
                "requiere_confirmacion": True,
                "accion": "olvidar_mis_datos",
                "token": _token_de(entrada.usuario_id, "olvidar_mis_datos"),
                "mensaje": "¿Confirmas que borre tu autorización y los datos de tu diagnóstico?",
            },
        )
    if not _consumir_token(entrada.usuario_id, "olvidar_mis_datos", entrada.token):
        return error(
            "olvidar_mis_datos",
            "confirmacion_invalida",
            "La confirmación no coincide o expiró; vuelve a pedir el borrado.",
        )
    _maquina().revocar(entrada.usuario_id)
    return ok(
        "olvidar_mis_datos",
        {
            "borrado": True,
            "estado": _maquina().estado(entrada.usuario_id),
        },
    )


def solicitar_asesor(
    usuario_id: str,
    motivo: str = "asesor_solicitado",
    confirmar: bool = False,
    token: str | None = None,
) -> SalidaHerramienta:
    """Abre un caso de asesor humano, con confirmación previa.

    Args:
        usuario_id: huella HMAC del número.
        motivo: causa del caso, sin datos personales.
        confirmar: segundo paso; sin él solo se pide confirmación.
        token: token que devolvió el primer paso.

    Returns:
        El token pendiente o el id del caso, sin duplicar uno ya abierto.
    """
    entrada = SolicitarAsesorEntrada(
        usuario_id=usuario_id,
        motivo=motivo,
        confirmar=confirmar,
        token=token,
    )
    if not entrada.confirmar:
        return ok(
            "solicitar_asesor",
            {
                "requiere_confirmacion": True,
                "accion": "solicitar_asesor",
                "token": _token_de(entrada.usuario_id, "solicitar_asesor"),
                "mensaje": "¿Confirmas que un asesor del banco te contacte?",
            },
        )
    if not _consumir_token(entrada.usuario_id, "solicitar_asesor", entrada.token):
        return error(
            "solicitar_asesor",
            "confirmacion_invalida",
            "La confirmación no coincide o expiró; vuelve a pedir el asesor.",
        )
    id_caso = abrir_caso(_ruta_canal(), entrada.usuario_id, entrada.motivo, semaforo="pendiente")
    return ok(
        "solicitar_asesor",
        {
            "caso": id_caso,
            "motivo": entrada.motivo,
            "estado": "pendiente",
        },
    )


def consultar_caso(usuario_id: str) -> SalidaHerramienta:
    """Consulta los casos de asesor que pertenecen a la huella que pregunta.

    Args:
        usuario_id: huella HMAC del número.

    Returns:
        Los casos de esa huella, sin datos personales ni los de terceros.
    """
    entrada = ConsultarCasoEntrada(usuario_id=usuario_id)
    casos = listar_casos(_ruta_canal(), usuario_id=entrada.usuario_id)
    return ok("consultar_caso", {"casos": como_json(casos), "total": len(casos)})


def generar_tarjeta_pana(
    respuestas: list[str],
    incluir_imagen: bool = False,
) -> SalidaHerramienta:
    """Genera la tarjeta de Pana con su texto equivalente.

    Args:
        respuestas: ids canónicos de la entrevista.
        incluir_imagen: si se incluye el PNG en base64.

    Returns:
        El texto equivalente y, si se pidió, la imagen en base64.
    """
    entrada = GenerarTarjetaPanaEntrada(respuestas=respuestas, incluir_imagen=incluir_imagen)
    resultado = diagnostico_de(entrada.respuestas)
    imagen, texto = tarjeta_y_texto(resultado)
    datos: dict[str, object] = {"texto": texto, "png_bytes": len(imagen)}
    if entrada.incluir_imagen:
        datos["png_base64"] = base64.b64encode(imagen).decode("ascii")
    return ok("generar_tarjeta_pana", dict(datos))
