"""Envío de correo transaccional con la API HTTPS de Brevo (el plan gratuito de Render bloquea el SMTP saliente).

Solo se usa para el código de recuperación de contraseña. Nunca registra destinatarios, textos ni la clave de la API.
"""

import logging
import re

import httpx

from tinotify.real_remoto import cuentas as c
from tinotify.real_remoto.plantillas_correo import correo_prueba

URL_BREVO = "https://api.brevo.com/v3/smtp/email"
_CLAVE = re.compile(r"[A-Za-z0-9_.\-]{20,200}")
registro = logging.getLogger("tinotify.real_remoto")


def _codigo_de_error(respuesta):
    """`código: mensaje` del error de Brevo (p. ej. `unauthorized: ...unrecognised IP address...`), acotado. No lleva datos de nadie."""
    try:
        datos = respuesta.json()
        return f"{datos.get('code', '')}: {datos.get('message', '')}"[:200].strip(": ")
    except (ValueError, AttributeError):
        return ""


class CorreoNoValido(Exception):
    """Configuración de correo inválida (sin detalles: nunca incluye la clave)."""


def validar_clave_api(clave):
    if not isinstance(clave, str) or _CLAVE.fullmatch(clave) is None:
        raise CorreoNoValido("clave_brevo_no_valida")
    return clave


class ClienteBrevo:
    def __init__(self, clave, remitente, *, http=None, nombre="Tinotify"):
        self._clave = validar_clave_api(clave)
        try:
            self._remitente = c.normalizar_correo(remitente)
        except c.DatosNoValidos:
            raise CorreoNoValido("remitente_no_valido") from None
        self._nombre = nombre
        self._http = http or httpx.Client(timeout=15, follow_redirects=False, trust_env=False)

    def __repr__(self):
        return "ClienteBrevo()"

    def enviar(self, destino, asunto, texto, html):
        """None si Brevo aceptó el mensaje; si no, un motivo corto (`sin_conexion` o `http_<estado>:<código de Brevo>`). Nunca incluye el
        destinatario ni el contenido."""
        cuerpo = {"sender": {"name": self._nombre, "email": self._remitente}, "to": [{"email": destino}], "subject": asunto,
                  "textContent": texto, "htmlContent": html}
        try:
            r = self._http.post(URL_BREVO, headers={"api-key": self._clave, "accept": "application/json"}, json=cuerpo)
        except httpx.HTTPError as error:
            registro.warning("correo_brevo_error tipo=%s", type(error).__name__)
            return "sin_conexion"
        if r.status_code not in (200, 201):
            motivo = f"http_{r.status_code}:{_codigo_de_error(r)}"
            registro.warning("correo_brevo_rechazado motivo=%s", motivo)
            return motivo
        return None

    def enviar_prueba(self):
        """Un correo de prueba al propio remitente: sirve para comprobar la configuración. Mismo resultado que `enviar`."""
        return self.enviar(self._remitente, *correo_prueba())
