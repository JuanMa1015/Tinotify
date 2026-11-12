
import httpx
import pytest

from tinotify.integrations.sigac.sigac_client import (
    BASE_URL,
    SigacClient,
    SigacClientError,
    SigacSessionExpired,
)
from tinotify.integrations.sigac.sigac_session import SigacSession


def crear_sesion(handler):
    http = httpx.Client(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )

    return SigacSession(SigacClient(http))


def test_pagina_principal_simulada():
    def handler(request):
        assert request.url.path == (
            "/sigac/general.principal.con"
        )

        return httpx.Response(
            200,
            text="""
            <html>
                <body>
                    <h1>SIGAC</h1>
                    <p>Menú principal</p>
                </body>
            </html>
            """,
            headers={
                "content-type": "text/html"
            },
        )

    sesion = crear_sesion(handler)
    resultado = sesion.verificar_pagina_principal()

    assert resultado.autenticada is False


def test_detectar_formulario_login():
    def handler(request):
        return httpx.Response(
            200,
            text="""
            <html>
                <form action="sesion.validar.ses">
                    <input name="txtUsuario">
                </form>
            </html>
            """,
            headers={
                "content-type": "text/html"
            },
        )

    sesion = crear_sesion(handler)

    with pytest.raises(SigacSessionExpired):
        sesion.verificar_pagina_principal()


def test_rechazar_pagina_vacia():
    def handler(request):
        return httpx.Response(
            200,
            text="<html><body></body></html>",
            headers={
                "content-type": "text/html"
            },
        )

    sesion = crear_sesion(handler)

    with pytest.raises(SigacClientError):
        sesion.verificar_pagina_principal()


def test_detectar_redireccion():
    def handler(request):
        return httpx.Response(
            302,
            headers={
                "location": "index.jsp"
            },
        )

    sesion = crear_sesion(handler)

    with pytest.raises(SigacSessionExpired):
        sesion.verificar_pagina_principal()


def test_reconocer_menu_estudiante(tmp_path):
    def handler(request):
        assert request.url.path == (
            "/sigac/general.menu.con"
        )

        return httpx.Response(
            200,
            text="""
            <html>
                <input onclick="abrir('casos.verAgendaEstudiante.con')">
                <input onclick="abrir('casos.seleccionarCasos.con?motivo=ACTUAR_ESTUDIANTE')">
                <input onclick="redirigir('sesion.invalidar.ses')">
            </html>
            """,
            headers={"content-type": "text/html"},
        )

    sesion = crear_sesion(handler)
    resultado = sesion.verificar_menu_estudiante()

    assert resultado.pagina == "general.menu.con"
    assert resultado.autenticada is False


def test_rechazar_menu_incompleto():
    def handler(request):
        return httpx.Response(
            200,
            text="<html><body>Menú incompleto</body></html>",
            headers={"content-type": "text/html"},
        )

    sesion = crear_sesion(handler)

    with pytest.raises(SigacClientError):
        sesion.verificar_menu_estudiante()


def test_menu_redirige_a_login():
    def handler(request):
        return httpx.Response(
            302,
            headers={"location": "index.jsp"},
        )

    sesion = crear_sesion(handler)

    with pytest.raises(SigacSessionExpired):
        sesion.verificar_menu_estudiante()
