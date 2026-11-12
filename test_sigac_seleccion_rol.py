
import httpx
import pytest

from sigac_client import (
    BASE_URL,
    SigacClient,
    SigacClientError,
    SigacSessionExpired,
)
from sigac_roles import RolSigac


def crear_cliente(handler):
    http = httpx.Client(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    return SigacClient(http)


def test_seleccionar_rol_estudiante():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == (
            "/sigac/sesion.cambiar.ses"
        )

        assert request.content == (
            b"chkTipoUsuario=ESTUDIANTE"
            b"&cmdAceptar=Aceptar"
        )

        return httpx.Response(
            302,
            headers={
                "location": "general.principal.con"
            },
        )

    cliente = crear_cliente(handler)

    destino = cliente.seleccionar_rol(
        RolSigac.ESTUDIANTE
    )

    assert destino == "general.principal.con"


def test_seleccionar_rol_asistente_asesor():
    def handler(request):
        assert b"ASISTENTE_ASESOR" in request.content

        return httpx.Response(
            302,
            headers={
                "location": "general.principal.con"
            },
        )

    cliente = crear_cliente(handler)

    destino = cliente.seleccionar_rol(
        RolSigac.ASISTENTE_ASESOR
    )

    assert destino == "general.principal.con"


def test_rechazar_redireccion_externa():
    def handler(request):
        return httpx.Response(
            302,
            headers={
                "location": "https://otro-servidor.com/"
            },
        )

    cliente = crear_cliente(handler)

    with pytest.raises(SigacClientError):
        cliente.seleccionar_rol(
            RolSigac.ESTUDIANTE
        )


def test_detectar_sesion_vencida():
    def handler(request):
        return httpx.Response(403)

    cliente = crear_cliente(handler)

    with pytest.raises(SigacSessionExpired):
        cliente.seleccionar_rol(
            RolSigac.ESTUDIANTE
        )


def test_rechazar_respuesta_inesperada():
    def handler(request):
        return httpx.Response(
            200,
            text="<html>Error</html>",
        )

    cliente = crear_cliente(handler)

    with pytest.raises(SigacClientError):
        cliente.seleccionar_rol(
            RolSigac.ESTUDIANTE
        )


def test_rechazar_rol_invalido():
    def handler(request):
        pytest.fail(
            "No debería realizar una petición HTTP."
        )

    cliente = crear_cliente(handler)

    with pytest.raises(ValueError):
        cliente.seleccionar_rol("ADMINISTRADOR")
