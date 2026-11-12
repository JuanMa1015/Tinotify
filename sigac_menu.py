
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class ValidacionMenu:
    es_menu_estudiante: bool
    tiene_agenda: bool
    tiene_casos: bool
    tiene_cerrar_sesion: bool


def validar_menu_estudiante(html: str) -> ValidacionMenu:
    soup = BeautifulSoup(html, "html.parser")

    rutas = set()

    for elemento in soup.select("[onclick]"):
        javascript = elemento.get("onclick", "")

        coincidencias = re.findall(
            r"""(?:abrir|redirigir)\(\s*['"]([^'"]+)['"]\s*\)""",
            javascript,
        )

        rutas.update(coincidencias)

    tiene_agenda = (
        "casos.verAgendaEstudiante.con" in rutas
    )

    tiene_casos = (
        "casos.seleccionarCasos.con"
        "?motivo=ACTUAR_ESTUDIANTE" in rutas
    )

    tiene_cerrar_sesion = (
        "sesion.invalidar.ses" in rutas
    )

    return ValidacionMenu(
        es_menu_estudiante=(
            tiene_agenda
            and tiene_casos
            and tiene_cerrar_sesion
        ),
        tiene_agenda=tiene_agenda,
        tiene_casos=tiene_casos,
        tiene_cerrar_sesion=tiene_cerrar_sesion,
    )
