"""Utilidades compartidas para observaciones exclusivamente sintéticas."""

import json
from datetime import datetime, timedelta

from tinotify.parsers.parser import PREFIJO_FILAS

CASO_OBSERVADO = "00000000-0000-4000-8000-0000000000c1"
TITULO_OBSERVADO = "Proceso sintético observado"
INSTANCIA = "demo-local"
INSTANCIA_REAL = "sigac-real"


class ObservacionRechazada(ValueError):
    """La observación no puede ser baseline ni novedad; el estado no cambió."""


def html_historial_sintetico(cantidad):
    """Historial HTML ficticio con `cantidad` actuaciones, en el formato que el parser ya reconoce."""
    if type(cantidad) is not int or not 1 <= cantidad <= 200:
        raise ValueError("Cantidad de actuaciones sintéticas no válida")
    base = datetime(2026, 2, 1, 9, 0, 0)
    bloques = []
    for n in range(cantidad):
        direccion = "ASESOR--&gt;ESTUDIANTE" if n % 2 else "ESTUDIANTE--&gt;ASESOR"
        bloques.append(
            '<tr><td colspan="2"><hr></td></tr>'
            f'<tr><td>TITULO SINTETICO {n + 1}</td><td>{direccion}</td></tr>'
            f'<tr><td>{(base + timedelta(hours=n)).strftime("%Y-%m-%d %H:%M:%S")}</td><td>REMITENTE SINTETICO</td></tr>'
            f'<tr><td>Actuación :</td><td>Actuación sintética número {n + 1}.</td></tr>')
    return '<html><body><form id="form1"><table>' + "".join(bloques) + "</table></form></body></html>"


def _texto_legible(descripcion):
    """El parser codifica varias filas como JSON con prefijo; se muestran como «Etiqueta: texto»."""
    if descripcion.startswith(PREFIJO_FILAS):
        try:
            filas = json.loads(descripcion[len(PREFIJO_FILAS):])["filas"]
            return "\n".join(f"{e}: {t}" if e else t for e, t in filas)
        except (ValueError, KeyError, TypeError):
            return descripcion
    return descripcion


def _contenido(a):
    return {"fecha": a.fecha.isoformat(), "titulo": a.etapa, "direccion": a.direccion, "remitente": a.remitente,
            "descripcion": _texto_legible(a.descripcion),
            "anexos": [{"descripcion": x.descripcion, "sin_enlace": x.sin_enlace} for x in a.anexos]}
