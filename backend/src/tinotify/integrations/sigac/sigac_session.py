
from dataclasses import dataclass

from bs4 import BeautifulSoup

from tinotify.integrations.sigac.sigac_client import (
    SigacClient,
    SigacClientError,
    SigacSessionExpired,
)
from tinotify.integrations.sigac.sigac_menu import validar_menu_estudiante


@dataclass(frozen=True)
class EstadoSesion:
    autenticada: bool
    pagina: str


class SigacSession:
    def __init__(self, cliente: SigacClient):
        self.cliente = cliente

    def verificar_pagina_principal(self) -> EstadoSesion:
        """
        Verificación preliminar de la página principal.

        Se conserva por compatibilidad con las
        pruebas existentes. No confirma autenticación.
        """
        html = self.cliente.obtener_html(
            "general.principal.con"
        )

        soup = BeautifulSoup(html, "html.parser")

        if soup.select(
            'form[action*="sesion.validar.ses"]'
        ):
            raise SigacSessionExpired(
                "SIGAC devolvió el formulario de acceso."
            )

        if not soup.get_text(" ", strip=True):
            raise SigacClientError(
                "La página principal está vacía."
            )

        return EstadoSesion(
            autenticada=False,
            pagina="general.principal.con",
        )

    def verificar_menu_estudiante(self) -> EstadoSesion:
        """
        Reconoce el menú de Estudiante.

        No sustituye la autorización del servidor
        para consultar expedientes.
        """
        html = self.cliente.obtener_html(
            "general.menu.con"
        )

        soup = BeautifulSoup(html, "html.parser")

        if soup.select(
            'form[action*="sesion.validar.ses"]'
        ):
            raise SigacSessionExpired(
                "SIGAC devolvió el formulario de acceso."
            )

        validacion = validar_menu_estudiante(html)

        if not validacion.es_menu_estudiante:
            raise SigacClientError(
                "No se reconoce el menú de Estudiante."
            )

        return EstadoSesion(
            autenticada=False,
            pagina="general.menu.con",
        )
