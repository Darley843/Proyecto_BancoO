"""Perfiles seguros de la escena: respaldo cuando falla el voluntario o la voz.

Los perfiles viven en `config/escena.toml [[perfiles]]`. Son ficticios: no
llevan nombres, teléfonos, correos ni documentos, y sus textos pasan por
`detectar_pii` al cargar. Cada uno declara sus cuatro respuestas como letras
A–F de las mismas opciones de la entrevista del diagnóstico
(`config/diagnostico.toml`):

- `monto` → rango `monto` (A–E), con el monto exacto que declara el perfil;
- `ingresos` → rango `ingresos` (A–F);
- `gastos` → rango `gastos` (A–E);
- `deudas` → rango `cuotas` (A–F).

La letra es la posición de la opción en el TOML del diagnóstico, así que A es
siempre la primera opción del rango. `opciones_escena` expone ese catálogo para
que la entrada por voz y la pantalla usen exactamente las mismas letras.

Al cargar, el color esperado de cada perfil se compara con el semáforo que
calcula `diagnostico.motor` con la tabla Gold vigente. Si no coincide, o si el
motor no puede calcularlo, el perfil queda marcado como no válido y no se usa
en modo seguro: así la demo nunca promete un color que el motor no confirma.
Los valores fijos de la escena (empleado, 36 meses, libre inversión) son los
de `PerfilEscena`.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from ..asistente.validacion import detectar_pii
from ..canal.contratos import EntradaDiagnostico
from ..config import PROJECT_ROOT
from ..diagnostico import motor
from .contratos import PerfilEscena, RespuestaEscena

#: Archivo versionado con los perfiles seguros.
RUTA_CONFIG = PROJECT_ROOT / "config" / "escena.toml"
#: Preguntas de la escena, en el orden en que Pana las hace.
PREGUNTAS: tuple[Literal["monto", "ingresos", "gastos", "deudas"], ...] = (
    "monto",
    "ingresos",
    "gastos",
    "deudas",
)
#: Rango de `config/diagnostico.toml` que alimenta cada pregunta.
RANGO_DE_PREGUNTA: dict[str, str] = {
    "monto": "monto",
    "ingresos": "ingresos",
    "gastos": "gastos",
    "deudas": "cuotas",
}
#: Letras de las tarjetas; una pregunta usa tantas como opciones tenga.
LETRAS: tuple[Literal["A", "B", "C", "D", "E", "F"], ...] = ("A", "B", "C", "D", "E", "F")
#: Colores que un perfil puede esperar del motor.
COLORES: frozenset[str] = frozenset({"verde", "amarillo", "rojo"})
#: Cantidad de perfiles que exige el diseño.
MINIMO_PERFILES = 3
MAXIMO_PERFILES = 5


@dataclass(frozen=True, slots=True)
class OpcionEscena:
    """Una tarjeta A–F de la escena, tomada de la entrevista del diagnóstico."""

    pregunta: str
    letra: Literal["A", "B", "C", "D", "E", "F"]
    opcion_id: str
    texto: str
    valor: Decimal
    desde: Decimal | None
    hasta: Decimal | None

    def contiene(self, monto: Decimal) -> bool:
        """Indica si un monto cae dentro del rango de la opción.

        Args:
            monto: monto en pesos.

        Returns:
            `True` si el monto está entre `desde` y `hasta`, incluidos.
        """
        if self.desde is not None and monto < self.desde:
            return False
        return self.hasta is None or monto <= self.hasta


@dataclass(frozen=True, slots=True)
class PerfilSeguro:
    """Perfil seguro ya validado contra el motor."""

    id: str
    esperado: str
    perfil: PerfilEscena
    obtenido: str | None
    motivo: str

    @property
    def valido(self) -> bool:
        """Indica si el perfil se puede usar en modo seguro.

        Returns:
            `True` si el motor confirmó el color esperado.
        """
        return not self.motivo


def opciones_escena(ruta: Path | None = None) -> dict[str, tuple[OpcionEscena, ...]]:
    """Lee las tarjetas A–F de cada pregunta desde `config/diagnostico.toml`.

    Args:
        ruta: archivo del diagnóstico alternativo; por defecto el del motor.

    Returns:
        Las opciones de cada pregunta, en el orden del TOML y con su letra.

    Raises:
        ValueError: si falta un rango o tiene más opciones que letras.
    """
    archivo = Path(ruta) if ruta is not None else motor.RUTA_CONFIG
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    rangos = {str(rango.get("clave")): rango for rango in datos.get("rango", [])}
    opciones: dict[str, tuple[OpcionEscena, ...]] = {}
    for pregunta in PREGUNTAS:
        clave = RANGO_DE_PREGUNTA[pregunta]
        rango = rangos.get(clave)
        if rango is None:
            raise ValueError(f"config/diagnostico.toml no declara el rango «{clave}»")
        crudas = list(rango.get("opcion", []))
        if not crudas or len(crudas) > len(LETRAS):
            raise ValueError(f"el rango «{clave}» debe tener entre 1 y 6 opciones")
        opciones[pregunta] = tuple(
            OpcionEscena(
                pregunta=pregunta,
                letra=letra,
                opcion_id=str(cruda["id"]),
                texto=str(cruda["texto"]),
                valor=_decimal(cruda["valor"], str(cruda["id"])),
                desde=_decimal(cruda["desde"], str(cruda["id"])) if "desde" in cruda else None,
                hasta=_decimal(cruda["hasta"], str(cruda["id"])) if "hasta" in cruda else None,
            )
            for letra, cruda in zip(LETRAS, crudas, strict=False)
        )
    return opciones


def cargar_perfiles(
    ruta: Path | None = None,
    *,
    ruta_diagnostico: Path | None = None,
    hoy: date | None = None,
    raiz: Path | None = None,
) -> tuple[PerfilSeguro, ...]:
    """Lee los perfiles seguros y valida su color contra el motor.

    Args:
        ruta: archivo de la escena alternativo; por defecto `config/escena.toml`.
        ruta_diagnostico: archivo del diagnóstico alternativo.
        hoy: fecha con la que el motor comprueba la vigencia de la tasa.
        raiz: carpeta de tablas Gold alternativa.

    Returns:
        Todos los perfiles, cada uno con el color que obtuvo y, si no sirve, el
        motivo. Los no válidos no se usan en modo seguro.

    Raises:
        ValueError: si falta la sección, hay menos de tres o más de cinco
            perfiles, un id se repite, una letra no existe, el monto no cae en
            su rango, el color esperado no es un color o un texto trae datos
            personales.
    """
    archivo = Path(ruta) if ruta is not None else RUTA_CONFIG
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    crudos = datos.get("perfiles")
    if not isinstance(crudos, list):
        raise ValueError("config/escena.toml no declara [[perfiles]]")
    if not MINIMO_PERFILES <= len(crudos) <= MAXIMO_PERFILES:
        raise ValueError(
            f"la escena necesita entre {MINIMO_PERFILES} y {MAXIMO_PERFILES} perfiles seguros; "
            f"hay {len(crudos)}"
        )
    opciones = opciones_escena(ruta_diagnostico)
    config = motor.cargar_config(ruta_diagnostico)
    vistos: set[str] = set()
    perfiles: list[PerfilSeguro] = []
    for crudo in crudos:
        ident = str(crudo.get("id", "")).strip()
        if not ident or ident in vistos:
            raise ValueError(f"el id de perfil «{ident}» está vacío o repetido")
        vistos.add(ident)
        esperado = str(crudo.get("esperado", ""))
        if esperado not in COLORES:
            raise ValueError(f"el perfil «{ident}» espera «{esperado}», que no es un color")
        perfil = _perfil(ident, crudo, opciones)
        obtenido, motivo = _validar_color(perfil, esperado, config=config, hoy=hoy, raiz=raiz)
        perfiles.append(
            PerfilSeguro(
                id=ident, esperado=esperado, perfil=perfil, obtenido=obtenido, motivo=motivo
            )
        )
    return tuple(perfiles)


def perfiles_seguros(
    ruta: Path | None = None,
    *,
    ruta_diagnostico: Path | None = None,
    hoy: date | None = None,
    raiz: Path | None = None,
) -> tuple[PerfilSeguro, ...]:
    """Devuelve solo los perfiles que el motor confirmó.

    Args:
        ruta: archivo de la escena alternativo.
        ruta_diagnostico: archivo del diagnóstico alternativo.
        hoy: fecha con la que el motor comprueba la vigencia de la tasa.
        raiz: carpeta de tablas Gold alternativa.

    Returns:
        Los perfiles válidos, en el orden del TOML.
    """
    return tuple(
        perfil
        for perfil in cargar_perfiles(ruta, ruta_diagnostico=ruta_diagnostico, hoy=hoy, raiz=raiz)
        if perfil.valido
    )


def perfil_seguro(
    ident: str | None = None,
    ruta: Path | None = None,
    *,
    ruta_diagnostico: Path | None = None,
    hoy: date | None = None,
    raiz: Path | None = None,
) -> PerfilEscena:
    """Devuelve un perfil seguro listo para la escena.

    Args:
        ident: id del perfil; si falta, el de `[seguro] por_defecto` o el
            primero válido.
        ruta: archivo de la escena alternativo.
        ruta_diagnostico: archivo del diagnóstico alternativo.
        hoy: fecha con la que el motor comprueba la vigencia de la tasa.
        raiz: carpeta de tablas Gold alternativa.

    Returns:
        El `PerfilEscena` del perfil pedido.

    Raises:
        ValueError: si el perfil no existe o el motor no confirmó su color.
    """
    todos = cargar_perfiles(ruta, ruta_diagnostico=ruta_diagnostico, hoy=hoy, raiz=raiz)
    buscado = ident or _por_defecto(ruta)
    if buscado is None:
        validos = [perfil for perfil in todos if perfil.valido]
        if not validos:
            raise ValueError("ningún perfil seguro coincide con el motor")
        return validos[0].perfil
    elegido = next((perfil for perfil in todos if perfil.id == buscado), None)
    if elegido is None:
        raise ValueError(f"no existe el perfil seguro «{buscado}»")
    if not elegido.valido:
        raise ValueError(f"el perfil «{buscado}» no se usa en modo seguro: {elegido.motivo}")
    return elegido.perfil


def entrada_del_perfil(perfil: PerfilEscena) -> EntradaDiagnostico:
    """Convierte un perfil de la escena en la entrada del motor.

    Args:
        perfil: perfil con sus cuatro respuestas.

    Returns:
        La entrada del diagnóstico con los valores fijos de la escena.

    Raises:
        ValueError: si falta alguna de las cuatro respuestas.
    """
    valores = {respuesta.pregunta: respuesta.valor for respuesta in perfil.respuestas}
    faltan = [pregunta for pregunta in PREGUNTAS if pregunta not in valores]
    if faltan:
        raise ValueError("el perfil no trae las respuestas: " + ", ".join(faltan))
    return EntradaDiagnostico(
        producto=perfil.producto,
        vinculacion=perfil.vinculacion,
        ingreso_mensual=valores["ingresos"],
        gastos_mensuales=valores["gastos"],
        cuotas_deudas=valores["deudas"],
        monto_credito=perfil.monto_calculo,
        plazo_meses=perfil.plazo_meses,
    )


def _perfil(
    ident: str,
    crudo: Mapping[str, object],
    opciones: Mapping[str, tuple[OpcionEscena, ...]],
) -> PerfilEscena:
    """Arma el `PerfilEscena` de un perfil del TOML.

    Args:
        ident: id del perfil.
        crudo: tabla del TOML.
        opciones: tarjetas A–F de cada pregunta.

    Returns:
        El perfil con sus respuestas, confirmado.

    Raises:
        ValueError: si falta un campo, una letra no existe, el monto no cae en
            su rango o un texto trae datos personales.
    """
    personaje = str(crudo.get("personaje", "")).strip()
    proposito = str(crudo.get("proposito", "")).strip()
    for campo, texto in (("personaje", personaje), ("proposito", proposito)):
        if not texto:
            raise ValueError(f"el perfil «{ident}» no declara {campo}")
        if detectar_pii(texto) is not None or any(caracter.isdigit() for caracter in texto):
            raise ValueError(f"el {campo} del perfil «{ident}» no puede llevar datos ni cifras")
    letras = crudo.get("letras")
    if not isinstance(letras, Mapping):
        raise ValueError(f"el perfil «{ident}» no declara sus letras")
    monto = _decimal(crudo.get("monto", ""), ident)

    respuestas: list[RespuestaEscena] = []
    for pregunta in PREGUNTAS:
        letra = str(letras.get(pregunta, "")).strip().upper()
        opcion = next((op for op in opciones[pregunta] if op.letra == letra), None)
        if opcion is None:
            raise ValueError(
                f"el perfil «{ident}» usa la letra «{letra}» en {pregunta}, que no existe"
            )
        if pregunta == "monto" and not opcion.contiene(monto):
            raise ValueError(
                f"el monto del perfil «{ident}» no cae en la opción {letra} ({opcion.texto})"
            )
        respuestas.append(
            RespuestaEscena(
                pregunta=pregunta,
                letra=opcion.letra,
                opcion_id=opcion.opcion_id,
                texto=opcion.texto,
                valor=monto if pregunta == "monto" else opcion.valor,
            )
        )
    return PerfilEscena(
        personaje=personaje,
        proposito=proposito,
        monto_declarado=monto,
        monto_calculo=monto,
        respuestas=tuple(respuestas),
        confirmado=True,
    )


def _validar_color(
    perfil: PerfilEscena,
    esperado: str,
    *,
    config: motor.ConfigDiagnostico,
    hoy: date | None,
    raiz: Path | None,
) -> tuple[str | None, str]:
    """Calcula el semáforo del perfil y lo compara con el esperado.

    Args:
        perfil: perfil de la escena.
        esperado: color que declara el TOML.
        config: configuración del diagnóstico.
        hoy: fecha con la que el motor comprueba la vigencia de la tasa.
        raiz: carpeta de tablas Gold alternativa.

    Returns:
        El color obtenido y el motivo por el que no sirve, o vacío si coincide.
    """
    try:
        resultado = motor.calcular(entrada_del_perfil(perfil), hoy=hoy, raiz=raiz, config=config)
    except Exception as error:  # noqa: BLE001 - un perfil que no calcula no se usa
        return None, f"el motor no pudo calcularlo ({type(error).__name__})"
    if resultado.semaforo != esperado:
        return resultado.semaforo, (
            f"el motor da {resultado.semaforo or 'sin semáforo'} y el perfil espera {esperado}"
        )
    return resultado.semaforo, ""


def _por_defecto(ruta: Path | None) -> str | None:
    """Lee `[seguro] por_defecto` de la escena.

    Args:
        ruta: archivo de la escena alternativo.

    Returns:
        El id del perfil por defecto, o `None` si no está declarado.
    """
    archivo = Path(ruta) if ruta is not None else RUTA_CONFIG
    with archivo.open("rb") as fh:
        datos = tomllib.load(fh)
    seguro = datos.get("seguro", {})
    valor = seguro.get("por_defecto") if isinstance(seguro, dict) else None
    return str(valor) if valor else None


def _decimal(valor: object, contexto: str) -> Decimal:
    """Convierte un valor del TOML en decimal o explica el error.

    Args:
        valor: número o texto.
        contexto: id del perfil o de la opción, para el mensaje.

    Returns:
        El decimal.

    Raises:
        ValueError: si el valor no es un número.
    """
    try:
        numero = Decimal(str(valor))
    except InvalidOperation as error:
        raise ValueError(f"«{valor}» no es un número válido en «{contexto}»") from error
    if not numero.is_finite():
        raise ValueError(f"«{valor}» no es un número finito en «{contexto}»")
    return numero
