"""Servicio de cuentas: registro por invitación, acceso con código por correo, sesiones por dispositivo y administración.

No hay contraseñas de Tinotify: la persona demuestra que es dueña de su correo con un código de un solo uso. Eso verifica el correo (con
el que llegan los avisos) y evita que haya que recordar o recuperar una clave más. No conoce HTTP ni SQL: opera sobre un almacén
(PostgreSQL en producción, memoria en pruebas). Los errores son de catálogo cerrado y nunca incluyen correos ni tokens.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tinotify.real_remoto import cuentas as c
from tinotify.real_remoto.cifrado import CifradoNoValido, cifrar_correo, descifrar_correo
from tinotify.real_remoto.plantillas_correo import correo_codigo

DURACION_SESION = timedelta(days=30)
DURACION_INVITACION = timedelta(days=7)
DURACION_CODIGO_ACCESO = timedelta(minutes=15)
MAX_CODIGOS_HORA = 3


class RegistroNoValido(Exception):
    """Invitación inexistente, usada o vencida, código incorrecto o correo ya registrado (no se distingue a propósito)."""


class CodigoNoValido(Exception):
    """Código de acceso incorrecto, vencido, usado o con demasiados intentos (no se distingue a propósito)."""


class UsuarioNoEncontrado(Exception):
    pass


class AccionNoPermitida(Exception):
    """Una persona administradora no puede suspenderse, borrarse ni quitarse el rol a sí misma."""


class ConfirmacionIncorrecta(Exception):
    """Para borrar la cuenta hay que escribir el correo de la cuenta."""


@dataclass(frozen=True)
class Usuario:
    id: str
    es_admin: bool


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class ServicioCuentas:
    def __init__(self, almacen, llave: bytes, *, reloj=_ahora, llave_correo: bytes | None = None, correo=None):
        if len(llave) < 32:
            raise ValueError("llave_corta")
        self._a, self._llave, self._reloj = almacen, llave, reloj
        self._correo = correo  # cliente de correo (Brevo): envía los códigos; sin él nadie puede crear cuenta ni entrar con correo
        self._llave_correo = llave_correo  # con ella, el correo se guarda CIFRADO para poder enviar los avisos

    # --- administración de invitaciones --------------------------------------------------------------------------
    def crear_invitacion(self) -> str:
        codigo, hash_ = c.nueva_invitacion()
        self._a.crear_invitacion(hash_, self._reloj() + DURACION_INVITACION)
        return codigo

    # --- envío de códigos ----------------------------------------------------------------------------------------
    def _enviar_codigo(self, destino: str, codigo: str, motivo: str, vigencia: str) -> str:
        asunto, texto, html = correo_codigo(codigo, motivo, vigencia)
        return "enviado" if self._correo.enviar(destino, asunto, texto, html) is None else "fallo_envio"

    def solicitar_codigo_registro(self, correo: str, invitacion: str) -> str:
        """Primer paso de la cuenta nueva: manda al correo el código que lo verifica. Estados: `enviado`, `invitacion_invalida`,
        `ya_registrado`, `correo_invalido` o `fallo_envio`. No consume la invitación (eso ocurre al terminar el registro) ni guarda nada."""
        try:
            normalizado = c.normalizar_correo(correo)
        except c.DatosNoValidos:
            return "correo_invalido"
        ahora = self._reloj()
        if not self._a.invitacion_vigente(c.hash_invitacion(invitacion), ahora):
            return "invitacion_invalida"
        if self._a.usuario_por_correo_ref(c.correo_ref(self._llave, normalizado)) is not None:
            return "ya_registrado"
        if self._correo is None:
            return "fallo_envio"
        codigo = c.codigo_registro(self._llave, normalizado, invitacion, c.ventana_registro(ahora))
        return self._enviar_codigo(normalizado, codigo, "crear tu cuenta", "10 minutos")

    def solicitar_codigo_acceso(self, correo: str) -> str:
        """Manda un código de un solo uso para entrar. Estados: `enviado`, `no_registrado`, `limite` o `fallo_envio`. Es una beta cerrada: se
        prefiere decirle con claridad a quien escribe qué ocurrió (el tope global de solicitudes limita el uso malintencionado)."""
        try:
            normalizado = c.normalizar_correo(correo)
        except c.DatosNoValidos:
            return "no_registrado"
        fila = self._a.usuario_por_correo_ref(c.correo_ref(self._llave, normalizado))
        if fila is None or not fila["activo"]:
            return "no_registrado"
        if self._correo is None:
            return "fallo_envio"
        ahora = self._reloj()
        codigo = c.nuevo_codigo_acceso()
        if not self._a.crear_recuperacion(fila["id"], c.hash_codigo_acceso(fila["id"], codigo), ahora + DURACION_CODIGO_ACCESO, ahora, MAX_CODIGOS_HORA):
            return "limite"
        return self._enviar_codigo(normalizado, codigo, "entrar a tu cuenta", "15 minutos")

    def probar_correo(self):
        """Solo para el propietario: envía un correo de prueba al remitente. Devuelve (enviado, motivo)."""
        if self._correo is None:
            return False, "correo_no_configurado"
        motivo = self._correo.enviar_prueba()
        return motivo is None, motivo

    # --- registro y entrada --------------------------------------------------------------------------------------
    def registrar(self, correo: str, codigo: str, invitacion: str, consentimiento_version: str, dispositivo: str | None = None):
        """Segundo paso: con el código recibido por correo crea la cuenta (consume la invitación) y abre sesión.
        `c.DatosNoValidos` si el correo no tiene formato; `RegistroNoValido` en todo lo demás."""
        normalizado = c.normalizar_correo(correo)
        ahora = self._reloj()
        if not c.codigo_registro_valido(self._llave, normalizado, invitacion, codigo, ahora):
            raise RegistroNoValido
        cifrado = cifrar_correo(self._llave_correo, normalizado) if self._llave_correo else None
        usuario_id = self._a.registrar_usuario(
            c.hash_invitacion(invitacion), c.correo_ref(self._llave, normalizado), c.SIN_CLAVE,
            consentimiento_version, ahora, correo=cifrado)  # atómico: consume la invitación y crea la cuenta, o no hace nada
        return self._nueva_sesion(usuario_id, dispositivo, ahora), Usuario(usuario_id, False)

    def entrar(self, correo: str, codigo: str, dispositivo: str | None = None):
        """Entra con el código recibido por correo. Cierra el código (un solo uso) y abre una sesión en este dispositivo."""
        try:
            normalizado = c.normalizar_correo(correo)
        except c.DatosNoValidos:
            raise CodigoNoValido from None
        fila = self._a.usuario_por_correo_ref(c.correo_ref(self._llave, normalizado))
        if fila is None or not fila["activo"]:
            raise CodigoNoValido
        ahora = self._reloj()
        if not self._a.consumir_recuperacion(fila["id"], c.hash_codigo_acceso(fila["id"], codigo), ahora):
            raise CodigoNoValido
        return self._nueva_sesion(fila["id"], dispositivo, ahora), Usuario(fila["id"], fila["es_admin"])

    def _nueva_sesion(self, usuario_id: str, dispositivo: str | None, ahora: datetime) -> str:
        token, hash_ = c.nuevo_token()
        self._a.crear_sesion(usuario_id, hash_, (dispositivo or "")[:60] or None, ahora + DURACION_SESION)
        return token

    def correo_de(self, usuario_id: str) -> str | None:
        """Correo al que avisar a este usuario (descifrado solo para enviar el aviso); None si no hay o no se puede leer."""
        if not self._llave_correo:
            return None
        guardado = self._a.correo_cifrado_de(usuario_id)
        if guardado is None:
            return None
        try:
            return descifrar_correo(self._llave_correo, *guardado)
        except CifradoNoValido:
            return None

    # --- administración --------------------------------------------------------------------------------------------
    def listar_usuarios(self):
        """Para el panel de administración: correo (si se puede leer), estado y conteos. Nunca credenciales de SIGAC ni expedientes."""
        salida = []
        for u in self._a.listar_usuarios():
            correo = None
            if u["correo"] and self._llave_correo:
                try:
                    correo = descifrar_correo(self._llave_correo, *u["correo"])
                except CifradoNoValido:
                    correo = None
            salida.append({**{k: v for k, v in u.items() if k != "correo"}, "correo": correo})
        return salida

    def _existente(self, objetivo: str, quien: str | None, propia_permitida=False):
        if self._a.usuario_por_id(objetivo) is None:
            raise UsuarioNoEncontrado
        if quien is not None and quien == objetivo and not propia_permitida:
            raise AccionNoPermitida

    def fijar_activo(self, objetivo: str, activo: bool, quien: str | None) -> None:
        self._existente(objetivo, quien)
        self._a.fijar_activo(objetivo, activo)
        if not activo:
            self._a.revocar_todas(objetivo, self._reloj())  # una cuenta suspendida pierde todas sus sesiones

    def fijar_admin(self, objetivo: str, es_admin: bool, quien: str | None) -> None:
        self._existente(objetivo, quien)
        self._a.fijar_admin(objetivo, es_admin)

    def borrar_datos(self, objetivo: str, quien: str | None) -> None:
        """Quita las credenciales de SIGAC y todo el seguimiento de ese usuario; su cuenta sigue existiendo. Sobre uno mismo sí se permite."""
        self._existente(objetivo, quien, propia_permitida=True)
        self._a.borrar_datos_de(objetivo)

    def eliminar_usuario(self, objetivo: str, quien: str | None) -> None:
        self._existente(objetivo, quien)
        self._a.borrar_usuario(objetivo)

    # --- sesiones ---------------------------------------------------------------------------------------------------
    def autenticar(self, token: str | None) -> Usuario | None:
        if not token or not token.startswith("tn_") or len(token) > 200:
            return None
        fila = self._a.usuario_por_token(c.sha256_hex(token), self._reloj())
        return None if fila is None else Usuario(fila["id"], fila["es_admin"])

    def cerrar_sesion(self, token: str) -> None:
        self._a.revocar_sesion(c.sha256_hex(token), self._reloj())

    def cerrar_todas(self, usuario_id: str) -> None:
        self._a.revocar_todas(usuario_id, self._reloj())

    # --- cuenta --------------------------------------------------------------------------------------------------------
    def eliminar_cuenta(self, usuario_id: str, correo: str) -> None:
        """Borra la cuenta y todos sus datos. Para evitar un toque accidental hay que escribir el correo de la cuenta."""
        try:
            ref = c.correo_ref(self._llave, c.normalizar_correo(correo))
        except c.DatosNoValidos:
            raise ConfirmacionIncorrecta from None
        fila = self._a.usuario_por_correo_ref(ref)
        if fila is None or fila["id"] != usuario_id:
            raise ConfirmacionIncorrecta
        self._a.borrar_usuario(usuario_id)  # sesiones en cascada, igual que los datos del seguimiento
