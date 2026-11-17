"""Clasificación local cerrada. Observar un destino no autoriza navegar a él."""

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from tinotify.integrations.sigac.sigac_respuestas import RespuestaIncompleta, destino_login_confirmado
from tinotify.parsers.diagnostico_historial import CodigoHistorial, EtapaSigac


class TipoDestinoLogin(str, Enum):
    ACCESO = "retorno_acceso"
    SELECTOR = "selector_rol"
    PRINCIPAL = "principal_conocida_fuera_de_etapa"
    MENU = "menu_conocido_fuera_de_etapa"
    DESCONOCIDO = "destino_desconocido"


# Catálogo de observación, NO lista de destinos autorizados para autenticarse.
_CATALOGO = {
    "index.jsp": TipoDestinoLogin.ACCESO,
    "general.formCambiarTipoUsuario.con": TipoDestinoLogin.SELECTOR,
    "general.principal.con": TipoDestinoLogin.PRINCIPAL,
    "general.menu.con": TipoDestinoLogin.MENU,
}


@dataclass(frozen=True)
class ObservacionLogin:
    tipo: TipoDestinoLogin
    prefijo_punto: bool
    parametros_en_ruta: bool
    ruta_fuera_ambito_esperado: bool
    variante_conocida: bool

    def diagnostico(self):
        # Nunca conserva la ruta, ni siquiera si no pertenece al catálogo.
        return {
            "diagnostico_version": 2,
            "etapa": EtapaSigac.REDIRECCION_LOGIN.value,
            "categoria": self.tipo.value,
            "indicadores": {
                "prefijo_punto": self.prefijo_punto,
                "parametros_en_ruta": self.parametros_en_ruta,
                "ruta_fuera_ambito_esperado": self.ruta_fuera_ambito_esperado,
                "variante_conocida": self.variante_conocida,
            },
            "autenticacion_confirmada": False,
            "redireccion_seguida": False,
        }


def observar_destino_login(cabeceras):
    # Se ejecutan las mismas comprobaciones de formato/origen del login.
    # Solo los rechazos por destino se pueden clasificar, nunca seguir.
    try:
        destino_login_confirmado(cabeceras)
    except RespuestaIncompleta as error:
        if error.codigo not in (CodigoHistorial.REDIRECCION_ACCESO, CodigoHistorial.REDIRECCION_DESTINO):
            raise

    ruta_original = urlsplit(cabeceras.get_list("location")[0]).path
    fuera = ((ruta_original.startswith("/") and not ruta_original.startswith("/sigac/"))
             or ".." in ruta_original.split("/"))
    ruta = ruta_original.removeprefix("/sigac/")
    prefijo_punto = ruta.startswith("./")
    parametros = ";" in ruta
    candidato = ruta.removeprefix("./")
    base, separador, resto = candidato.partition(";")
    if separador and "/" not in resto:
        candidato = base
    tipo = _CATALOGO.get(candidato, TipoDestinoLogin.DESCONOCIDO) if not fuera else TipoDestinoLogin.DESCONOCIDO
    return ObservacionLogin(
        tipo, prefijo_punto, parametros, fuera,
        tipo is not TipoDestinoLogin.DESCONOCIDO and candidato != ruta,
    )
