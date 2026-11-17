"""Historial DOM sin red: separadores del contenedor y extracción completa.

Los UUID y la confianza de origen pertenecen al reconciliador. Las referencias
de anexos son metadatos opacos, nunca identificadores estables de actuación.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup, CData, Comment, NavigableString, Tag

from tinotify.domain.actuaciones import Actuacion, Anexo, texto_canonico
from tinotify.parsers.diagnostico_historial import CLAVES_CONTEOS_BASE, CodigoHistorial, conteos_seguros


PREFIJO_FILAS = "TINOTIFY_FILAS_V1:"
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
_CATEGORIAS_CONOCIDAS = {
    "actuacion", "reparto", "creacion de cita", "relacion de los hechos",
}


class ErrorParseoHistorial(ValueError):
    """HTML histórico no interpretable; no devolver una extracción parcial."""

    def __init__(self, mensaje, *, codigo=CodigoHistorial.NO_CLASIFICADO):
        super().__init__(mensaje)
        self.codigo = codigo if isinstance(codigo, CodigoHistorial) else CodigoHistorial.NO_CLASIFICADO


@dataclass(frozen=True)
class _FilaContenido:
    etiqueta: str
    texto: str


def clean(node: Tag) -> str:
    # Los elementos inline no crean espacios dentro de una palabra.
    return re.sub(r"\s+", " ", node.get_text("", strip=False)).strip()


def _normalizar_etiqueta(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.rstrip(":").strip()).casefold()
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _celdas(fila: Tag) -> list[Tag]:
    return fila.find_all(["td", "th"], recursive=False)


def _filas_propias(tabla: Tag) -> list[Tag]:
    # tbody/thead no alteran pertenencia; tablas anidadas tienen otro dueño.
    return [fila for fila in tabla.find_all("tr") if fila.find_parent("table") is tabla]


def _es_separador(fila: Tag, tabla: Tag) -> bool:
    celdas = _celdas(fila)
    return (
        bool(celdas)
        and not clean(fila)
        and not fila.find(["input", "textarea", "select", "button"])
        and any(hr.find_parent("table") is tabla for hr in fila.find_all("hr"))
    )


def _fila_vacia(fila: Tag) -> bool:
    return not clean(fila) and not fila.find(["table", "a", "input", "textarea", "select", "button"])


def _bloques(tabla: Tag) -> tuple[list[Tag], list[list[Tag]]]:
    prefijo = []
    bloques = []
    actual = None
    for fila in _filas_propias(tabla):
        if _es_separador(fila, tabla):
            if actual:
                bloques.append(actual)
            actual = []
        elif actual is not None:
            # Las dos celdas vacías pueden ser el título opcional y se conservan.
            if not _fila_vacia(fila) or len(_celdas(fila)) == 2:
                actual.append(fila)
        else:
            prefijo.append(fila)
    if actual:
        bloques.append(actual)
    return prefijo, bloques


def _tiene_controles(bloque: list[Tag]) -> bool:
    return any(fila.find(["input", "textarea", "select", "button"]) for fila in bloque)


def _parece_historial(bloque: list[Tag]) -> bool:
    # Una fecha visible en la cabecera o categoría conocida permite reconocer
    # también un bloque roto. No consultar valores de controles de creación.
    for fila in bloque[:2]:
        celdas = _celdas(fila)
        if (
            celdas and not celdas[0].find("table")
            and re.match(r"^\d{4}-\d{2}-\d{2}", clean(celdas[0]))
        ):
            return True
    return any(
        len(celdas := _celdas(fila)) == 2
        and not celdas[0].find("table")
        and _normalizar_etiqueta(clean(celdas[0])) in _CATEGORIAS_CONOCIDAS
        for fila in bloque
    )


def _tiene_senales_historicas(filas: list[Tag]) -> bool:
    """Impide descartar una tabla ambigua como si fuera solo un formulario.

    Examina filas propias, sin valores/textos de controles ni tablas internas
    en la celda de etiqueta. Una fecha visible o contenido estático de una
    categoría conocida exige validación histórica; no demuestra una actuación.
    La copia solo decide la exclusión: nunca modifica contenido ni huellas.
    """
    for fila in filas:
        copia = deepcopy(fila)
        for control in copia.find_all(["input", "textarea", "select", "button"]):
            control.decompose()
        celdas = _celdas(copia)
        if not celdas or celdas[0].find("table"):
            continue
        etiqueta = clean(celdas[0])
        if re.match(r"^\d{4}-\d{2}-\d{2}", etiqueta):
            return True
        if (len(celdas) == 2 and _normalizar_etiqueta(etiqueta) in _CATEGORIAS_CONOCIDAS
                and clean(celdas[1])):
            return True
    return False


def _validar_tabla_omitida(tabla: Tag, conteos: dict) -> None:
    """No absorber historia reconocible como anexo o texto de una actuación.

    Solo decide RECHAZO: una coincidencia no acredita una nueva ocurrencia.
    Fechas citadas en valores, títulos o texto no bastan. Se conserva la
    gramática de cabecera de dos celdas y las categorías estáticas conocidas;
    con separadores propios también se detectan bloques históricos malformados.
    Los valores de controles nunca se usan como señales de historia.
    """
    senales = False
    for fila in _filas_propias(tabla):
        copia = deepcopy(fila)
        for control in copia.find_all(["input", "textarea", "select", "button"]):
            control.decompose()
        celdas = _celdas(copia)
        if len(celdas) != 2 or celdas[0].find("table"):
            continue
        etiqueta = clean(celdas[0])
        if (_FECHA.fullmatch(etiqueta)
                or (_normalizar_etiqueta(etiqueta) in _CATEGORIAS_CONOCIDAS and clean(celdas[1]))):
            senales = True
            break
    if not senales:
        _, bloques = _bloques(tabla)
        senales = any(_tiene_senales_historicas(bloque) for bloque in bloques)
    if senales:
        conteos["tablas_no_interpretadas"] += 1
        raise ErrorParseoHistorial(
            "Tabla excluida o anidada con señales históricas; ámbito ambiguo.",
            codigo=CodigoHistorial.AMBITO_NO_VERIFICADO,
        )


def _texto_contenido(celda: Tag) -> str:
    # Excluir anexos sin modificar el DOM original ni mezclar filas anidadas.
    copia = deepcopy(celda)
    for tabla in copia.find_all("table", id="tablaAnexos"):
        if tabla.parent is not None:
            tabla.decompose()
    partes = []
    elementos_de_bloque = {
        "p", "div", "li", "ul", "ol", "blockquote", "pre", "table", "tr", "td", "th",
        "section", "article", "h1", "h2", "h3", "h4", "h5", "h6",
    }

    def salto():
        # Agrupar límites estructurales consecutivos, sin truncar saltos que
        # estén realmente presentes en un nodo de texto.
        if partes and not partes[-1].endswith(("\n", "\r")):
            partes.append("\n")

    def visitar(nodo):
        if type(nodo) in (NavigableString, CData):
            if str(nodo).isspace() and nodo.find_parent("pre") is None:
                vecinos = (nodo.previous_sibling, nodo.next_sibling)
                if any(
                    isinstance(vecino, Tag)
                    and vecino.name in elementos_de_bloque | {"br", "hr"}
                    for vecino in vecinos
                ):
                    return  # Sangría de maquetación entre límites de bloque.
            partes.append(str(nodo))
        elif isinstance(nodo, Tag):
            if nodo.name in {"script", "style", "template"}:
                return
            if nodo.name in {"br", "hr"}:
                salto()
                return
            if nodo.name in elementos_de_bloque:
                salto()
            for hijo in nodo.children:
                visitar(hijo)
            if nodo.name in elementos_de_bloque:
                salto()

    for hijo in copia.children:
        visitar(hijo)
    return texto_canonico("".join(partes)).strip()


def _descripcion(filas: list[_FilaContenido]) -> str:
    if (
        len(filas) == 1
        and filas[0].etiqueta == "Actuación"
        and not filas[0].texto.startswith(PREFIJO_FILAS)
    ):
        # Compatibilidad exacta con las descripciones históricas simples.
        return filas[0].texto
    # El prefijo está reservado. Un texto legacy que empieza así también se
    # encapsula, para que no colisione con la representación de varias filas.
    contenido = {
        "parser_content_version": 1,
        "filas": [[texto_canonico(fila.etiqueta), texto_canonico(fila.texto)] for fila in filas],
    }
    return PREFIJO_FILAS + json.dumps(
        contenido, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _referencia_anexo(href: str) -> str:
    href = href.strip()
    if any(ord(c) < 32 or ord(c) == 127 for c in href):
        raise ErrorParseoHistorial("Referencia de anexo no admitida.", codigo=CodigoHistorial.ANEXO_REFERENCIA_INVALIDA)
    if re.search(r"%(?![0-9A-Fa-f]{2})", href):
        raise ErrorParseoHistorial("Referencia de anexo no admitida.", codigo=CodigoHistorial.ANEXO_REFERENCIA_INVALIDA)
    try:
        partes = urlsplit(href)
        query = parse_qsl(
            partes.query, keep_blank_values=True, strict_parsing=True,
            max_num_fields=2, encoding="utf-8", errors="strict",
        )
    except (ValueError, UnicodeError):
        raise ErrorParseoHistorial("Referencia de anexo no admitida.", codigo=CodigoHistorial.ANEXO_REFERENCIA_INVALIDA) from None
    if (
        partes.scheme or partes.netloc or "#" in href
        or partes.path != "general.descargarAnexo.con"
        or len(query) != 1 or query[0][0] != "codigo"
        or not query[0][1].strip()
        or any(ord(c) < 32 or ord(c) == 127 for c in query[0][1])
    ):
        raise ErrorParseoHistorial("Referencia de anexo no admitida.", codigo=CodigoHistorial.ANEXO_REFERENCIA_INVALIDA)
    return href


def _indicadores_enlace_ausente(celdas: list[Tag], tabla: Tag) -> dict[str, int]:
    """Cantidades estructurales de la fila rechazada; no devuelve contenido DOM."""
    primera, segunda = celdas
    enlaces_segunda = segunda.find_all("a", href=True)
    return {
        "anexo_ausente_celdas_th": sum(celda.name == "th" for celda in celdas),
        "anexo_ausente_celda1_con_texto": int(bool(clean(primera))),
        "anexo_ausente_celda2_con_texto": int(bool(clean(segunda))),
        "anexo_ausente_a_sin_href_celda2": len(segunda.find_all("a", href=False)),
        "anexo_ausente_a_href_celda1": len(primera.find_all("a", href=True)),
        "anexo_ausente_a_href_anidado_celda2": sum(
            enlace.find_parent("table") is not tabla for enlace in enlaces_segunda),
        "anexo_ausente_imagenes_celda2": len(segunda.find_all("img")),
        "anexo_ausente_onclick_celda2": len(segunda.find_all(attrs={"onclick": True})),
    }


class _FinPrimerToken(Exception):
    pass


class _PrimeraEtiqueta(HTMLParser):
    """Tokeniza con la misma biblioteca que BeautifulSoup; solo conserva el primer inicio."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nombre = None
        self.autocerrada = None

    def handle_starttag(self, tag, attrs):
        self.nombre, self.autocerrada = tag, False
        raise _FinPrimerToken

    def handle_startendtag(self, tag, attrs):
        self.nombre, self.autocerrada = tag, True
        raise _FinPrimerToken


