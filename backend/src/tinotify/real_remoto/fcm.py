"""Envío de notificaciones push por Firebase Cloud Messaging (API HTTP v1) con una cuenta de servicio.

Sin dependencias nuevas: el JWT RS256 se firma con `cryptography` y las llamadas van con `httpx`. El mensaje es genérico y nunca
lleva datos del caso. Los errores y el registro no incluyen tokens de dispositivo, claves ni cuerpos de respuesta.
"""

import base64
import json
from pathlib import Path
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

ALCANCE = "https://www.googleapis.com/auth/firebase.messaging"
URL_TOKEN = "https://oauth2.googleapis.com/token"
VIGENCIA_S = 3600
OK, TOKEN_INVALIDO, ERROR = "ok", "token_invalido", "error"


class CuentaServicioNoValida(Exception):
    """El archivo no es una cuenta de servicio utilizable (el mensaje nunca incluye su contenido)."""


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).rstrip(b"=").decode("ascii")


class ClienteFcm:
    def __init__(self, ruta, *, transporte=None, reloj=time.time):
        try:
            datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
            self._correo, self._proyecto = datos["client_email"], datos["project_id"]
            self._llave = serialization.load_pem_private_key(datos["private_key"].encode("ascii"), password=None)
            uri = datos.get("token_uri", URL_TOKEN)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise CuentaServicioNoValida from None
        if datos.get("type") != "service_account" or uri != URL_TOKEN or not str(self._correo).endswith(".iam.gserviceaccount.com"):
            raise CuentaServicioNoValida
        self._http = httpx.Client(transport=transporte, timeout=15, follow_redirects=False, trust_env=False)
        self._reloj, self._acceso, self._expira = reloj, None, 0.0

    def _jwt(self) -> str:
        ahora = int(self._reloj())
        cabecera = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
        cuerpo = _b64(json.dumps({"iss": self._correo, "scope": ALCANCE, "aud": URL_TOKEN, "iat": ahora, "exp": ahora + VIGENCIA_S},
                                 separators=(",", ":")).encode())
        firma = self._llave.sign(f"{cabecera}.{cuerpo}".encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{cabecera}.{cuerpo}.{_b64(firma)}"

    def _token_acceso(self) -> str:
        if self._acceso and self._reloj() < self._expira - 120:
            return self._acceso
        r = self._http.post(URL_TOKEN, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": self._jwt()})
        r.raise_for_status()
        cuerpo = r.json()
        self._acceso = cuerpo["access_token"]
        self._expira = self._reloj() + int(cuerpo.get("expires_in", VIGENCIA_S))
        return self._acceso

    def enviar(self, token_dispositivo: str, titulo: str, cuerpo: str, datos: dict | None = None, privado: bool = False) -> str:
        """Devuelve OK, TOKEN_INVALIDO (hay que borrar el dispositivo) o ERROR (reintentable)."""
        mensaje = {"token": token_dispositivo, "notification": {"title": titulo, "body": cuerpo},
                   "android": {"priority": "HIGH", "notification": {"channel_id": "avisos", **({"visibility": "PRIVATE"} if privado else {})}}}
        if datos:
            mensaje["data"] = {str(k): str(v) for k, v in datos.items()}
        try:
            r = self._http.post(f"https://fcm.googleapis.com/v1/projects/{self._proyecto}/messages:send",
                                headers={"Authorization": f"Bearer {self._token_acceso()}"}, json={"message": mensaje})
        except (httpx.HTTPError, KeyError, ValueError):
            return ERROR
        if r.status_code == 200:
            return OK
        if r.status_code in (400, 404):
            try:
                estado = r.json().get("error", {}).get("status", "")
            except ValueError:
                estado = ""
            if estado in ("NOT_FOUND", "UNREGISTERED", "INVALID_ARGUMENT"):
                return TOKEN_INVALIDO
        if r.status_code == 401:
            self._acceso = None  # el siguiente intento pide un token nuevo
        return ERROR
