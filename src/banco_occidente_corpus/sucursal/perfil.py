"""Memoria de perfil: deteccion, respuestas y envoltura sobre el `BaseStore`.

El perfil vive fuera del hilo: se guarda en el store de LangGraph bajo el
namespace ``("perfil", hash_del_perfil_id)`` y sobrevive a una conversacion
nueva. Solo se guardan dos datos declarados por el usuario (nombre y empresa);
el valor crudo del `perfil_id` nunca se usa como namespace ni se escribe en el
estado, la cache o los logs.

Las reglas de deteccion son deterministas y estrechas: «soy X» solo captura un
nombre propio con mayuscula y fuera de una lista de palabras comunes, para no
confundir «soy cliente», «soy de Cali» o «soy estudiante» con un perfil.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from langgraph.store.base import BaseStore

from ..texto import normalizar

#: Nombre del namespace de los perfiles en el store de LangGraph.
NOMBRE_ESPACIO = "perfil"
#: Clave unica del documento de cada perfil dentro de su namespace.
CLAVE_DATOS = "datos"
#: Campos que forman el perfil. No se guarda nada mas.
CAMPOS: tuple[str, ...] = ("nombre", "empresa")
#: Largo maximo del identificador de perfil que llega desde la Ventanilla.
LARGO_PERFIL_ID = 128

#: Mensaje cuando la conversacion no trae `perfil_id`.
MENSAJE_PERFIL_INACTIVO = "La memoria del perfil no está activa en esta conversación."
#: Mensaje cuando el perfil existe pero no tiene el dato consultado.
MENSAJE_PERFIL_SIN_DATO = (
    "No tengo ese dato en tu perfil. Puedes decírmelo, por ejemplo: «trabajo en…» o «me llamo…»."
)
#: Mensaje cuando el usuario pide borrar su perfil.
MENSAJE_PERFIL_BORRADO = "Listo. Borré los datos de tu perfil."

#: Palabras que nunca son un nombre propio en la regla «soy X».
EXCLUIDAS: frozenset[str] = frozenset(
    {
        "abogado",
        "abogada",
        "administrador",
        "administradora",
        "adulto",
        "adulta",
        "analista",
        "antioqueno",
        "antioquena",
        "arquitecto",
        "arquitecta",
        "asesor",
        "asesora",
        "bogotano",
        "bogotana",
        "caleno",
        "calena",
        "cliente",
        "clienta",
        "colombiano",
        "colombiana",
        "comerciante",
        "con",
        "contador",
        "contadora",
        "de",
        "del",
        "docente",
        "economista",
        "el",
        "empleado",
        "empleada",
        "empresario",
        "empresaria",
        "en",
        "enfermero",
        "enfermera",
        "estudiante",
        "extranjero",
        "extranjera",
        "gerente",
        "hombre",
        "independiente",
        "ingeniero",
        "ingeniera",
        "joven",
        "jubilado",
        "jubilada",
        "la",
        "las",
        "los",
        "mayor",
        "medico",
        "medica",
        "menor",
        "mujer",
        "nuevo",
        "nueva",
        "odontologo",
        "odontologa",
        "para",
        "pensionado",
        "pensionada",
        "persona",
        "profesional",
        "psicologo",
        "psicologa",
        "sin",
        "tecnico",
        "tecnica",
        "tecnologo",
        "tecnologa",
        "trabajador",
        "trabajadora",
        "un",
        "una",
        "usuario",
        "usuaria",
        "vendedor",
        "vendedora",
    }
)

#: Conectores que cortan la captura de un nombre.
_CONECTORES = (
    "y",
    "e",
    "o",
    "u",
    "pero",
    "que",
    "quiero",
    "necesito",
    "deseo",
    "para",
    "donde",
    "como",
    "cuando",
    "cual",
    "cuanto",
)
_NO_CONECTOR = r"(?!" + "|".join(_CONECTORES) + r"\b)"
_TOKEN = r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’-]+"
_TOKEN_PROPIO = r"[A-ZÁÉÍÓÚÜÑ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’-]*"
_NOMBRE = re.compile(
    rf"\b(?:me llamo|mi nombre es)\s+"
    rf"(?P<nombre>{_TOKEN}(?:\s+{_NO_CONECTOR}{_TOKEN}){{0,3}})",
    re.IGNORECASE,
)
_SOY = re.compile(
    rf"(?i:\bsoy)\s+(?P<nombre>{_TOKEN_PROPIO}(?:\s+{_TOKEN_PROPIO}){{0,3}})",
)
_EMPRESA = re.compile(
    r"\b(?:trabajo en|mi empresa es)\s+"
    r"(?P<empresa>[^,;¿?¡!\n]+?)(?=\.\s|[,;¿?¡!\n]|$)",
    re.IGNORECASE,
)
_BORRAR = re.compile(
    r"\b(?:olvida|olvidate de|borra|elimina)\s+"
    r"(?:mi perfil|mis datos|mi nombre|mi empresa)\b",
    re.IGNORECASE,
)
_CONSULTAS: dict[str, tuple[re.Pattern[str], ...]] = {
    "nombre": (
        re.compile(r"\bc[oó]mo me llamo\b", re.IGNORECASE),
        re.compile(r"\bcu[aá]l es mi nombre\b", re.IGNORECASE),
        re.compile(r"\bqui[eé]n soy\b", re.IGNORECASE),
    ),
    "empresa": (
        re.compile(r"\bd[oó]nde trabajo\b", re.IGNORECASE),
        re.compile(r"\ben qu[eé] empresa trabajo\b", re.IGNORECASE),
        re.compile(r"\bcu[aá]l es mi empresa\b", re.IGNORECASE),
        re.compile(r"\bd[oó]nde queda mi empresa\b", re.IGNORECASE),
    ),
}


@dataclass(frozen=True, slots=True)
class DatoPerfil:
    """Un dato declarado por el usuario, listo para guardar."""

    campo: Literal["nombre", "empresa"]
    valor: str


@dataclass(frozen=True, slots=True)
class IntencionPerfil:
    """Lo que pide un mensaje sobre el perfil y el resto que no es perfil."""

    guardar: tuple[DatoPerfil, ...] = ()
    consultar: tuple[str, ...] = ()
    borrar: bool = False
    resto: str = ""


def normalizar_perfil_id(valor: str) -> str:
    """Limpia el identificador de perfil y descarta valores inservibles.

    No se valida con un formato cerrado: la Ventanilla manda un UUID, pero una
    prueba puede usar un texto corto. Se rechazan vacios, controles y valores
    mayores que :data:`LARGO_PERFIL_ID`; en ese caso la memoria queda inactiva.

    Args:
        valor: identificador recibido del cliente.

    Returns:
        El identificador limpio o ``""`` si no sirve.
    """
    limpio = valor.strip()
    if not limpio or len(limpio) > LARGO_PERFIL_ID:
        return ""
    if any(unicodedata.category(caracter).startswith("C") for caracter in limpio):
        return ""
    return limpio


def huella_perfil(perfil_id: str) -> str:
    """Devuelve el SHA-256 del identificador; es el namespace del store."""
    return hashlib.sha256(perfil_id.encode("utf-8")).hexdigest()


def detectar_intencion(texto: str) -> IntencionPerfil | None:
    """Detecta si el mensaje guarda, consulta o borra el perfil.

    La deteccion es deliberadamente estrecha. «me llamo» y «trabajo en» son
    explicitos; «soy X» exige un nombre propio con mayuscula y fuera de
    :data:`EXCLUIDAS`. Si no hay ninguna senal, devuelve ``None`` y el mensaje
    sigue su ruta normal.

    Args:
        texto: mensaje original del cliente.

    Returns:
        La intencion con los datos, las consultas y el resto no relacionado con
        el perfil, o ``None`` si el mensaje no habla del perfil.
    """
    spans: list[tuple[int, int]] = []
    guardar: dict[Literal["nombre", "empresa"], str] = {}
    consultar: set[str] = set()
    borrar = False

    for patron in (_NOMBRE, _SOY):
        for coincidencia in patron.finditer(texto):
            valor = _nombre_valido(coincidencia.group("nombre"))
            if not valor:
                continue
            guardar["nombre"] = valor
            spans.append(coincidencia.span())

    for coincidencia in _EMPRESA.finditer(texto):
        if _es_pregunta(texto, coincidencia.start()):
            continue
        valor = _empresa_valida(coincidencia.group("empresa"))
        if not valor:
            continue
        guardar["empresa"] = valor
        spans.append(coincidencia.span())

    for coincidencia in _BORRAR.finditer(texto):
        borrar = True
        spans.append(coincidencia.span())

    for campo, patrones in _CONSULTAS.items():
        for patron in patrones:
            for coincidencia in patron.finditer(texto):
                consultar.add(campo)
                spans.append(coincidencia.span())

    if not guardar and not consultar and not borrar:
        return None

    return IntencionPerfil(
        guardar=tuple(DatoPerfil(campo=campo, valor=valor) for campo, valor in guardar.items()),
        consultar=tuple(sorted(consultar)),
        borrar=borrar,
        resto=_limpiar_resto(texto, spans),
    )


def respuesta_perfil(datos: Mapping[str, str], consultar: Iterable[str]) -> str:
    """Responde una consulta con los datos del perfil, sin inventar.

    Args:
        datos: campos guardados del perfil.
        consultar: campos que pidio el usuario.

    Returns:
        Una frase con los datos disponibles o el mensaje de perfil sin dato.
    """
    partes: list[str] = []
    for campo in consultar:
        valor = str(datos.get(campo, "")).strip()
        if not valor:
            continue
        if campo == "nombre":
            partes.append(f"te llamas {valor}")
        elif campo == "empresa":
            partes.append(f"trabajas en {valor}")
    if not partes:
        return MENSAJE_PERFIL_SIN_DATO
    return f"Según tu perfil, {' y '.join(partes)}."


def confirmacion_perfil(datos: Mapping[str, str], guardados: Iterable[str]) -> str:
    """Arma la confirmacion corta de un guardado, con el nombre si se conoce.

    Args:
        datos: perfil completo despues del guardado.
        guardados: campos que se acaban de guardar.

    Returns:
        Una frase breve, sin cifras y sin fuentes.
    """
    nombre = str(datos.get("nombre", "")).strip()
    empresa = str(datos.get("empresa", "")).strip()
    saludo = f"Listo, {nombre}." if nombre else "Listo."
    campos = set(guardados)
    if {"nombre", "empresa"} <= campos:
        detalle = (
            f" Guardé tu nombre y tu empresa: {empresa}."
            if empresa
            else " Guardé tu nombre y tu empresa."
        )
        return f"{saludo}{detalle}"
    if "nombre" in campos:
        return f"{saludo} Guardé tu nombre."
    if "empresa" in campos:
        detalle = f" Guardé tu empresa: {empresa}." if empresa else " Guardé tu empresa."
        return f"{saludo}{detalle}"
    return saludo


@dataclass(frozen=True, slots=True)
class AlmacenPerfil:
    """Envoltura delgada sobre un ``BaseStore`` de LangGraph.

    No abre archivos ni conexiones: el store se compila con el grafo
    (``SqliteStore`` en produccion, ``InMemoryStore`` en demo y pruebas) y el
    nodo ``perfil`` lo recibe inyectado por LangGraph.
    """

    store: BaseStore

    def namespace(self, perfil: str) -> tuple[str, str]:
        """Devuelve el namespace aislado de un perfil ya hasheado."""
        return (NOMBRE_ESPACIO, perfil)

    def leer(self, perfil: str) -> dict[str, str]:
        """Lee el documento del perfil con ``search`` sobre su namespace.

        Args:
            perfil: hash del identificador de perfil.

        Returns:
            Los campos guardados; vacio si el perfil no existe.
        """
        if not perfil:
            return {}
        encontrados = self.store.search(self.namespace(perfil), limit=1)
        if not encontrados:
            return {}
        valor = encontrados[0].value
        return {
            campo: str(valor[campo])
            for campo in CAMPOS
            if isinstance(valor.get(campo), str) and str(valor[campo]).strip()
        }

    def guardar(self, perfil: str, cambios: Mapping[str, str]) -> dict[str, str]:
        """Guarda o actualiza los campos del perfil con ``put``.

        Args:
            perfil: hash del identificador de perfil.
            cambios: campos nuevos o actualizados.

        Returns:
            El documento completo despues del guardado; vacio si no hay perfil.
        """
        if not perfil:
            return {}
        datos = self.leer(perfil)
        for campo in CAMPOS:
            valor = str(cambios.get(campo, "")).strip()
            if valor:
                datos[campo] = valor
        self.store.put(self.namespace(perfil), CLAVE_DATOS, dict(datos))
        return datos

    def borrar(self, perfil: str) -> None:
        """Borra el documento del perfil, si existe."""
        if perfil:
            self.store.delete(self.namespace(perfil), CLAVE_DATOS)


def _nombre_valido(valor: str) -> str:
    """Valida un nombre capturado y descarta roles, lugares y conectores."""
    palabras = [palabra for palabra in re.split(r"\s+", valor.strip()) if palabra]
    if not 1 <= len(palabras) <= 4:
        return ""
    if any(normalizar(palabra).strip(".,;:") in EXCLUIDAS for palabra in palabras):
        return ""
    if not all(re.fullmatch(_TOKEN, palabra) for palabra in palabras):
        return ""
    return " ".join(palabras).strip(" .,;:")


def _empresa_valida(valor: str) -> str:
    """Limpia el nombre de la empresa y descarta frases sin letras."""
    limpio = " ".join(valor.split()).strip(" .,;:")
    limpio = re.sub(r"^(el|la|los|las)\s+", "", limpio, flags=re.IGNORECASE)
    if not limpio or len(limpio) > 80:
        return ""
    if not re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", limpio):
        return ""
    return limpio


def _es_pregunta(texto: str, inicio: int) -> bool:
    """Indica si la coincidencia cae dentro de una pregunta y no de una frase."""
    previo = texto[:inicio]
    ultimo_cierre = max(
        previo.rfind("."),
        previo.rfind("?"),
        previo.rfind("!"),
        previo.rfind("\n"),
    )
    return previo.rfind("¿") > ultimo_cierre


def _limpiar_resto(texto: str, spans: Iterable[tuple[int, int]]) -> str:
    """Quita del mensaje las frases de perfil y deja la pregunta residual."""
    partes: list[str] = []
    ultimo = 0
    for inicio, fin in sorted(set(spans)):
        partes.append(texto[ultimo:inicio])
        ultimo = max(ultimo, fin)
    partes.append(texto[ultimo:])
    resto = " ".join(partes)
    resto = re.sub(r"\s+", " ", resto).strip()
    resto = re.sub(r"^[\s,.;:]+", "", resto)
    resto = re.sub(r"^(?:y|e|o|u|pero|ademas|tambien)\b\s*", "", resto, flags=re.IGNORECASE)
    resto = re.sub(r"[\s,.;:]+$", "", resto)
    if not re.search(r"\w", resto):
        return ""
    return resto.strip()
