
from urllib.parse import urlsplit
from sigac_roles import RolSigac, datos_seleccion_rol

import httpx


BASE_URL = "https://sigac.udea.edu.co/sigac/"


class SigacClientError(Exception):
    """Error de comunicación o validación con SIGAC."""


class SigacSessionExpired(SigacClientError):
    """La sesión ya no permite acceder al recurso."""


class SigacClient:
    """
    Cliente HTTP de lectura para SIGAC.

    No realiza inicio de sesión.
    No recibe ni almacena contraseñas.
    """

    def __init__(
        self,
        http_client: httpx.Client | None = None,
    ):
        self._owns_client = http_client is None

        self.http = http_client or httpx.Client(
            base_url=BASE_URL,
            timeout=10.0,
            follow_redirects=False,
            verify=True,
            trust_env=False,
        )

    @staticmethod
    def _validar_ruta(ruta: str) -> str:
        parsed = urlsplit(ruta)

        if (
            not ruta
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or "\\" in ruta
        ):
            raise ValueError(
                "La ruta debe ser relativa a SIGAC."
            )

        path = parsed.path

        if (
            not path
            or path.startswith("/")
            or any(
                segmento in (".", "..")
                for segmento in path.split("/")
            )
        ):
            raise ValueError("Ruta no permitida.")

        return ruta

    def obtener_html(self, ruta: str) -> str:
        ruta = self._validar_ruta(ruta)

        try:
            respuesta = self.http.get(
                ruta,
                follow_redirects=False,
            )

            if respuesta.is_redirect:
                raise SigacSessionExpired(
                    "SIGAC devolvió una redirección. "
                    "Verifica la sesión."
                )

            if respuesta.status_code in (401, 403):
                raise SigacSessionExpired(
                    "Acceso no autorizado o sesión vencida."
                )

            respuesta.raise_for_status()

            content_type = respuesta.headers.get(
                "content-type", ""
            ).lower()

            if "text/html" not in content_type:
                raise SigacClientError(
                    "SIGAC no devolvió contenido HTML."
                )

            return respuesta.text

        except httpx.HTTPError as error:
            raise SigacClientError(
                "Error de comunicación con SIGAC."
            ) from error

    
    def seleccionar_rol(self, rol: RolSigac) -> str:
        """
        Envía la selección de rol.

        Devuelve la ruta de redirección para
        su posterior verificación.

        No confirma por sí mismo que el rol
        haya sido activado correctamente.
        """
        datos = datos_seleccion_rol(rol)

        try:
            respuesta = self.http.post(
                "sesion.cambiar.ses",
                data=datos,
                follow_redirects=False,
            )

            if respuesta.status_code in (401, 403):
                raise SigacSessionExpired(
                    "Sesión no autorizada o vencida."
                )

            if respuesta.status_code != 302:
                raise SigacClientError(
                    "Respuesta inesperada al seleccionar rol."
                )

            destino = respuesta.headers.get(
                "location", ""
            )

            try:
                return self._validar_ruta(destino)
            except ValueError as error:
                raise SigacClientError(
                    "SIGAC devolvió una redirección "
                    "no permitida."
                ) from error

        except httpx.HTTPError as error:
            raise SigacClientError(
                "Error de comunicación al seleccionar rol."
            ) from error


    def cerrar(self):
        if self._owns_client:
            self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.cerrar()