_TRAMOS_ETIQUETA = (512, 8192, 131072)


def _celda_autocerrada(html: str | None, celda: Tag) -> int | None:
    """1/0 si la etiqueta de apertura original de la celda es/no es `<x/>`; None si no se verifica.

    La posición la registró html.parser al construir este mismo nodo (línea contada solo
    por '\\n', columna en caracteres). Se comprueba que en ese desplazamiento haya un '<' y
    que el primer token sea una etiqueta con el mismo nombre; si algo falla, se omite el dato.
    Solo se tokeniza un tramo acotado desde ese punto, sin copiar el documento completo.
    """
    linea, columna = getattr(celda, "sourceline", None), getattr(celda, "sourcepos", None)
    if (
        not isinstance(html, str) or type(linea) is not int or type(columna) is not int
        or linea < 1 or columna < 0
    ):
        return None
    desplazamiento = 0
    for _ in range(linea - 1):
        salto = html.find("\n", desplazamiento)
        if salto < 0:
            return None
        desplazamiento = salto + 1
    desplazamiento += columna
    if desplazamiento >= len(html) or html[desplazamiento] != "<":
        return None
    for tramo in _TRAMOS_ETIQUETA:
        analizador = _PrimeraEtiqueta()
        try:
            analizador.feed(html[desplazamiento:desplazamiento + tramo])
        except _FinPrimerToken:
            pass
        if analizador.nombre is not None:
            return int(analizador.autocerrada) if analizador.nombre == celda.name else None
        if desplazamiento + tramo >= len(html):
            break
    return None


