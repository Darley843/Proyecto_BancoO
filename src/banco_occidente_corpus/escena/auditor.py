"""Auditor de la escena «Pana vs. el gota a gota»: reglas en código y veredicto.

El auditor no usa modelo. Revisa cada `TurnoEscena` con reglas deterministas y
devuelve un `VeredictoAuditor` que **no usa colores**: `conforme`,
`con_observaciones` u `objeta`. El semáforo del crédito (verde, amarillo, rojo)
es otra cosa y la pantalla los muestra por separado.

Reglas de gravedad alta (cualquiera da `objeta`):

- `cifra_inventada`: el texto dice una cifra que ninguna `CifraEscena` del
  turno respalda. Solo se revisan los turnos con cifras o con escenario, y no
  cuentan el artículo 305 ni el año de la vigencia que cita la fuente.
- `fuente_ausente`: una cifra cita una referencia que no tiene la forma de su
  tipo de fuente, o su texto legible no corresponde a su valor. En la
  negociación, una cifra del motor debe existir en la mesa precalculada.
- `promesa_aprobacion`: «aprobado», «garantizado», «te lo apruebo» y
  similares, salvo negados de forma inmediata en la misma cláusula («no está
  aprobado»). «Sin duda» y «no solo» no niegan.
- `recomienda_gota`: Pana, los agentes o el auditor recomiendan el gota a
  gota. Don Gota está exento porque es quien lo ofrece; sus cifras sí se
  auditan.
- `semaforo_alterado`: un turno nombra un color distinto del de su escenario,
  o el banco da por sostenible un escenario que el motor dejó en rojo.
- `dato_personal`: teléfono, correo, documento o tarjeta en el texto.

El personaje `invitado` queda fuera de las reglas de texto: es el voluntario
escribiendo por WhatsApp, así que puede citar cifras o preguntar por una
aprobación sin que el auditor las tome como promesas de Pana. Sus datos
personales sí se revisan.

Observaciones de gravedad media (sin altas, dan `con_observaciones`):
`sin_negociacion`, `sin_acuerdo`, `tasa_no_disponible`,
`usura_sin_certificar` y `vigencia_vencida`.

Las cifras y las promesas reutilizan `diagnostico.comite.auditar_texto`, la
misma base del auditor del comité; la escena suma sus frases propias («te lo
apruebo», «ya es tuyo») y la recomendación del gota a gota con la misma
negación (`negada_antes`). Los datos personales usan `detectar_pii`.
`auditar_negociacion` tiene la firma que espera el orquestador de la
negociación (`auditor(turnos, mesa, acuerdo)`), y `crear_auditor_negociacion`
arma esa misma función con las alertas de la comparación.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Literal

from ..asistente.validacion import cifras_duras, detectar_pii
from ..cifras_legibles import formatear_pesos, formatear_porcentaje, formatear_tasa_ea
from ..diagnostico.comite import auditar_texto, negada_antes
from .contratos import (
    CifraEscena,
    EscenarioEscena,
    HallazgoEscena,
    PersonajeEscena,
    TurnoEscena,
    VeredictoAuditor,
)

#: Veredictos posibles; ninguno es un color del semáforo.
Veredicto = Literal["conforme", "con_observaciones", "objeta"]
#: Gravedad de un hallazgo.
Gravedad = Literal["alta", "media"]
#: Firma del auditor que inyecta la negociación.
AuditorNegociacion = Callable[
    [Sequence[TurnoEscena], Sequence[EscenarioEscena], EscenarioEscena | None],
    VeredictoAuditor,
]

#: Reglas de gravedad alta: cualquiera hace que el auditor objete.
REGLAS_ALTAS: tuple[str, ...] = (
    "cifra_inventada",
    "fuente_ausente",
    "promesa_aprobacion",
    "recomienda_gota",
    "semaforo_alterado",
    "dato_personal",
)
#: Observaciones de gravedad media: sin altas, el veredicto queda con observaciones.
REGLAS_MEDIAS: tuple[str, ...] = (
    "sin_negociacion",
    "sin_acuerdo",
    "tasa_no_disponible",
    "usura_sin_certificar",
    "vigencia_vencida",
)
#: Todas las reglas, en el orden en que se reportan.
REGLAS: tuple[str, ...] = REGLAS_ALTAS + REGLAS_MEDIAS
#: Gravedad de cada regla.
GRAVEDAD: dict[str, Gravedad] = {
    **dict.fromkeys(REGLAS_ALTAS, "alta"),
    **dict.fromkeys(REGLAS_MEDIAS, "media"),
}
#: Alertas de la comparación o del diagnóstico que el auditor convierte en observación.
ALERTAS_OBSERVADAS: tuple[str, ...] = (
    "tasa_no_disponible",
    "usura_sin_certificar",
    "vigencia_vencida",
)
#: Alternativas formales que Pana ofrece cuando el auditor objeta o no hay acuerdo.
ALTERNATIVAS_FORMALES: tuple[str, ...] = (
    "microcrédito",
    "cooperativas",
    "entidades vigiladas por la Superfinanciera",
)
#: Etiqueta de cada veredicto para la pantalla; nunca coincide con un color.
ETIQUETA_VEREDICTO: dict[Veredicto, str] = {
    "conforme": "Auditor: conforme",
    "con_observaciones": "Auditor: con observaciones",
    "objeta": "Auditor: objeta",
}
#: Personajes que hablan en la negociación.
AGENTES_NEGOCIACION: frozenset[str] = frozenset({"agente_joven", "agente_banco"})
#: Personajes cuyas palabras no se auditan como si prometieran por Pana o el
#: banco: el invitado escribe libremente por WhatsApp y solo se revisa su PII.
PERSONAJES_SIN_AUDITORIA_DE_TEXTO: frozenset[str] = frozenset({"invitado"})
#: Cifras que la escena cita y que no son financieras: el artículo del Código Penal.
CIFRAS_LEGALES: frozenset[str] = frozenset({"305"})

#: Frase con la que Pana recuerda quién decide.
_FRASE_ASESOR = "la decisión final es de un asesor."
#: Ids de los turnos que arma este módulo.
ID_TURNO_AUDITOR = "auditor.veredicto.v1"
ID_TURNO_CIERRE = "pana.cierre.v1"

#: Forma de la referencia que exige cada tipo de fuente.
_REFERENCIA_POR_TIPO: dict[str, re.Pattern[str]] = {
    "config": re.compile(r"^config/[\w./-]+\.toml#[\w.]+$"),
    "motor": re.compile(r"^(?:diagnostico\.motor|escena\.[a-z_]+)#[\w.]+$"),
    "calculo_gota": re.compile(r"^escena\.[a-z_]+#[\w.]+$"),
    "usura": re.compile(r"^config/tasas\.toml#usura\.[\w.]+$"),
    "gold": re.compile(r"^data/gold/[\w./-]+(?:#[\w.-]+)?$"),
    # README, AGENTS y CONSTITUTION de la raíz o un .md de docs/, con ancla y sin «..».
    "documento": re.compile(
        r"^(?!.*\.\.)(?:(?:README|AGENTS|CONSTITUTION)\.md|docs/[\w./-]+\.md)#[\w.-]+$"
    ),
    "guion": re.compile(r"^(?:config/escena\.toml|docs/[\w./-]+\.md)#[\w.-]+$"),
}
#: Promesas propias de la escena que la lista del comité no trae. Las del comité
#: («aprobado», «garantizado», «te lo aprueban»…) las revisa `auditar_texto`.
_PROMESAS_ESCENA = re.compile(
    r"\b(?:te\s+l[oa]\s+apruebo|se\s+l[oa]\s+apruebo|apruebo|ya\s+es\s+tuy[oa])\b",
    re.IGNORECASE,
)
#: Recomendar el gota a gota: un verbo de recomendación seguido del gota.
_RECOMIENDA_GOTA = re.compile(
    r"\b(?:te\s+)?(?:recomiendo|conviene|elige|escoge|acepta|ac[eé]ptale|toma|usa|"
    r"ve\s+con|vete\s+con|anda\s+con|[aá]ndate\s+con|qu[eé]date\s+con|p[ií]dele\s+a|"
    r"(?:ve|vete|anda|[aá]ndate|vaya|v[aá]yase)\s+(?:a\s+)?donde|mejor\s+con|"
    r"mejor)\s+(?:(?:el|al|a|la\s+oferta\s+de|lo\s+de)\s+)?"
    r"(?:pr[eé]stamo\s+(?:de\s+|del\s+)?)?(?:gota\s+a\s+gota|don\s+gota)\b",
    re.IGNORECASE,
)
#: Nombres de color del semáforo dentro de un texto.
_COLOR = re.compile(r"\b(verde|amarillo|rojo|[aá]mbar)\b", re.IGNORECASE)
#: Frases con las que el banco da por sostenible un escenario.
_AFIRMA_QUE_CABE = re.compile(
    r"\b(?:es\s+sostenible|cabe\s+con\s+holgura|cabe,\s+pero\s+ajustado)\b",
    re.IGNORECASE,
)
#: Años que aparecen en la vigencia de una fuente (``2026-11-01/2026-11-30``).
_ANIO = re.compile(r"\b(20\d{2})\b")
#: Número dentro del texto legible de una cifra en veces («5,7 veces», «6»).
_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
#: Marca interna para reconocer el hallazgo de datos personales de `auditar_texto`.
_MARCA_PII = "__dato_personal__"
#: Prefijo con el que `auditar_texto` reporta una cifra no respaldada.
_PREFIJO_CIFRA = "Cifra no presente en la entrada: "
#: Prefijo con el que `auditar_texto` reporta una promesa de aprobación.
_PREFIJO_PROMESA = "Promesa de aprobación: "


def auditar_turno(
    turno: TurnoEscena,
    *,
    mesa: Sequence[EscenarioEscena] = (),
) -> tuple[HallazgoEscena, ...]:
    """Revisa un turno con las seis reglas de gravedad alta.

    Args:
        turno: turno de la escena.
        mesa: escenarios precalculados de la negociación; si se pasa, las cifras
            del motor en los turnos de los agentes deben existir en ella.

    Returns:
        Los hallazgos del turno, sin repetir; vacío si el turno pasa.
    """
    hallazgos: list[HallazgoEscena] = []
    audita_texto = turno.personaje not in PERSONAJES_SIN_AUDITORIA_DE_TEXTO
    audita_cifras = bool(turno.cifras) or turno.escenario is not None
    permitidas = _cifras_permitidas(turno) if audita_cifras and audita_texto else None

    if audita_texto:
        for texto in auditar_texto(
            turno.texto,
            cifras_permitidas=permitidas,
            revisar_promesas=True,
            mensaje_pii=_MARCA_PII,
        ):
            if texto.startswith(_PREFIJO_PROMESA):
                frase = texto.removeprefix(_PREFIJO_PROMESA).strip("«»")
                hallazgos.append(
                    _hallazgo("promesa_aprobacion", turno.id, f"Promete una aprobación: «{frase}».")
                )
            elif texto.startswith(_PREFIJO_CIFRA):
                cifra = texto.removeprefix(_PREFIJO_CIFRA)
                hallazgos.append(
                    _hallazgo(
                        "cifra_inventada",
                        turno.id,
                        f"El texto dice {cifra} y ninguna cifra del turno la respalda.",
                    )
                )

        for frase in _promesas_escena(turno.texto):
            hallazgos.append(
                _hallazgo("promesa_aprobacion", turno.id, f"Promete una aprobación: «{frase}».")
            )

    for cifra in turno.cifras:
        motivo = _motivo_fuente(cifra, turno, mesa)
        if motivo:
            hallazgos.append(_hallazgo("fuente_ausente", turno.id, motivo))

    if audita_texto and turno.personaje != "don_gota":
        for frase in _recomendaciones_gota(turno.texto):
            hallazgos.append(
                _hallazgo(
                    "recomienda_gota",
                    turno.id,
                    f"{_nombre(turno.personaje)} recomienda el gota a gota: «{frase}».",
                )
            )

    motivo_semaforo = _motivo_semaforo(turno) if audita_texto else ""
    if motivo_semaforo:
        hallazgos.append(_hallazgo("semaforo_alterado", turno.id, motivo_semaforo))

    pii = detectar_pii(turno.texto)
    if pii is not None:
        hallazgos.append(
            _hallazgo(
                "dato_personal",
                turno.id,
                f"El texto trae un dato personal ({pii.categoria}).",
            )
        )

    return _sin_repetir(hallazgos)


def auditar_escena(
    turnos: Sequence[TurnoEscena],
    *,
    mesa: Sequence[EscenarioEscena] = (),
    acuerdo: EscenarioEscena | None = None,
    alertas: Iterable[str] = (),
    exigir_negociacion: bool = False,
    semaforo: str | None = None,
) -> VeredictoAuditor:
    """Revisa todos los turnos y devuelve el veredicto de la escena.

    Args:
        turnos: turnos de la escena, en orden.
        mesa: escenarios precalculados de la negociación, si la hubo.
        acuerdo: escenario recomendado al cerrar la negociación, o `None`.
        alertas: códigos de la comparación o del diagnóstico, como
            `usura_sin_certificar` o `vigencia_vencida`.
        exigir_negociacion: si la escena debía traer la negociación; sin turnos
            de los agentes se observa `sin_negociacion` (por ejemplo, el núcleo).
        semaforo: semáforo del mejor escenario del perfil, si se conoce; en rojo
            Pana ofrece las alternativas formales aunque el auditor esté conforme.

    Returns:
        El veredicto, sus hallazgos, los turnos revisados, las reglas aplicadas y
        las alternativas formales cuando corresponden.
    """
    hallazgos: list[HallazgoEscena] = []
    for turno in turnos:
        hallazgos.extend(auditar_turno(turno, mesa=mesa))

    hubo_negociacion = any(turno.personaje in AGENTES_NEGOCIACION for turno in turnos)
    if exigir_negociacion and not hubo_negociacion:
        hallazgos.append(
            _hallazgo(
                "sin_negociacion",
                None,
                "La escena no trae la negociación: se mostró el núcleo.",
            )
        )
    if mesa and acuerdo is None:
        hallazgos.append(
            _hallazgo("sin_acuerdo", None, "La negociación cerró sin un escenario aceptable.")
        )
    vistas = set(alertas)
    for alerta in ALERTAS_OBSERVADAS:
        if alerta in vistas:
            hallazgos.append(_hallazgo(alerta, None, _DETALLE_ALERTA[alerta]))

    unicos = _sin_repetir(hallazgos)
    veredicto = veredicto_desde_hallazgos(unicos)
    rojo = semaforo == "rojo" or (acuerdo is not None and acuerdo.semaforo == "rojo")
    sin_acuerdo = bool(mesa) and acuerdo is None
    alternativas = ALTERNATIVAS_FORMALES if veredicto == "objeta" or rojo or sin_acuerdo else ()
    return VeredictoAuditor(
        veredicto=veredicto,
        hallazgos=unicos,
        turnos_revisados=tuple(turno.id for turno in turnos),
        reglas=REGLAS,
        alternativas=alternativas,
    )


def auditar_negociacion(
    turnos: Sequence[TurnoEscena],
    mesa: Sequence[EscenarioEscena],
    acuerdo: EscenarioEscena | None,
) -> VeredictoAuditor:
    """Auditor con la firma que inyecta `escena.negociacion.negociar`.

    Args:
        turnos: turnos de la negociación.
        mesa: escenarios precalculados.
        acuerdo: escenario recomendado, o `None` si no hubo acuerdo.

    Returns:
        El veredicto de la negociación, con `sin_negociacion` si no hubo turnos.
    """
    return auditar_escena(turnos, mesa=mesa, acuerdo=acuerdo, exigir_negociacion=True)


def crear_auditor_negociacion(
    *,
    alertas: Iterable[str] = (),
    semaforo: str | None = None,
) -> AuditorNegociacion:
    """Arma el auditor de la negociación con las alertas de la escena.

    Args:
        alertas: códigos de la comparación o del diagnóstico que deben quedar
            como observación (`usura_sin_certificar`, `vigencia_vencida`…).
        semaforo: semáforo del perfil, si se conoce.

    Returns:
        Una función `auditor(turnos, mesa, acuerdo) -> VeredictoAuditor`.
    """
    fijas = tuple(alertas)

    def auditor(
        turnos: Sequence[TurnoEscena],
        mesa: Sequence[EscenarioEscena],
        acuerdo: EscenarioEscena | None,
    ) -> VeredictoAuditor:
        """Audita la negociación con las alertas fijadas al crear el auditor."""
        return auditar_escena(
            turnos,
            mesa=mesa,
            acuerdo=acuerdo,
            alertas=fijas,
            exigir_negociacion=True,
            semaforo=semaforo,
        )

    return auditor


def veredicto_desde_hallazgos(hallazgos: Iterable[HallazgoEscena]) -> Veredicto:
    """Convierte la gravedad de los hallazgos en el veredicto, sin colores.

    Args:
        hallazgos: hallazgos de la escena.

    Returns:
        `objeta` si hay alguno alto, `con_observaciones` si solo hay medios y
        `conforme` si no hay ninguno.
    """
    gravedades = {hallazgo.gravedad for hallazgo in hallazgos}
    if "alta" in gravedades:
        return "objeta"
    if "media" in gravedades:
        return "con_observaciones"
    return "conforme"


def etiqueta_veredicto(veredicto: VeredictoAuditor) -> str:
    """Devuelve la etiqueta del veredicto para la pantalla.

    Args:
        veredicto: veredicto del auditor.

    Returns:
        «Auditor: conforme», «Auditor: con observaciones» o «Auditor: objeta».
    """
    return ETIQUETA_VEREDICTO[veredicto.veredicto]


def permite_cierre_favorable(veredicto: VeredictoAuditor) -> bool:
    """Indica si la pantalla puede mostrar un cierre favorable.

    Args:
        veredicto: veredicto del auditor.

    Returns:
        `False` si el auditor objeta: la UI no habilita el cierre verde.
    """
    return veredicto.veredicto != "objeta"


def turno_auditor(veredicto: VeredictoAuditor, *, orden: int) -> TurnoEscena:
    """Arma el turno corto del auditor; el detalle va en el panel.

    Args:
        veredicto: veredicto de la escena.
        orden: orden del turno en la escena completa.

    Returns:
        El turno del auditor, sin cifras y con `origen="reglas"`.
    """
    textos: dict[Veredicto, str] = {
        "conforme": "Revisé cada cifra y cada frase: conforme. Todo tiene su fuente.",
        "con_observaciones": (
            "Revisé cada cifra y cada frase: con observaciones. Las dejo en el panel."
        ),
        "objeta": (
            "Revisé cada cifra y cada frase: objeto. Hay un problema grave y el detalle "
            "está en el panel."
        ),
    }
    return TurnoEscena(
        id=ID_TURNO_AUDITOR,
        orden=orden,
        personaje="auditor",
        texto=textos[veredicto.veredicto],
        origen="reglas",
    )


def cierre_pana(veredicto: VeredictoAuditor, *, orden: int) -> TurnoEscena:
    """Arma el cierre fijo de Pana según el veredicto.

    Con `objeta`, o cuando el veredicto trae alternativas (sin acuerdo o rojo),
    Pana nombra las alternativas formales sin prometer nada. En los demás casos
    recuerda que el resultado es orientativo y que decide un asesor.

    Args:
        veredicto: veredicto de la escena.
        orden: orden del turno en la escena completa.

    Returns:
        El turno de cierre de Pana, sin cifras y con `origen="reglas"`.
    """
    alternativas = _lista(veredicto.alternativas)
    if veredicto.veredicto == "objeta":
        texto = (
            "El auditor objetó esta escena, así que no la doy por buena. "
            f"Busca alternativas formales: {alternativas}."
        )
    elif veredicto.alternativas:
        texto = (
            "Hoy no hay una opción que quepa en tu presupuesto. Antes de endeudarte, "
            f"busca alternativas formales: {alternativas}."
        )
    elif veredicto.veredicto == "con_observaciones":
        texto = "El auditor dejó observaciones en el panel. Esto es orientativo: " + _FRASE_ASESOR
    else:
        texto = "El auditor está conforme. Esto es orientativo: " + _FRASE_ASESOR
    return TurnoEscena(
        id=ID_TURNO_CIERRE,
        orden=orden,
        personaje="pana",
        texto=texto,
        origen="reglas",
    )


#: Detalle de cada alerta observada.
_DETALLE_ALERTA: dict[str, str] = {
    "tasa_no_disponible": "El Tablero no publica la tasa del producto: no se inventó una.",
    "usura_sin_certificar": "No hay usura certificada vigente: no se calculó el ratio.",
    "vigencia_vencida": "La tasa del banco tiene la vigencia vencida.",
}


def _hallazgo(regla: str, turno_id: str | None, detalle: str) -> HallazgoEscena:
    """Arma un hallazgo con la gravedad de su regla.

    Args:
        regla: código de la regla.
        turno_id: turno donde se encontró, o `None` si es de la escena.
        detalle: explicación en español.

    Returns:
        El hallazgo listo para el veredicto.
    """
    return HallazgoEscena(
        codigo=regla,
        turno_id=turno_id,
        detalle=detalle,
        gravedad=GRAVEDAD[regla],
    )


def _cifras_permitidas(turno: TurnoEscena) -> set[str]:
    """Cifras que el texto del turno puede decir.

    Son las de sus `CifraEscena`, el artículo 305 y los años de la vigencia que
    citan sus fuentes.

    Args:
        turno: turno con cifras o escenario.

    Returns:
        Las cifras normalizadas como las devuelve `cifras_duras`.
    """
    permitidas: set[str] = set(CIFRAS_LEGALES)
    for cifra in turno.cifras:
        permitidas.update(cifras_duras(cifra.valor_legible))
        if cifra.fuente.vigencia:
            permitidas.update(_ANIO.findall(cifra.fuente.vigencia))
            permitidas.update(cifras_duras(cifra.fuente.vigencia))
    return permitidas


def _motivo_fuente(
    cifra: CifraEscena,
    turno: TurnoEscena,
    mesa: Sequence[EscenarioEscena],
) -> str:
    """Explica por qué la fuente de una cifra no es válida, o devuelve vacío.

    Args:
        cifra: cifra del turno.
        turno: turno al que pertenece.
        mesa: escenarios precalculados de la negociación.

    Returns:
        El motivo, o una cadena vacía si la fuente y el valor cuadran.
    """
    referencia = cifra.fuente.referencia.strip()
    patron = _REFERENCIA_POR_TIPO.get(cifra.fuente.tipo)
    if not referencia or patron is None or not patron.match(referencia):
        return (
            f"La cifra «{cifra.valor_legible}» cita una fuente {cifra.fuente.tipo} "
            f"sin una referencia válida: «{referencia}»."
        )
    if not _legible_cuadra(cifra):
        return f"La cifra «{cifra.valor_legible}» no corresponde a su valor ({cifra.valor})."
    if (
        mesa
        and turno.personaje in AGENTES_NEGOCIACION
        and cifra.fuente.tipo == "motor"
        and cifra.unidad == "pesos"
        and "diferencia" not in referencia
        and cifra.valor not in _valores_mesa(mesa)
    ):
        return f"La cifra «{cifra.valor_legible}» no está en la mesa que calculó el motor."
    return ""


def _legible_cuadra(cifra: CifraEscena) -> bool:
    """Comprueba que el texto legible de una cifra corresponda a su valor.

    Args:
        cifra: cifra del turno.

    Returns:
        `True` si el texto es el que produce el formateador de su unidad.
    """
    valor = cifra.valor
    legible = cifra.valor_legible.strip()
    if cifra.unidad == "pesos":
        return legible == formatear_pesos(valor)
    if cifra.unidad == "porcentaje_ea":
        return legible == formatear_tasa_ea(valor)
    if cifra.unidad == "porcentaje":
        return legible == formatear_porcentaje(valor)
    if cifra.unidad in {"meses", "dias"}:
        return valor == valor.to_integral_value() and legible == str(int(valor))
    numero = _NUMERO.search(legible)
    if numero is None:
        return False
    texto = numero.group(0).replace(",", ".")
    try:
        dicho = Decimal(texto)
    except InvalidOperation:
        return False
    decimales = len(texto.split(".")[1]) if "." in texto else 0
    tolerancia = Decimal("0.5") * Decimal(10) ** -decimales
    return abs(dicho - valor) <= tolerancia


def _valores_mesa(mesa: Sequence[EscenarioEscena]) -> set[Decimal]:
    """Montos en pesos que la mesa precalculó.

    Args:
        mesa: escenarios de la negociación.

    Returns:
        Los montos, cuotas, totales e intereses de todos los escenarios.
    """
    valores: set[Decimal] = set()
    for escenario in mesa:
        for valor in (
            escenario.monto,
            escenario.cuota_mensual,
            escenario.total_pagado,
            escenario.total_intereses,
        ):
            if valor is not None:
                valores.add(valor)
    return valores


def _promesas_escena(texto: str) -> list[str]:
    """Promesas propias de la escena («te lo apruebo», «ya es tuyo») que no estén negadas.

    La negación es la del comité (`negada_antes`): «no te lo apruebo» no cuenta,
    pero «sin duda te lo apruebo» sí.

    Args:
        texto: texto del turno.

    Returns:
        Las frases encontradas.
    """
    return [
        coincidencia.group(0)
        for coincidencia in _PROMESAS_ESCENA.finditer(texto)
        if not negada_antes(texto, coincidencia.start())
    ]


def _recomendaciones_gota(texto: str) -> list[str]:
    """Frases que recomiendan el gota a gota y no están negadas.

    Args:
        texto: texto del turno.

    Returns:
        Las frases encontradas.
    """
    return [
        coincidencia.group(0)
        for coincidencia in _RECOMIENDA_GOTA.finditer(texto)
        if not negada_antes(texto, coincidencia.start())
    ]


def _motivo_semaforo(turno: TurnoEscena) -> str:
    """Explica si el turno contradice el semáforo de su escenario.

    Args:
        turno: turno de la escena.

    Returns:
        El motivo, o una cadena vacía si no hay contradicción.
    """
    escenario = turno.escenario
    if escenario is None or escenario.semaforo is None:
        return ""
    for coincidencia in _COLOR.finditer(turno.texto):
        color = coincidencia.group(1).casefold().replace("á", "a")
        color = "amarillo" if color == "ambar" else color
        if color != escenario.semaforo:
            return (
                f"El turno dice «{coincidencia.group(1)}», pero el motor dejó el escenario "
                f"«{escenario.codigo}» en {escenario.semaforo}."
            )
    if (
        turno.personaje == "agente_banco"
        and escenario.semaforo == "rojo"
        and (afirma := _AFIRMA_QUE_CABE.search(turno.texto)) is not None
        and not negada_antes(turno.texto, afirma.start())
    ):
        frase = afirma.group(0)
        return f"El banco dice «{frase}» de «{escenario.codigo}», pero el motor lo dejó en rojo."
    return ""


def _nombre(personaje: PersonajeEscena) -> str:
    """Nombre legible del personaje para los hallazgos.

    Args:
        personaje: clave del personaje.

    Returns:
        El nombre en español.
    """
    nombres: dict[str, str] = {
        "pana": "Pana",
        "joven": "El joven",
        "agente_joven": "El agente del joven",
        "agente_banco": "El agente del banco",
        "auditor": "El auditor",
        "invitado": "El invitado",
    }
    return nombres.get(personaje, personaje)


def _lista(elementos: Sequence[str]) -> str:
    """Une una lista en español con «o» antes del último elemento.

    Args:
        elementos: textos de la lista.

    Returns:
        La lista legible, o las alternativas formales si viene vacía.
    """
    items = list(elementos) or list(ALTERNATIVAS_FORMALES)
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} o {items[-1]}"


def _sin_repetir(hallazgos: Sequence[HallazgoEscena]) -> tuple[HallazgoEscena, ...]:
    """Quita hallazgos repetidos conservando el orden.

    Args:
        hallazgos: hallazgos encontrados.

    Returns:
        Los hallazgos sin repetir.
    """
    vistos: set[tuple[str, str | None, str]] = set()
    unicos: list[HallazgoEscena] = []
    for hallazgo in hallazgos:
        clave = (hallazgo.codigo, hallazgo.turno_id, hallazgo.detalle)
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(hallazgo)
    return tuple(unicos)
