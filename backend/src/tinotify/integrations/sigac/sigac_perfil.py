"""Nombre de la persona que inició sesión, tal como lo muestra el marco superior (banner) de SIGAC. Función pura, sin red."""

import re

from bs4 import BeautifulSoup

RUTA_BANNER = "general.banner.con"


def extraer_nombre(html):
    """El texto del elemento `span.nombre` del banner, o None si no hay uno único y razonable (solo letras, espacios y signos de nombre)."""
    if not isinstance(html, str):
        return None
    candidatos = BeautifulSoup(html, "html.parser").select("span.nombre")
    if len(candidatos) != 1:
        return None
    nombre = " ".join(candidatos[0].get_text().split())
    if not 2 <= len(nombre) <= 120 or not re.fullmatch(r"[^\W\d_]+(?:[ .'\-][^\W\d_]+)*\.?", nombre):
        return None
    return nombre
