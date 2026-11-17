"""Habilitación local y explícita del contrato de expediente acreditado.

El catálogo de código ya contiene el contrato, pero solo esta función arma una política que lo habilita, y
únicamente si existe la clave local de acreditación (archivo fuera del repositorio). Sin ella, o sin que el
número coincida con un compromiso del contrato, todo sigue cerrado. La clave no concede nada por sí sola.
"""

import json
from pathlib import Path

from tinotify.domain.identificadores import CATALOGO_PRODUCCION, CONTRATO_CASO_NRO_CONTINUIDAD, PoliticaConfianza
from tinotify.services.consulta_real_local import IdentidadExpedienteNoVerificada

RUTA_ACREDITACION = Path("backend/.local/acreditacion_sigac.json")
RUTA_V2_PREDETERMINADA = Path("backend/.local/real_v2.sqlite3")


def cargar_clave_acreditacion(ruta=None):
    """Bytes de la clave local de acreditación. Sin valores en los mensajes de error."""
    try:
        datos = json.loads(Path(ruta if ruta is not None else RUTA_ACREDITACION).read_text(encoding="utf-8"))
        clave = bytes.fromhex(datos["clave_hex"])
        if datos.get("version") != 1 or len(clave) < 16:
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise IdentidadExpedienteNoVerificada(
            "Persistencia SIGAC bloqueada: falta la clave local de acreditación del expediente") from None
    return clave


def politica_desde_clave(clave):
    return PoliticaConfianza(CATALOGO_PRODUCCION, expedientes_habilitados=(CONTRATO_CASO_NRO_CONTINUIDAD.referencia,),
                             clave_acreditacion=clave)


def politica_real_local(ruta=None):
    return politica_desde_clave(cargar_clave_acreditacion(ruta))
