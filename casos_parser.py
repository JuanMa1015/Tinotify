
from dataclasses import dataclass
from bs4 import BeautifulSoup
import re


@dataclass(frozen=True)
class Caso:
    numero: int
    cliente: str
    estado: str


PATRON_ABRIR = re.compile(
    r"^\s*abrir\(\s*(\d+)\s*\)\s*;?\s*$"
)


def extraer_casos(html: str) -> list[Caso]:
    """
    Extrae los casos asignados desde el HTML de SIGAC.

    No realiza solicitudes HTTP ni modifica expedientes.
    """
    soup = BeautifulSoup(html, "html.parser")
    casos = []
    numeros_vistos = set()

    for tabla in soup.find_all("table"):
        encabezados = [
            th.get_text(" ", strip=True).lower()
            for th in tabla.find_all("th", recursive=False)
        ]

        # Los encabezados suelen estar dentro de un <tr>.
        if not encabezados:
            encabezados = [
                th.get_text(" ", strip=True).lower()
                for th in tabla.find_all("th")
            ]

        if not {"caso", "cliente", "estado"}.issubset(
            set(encabezados)
        ):
            continue

        for fila in tabla.find_all("tr"):
            clases = fila.get("class", [])

            if "fila_enlace" not in clases:
                continue

            columnas = fila.find_all("td", recursive=False)

            if len(columnas) < 3:
                continue

            numero_texto = columnas[0].get_text(strip=True)
            cliente = columnas[1].get_text(" ", strip=True)
            estado = columnas[2].get_text(" ", strip=True)

            if not numero_texto.isdigit():
                continue

            numero = int(numero_texto)

            onclick = fila.get("onclick", "")
            coincidencia = PATRON_ABRIR.fullmatch(onclick)

            if not coincidencia:
                continue

            numero_onclick = int(coincidencia.group(1))

            # Evita asociar una fila con un expediente incorrecto.
            if numero != numero_onclick:
                continue

            if numero in numeros_vistos:
                continue

            numeros_vistos.add(numero)

            casos.append(
                Caso(
                    numero=numero,
                    cliente=cliente,
                    estado=estado,
                )
            )

    return casos