def _nodos_no_vacios(celda: Tag) -> int:
    return sum(
        1 for nodo in celda.children
        if isinstance(nodo, Tag) or str(nodo).strip(" \t\n\r\f")
    )


def _tabla_en_fila_anexos(fila: Tag, tabla: Tag) -> int:
    """1 si la tabla está en la segunda celda de la fila «Anexos» de su propio bloque, 0 si no."""
    if tabla.find_parent("tr") is not fila:  # colgada de otra fila o de una tabla interna
        return 0
    celdas = _celdas(fila)
    if len(celdas) != 2 or tabla.find_parent(["td", "th"]) is not celdas[1]:
        return 0
    return int(_normalizar_etiqueta(clean(celdas[0])) == "anexos")


def _filas_forma_cabecera(tabla: Tag) -> int:
    """Filas propias con la forma que el parser usa para la cabecera de una actuación.

    Dos celdas, fecha completa en la primera y texto sin enlace en la segunda. Es solo una
    coincidencia de forma: no demuestra que la fila pertenezca a otra actuación.
    """
    total = 0
    for fila in _filas_propias(tabla):
        celdas = _celdas(fila)
        if (
            len(celdas) == 2 and _FECHA.fullmatch(clean(celdas[0]))
            and clean(celdas[1]) and not celdas[1].find("a", href=True)
        ):
            total += 1
    return total


def _filas_equivalentes_otras_tablas(tabla: Tag, primera: Tag) -> int | None:
    """Filas `td`/`td` con la segunda celda sin nodos y el mismo texto normalizado en la primera.

    Se busca en las demás `tablaAnexos` del mismo árbol ya construido (sin reparsear).
    La comparación es solo en memoria; únicamente se devuelve el conteo.
    """
    objetivo = _normalizar_etiqueta(clean(primera))
    raiz = tabla
    while raiz.parent is not None:
        raiz = raiz.parent
    if not objetivo or not isinstance(raiz, BeautifulSoup):
        return None
    total = 0
    for otra in raiz.find_all("table", id="tablaAnexos"):
        if otra is tabla:
            continue
        for fila in _filas_propias(otra):
            celdas = _celdas(fila)
            if (
                len(celdas) == 2 and celdas[0].name == "td" and celdas[1].name == "td"
                and not _nodos_no_vacios(celdas[1])
                and _normalizar_etiqueta(clean(celdas[0])) == objetivo
            ):
                total += 1
    return total


def _indicadores_contexto_enlace_ausente(fila: Tag, tabla: Tag, celdas: list[Tag]) -> dict[str, int]:
    """Tres enteros de contexto; cada uno se omite si no puede determinarse."""
    medidas = (
        ("anexo_ausente_tabla_en_fila_anexos", lambda: _tabla_en_fila_anexos(fila, tabla)),
        ("anexo_ausente_filas_forma_cabecera", lambda: _filas_forma_cabecera(tabla)),
        ("anexo_ausente_filas_equivalentes_otras_tablas",
         lambda: _filas_equivalentes_otras_tablas(tabla, celdas[0])),
    )
    indicadores = {}
    for clave, medir in medidas:
        try:
            valor = medir()
        except Exception:  # una medición fallida se omite; nunca se sustituye por 0
            continue
        if type(valor) is int and valor >= 0:
            indicadores[clave] = valor
    return indicadores


def _indicadores_posicion_enlace_ausente(
    fila: Tag, celdas: list[Tag], html: str | None,
) -> dict[str, int]:
    """Cuatro enteros que separan `<td/>`, enlace fuera de celda, contenido no visible y celda vacía."""
    segunda = celdas[1]
    fuera = 0
    for enlace in fila.find_all("a", href=True):
        for ancestro in enlace.parents:
            if ancestro is fila:
                fuera += 1
                break
            if ancestro.name in ("td", "th", "tr", "table"):
                break  # pertenece a una celda, a otra fila o a una tabla interna
    indicadores = {
        "anexo_ausente_a_fuera_de_celdas": fuera,
        "anexo_ausente_celda2_no_visibles": (
            len(segunda.find_all(["script", "style"]))
            + len(segunda.find_all(string=lambda s: isinstance(s, Comment)))
        ),
        "anexo_ausente_celda2_hijos": _nodos_no_vacios(segunda),
    }
    autocerrada = _celda_autocerrada(html, segunda)
    if autocerrada is not None:  # desconocido no se sustituye por 0
        indicadores["anexo_ausente_celda2_autocerrada"] = autocerrada
    return indicadores


