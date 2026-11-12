
from casos_parser import extraer_casos


HTML_PRUEBA = """
<table class="tabla">
    <tr>
        <th>Caso</th>
        <th>Cliente</th>
        <th>Estado</th>
    </tr>
    <tr onclick="abrir(12345)" class="fila_enlace">
        <td>12345</td>
        <td>Cliente Ficticio Uno</td>
        <td>En proceso</td>
    </tr>
    <tr onclick="abrir(67890)" class="fila_enlace">
        <td>67890</td>
        <td>Cliente Ficticio Dos</td>
        <td>Finalizado</td>
    </tr>
</table>
"""


def test_extraer_casos():
    casos = extraer_casos(HTML_PRUEBA)

    assert len(casos) == 2
    assert casos[0].numero == 12345
    assert casos[0].cliente == "Cliente Ficticio Uno"
    assert casos[0].estado == "En proceso"
    assert casos[1].numero == 67890


def test_evitar_casos_duplicados():
    html = HTML_PRUEBA.replace(
        "</table>",
        """
        <tr onclick="abrir(12345)" class="fila_enlace">
            <td>12345</td>
            <td>Cliente Ficticio Uno</td>
            <td>En proceso</td>
        </tr>
        </table>
        """,
    )

    casos = extraer_casos(html)
    assert len(casos) == 2


def test_rechazar_numero_inconsistente():
    html = HTML_PRUEBA.replace(
        "abrir(12345)",
        "abrir(99999)",
    )

    casos = extraer_casos(html)

    assert len(casos) == 1
    assert casos[0].numero == 67890
