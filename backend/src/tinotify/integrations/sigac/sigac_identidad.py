"""Consistencia del detalle HTTP observado, NO identidad institucional independiente.

No delimita historial mediante clases inventadas: valida el formulario y deja
la separación de sus tablas/bloques al parser genérico, con todos sus rechazos.
"""

from html.parser import HTMLParser
import re

from tinotify.integrations.sigac.sigac_respuestas import documento_completo
from tinotify.parsers.diagnostico_historial import CodigoHistorial
from tinotify.parsers.parser import ErrorParseoHistorial, parse_actuaciones


class ErrorIdentidadRespuesta(ValueError):
    def __init__(self, *, fuera=False):
        super().__init__("Consistencia o delimitación del detalle no confirmada.")
        self.codigo = (CodigoHistorial.HISTORIAL_FUERA_DETALLE if fuera
                       else CodigoHistorial.IDENTIDAD_DETALLE_NO_CONFIRMADA)


class _FormulariosExplicitos(HTMLParser):
    """No atribuir historial a un form por reparación de cierres o anidamiento."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.abierto = False
        self.invalido = False

    def handle_starttag(self, tag, attrs):
        if tag == "form":
            self.invalido |= self.abierto
            self.abierto = True
        relevantes = {"id", "name", "action", "method", "enctype", "type", "value", "form", "class"}
        nombres = [k for k, _ in attrs if k in relevantes]
        if len(nombres) != len(set(nombres)):
            self.invalido = True

    def handle_startendtag(self, tag, attrs):
        if tag == "form":
            self.invalido = True
        else:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "form":
            self.invalido |= not self.abierto
            self.abierto = False


def _clases(nodo, requeridas):
    return nodo.name == "div" and requeridas <= set(nodo.get("class", []))


def _fuera_de_controles(nodo):
    return nodo.find_parent(["form", "input", "select", "textarea", "button", "script", "style", "template", "noscript"]) is None


def validar_detalle(html, numero):
    """Devuelve SOLO el formulario validado, sin escribir ni hacer solicitudes.

    Números ASCII positivos canónicos: no se eliminan ceros iniciales ni signos.
    Cualquier estructura no interpretable conserva el rechazo del parser.
    """
    if type(numero) is not int or numero <= 0:
        raise ErrorIdentidadRespuesta()
    estructura = _FormulariosExplicitos()
    estructura.feed(html)
    estructura.close()
    if estructura.abierto or estructura.invalido:
        raise ErrorIdentidadRespuesta()
    soup = documento_completo(html)
    por_id, por_nombre = soup.find_all(id="form1"), soup.find_all("form", attrs={"name": "form1"})
    if len(por_id) != 1 or len(por_nombre) != 1 or por_id[0] is not por_nombre[0]:
        raise ErrorIdentidadRespuesta()
    formulario = por_id[0]
    if (formulario.name != "form" or not _fuera_de_controles(formulario)
            or formulario.find("form") is not None
            or formulario.get("action") != "casos.guardarCaso.con"
            or formulario.get("method", "").lower() != "post"
            or formulario.get("enctype", "").lower() != "multipart/form-data"
            or formulario.find_parent("table", id="tablaAnexos") is not None):
        raise ErrorIdentidadRespuesta()
    # Unicidad global del atributo conocido evita elegir una copia conveniente.
    campos = soup.find_all(lambda n: n.get("id") == "hidCaso" or n.get("name") == "hidCaso")
    if len(campos) != 1:
        raise ErrorIdentidadRespuesta()
    campo = campos[0]
    if (campo.name != "input" or campo.get("name") != "hidCaso" or campo.get("id") != "hidCaso"
            or campo.get("type", "").lower() != "hidden" or campo.has_attr("form")
            or campo.find_parent("form") is not formulario
            or campo.find_parent(["template", "script", "style", "noscript", "button", "textarea", "select"])
            or campo.find_parent("table", id="tablaAnexos") is not None
            or campo.has_attr("disabled")):
        raise ErrorIdentidadRespuesta()
    orden = {id(n): i for i, n in enumerate(soup.descendants)}
    candidatos = []
    for contenedor in formulario.find_parents("div"):
        if not _clases(contenedor, {"ui-widget-content", "ui-corner-all"}):
            continue
        cabeceras = [n for n in contenedor.find_all("div")
                     if _clases(n, {"ui-state-default", "ui-corner-all"})
                     and _fuera_de_controles(n) and n.find("form") is None
                     and re.sub(r"\s+", " ", n.get_text()).strip().startswith("Información del caso Nro.")]
        if cabeceras:
            candidatos.append((contenedor, cabeceras))
    if len(candidatos) != 1 or len(candidatos[0][1]) != 1:
        raise ErrorIdentidadRespuesta()
    cabecera = candidatos[0][1][0]
    if orden[id(cabecera)] >= orden[id(formulario)] or cabecera.find_parent("table", id="tablaAnexos"):
        raise ErrorIdentidadRespuesta()
    texto = re.sub(r"\s+", " ", cabecera.get_text()).strip()
    coincidencia = re.fullmatch(r"Información del caso Nro\.\s*([1-9][0-9]*)\s*-\s*(\S.*)", texto)
    esperado = str(numero)
    if (coincidencia is None or coincidencia.group(1) != esperado
            or campo.get("value") != esperado):
        raise ErrorIdentidadRespuesta()
    detalle = str(formulario)
    formulario.decompose()
    # Usar la gramática existente, no una nueva heurística de tablas/separadores.
    # Un historial fuera, o una región externa ambigua, nunca queda oculto por el recorte.
    try:
        externas = parse_actuaciones(str(soup), esperado)
    except ErrorParseoHistorial:
        raise ErrorIdentidadRespuesta(fuera=True) from None
    if externas:
        raise ErrorIdentidadRespuesta(fuera=True)
    return detalle
