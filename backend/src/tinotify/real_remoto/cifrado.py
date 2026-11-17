"""Cifrado de las credenciales SIGAC guardadas (AES-256-GCM). La llave NO está en la base de datos.

La base solo guarda `nonce` y `cifrado` (texto cifrado + etiqueta de autenticación). Sin la llave del servicio, o con otra
llave, o con el texto alterado, el descifrado falla y no revela nada. Los datos asociados (AAD) ligan el texto cifrado a este uso.
"""

import json
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION_LLAVE = 1
AAD = b"tinotify-real|credenciales|v1"


class CifradoNoValido(ValueError):
    """No se pudo cifrar o descifrar (llave incorrecta, datos alterados o formato no reconocido). Sin detalles."""


def cifrar_credenciales(llave, usuario, clave, caso_login=None):
    if not isinstance(llave, (bytes, bytearray)) or len(llave) != 32:
        raise CifradoNoValido("llave")
    if not all(isinstance(v, str) and v for v in (usuario, clave)) or (caso_login is not None and not isinstance(caso_login, str)):
        raise CifradoNoValido("datos")
    nonce = os.urandom(12)
    claro = json.dumps({"usuario": usuario, "clave": clave, "caso_login": caso_login}, separators=(",", ":")).encode("utf-8")
    return nonce, AESGCM(bytes(llave)).encrypt(nonce, claro, AAD)


def descifrar_credenciales(llave, nonce, cifrado):
    if not isinstance(llave, (bytes, bytearray)) or len(llave) != 32:
        raise CifradoNoValido("llave")
    try:
        claro = AESGCM(bytes(llave)).decrypt(bytes(nonce), bytes(cifrado), AAD)
        datos = json.loads(claro.decode("utf-8"))
        usuario, clave, caso_login = datos["usuario"], datos["clave"], datos.get("caso_login")
        if not (isinstance(usuario, str) and usuario and isinstance(clave, str) and clave) or set(datos) - {"usuario", "clave", "caso_login"}:
            raise ValueError
    except (InvalidTag, ValueError, KeyError, TypeError, UnicodeError):
        raise CifradoNoValido("descifrado") from None
    return usuario, clave, caso_login
