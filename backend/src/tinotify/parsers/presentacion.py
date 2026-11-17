"""Presentación legible de la descripción de una actuación. Solo para mostrar: jamás altera la huella.

El parser guarda las descripciones con varias filas en una representación canónica (`TINOTIFY_FILAS_V1:{json}`)
que sí entra en la huella. Aquí se interpreta ESA representación, sin modificarla, para mostrar títulos y párrafos.
Un formato no reconocido no se oculta ni se vuelca crudo: se devuelve un aviso controlado y la marca de error.
"""

import json

from tinotify.parsers.parser import PREFIJO_FILAS

TITULO_SIMPLE = "Actuación"
TITULO_ERROR = "Contenido no interpretable"
TEXTO_ERROR = ("El formato de este contenido no se reconoce y no se puede mostrar. "
               "La referencia y la huella guardadas no se ven afectadas.")


class FormatoInesperado(ValueError):
    pass


def secciones(descripcion):
    """[(titulo, texto)] de una descripción canónica. Lanza FormatoInesperado si no coincide con el contrato."""
    if not isinstance(descripcion, str):
        raise FormatoInesperado("descripción no textual")
    if not descripcion.startswith(PREFIJO_FILAS):
        return [(TITULO_SIMPLE, descripcion)]  # descripción histórica simple
    try:
        contenido = json.loads(descripcion[len(PREFIJO_FILAS):])
    except ValueError:
        raise FormatoInesperado("JSON inválido") from None
    if (not isinstance(contenido, dict) or set(contenido) != {"filas", "parser_content_version"}
            or contenido["parser_content_version"] != 1 or not isinstance(contenido["filas"], list)
            or not contenido["filas"]):
        raise FormatoInesperado("estructura no reconocida")
    filas = []
    for fila in contenido["filas"]:
        if (not isinstance(fila, list) or len(fila) != 2 or not all(isinstance(x, str) for x in fila)
                or fila[0].startswith(PREFIJO_FILAS) or fila[1].startswith(PREFIJO_FILAS)):
            raise FormatoInesperado("fila no reconocida")
        filas.append((fila[0], fila[1]))
    return filas


def presentar(descripcion):
    """(secciones [{titulo, texto}], texto_legible, formato_inesperado)."""
    try:
        partes = secciones(descripcion)
        inesperado = False
    except FormatoInesperado:
        partes, inesperado = [(TITULO_ERROR, TEXTO_ERROR)], True
    if len(partes) == 1 and partes[0][0] == TITULO_SIMPLE:
        legible = partes[0][1]  # descripción simple: sin título redundante
    else:
        legible = "\n\n".join(f"{t}\n{x}" if x else t for t, x in partes)
    return [{"titulo": t, "texto": x} for t, x in partes], legible, inesperado


def vista_previa(partes, largo):
    """Texto de las secciones sin títulos, en una línea."""
    texto = " ".join(" ".join(p["texto"].split()) for p in partes if p["texto"].strip())
    return texto[:largo], len(texto) > largo