def _es_anexo_sin_enlace(
    fila: Tag, tabla: Tag, fila_anexo: Tag, celdas: list[Tag], html: str | None,
) -> bool:
    """Condiciones estrictas 1-6 para admitir una fila descriptiva sin enlace.

    La condición 7 (la tabla tiene además un anexo con enlace válido) se comprueba en
    `_anexos()` al terminar la tabla. Ante cualquier duda, devuelve False (se rechaza).
    """
    try:
        if len(celdas) != 2 or any(celda.name != "td" for celda in celdas):  # 2
            return False
        if _tabla_en_fila_anexos(fila, tabla) != 1:  # 1
            return False
        descripcion = clean(celdas[0])
        if not descripcion or _FECHA.fullmatch(descripcion):  # 3
            return False
        if _nodos_no_vacios(celdas[1]) != 0:  # 4: sin texto, br, nbsp, imagen, script, comentario...
            return False
        if _celda_autocerrada(html, celdas[1]) != 0:  # 5: sin verificar o `<td/>` => rechazo
            return False
        return fila_anexo.find("a", href=True) is None  # 6
    except Exception:  # un fallo inesperado nunca admite una fila
        return False


def _registrar_indicadores_enlace_ausente(
    conteos: dict | None, fila: Tag, tabla: Tag, fila_anexo: Tag, celdas: list[Tag], html: str | None,
) -> None:
    if conteos is None:
        return
    conteos.update(_indicadores_enlace_ausente(celdas, tabla))
    try:
        conteos.update(_indicadores_posicion_enlace_ausente(fila_anexo, celdas, html))
    except Exception:  # el diagnóstico nunca cambia el código de rechazo
        pass
    try:
        conteos.update(_indicadores_contexto_enlace_ausente(fila, tabla, celdas))
    except Exception:
        pass


def _anexos(bloque: list[Tag], conteos: dict | None = None, html: str | None = None) -> tuple[Anexo, ...]:
    anexos = []
    for fila in bloque:
        for tabla in fila.find_all("table", id="tablaAnexos"):
            if tabla.find_parent("table", id="tablaAnexos") is not None:
                raise ErrorParseoHistorial("Tablas de anexos anidadas no interpretables.", codigo=CodigoHistorial.ANEXOS_ANIDADOS)
            con_enlace = 0
            primera_sin_enlace = None
            for fila_anexo in _filas_propias(tabla):
                celdas = _celdas(fila_anexo)
                if celdas and all(celda.name == "th" for celda in celdas):
                    continue
                if not clean(fila_anexo) and not fila_anexo.find("a", href=True):
                    continue
                if len(celdas) != 2:
                    raise ErrorParseoHistorial("Fila de anexo no interpretable.", codigo=CodigoHistorial.ANEXO_FILA_INVALIDA)
                enlaces = [
                    enlace for enlace in celdas[1].find_all("a", href=True)
                    if enlace.find_parent("table") is tabla
                ]
                if not enlaces and _es_anexo_sin_enlace(fila, tabla, fila_anexo, celdas, html):
                    # Se conserva como anexo; nunca se ignora. La condición 7 se evalúa al cerrar la tabla.
                    anexos.append(Anexo(clean(celdas[0]), "", "", sin_enlace=True))
                    if primera_sin_enlace is None:
                        primera_sin_enlace = (fila_anexo, celdas)
                    continue
                if not enlaces:
                    _registrar_indicadores_enlace_ausente(conteos, fila, tabla, fila_anexo, celdas, html)
                if len(enlaces) != 1:
                    raise ErrorParseoHistorial("Fila de anexo no interpretable.", codigo=(
                        CodigoHistorial.ANEXO_ENLACE_AUSENTE if not enlaces
                        else CodigoHistorial.ANEXO_ENLACES_MULTIPLES))
                enlace = enlaces[0]
                anexos.append(Anexo(
                    clean(celdas[0]), clean(enlace),
                    _referencia_anexo(enlace["href"]),
                ))
                con_enlace += 1
            if primera_sin_enlace is not None and con_enlace == 0:  # condición 7
                fila_anexo, celdas = primera_sin_enlace
                _registrar_indicadores_enlace_ausente(conteos, fila, tabla, fila_anexo, celdas, html)
                raise ErrorParseoHistorial("Fila de anexo no interpretable.", codigo=CodigoHistorial.ANEXO_ENLACE_AUSENTE)
    return tuple(anexos)


