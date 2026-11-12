
import httpx
import pytest

from tinotify.integrations.sigac.sigac_client import (
    BASE_URL,
    SigacClient,
    SigacClientError,
    SigacSessionExpired,
)


def crear_cliente(handler):
    transport = httpx.MockTransport(handler)

    http = httpx.Client(
        base_url=BASE_URL,
        transport=transport,
        follow_redirects=False,
    )

    return SigacClient(http)


def test_obtener_html_correctamente():
    def handler(request):
        assert request.url.host == "sigac.udea.edu.co"
        assert request.url.path == "/sigac/index.jsp"

        return httpx.Response(
            200,
            text="<html>SIGAC</html>",
            headers={"content-type": "text/html"},
        )

    cliente = crear_cliente(handler)

    resultado = cliente.obtener_html("index.jsp")

    assert resultado == "<html>SIGAC</html>"


@pytest.mark.parametrize(
    "ruta",
    [
        "https://otro-servidor.com/",
        "//otro-servidor.com/",
        "/sigac/index.jsp",
        "../administracion",
        "casos/../index.jsp",
        "",
        "index.jsp#fragmento",
        r"..\index.jsp",
    ],
)
def test_rechazar_rutas_no_permitidas(ruta):
    def handler(request):
        pytest.fail(
            "No debía realizar una petición HTTP."
        )

    cliente = crear_cliente(handler)

    with pytest.raises(ValueError):
        cliente.obtener_html(ruta)


def test_detectar_redireccion_de_sesion():
    def handler(request):
        return httpx.Response(
            302,
            headers={
                "location": "index.jsp",
            },
        )

    cliente = crear_cliente(handler)

    with pytest.raises(SigacSessionExpired):
        cliente.obtener_html("general.principal.con")


def test_detectar_acceso_no_autorizado():
    def handler(request):
        return httpx.Response(403)

    cliente = crear_cliente(handler)

    with pytest.raises(SigacSessionExpired):
        cliente.obtener_html("general.principal.con")


def test_rechazar_contenido_no_html():
    def handler(request):
        return httpx.Response(
            200,
            content=b"contenido binario",
            headers={
                "content-type": "application/octet-stream",
            },
        )

    cliente = crear_cliente(handler)

    with pytest.raises(SigacClientError):
        cliente.obtener_html("general.principal.con")
