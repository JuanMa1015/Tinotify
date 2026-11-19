"""Primitivas de cuentas de Tinotify: contraseñas, tokens de sesión e invitaciones. Puras: sin red ni base de datos.

- Contraseña: scrypt de la biblioteca estándar, sal única por usuario, comparación en tiempo constante.
- Token de sesión e invitación: aleatorios; en la base solo se guarda su SHA-256 (si se filtra la base, no sirven).
- Correo: se normaliza y se busca por HMAC con la llave del servidor (el correo en claro no es la clave de búsqueda).
"""

import base64
import hashlib
import hmac
import re
import secrets

N_SCRYPT, R_SCRYPT, P_SCRYPT = 2**15, 8, 1
MAXMEM = 64 * 1024 * 1024
LARGO_SAL = 16
MIN_CLAVE, MAX_CLAVE = 10, 128
_CORREO = re.compile(r"[a-z0-9._%+\-]{1,64}@[a-z0-9\-]+(\.[a-z0-9\-]+)+")
_ALFABETO_INVITACION = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sin caracteres ambiguos (0/O, 1/I/L)


class DatosNoValidos(ValueError):
    """El dato no cumple el formato; el mensaje no incluye el valor recibido."""


def normalizar_correo(correo: str) -> str:
    valor = correo.strip().lower()
    if len(valor) > 254 or _CORREO.fullmatch(valor) is None or ".." in valor:
        raise DatosNoValidos("correo_no_valido")
    return valor


def validar_clave(clave: str, correo: str | None = None) -> None:
    if not MIN_CLAVE <= len(clave) <= MAX_CLAVE:
        raise DatosNoValidos("clave_longitud")
    if correo is not None and clave.strip().lower() == correo.strip().lower():
        raise DatosNoValidos("clave_igual_al_correo")
    if len(set(clave)) < 4:
        raise DatosNoValidos("clave_muy_simple")


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


def _scrypt(clave: str, sal: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(clave.encode("utf-8"), salt=sal, n=n, r=r, p=p, maxmem=MAXMEM, dklen=32)


def hash_clave(clave: str, *, n: int = N_SCRYPT) -> str:
    """Formato: scrypt$N$r$p$sal$hash (los parámetros viajan en el valor, así se pueden subir sin romper cuentas viejas)."""
    sal = secrets.token_bytes(LARGO_SAL)
    return f"scrypt${n}${R_SCRYPT}${P_SCRYPT}${_b64(sal)}${_b64(_scrypt(clave, sal, n, R_SCRYPT, P_SCRYPT))}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        esquema, n, r, p, sal, esperado = guardado.split("$")
        if esquema != "scrypt":
            return False
        obtenido = _scrypt(clave, base64.b64decode(sal), int(n), int(r), int(p))
        return hmac.compare_digest(obtenido, base64.b64decode(esperado))
    except (ValueError, TypeError):
        return False


_FALSO = hash_clave("clave-falsa-para-igualar-tiempos", n=N_SCRYPT)


def verificar_clave_inexistente(clave: str) -> bool:
    """Gasta el mismo tiempo que una verificación real cuando el usuario no existe (no revela si el correo está registrado)."""
    verificar_clave(clave, _FALSO)
    return False


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
    letras = "".join(secrets.choice(_ALFABETO_INVITACION) for _ in range(16))
    codigo = "-".join(letras[i:i + 4] for i in range(0, 16, 4))
    return codigo, sha256_hex(normalizar_invitacion(codigo))


def normalizar_invitacion(codigo: str) -> str:
    return re.sub(r"[\s\-]", "", codigo).upper()


def hash_invitacion(codigo: str) -> str:
    return sha256_hex(normalizar_invitacion(codigo))


def nuevo_codigo_recuperacion() -> str:
    """Código legible XXXX-XXXX (8 caracteres sin ambiguos, ~40 bits). Vale 15 minutos, un solo uso y 5 intentos."""
    letras = "".join(secrets.choice(_ALFABETO_INVITACION) for _ in range(8))
    return f"{letras[:4]}-{letras[4:]}"


def hash_recuperacion(usuario_id: str, codigo: str) -> str:
    """Hash ligado al usuario: el mismo código no sirve para otra cuenta."""
    return sha256_hex(f"recuperacion|{usuario_id}|{normalizar_invitacion(codigo)}")


def hashes_iguales(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
