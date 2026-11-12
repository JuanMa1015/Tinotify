
from tinotify.integrations.sigac.sigac_menu import validar_menu_estudiante


HTML_MENU = """
<html>
<body>
    <input
        onclick="abrir('casos.verAgendaEstudiante.con')"
    >
    <input
        onclick="abrir('casos.seleccionarCasos.con?motivo=ACTUAR_ESTUDIANTE')"
    >
    <input
        onclick="redirigir('sesion.invalidar.ses')"
    >
</body>
</html>
"""


def test_menu_estudiante_valido():
    resultado = validar_menu_estudiante(HTML_MENU)

    assert resultado.es_menu_estudiante is True
    assert resultado.tiene_agenda is True
    assert resultado.tiene_casos is True
    assert resultado.tiene_cerrar_sesion is True


def test_rechazar_menu_incompleto():
    html = """
    <html>
        <input
            onclick="abrir('casos.verAgendaEstudiante.con')"
        >
    </html>
    """

    resultado = validar_menu_estudiante(html)

    assert resultado.es_menu_estudiante is False
    assert resultado.tiene_agenda is True
    assert resultado.tiene_casos is False


def test_rechazar_formulario_login():
    html = """
    <html>
        <form action="sesion.validar.ses">
            <input name="txtUsuario">
        </form>
    </html>
    """

    resultado = validar_menu_estudiante(html)

    assert resultado.es_menu_estudiante is False


def test_rechazar_html_vacio():
    resultado = validar_menu_estudiante("")

    assert resultado.es_menu_estudiante is False
