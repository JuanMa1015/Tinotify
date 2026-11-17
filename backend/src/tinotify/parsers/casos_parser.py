
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


def extraer_casos(html: str, *, estricto=False, total_esperado=None, estructural=False) -> list[Caso]:
    """
    Extrae los casos asignados desde el HTML de SIGAC.

    No realiza solicitudes HTTP ni modifica expedientes.
    """
    if estricto:
        return _extraer_completo(html, total_esperado, estructural)
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


def _extraer_completo(html, total_esperado, estructural=False):
    """No omitir filas. El total global lo contrasta el operador, no una heurística.

    El modo legacy continúa disponible para sus consumidores anteriores; el
    flujo HTTP usa exclusivamente este modo estricto.
    """
    # Modo estructural (explícito): sin total fijado por el operador. Se conservan TODAS las comprobaciones de
    # estructura, filas y duplicados; solo se omite la igualdad con un total externo, y se exige al menos un caso.
    if estructural:
        if total_esperado is not None:
            raise ValueError("El modo estructural no admite un total.")
    elif type(total_esperado) is not int or total_esperado < 0:
        raise ValueError("Se requiere el total del listado completo contrastado.")
    soup = BeautifulSoup(html, "html.parser")
    candidatas = []
    for tabla in soup.find_all("table"):
        propias = [fila for fila in tabla.find_all("tr") if fila.find_parent("table") is tabla]
        cabeceras = [fila for fila in propias if fila.find("th", recursive=False)]
        for cabecera in cabeceras:
            etiquetas = [c.get_text(" ", strip=True).casefold()
                         for c in cabecera.find_all(["td", "th"], recursive=False)]
            if {"caso", "cliente", "estado"}.issubset(etiquetas):
                if etiquetas != ["caso", "cliente", "estado"]:
                    raise ValueError("Orden o columnas del listado no confirmados.")
                candidatas.append((tabla, propias, cabecera))
    if len(candidatas) != 1:
        raise ValueError("Tabla del listado ausente o ambigua.")
    tabla, filas, cabecera = candidatas[0]
    if any(("fila_enlace" in fila.get("class", []) or PATRON_ABRIR.fullmatch(fila.get("onclick", "")))
           and fila.find_parent("table") is not tabla for fila in soup.find_all("tr")):
        raise ValueError("Hay filas de expedientes fuera del listado identificado.")
    casos, vistos = [], set()
    for fila in filas:
        if fila is cabecera:
            continue
        columnas = fila.find_all(["td", "th"], recursive=False)
        if not fila.get_text(strip=True) and not fila.find(["a", "input", "select", "table", "button"]):
            continue
        if (len(columnas) != 3 or any(c.name != "td" for c in columnas)
                or "fila_enlace" not in fila.get("class", [])
                or any(c.has_attr("colspan") or c.has_attr("rowspan") for c in columnas)
                or fila.find("table")):
            raise ValueError("Fila del listado incompleta o no interpretable.")
        valores = [c.get_text(" ", strip=True) for c in columnas]
        enlace = PATRON_ABRIR.fullmatch(fila.get("onclick", ""))
        if (not valores[0].isascii() or not valores[0].isdigit() or not enlace
                or int(valores[0]) != int(enlace.group(1)) or int(valores[0]) <= 0
                or not valores[1] or not valores[2]):
            raise ValueError("Datos del listado inconsistentes.")
        numero = int(valores[0])
        if numero in vistos:
            raise ValueError("El listado contiene expedientes duplicados.")
        vistos.add(numero)
        casos.append(Caso(numero, valores[1], valores[2]))
    if estructural:
        if not casos:
            raise ValueError("El listado estructural no contiene expedientes.")
        return casos
    if len(casos) != total_esperado:
        raise ValueError("El listado no coincide con el total completo contrastado.")
    return casos
