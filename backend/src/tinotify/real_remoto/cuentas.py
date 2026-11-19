"""Primitivas de cuentas de Tinotify: tokens de sesión, invitaciones y códigos de acceso. Puras: sin red ni base de datos.

No hay contraseñas de Tinotify: se entra con un código de un solo uso enviado al correo.
- Token de sesión e invitación: aleatorios; en la base solo se guarda su SHA-256 (si se filtra la base, no sirven).
- Código de acceso: de la cuenta, guardado solo como hash ligado al usuario. Código de registro: sin estado (HMAC con la llave del servidor).
- Correo: se normaliza y se busca por HMAC con la llave del servidor (el correo en claro no es la clave de búsqueda).
"""

import hashlib
import hmac
import re
import secrets

SIN_CLAVE = "scrypt$0$0$0$SIN$CLAVE"  # la columna pass_hash existe por historia; ya nada la verifica ni se puede entrar con ella
VENTANA_REGISTRO_S = 600
_CORREO = re.compile(r"[a-z0-9._%+\-]{1,64}@[a-z0-9\-]+(\.[a-z0-9\-]+)+")
_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sin caracteres ambiguos (0/O, 1/I/L)


class DatosNoValidos(ValueError):
    """El dato no cumple el formato; el mensaje no incluye el valor recibido."""


def normalizar_correo(correo: str) -> str:
    valor = correo.strip().lower()
    if len(valor) > 254 or _CORREO.fullmatch(valor) is None or ".." in valor:
        raise DatosNoValidos("correo_no_valido")
    return valor


def correo_ref(llave: bytes, correo_normalizado: str) -> str:
    return hmac.new(llave, b"cuenta-correo|" + correo_normalizado.encode(), hashlib.sha256).hexdigest()


def sha256_hex(valor: str) -> str:
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def nuevo_token() -> tuple[str, str]:
    """(token para el dispositivo, hash para la base). 256 bits de aleatoriedad."""
    token = "tn_" + secrets.token_urlsafe(32)
    return token, sha256_hex(token)


def nueva_invitacion() -> tuple[str, str]:
    """(código legible XXXX-XXXX-XXXX-XXXX, hash para la base). ~80 bits."""
    letras = "".join(secrets.choice(_ALFABETO) for _ in range(16))
    codigo = "-".join(letras[i:i + 4] for i in range(0, 16, 4))
    return codigo, sha256_hex(normalizar_invitacion(codigo))


def normalizar_invitacion(codigo: str) -> str:
    return re.sub(r"[\s\-]", "", codigo).upper()


def hash_invitacion(codigo: str) -> str:
    return sha256_hex(normalizar_invitacion(codigo))


def hashes_iguales(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


# --- código de acceso (cuentas que ya existen) ---
def _digitos(codigo: str) -> str:
    return re.sub(r"\D", "", codigo)


def nuevo_codigo_acceso() -> str:
    """Código de 6 dígitos (fácil de leer y de escribir en el teléfono). Vale 15 minutos, un solo uso y 5 intentos, y solo se pueden pedir 3 por hora."""
    return f"{secrets.randbelow(10 ** 6):06d}"


def hash_codigo_acceso(usuario_id: str, codigo: str) -> str:
    """Hash ligado al usuario: el mismo código no sirve para otra cuenta."""
    return sha256_hex(f"acceso|{usuario_id}|{_digitos(codigo)}")


# --- código de registro (cuenta nueva): sin estado, se recalcula ---
def ventana_registro(ahora) -> int:
    return int(ahora.timestamp()) // VENTANA_REGISTRO_S


def codigo_registro(llave: bytes, correo_normalizado: str, invitacion: str, ventana: int) -> str:
    """Código de 6 dígitos que solo conoce quien recibe el correo. Depende del correo y de la invitación (que el atacante no conoce), así que no sirve para otra."""
    mac = hmac.new(llave, f"registro|{correo_normalizado}|{normalizar_invitacion(invitacion)}|{ventana}".encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(mac[:8], 'big') % 10 ** 6:06d}"


def codigo_registro_valido(llave: bytes, correo_normalizado: str, invitacion: str, codigo: str, ahora) -> bool:
    """Vale el de la ventana actual y el de la anterior (entre 10 y 20 minutos)."""
    recibido = _digitos(codigo)
    actual = ventana_registro(ahora)
    return any(hmac.compare_digest(codigo_registro(llave, correo_normalizado, invitacion, v), recibido) for v in (actual, actual - 1))
