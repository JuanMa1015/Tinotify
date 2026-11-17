"""Servicio de cuentas: registro por invitación, login, sesiones por dispositivo y borrado de cuenta.

No conoce HTTP ni SQL: opera sobre un almacén (PostgreSQL en producción, memoria en pruebas). Los errores son de catálogo cerrado y
nunca incluyen correos, contraseñas ni tokens; los fallos de login son idénticos exista o no el correo.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tinotify.real_remoto import cuentas as c

DURACION_SESION = timedelta(days=30)
DURACION_INVITACION = timedelta(days=7)
MAX_FALLOS, BLOQUEO = 5, timedelta(minutes=15)


class RegistroNoValido(Exception):
    """Invitación inexistente, usada o vencida, o correo ya registrado (no se distingue a propósito)."""


class CredencialesIncorrectas(Exception):
    pass


class CuentaBloqueada(Exception):
    def __init__(self, espera_s: int):
        super().__init__("cuenta_bloqueada")
        self.espera_s = espera_s


@dataclass(frozen=True)
class Usuario:
    id: str
    es_admin: bool


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class ServicioCuentas:
    def __init__(self, almacen, llave: bytes, *, reloj=_ahora, n_scrypt: int = c.N_SCRYPT):
        if len(llave) < 32:
            raise ValueError("llave_corta")
        self._a, self._llave, self._reloj, self._n = almacen, llave, reloj, n_scrypt

    # --- administración ------------------------------------------------------------------------------------------
    def crear_invitacion(self) -> str:
        codigo, hash_ = c.nueva_invitacion()
        self._a.crear_invitacion(hash_, self._reloj() + DURACION_INVITACION)
        return codigo

    # --- registro y login ----------------------------------------------------------------------------------------
    def registrar(self, correo: str, clave: str, invitacion: str, consentimiento_version: str, dispositivo: str | None = None):
        """Devuelve (token, usuario). `c.DatosNoValidos` si el formato es incorrecto; `RegistroNoValido` en lo demás."""
        correo = c.normalizar_correo(correo)
        c.validar_clave(clave, correo)
        ahora = self._reloj()
        usuario_id = self._a.registrar_usuario(
            c.hash_invitacion(invitacion), c.correo_ref(self._llave, correo), c.hash_clave(clave, n=self._n),
            consentimiento_version, ahora)  # atómico: consume la invitación y crea la cuenta, o no hace nada
        return self._nueva_sesion(usuario_id, dispositivo, ahora), Usuario(usuario_id, False)

    def iniciar_sesion(self, correo: str, clave: str, dispositivo: str | None = None):
        ahora = self._reloj()
        try:
            ref = c.correo_ref(self._llave, c.normalizar_correo(correo))
        except c.DatosNoValidos:
            c.verificar_clave_inexistente(clave)
            raise CredencialesIncorrectas from None
        fila = self._a.usuario_por_correo_ref(ref)
        if fila is None or not fila["activo"]:
            c.verificar_clave_inexistente(clave)
            raise CredencialesIncorrectas
        if fila["bloqueado_hasta"] and fila["bloqueado_hasta"] > ahora:
            raise CuentaBloqueada(int((fila["bloqueado_hasta"] - ahora).total_seconds()) + 1)
        if not c.verificar_clave(clave, fila["pass_hash"]):
            fallos = fila["intentos_fallidos"] + 1
            self._a.registrar_fallo(fila["id"], fallos, ahora + BLOQUEO if fallos >= MAX_FALLOS else None)
            raise CredencialesIncorrectas
        self._a.limpiar_fallos(fila["id"])
        return self._nueva_sesion(fila["id"], dispositivo, ahora), Usuario(fila["id"], fila["es_admin"])

    def _nueva_sesion(self, usuario_id: str, dispositivo: str | None, ahora: datetime) -> str:
        token, hash_ = c.nuevo_token()
        self._a.crear_sesion(usuario_id, hash_, (dispositivo or "")[:60] or None, ahora + DURACION_SESION)
        return token

    # --- sesiones ------------------------------------------------------------------------------------------------
    def autenticar(self, token: str | None) -> Usuario | None:
        if not token or not token.startswith("tn_") or len(token) > 200:
            return None
        fila = self._a.usuario_por_token(c.sha256_hex(token), self._reloj())
        return None if fila is None else Usuario(fila["id"], fila["es_admin"])

    def cerrar_sesion(self, token: str) -> None:
        self._a.revocar_sesion(c.sha256_hex(token), self._reloj())

    def cerrar_todas(self, usuario_id: str) -> None:
        self._a.revocar_todas(usuario_id, self._reloj())

    # --- cuenta --------------------------------------------------------------------------------------------------
    def _confirmar_clave(self, usuario_id: str, clave: str) -> None:
        fila = self._a.usuario_por_id(usuario_id)
        if fila is None or not c.verificar_clave(clave, fila["pass_hash"]):
            raise CredencialesIncorrectas

    def cambiar_clave(self, usuario_id: str, actual: str, nueva: str, token_actual: str) -> None:
        self._confirmar_clave(usuario_id, actual)
        c.validar_clave(nueva)
        self._a.cambiar_pass(usuario_id, c.hash_clave(nueva, n=self._n))
        self._a.revocar_todas_menos(usuario_id, c.sha256_hex(token_actual), self._reloj())  # el resto de dispositivos pierde acceso

    def eliminar_cuenta(self, usuario_id: str, clave: str) -> None:
        self._confirmar_clave(usuario_id, clave)
        self._a.borrar_usuario(usuario_id)  # sesiones en cascada; los datos por usuario se borran en la fase 2
