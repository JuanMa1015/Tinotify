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


def _aad_expediente(caso_ref):
    return b"tinotify-real|expediente|v1|" + caso_ref.encode("ascii")


def cifrar_expediente(llave, caso_ref, numero, cliente, estado):
    """Datos del listado de SIGAC de un expediente, cifrados y ligados a su `caso_ref` (no se pueden mover a otra fila)."""
    if not isinstance(llave, (bytes, bytearray)) or len(llave) != 32 or not isinstance(caso_ref, str) or not caso_ref.isascii():
        raise CifradoNoValido("llave")
    if not isinstance(numero, int) or not isinstance(cliente, str) or not isinstance(estado, str):
        raise CifradoNoValido("datos")
    nonce = os.urandom(12)
    claro = json.dumps({"numero": numero, "cliente": cliente[:300], "estado": estado[:100]}, separators=(",", ":")).encode("utf-8")
    return nonce, AESGCM(bytes(llave)).encrypt(nonce, claro, _aad_expediente(caso_ref))


def descifrar_expediente(llave, caso_ref, nonce, cifrado):
    if not isinstance(llave, (bytes, bytearray)) or len(llave) != 32:
        raise CifradoNoValido("llave")
    try:
        datos = json.loads(AESGCM(bytes(llave)).decrypt(bytes(nonce), bytes(cifrado), _aad_expediente(caso_ref)).decode("utf-8"))
        numero, cliente, estado = datos["numero"], datos["cliente"], datos["estado"]
        if not (isinstance(numero, int) and isinstance(cliente, str) and isinstance(estado, str)) or set(datos) - {"numero", "cliente", "estado"}:
            raise ValueError
    except (InvalidTag, ValueError, KeyError, TypeError, UnicodeError):
        raise CifradoNoValido("descifrado") from None
    return numero, cliente, estado


AAD_CORREO = b"tinotify-real|correo|v1"


def cifrar_correo(llave, correo):
    """Correo de aviso del usuario, cifrado (AES-256-GCM). La base solo guarda nonce y texto cifrado."""
    if not isinstance(llave, (bytes, bytearray)) or len(llave) != 32 or not isinstance(correo, str) or not 3 <= len(correo) <= 254:
        raise CifradoNoValido("datos")
    nonce = os.urandom(12)
    return nonce, AESGCM(bytes(llave)).encrypt(nonce, correo.encode("utf-8"), AAD_CORREO)


def descifrar_correo(llave, nonce, cifrado):
    if not isinstance(llave, (bytes, bytearray)) or len(llave) != 32:
        raise CifradoNoValido("llave")
    try:
        return AESGCM(bytes(llave)).decrypt(bytes(nonce), bytes(cifrado), AAD_CORREO).decode("utf-8")
    except (InvalidTag, ValueError, TypeError, UnicodeError):
        raise CifradoNoValido("descifrado") from None
