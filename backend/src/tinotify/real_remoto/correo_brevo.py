"""Envío de correo transaccional con la API HTTPS de Brevo (el plan gratuito de Render bloquea el SMTP saliente).

Solo se usa para el código de recuperación de contraseña. Nunca registra destinatarios, textos ni la clave de la API.
"""

import logging
import re

import httpx

from tinotify.real_remoto import cuentas as c

URL_BREVO = "https://api.brevo.com/v3/smtp/email"
_CLAVE = re.compile(r"[A-Za-z0-9_.\-]{20,200}")
registro = logging.getLogger("tinotify.real_remoto")


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
        """True si Brevo aceptó el mensaje. Un fallo se registra solo como código HTTP o tipo de error."""
        cuerpo = {"sender": {"name": self._nombre, "email": self._remitente}, "to": [{"email": destino}], "subject": asunto,
                  "textContent": texto, "htmlContent": html}
        try:
            r = self._http.post(URL_BREVO, headers={"api-key": self._clave, "accept": "application/json"}, json=cuerpo)
        except httpx.HTTPError as error:
            registro.warning("correo_brevo_error tipo=%s", type(error).__name__)
            return False
        if r.status_code not in (200, 201):
            registro.warning("correo_brevo_http estado=%s", r.status_code)
            return False
        return True