def _parsear_bloque(
    bloque: list[Tag], caso_id: str, conteos: dict | None = None, html: str | None = None,
) -> Actuacion:
    if _tiene_controles(bloque):
        # Si hay historial válido en esta misma tabla, no omitir un bloque
        # mezclado con formulario: rechazar la extracción completa.
        raise ErrorParseoHistorial("Historial mezclado con controles de formulario.", codigo=CodigoHistorial.BLOQUE_CON_CONTROLES)
    posicion_fecha = None
    for indice, fila in enumerate(bloque[:2]):
        celdas = _celdas(fila)
        if len(celdas) == 2 and _FECHA.fullmatch(clean(celdas[0])):
            posicion_fecha = indice
            break
    if posicion_fecha is None:
        raise ErrorParseoHistorial("Cabecera histórica no interpretable.", codigo=CodigoHistorial.CABECERA_INVALIDA)
    fecha_celdas = _celdas(bloque[posicion_fecha])
    if any(celda.find("table") for celda in fecha_celdas):
        raise ErrorParseoHistorial("Cabecera histórica no interpretable.", codigo=CodigoHistorial.CABECERA_INVALIDA)
    try:
        fecha = datetime.strptime(clean(fecha_celdas[0]), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise ErrorParseoHistorial("Fecha histórica no válida.", codigo=CodigoHistorial.FECHA_INVALIDA) from None
    responsable = clean(fecha_celdas[1])
    if not responsable:
        raise ErrorParseoHistorial("Responsable histórico ausente.", codigo=CodigoHistorial.RESPONSABLE_AUSENTE)

    titulo = comunicacion = ""
    if posicion_fecha == 1:
        cabecera = _celdas(bloque[0])
        if len(cabecera) != 2 or any(celda.find("table") for celda in cabecera):
            raise ErrorParseoHistorial("Título histórico no interpretable.", codigo=CodigoHistorial.TITULO_INVALIDO)
        titulo, comunicacion = map(clean, cabecera)
    origen = destino = ""
    if comunicacion:
        partes = comunicacion.split("-->")
        if len(partes) != 2 or not all(parte.strip() for parte in partes):
            raise ErrorParseoHistorial("Comunicación histórica no interpretable.", codigo=CodigoHistorial.COMUNICACION_INVALIDA)
        origen, destino = (parte.strip().upper() for parte in partes)

    filas = []
    for fila in bloque[posicion_fecha + 1:]:
        celdas = _celdas(fila)
        if not celdas and not clean(fila):
            continue
        if len(celdas) != 2 or any(celda.name != "td" for celda in celdas):
            raise ErrorParseoHistorial("Fila histórica no interpretable.", codigo=CodigoHistorial.FILA_INVALIDA)
        if celdas[0].find("table"):
            raise ErrorParseoHistorial("Etiqueta histórica no interpretable.", codigo=CodigoHistorial.ETIQUETA_INVALIDA)
        if _FECHA.fullmatch(clean(celdas[0])):
            raise ErrorParseoHistorial("Cabecera histórica sin separador de bloque.", codigo=CodigoHistorial.SEPARADOR_AUSENTE)
        etiqueta = clean(celdas[0]).rstrip(":").strip()
        normalizada = _normalizar_etiqueta(etiqueta)
        texto = _texto_contenido(celdas[1])
        if normalizada == "anexos":
            if texto:
                raise ErrorParseoHistorial("Fila de anexos no interpretable.", codigo=CodigoHistorial.ANEXOS_CONTENIDO_INVALIDO)
            continue
        if not etiqueta and not texto:
            continue
        if normalizada == "actuacion":
            etiqueta = "Actuación"
        filas.append(_FilaContenido(etiqueta, texto))
    if not filas:
        raise ErrorParseoHistorial("Bloque histórico sin filas de contenido.", codigo=CodigoHistorial.SIN_CONTENIDO)
    anexos = _anexos(bloque, conteos, html)
    descripcion = _descripcion(filas)
    signature = "\x1f".join((
        caso_id, fecha.isoformat(), origen, destino, responsable, descripcion,
    ))
    # Título conserva la ubicación legacy 'etapa'; no demuestra estado procesal.
    return Actuacion(
        titulo, origen, destino, fecha, responsable, descripcion,
        sha256(signature.encode()).hexdigest(), anexos,
    )


_CONTROLES = ["input", "textarea", "select", "button"]
_ENVOLTURAS_REGION = {"tr", "td", "table", "tbody"}
_PANEL_PESTANAS = re.compile(r"tabs-\d+")


def _es_envio(control: Tag) -> bool:
    return control.name == "button" or (
        control.name == "input" and str(control.get("type") or "").strip().lower() in {"submit", "button", "image"}
    )


def _es_ancestro(ancestro: Tag, nodo: Tag) -> bool:
    return any(padre is ancestro for padre in nodo.parents)


def _tabla_anexos_sin_datos_historicos(tabla_anexos: Tag) -> bool:
    """True solo si la tabla no puede contener anexos históricos.

    Dentro de la región interactiva el formulario reutiliza `tablaAnexos`. Se acepta únicamente
    si no hay ningún `<a>` (los anexos históricos se descargan por enlace), ninguna tabla
    interna y toda fila propia es una cabecera `th`, una fila vacía o una fila con controles.
    Cualquier otra fila (texto de datos sin controles, incluida una descripción sin enlace) es
    ambigua y mantiene el rechazo. No prueba a quién pertenece la tabla: prueba que excluirla
    no descarta ningún anexo reconocible.
    """
    if tabla_anexos.find("a") is not None or tabla_anexos.find("table") is not None:
        return False
    for fila in _filas_propias(tabla_anexos):
        celdas = _celdas(fila)
        if (celdas and all(celda.name == "th" for celda in celdas)) or _fila_vacia(fila) or _tiene_controles([fila]):
            continue
        return False
    return True


def _region_interactiva(raiz: BeautifulSoup, tabla: Tag, filas: list[Tag]) -> Tag | None:
    """Fila de la tabla que contiene, aislada, la región interactiva `div#tabs` de SIGAC.

    Devuelve None ante cualquier duda (se conserva el rechazo por controles). No basta el
    identificador: se exige unicidad, una fila exclusiva, paneles y controles de formulario
    dentro, todos los controles de la tabla dentro, ausencia de gramática de actuación y
    posición final. No depende de ningún `<form>`.
    """
    candidatas = raiz.find_all(id="tabs")
    if len(candidatas) != 1 or candidatas[0].name != "div" or not _es_ancestro(tabla, candidatas[0]):
        return None
    region = candidatas[0]
    dentro = {id(nodo) for nodo in region.descendants}
    fila = region.find_parent("tr")
    while fila is not None and fila.find_parent("table") is not tabla:
        fila = fila.find_parent("tr")
    indice = next((i for i, candidata in enumerate(filas) if candidata is fila), None)
    if indice is None:
        return None
    celdas = _celdas(fila)
    if len(celdas) != 1 or celdas[0].name != "td":  # fila exclusiva: una sola celda
        return None
    for nodo in fila.descendants:  # fuera de la región solo contenedores sin texto
        if nodo is region or id(nodo) in dentro:
            continue
        if isinstance(nodo, Tag):
            if nodo.name not in _ENVOLTURAS_REGION:
                return None
        elif str(nodo).strip(" \t\n\r\f"):
            return None
    controles = tabla.find_all(_CONTROLES)
    if not controles or any(id(control) not in dentro for control in controles):
        return None
    interiores = region.find_all(_CONTROLES)
    if not any(c.name == "textarea" for c in interiores) or not any(_es_envio(c) for c in interiores):
        return None
    if not any(panel.name == "div" and _PANEL_PESTANAS.fullmatch(str(panel.get("id") or "")) for panel in region.find_all("div")):
        return None
    if not all(_tabla_anexos_sin_datos_historicos(t) for t in region.find_all("table", id="tablaAnexos")):
        return None
    for interna in region.find_all("tr"):  # sin cabecera de actuación
        interna_celdas = _celdas(interna)
        if len(interna_celdas) == 2 and _FECHA.fullmatch(clean(interna_celdas[0])):
            return None
    for posterior in filas[indice + 1:]:  # nada de historial después
        if _es_ancestro(fila, posterior) or id(posterior) in dentro:
            continue
        if not (_fila_vacia(posterior) or _es_separador(posterior, tabla)):
            return None
    if indice > 0:  # la fila previa cierra la actuación (Anexos) o es un separador/vacía
        previa = filas[indice - 1]
        if _es_ancestro(previa, fila) or not (
            _es_separador(previa, tabla) or _fila_vacia(previa) or previa.find("table", id="tablaAnexos")
        ):
            return None
    return fila


def _cabeceras_historicas(tabla: Tag) -> int:
    """Filas propias de la tabla con la misma forma que `_parsear_bloque` reconoce como cabecera.

    Dos celdas y fecha completa en la primera. Las tablas internas tienen otro dueño y no cuentan.
    Es un indicio de forma: una fila con esa forma que no produzca actuación se rechaza, no se ignora.
    """
    total = 0
    for fila in _filas_propias(tabla):
        celdas = _celdas(fila)
        if len(celdas) == 2 and _FECHA.fullmatch(clean(celdas[0])):
            total += 1
    return total


def _diagnostico_region_interactiva(
    raiz: BeautifulSoup, tabla: Tag, filas: list[Tag], prefijo: list[Tag], bloques: list[list[Tag]],
) -> dict[str, int]:
    """Resultado independiente de cada criterio de `_region_interactiva`; solo enteros.

    Solo lectura: no altera el árbol ni decide nada. Un valor que no puede determinarse se omite.
    Tipos de fila previa: 0 no hay, 1 separador, 2 vacía, 3 con tablaAnexos, 4 otra, 5 ancestro.
    """
    d: dict[str, int] = {}
    controles = tabla.find_all(_CONTROLES)
    en_bloques = {id(nodo) for bloque in bloques for fila in bloque for nodo in fila.descendants}
    en_prefijo = {id(nodo) for fila in prefijo for nodo in fila.descendants}
    candidatas = raiz.find_all(id="tabs")
    d["region_ids_tabs"] = len(candidatas)
    if len(candidatas) != 1:
        fuera, dentro_ids = controles, set()
    else:
        region = candidatas[0]
        dentro_ids = {id(nodo) for nodo in region.descendants}
        fuera = [c for c in controles if id(c) not in dentro_ids]
        d["region_es_div"] = int(region.name == "div")
        d["region_dentro_de_tabla"] = int(_es_ancestro(tabla, region))
        interiores = region.find_all(_CONTROLES)
        d["region_controles_dentro"] = len(interiores)
        d["region_textareas"] = sum(c.name == "textarea" for c in interiores)
        d["region_envios"] = sum(_es_envio(c) for c in interiores)
        d["region_paneles"] = sum(
            1 for p in region.find_all("div") if _PANEL_PESTANAS.fullmatch(str(p.get("id") or "")))
        d["region_tablas_anexos_dentro"] = len(region.find_all("table", id="tablaAnexos"))
        d["region_filas_fecha_dentro"] = sum(
            1 for r in region.find_all("tr")
            if len(_celdas(r)) == 2 and _FECHA.fullmatch(clean(_celdas(r)[0])))
    d["region_controles_fuera_en_prefijo"] = sum(id(c) in en_prefijo for c in fuera)
    d["region_controles_fuera_en_actuaciones"] = sum(id(c) in en_bloques and id(c) not in en_prefijo for c in fuera)
    d["region_controles_fuera_otros"] = len(fuera) - d["region_controles_fuera_en_prefijo"] \
        - d["region_controles_fuera_en_actuaciones"]
    d["region_c1_ok"] = int(len(candidatas) == 1 and d["region_es_div"] == 1 and d["region_dentro_de_tabla"] == 1) \
        if len(candidatas) == 1 else 0
    if len(candidatas) != 1:
        return d
    d["region_c3_ok"] = int(
        bool(controles) and not fuera and d["region_textareas"] >= 1 and d["region_envios"] >= 1
        and d["region_paneles"] >= 1)
    d["region_c4_ok"] = int(
        d["region_filas_fecha_dentro"] == 0
        and all(_tabla_anexos_sin_datos_historicos(t) for t in region.find_all("table", id="tablaAnexos")))
    fila = region.find_parent("tr")
    while fila is not None and fila.find_parent("table") is not tabla:
        fila = fila.find_parent("tr")
    indice = next((i for i, candidata in enumerate(filas) if candidata is fila), None)
    if indice is None:
        return d
    celdas = _celdas(fila)
    d["region_celdas_fila"] = len(celdas)
    ajenos = texto = 0
    for nodo in fila.descendants:
        if nodo is region or id(nodo) in dentro_ids:
            continue
        if isinstance(nodo, Tag):
            ajenos += nodo.name not in _ENVOLTURAS_REGION
        elif str(nodo).strip(" \t\n\r\f"):
            texto = 1
    d["region_elementos_ajenos_fila"], d["region_texto_ajeno_fila"] = ajenos, texto
    d["region_c2_ok"] = int(len(celdas) == 1 and celdas[0].name == "td" and ajenos == 0 and texto == 0)
    d["region_filas_posteriores_no_vacias"] = sum(
        1 for posterior in filas[indice + 1:]
        if not (_es_ancestro(fila, posterior) or id(posterior) in dentro_ids)
        and not (_fila_vacia(posterior) or _es_separador(posterior, tabla)))
    d["region_c5_ok"] = int(d["region_filas_posteriores_no_vacias"] == 0)
    if indice == 0:
        tipo = 0
    else:
        previa = filas[indice - 1]
        tipo = (5 if _es_ancestro(previa, fila) else 1 if _es_separador(previa, tabla)
                else 2 if _fila_vacia(previa) else 3 if previa.find("table", id="tablaAnexos") else 4)
    d["region_fila_previa_tipo"] = tipo
    d["region_c6_ok"] = int(tipo in (0, 1, 2, 3))
    d["region_bloques_con_controles_tras_quitar_fila"] = sum(
        1 for bloque in bloques if _tiene_controles([f for f in bloque if f is not fila]))
    d["region_c7_ok"] = int(d["region_bloques_con_controles_tras_quitar_fila"] == 0)
    return d


def _es_envoltura(tabla: Tag) -> bool:
    if not tabla.find("table"):
        return False
    for fila in _filas_propias(tabla):
        copia = deepcopy(fila)
        for interna in copia.find_all("table"):
            if interna.parent is not None:
                interna.decompose()
        if clean(copia) or copia.find(["input", "textarea", "select", "button", "hr", "a"]):
            return False
    return True


def _conteos_documento(soup):
    return {"tablas_documento": len(soup.find_all("table")),
            "filas_documento": len(soup.find_all("tr")),
            "separadores_documento": len(soup.find_all("hr"))}


def estadisticas_documento(html):
    """Solo cantidades DOM para errores anteriores a la extracción histórica."""
    return _conteos_documento(BeautifulSoup(html, "html.parser"))


def _parse_actuaciones(
    html: str, caso_id: str, *, contenedor_id, conteos,
) -> list[Actuacion]:
    """Extraer el ámbito histórico completo o fallar, nunca seleccionar por éxito.

    Sin contenedor_id, el llamador declara que el fragmento contiene todo el
    historial. Para páginas con tablas ajenas debe proporcionar el ID exacto
    de su contenedor completo, respaldado por el contrato del adaptador.
    No se presupone ningún ID específico de SIGAC ni se hace fallback heurístico.
    """
    soup = BeautifulSoup(html, "html.parser")
    conteos.update(_conteos_documento(soup))
    ambito = soup
    if contenedor_id is not None:
        if not isinstance(contenedor_id, str) or not contenedor_id.strip():
            raise ErrorParseoHistorial("Contenedor histórico no válido.", codigo=CodigoHistorial.CONTENEDOR_INVALIDO)
        coincidencias = soup.find_all(id=contenedor_id)
        conteos["contenedores_coincidentes"] = len(coincidencias)
        if len(coincidencias) != 1:
            raise ErrorParseoHistorial("Contenedor histórico ausente o no único.", codigo=(
                CodigoHistorial.CONTENEDOR_AUSENTE if not coincidencias
                else CodigoHistorial.CONTENEDOR_DUPLICADO))
        ambito = coincidencias[0]
        if ambito.get("id") == "tablaAnexos" or ambito.find_parent("table", id="tablaAnexos"):
            raise ErrorParseoHistorial("Una tabla de anexos no es el contenedor histórico.", codigo=CodigoHistorial.CONTENEDOR_ANEXOS)
    tablas = ([ambito] if ambito.name == "table" else []) + ambito.find_all("table")
    conteos["tablas_ambito"] = len(tablas)
    conteos["filas_ambito"] = len(ambito.find_all("tr"))
    conteos["separadores_ambito"] = len(ambito.find_all("hr"))
    conteos["enlaces_ambito"] = len(ambito.find_all("a", href=True))
    conteos["tablas_anexos_ambito"] = sum(tabla.get("id") == "tablaAnexos" for tabla in tablas)
    if contenedor_id is not None and not tablas:
        raise ErrorParseoHistorial("Contenedor histórico sin tablas.", codigo=CodigoHistorial.CONTENEDOR_SIN_TABLAS)
    resultado = []
    contenedores = set()
    anexos_validados = set()
    no_interpretadas = []
    for tabla in tablas:
        if tabla.get("id") == "tablaAnexos" or tabla.find_parent("table", id="tablaAnexos"):
            if id(tabla) not in anexos_validados:
                _validar_tabla_omitida(tabla, conteos)
            continue
        if any(id(ancestro) in contenedores for ancestro in tabla.find_parents("table")):
            _validar_tabla_omitida(tabla, conteos)
            conteos["tablas_internas_omitidas"] += 1
            continue
        if _es_envoltura(tabla):
            conteos["tablas_envoltura"] += 1
            continue
        prefijo, bloques = _bloques(tabla)
        es_formulario = tabla.find_parent("form") is not None or tabla.find("form") is not None
        controles_propios = any(
            control.find_parent("table") is tabla
            for control in tabla.find_all(["input", "textarea", "select", "button"])
        )
        if contenedor_id is None and es_formulario and controles_propios and (
            (bloques and all(_tiene_controles(bloque) for bloque in bloques))
            or (not bloques and _tiene_controles(prefijo))
        ) and not _tiene_senales_historicas(_filas_propias(tabla)):
            # Solo excluir formularios sin señales históricas visibles. Una
            # mezcla ambigua pasa a las validaciones, nunca se descarta aquí.
            conteos["tablas_formulario_excluidas"] += 1
            continue
        if not bloques:
            if any(not _fila_vacia(fila) for fila in prefijo) or clean(tabla):
                no_interpretadas.append(tabla)
                conteos["tablas_no_interpretadas"] += 1
            continue
        conteos["tablas_con_bloques"] += 1
        conteos["bloques_detectados"] += len(bloques)
        if contenedor_id is None and any(_tiene_controles(bloque) for bloque in bloques):
            interactiva = _region_interactiva(soup, tabla, _filas_propias(tabla))
            if interactiva is not None:
                restantes = []
                for bloque in bloques:
                    conservadas = [fila for fila in bloque if fila is not interactiva]
                    if len(conservadas) == len(bloque) or conservadas:
                        restantes.append(conservadas)
                    # un bloque que solo contenía la región se retira completo (y se cuenta aparte)
                if not any(_tiene_controles(bloque) for bloque in restantes):
                    bloques = restantes
                    conteos["regiones_interactivas_excluidas"] += 1
                    conteos["filas_interactivas_excluidas"] += 1
        # Conservar el diagnóstico previo de cabeceras discordantes cuando
        # una cabecera completa del prefijo ya permite detectar la omisión.
        # Si está malformada, esa guarda no basta: rechazar por las señales
        # estáticas del prefijo incluso cuando también contiene controles.
        cabecera_en_prefijo = any(
            len(celdas := _celdas(fila)) == 2 and _FECHA.fullmatch(clean(celdas[0]))
            for fila in prefijo
        )
        if prefijo and (
            (not _tiene_controles(prefijo) and _parece_historial(prefijo))
            or (_tiene_senales_historicas(prefijo) and not cabecera_en_prefijo)
        ):
            raise ErrorParseoHistorial("Historial anterior al primer separador.", codigo=CodigoHistorial.ANTES_DEL_SEPARADOR)
        contenedores.add(id(tabla))
        extraidas_antes = len(resultado)
        for bloque in bloques:
            # Separadores finales y espaciadores vacíos no son actuaciones.
            if all(_fila_vacia(fila) for fila in bloque):
                conteos["bloques_vacios"] += 1
                continue
            try:
                resultado.append(_parsear_bloque(bloque, caso_id, conteos, html))
                # Acreditación por parseo efectivo de metadatos en la fila de
                # anexos, no por el id CSS. La tabla puede contener una fecha
                # como descripción legítima sin ser una actuación adicional.
                for fila in bloque:
                    celdas = _celdas(fila)
                    if len(celdas) == 2 and _normalizar_etiqueta(clean(celdas[0])) == "anexos":
                        anexos_validados.update(id(t) for t in celdas[1].find_all("table", id="tablaAnexos"))
            except ErrorParseoHistorial as error:
                conteos["bloques_rechazados"] += 1
                if (
                    error.codigo is CodigoHistorial.BLOQUE_CON_CONTROLES and contenedor_id is None
                    and conteos["regiones_interactivas_excluidas"] == 0
                ):
                    try:  # solo diagnóstico: nunca cambia el código ni la decisión
                        conteos.update(_diagnostico_region_interactiva(
                            soup, tabla, _filas_propias(tabla), prefijo, bloques))
                    except Exception:
                        pass
                raise
            conteos["bloques_validos"] += 1
        # Conservación: cada fila de cabecera reconocible de esta tabla debe haber producido una actuación.
        # Las exclusiones legítimas (formulario, región interactiva) ya se aplicaron a `bloques`.
        extraidas = len(resultado) - extraidas_antes
        cabeceras = _cabeceras_historicas(tabla)
        if cabeceras != extraidas:
            conteos["cabeceras_historicas_tabla"], conteos["actuaciones_extraidas_tabla"] = cabeceras, extraidas
            raise ErrorParseoHistorial(
                "Hay cabeceras históricas que no produjeron actuación; no se devuelve un historial parcial.",
                codigo=CodigoHistorial.CABECERAS_DISCORDANTES,
            )
    if no_interpretadas and (resultado or contenedor_id is not None):
        raise ErrorParseoHistorial("No se pudo verificar el ámbito histórico completo; delimita su contenedor.", codigo=CodigoHistorial.AMBITO_NO_VERIFICADO)
    return resultado


def parse_actuaciones(
    html: str, caso_id: str, *, contenedor_id: str | None = None, estadisticas: dict | None = None,
) -> list[Actuacion]:
    """Mismo parser y rechazos; opcionalmente copia solo conteos estructurales.

    Las estadísticas no son actuaciones recuperables ni una prueba de completitud.
    Algunos conteos reflejan solo el recorrido hasta el primer fallo.
    """
    conteos = {clave: 0 for clave in CLAVES_CONTEOS_BASE}
    try:
        return _parse_actuaciones(html, caso_id, contenedor_id=contenedor_id, conteos=conteos)
    finally:
        if estadisticas is not None:
            estadisticas.clear()
            estadisticas.update(conteos_seguros(conteos))
