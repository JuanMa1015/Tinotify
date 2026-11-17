"""Referencia portable y autenticada del único expediente acreditado, para el backend remoto.

Qué contiene (y nada más): versión, instancia, referencia del contrato de expediente, número de caso, un
identificador opaco derivado con clave, la generación y el conteo de eventos de la línea base, y una lista de huellas
CON CLAVE (HMAC) de las actuaciones, con su multiplicidad. No contiene `local_id`, fechas, remitentes, textos, anexos,
ni las `version_hash` originales. Todo el archivo lleva un MAC (HMAC-SHA256) con una subclave derivada de la clave de
acreditación; sin esa clave no se puede verificar ni fabricar, y las huellas con clave no se pueden reconstruir
desde el contenido ni cotejar con las de v2.

Se trata como secreto (Secret File): incluye el número de caso, que el servidor necesita para pedir el detalle.
La clave de acreditación es la misma que habilita el contrato de expediente (`politica_real_local`).
"""

import hashlib
import hmac
import json
from pathlib import Path
import re
from uuid import UUID

from tinotify.domain.identificadores import CONTRATO_CASO_NRO_CONTINUIDAD

VERSION = 1
TITULO = "Expediente local"
MAX_BYTES = 2_000_000
MAX_HUELLAS = 20000
_HEX64 = re.compile(r"[0-9a-f]{64}")
_CAMPOS = {"version", "instancia", "contrato", "numero", "caso_id", "generacion", "eventos_internos", "huellas", "mac"}


class ReferenciaPortableInvalida(ValueError):
    """Archivo ausente, alterado, de otro expediente o con formato no reconocido (mensajes sin valores)."""


def _sub(clave, rol):
    if not isinstance(clave, (bytes, bytearray)) or len(clave) < 16:
        raise ReferenciaPortableInvalida("Clave de acreditación no válida")
    return hmac.new(bytes(clave), b"tinotify/referencia-portable/v1/" + rol.encode(), hashlib.sha256).digest()


def huella_portable(clave, version_hash):
    """Huella con clave de la huella versionada del parser (`Actuacion.huella_version`)."""
    return hmac.new(_sub(clave, "huella"), version_hash.encode(), hashlib.sha256).hexdigest()


def id_caso_portable(clave, instancia, numero):
    """Identificador opaco (UUID v4-formato) que no permite recuperar el número sin la clave."""
    crudo = bytearray(hmac.new(_sub(clave, "caso"), f"{instancia}|{numero}".encode(), hashlib.sha256).digest()[:16])
    crudo[6] = (crudo[6] & 0x0F) | 0x40
    crudo[8] = (crudo[8] & 0x3F) | 0x80
    return str(UUID(bytes=bytes(crudo)))


def _mac(clave, cuerpo):
    canon = json.dumps(cuerpo, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hmac.new(_sub(clave, "mac"), canon, hashlib.sha256).hexdigest()


def construir(clave, *, instancia, numero, version_hashes, generacion, eventos_internos, contrato=None):
    """Documento firmado. `version_hashes` es la lista de `version_hash` de v2 (con repeticiones)."""
    if type(numero) is not int or numero < 1 or not version_hashes or len(version_hashes) > MAX_HUELLAS:
        raise ReferenciaPortableInvalida("Datos de referencia no válidos")
    if any(not isinstance(h, str) or not _HEX64.fullmatch(h) for h in version_hashes):
        raise ReferenciaPortableInvalida("Huellas no válidas")
    ref = (contrato or CONTRATO_CASO_NRO_CONTINUIDAD).referencia
    cuerpo = {
        "version": VERSION, "instancia": instancia,
        "contrato": {"clave": ref.clave, "version": ref.version, "revision": ref.revision},
        "numero": numero, "caso_id": id_caso_portable(clave, instancia, numero),
        "generacion": generacion, "eventos_internos": eventos_internos,
        "huellas": sorted(huella_portable(clave, h) for h in version_hashes),  # orden canónico: no revela el orden original
    }
    return {**cuerpo, "mac": _mac(clave, cuerpo)}


class ReferenciaPortable:
    """Referencia verificada. Implementa la interfaz usada por `leer_con_referencia`."""

    def __init__(self, clave, datos):
        self._clave = bytes(clave)
        self.instancia, self.numero, self.caso_id = datos["instancia"], datos["numero"], datos["caso_id"]
        self.generacion, self.eventos_internos = datos["generacion"], datos["eventos_internos"]
        self._huellas = tuple(datos["huellas"])

    def entradas(self):
        return [(None, h) for h in self._huellas]

    def multiconjunto(self):
        """Huellas con clave y su multiplicidad (semilla del monitor para el expediente acreditado)."""
        from collections import Counter
        return Counter(self._huellas)

    def huella(self, actuacion):
        return huella_portable(self._clave, actuacion.huella_version)

    def resumen_caso(self):
        """Datos de /real/cases, con la misma semántica que la consulta local."""
        return {"contrato_version": 1, "cobertura": "desconocida", "referencia": "ocurrencias_observadas",
                "entrega_externa": "no_autorizada", "id": self.caso_id, "titulo": TITULO,
                "generacion": self.generacion, "referencia_establecida": True,
                "ocurrencias_observadas": len(self._huellas), "eventos_internos": self.eventos_internos}


def verificar(clave, datos, *, instancia, contrato=None):
    """Valida estructura, MAC, contrato, identificador y huellas. Cualquier discrepancia rechaza todo el archivo."""
    try:
        if not isinstance(datos, dict) or set(datos) != _CAMPOS or datos["version"] != VERSION:
            raise ValueError
        esperado = _mac(clave, {k: v for k, v in datos.items() if k != "mac"})
        if not isinstance(datos["mac"], str) or not hmac.compare_digest(esperado, datos["mac"]):
            raise ValueError
        ref = (contrato or CONTRATO_CASO_NRO_CONTINUIDAD).referencia
        if datos["contrato"] != {"clave": ref.clave, "version": ref.version, "revision": ref.revision}:
            raise ValueError  # el contrato del código cambió: la referencia debe regenerarse y revisarse
        if datos["instancia"] != instancia or type(datos["numero"]) is not int or datos["numero"] < 1:
            raise ValueError
        if datos["caso_id"] != id_caso_portable(clave, instancia, datos["numero"]):
            raise ValueError
        if type(datos["generacion"]) is not int or datos["generacion"] < 1 or type(datos["eventos_internos"]) is not int \
                or datos["eventos_internos"] < 0:
            raise ValueError
        huellas = datos["huellas"]
        if (not isinstance(huellas, list) or not huellas or len(huellas) > MAX_HUELLAS
                or any(not isinstance(h, str) or not _HEX64.fullmatch(h) for h in huellas)):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ReferenciaPortableInvalida("La referencia portable no es válida para esta clave y contrato") from None
    return ReferenciaPortable(clave, datos)


def cargar(ruta, clave, *, instancia, contrato=None):
    try:
        ruta = Path(ruta)
        if not ruta.is_file() or ruta.stat().st_size > MAX_BYTES:
            raise ValueError
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ReferenciaPortableInvalida("La referencia portable no está disponible o no es legible") from None
    return verificar(clave, datos, instancia=instancia, contrato=contrato)
