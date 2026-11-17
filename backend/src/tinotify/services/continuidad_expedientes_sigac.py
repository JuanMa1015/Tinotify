"""Ensayo acotado de continuidad; no acredita identidad institucional estable.

Solo conserva números y sus representaciones DOM en RAM durante dos sesiones.
La fábrica de clientes es una frontera de confianza exclusiva de pruebas locales.
"""

from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from tinotify.integrations.sigac.sigac_client import LISTADO, SigacClient
from tinotify.parsers.casos_parser import PATRON_ABRIR, extraer_casos


@dataclass(frozen=True)
class _NumeroObservado:
    numero: int = field(repr=False)
    texto: str = field(repr=False)
    argumento: str = field(repr=False)


def _representaciones(html, total):
    # Validar primero con el contrato público vigente, sin aceptar omisiones.
    casos = extraer_casos(html, estricto=True, total_esperado=total)
    observados = []
    for fila in BeautifulSoup(html, "html.parser").find_all("tr"):
        columnas = fila.find_all(["td", "th"], recursive=False)
        if ("fila_enlace" not in fila.get("class", []) or len(columnas) != 3
                or any(c.name != "td" for c in columnas)):
            continue
        enlace = PATRON_ABRIR.fullmatch(fila.get("onclick", ""))
        if enlace is None:
            raise ValueError("Representación no contrastable")
        observados.append(_NumeroObservado(
            int(enlace.group(1)), columnas[0].get_text(), enlace.group(1),
        ))
    if tuple(o.numero for o in observados) != tuple(c.numero for c in casos):
        raise ValueError("Representaciones no corresponden al listado validado")
    return tuple(observados)


class _ClienteContinuidad(SigacClient):
    """Cliente dedicado: una autenticación, un listado y cierre del transporte."""

    _SECUENCIA = (
        ("GET", "index.jsp"),
        ("POST", "sesion.validar.ses"),
        ("GET", "general.formCambiarTipoUsuario.con"),
        ("POST", "sesion.cambiar.ses"),
        ("GET", "general.principal.con"),
        ("GET", LISTADO),
    )

    def __init__(self, total, http_client=None):
        super().__init__(http_client)
        self._total = total
        self._peticiones = 0
        self.observados = None

    def _solicitar(self, metodo, ruta, *, datos=None):
        if (self._peticiones >= len(self._SECUENCIA)
                or (metodo, ruta) != self._SECUENCIA[self._peticiones]):
            raise ValueError("Solicitud fuera del ensayo acotado")
        self._peticiones += 1
        return super()._solicitar(metodo, ruta, datos=datos)

    def obtener_html(self, ruta):
        html = super().obtener_html(ruta)
        if ruta == LISTADO:
            self.observados = _representaciones(html, self._total)
        return html

    def cerrar(self):
        try:
            super().cerrar()
        finally:
            self.observados = None
            # El transporte inyectado también es dedicado, nunca compartido.
            self.http.close()


def resumen_vacio():
    return {
        "sesiones": [
            {"autenticacion": None, "cantidad_expedientes": None, "identificadores_unicos": None}
            for _ in range(2)
        ],
        "igualdad_conjuntos": None,
        "identificadores_anadidos": None,
        "identificadores_ausentes": None,
        "diferencias_representacion": None,
        "clasificacion": "error",
    }


def ejecutar_continuidad(usuario, clave, *, total_casos, fabrica=None):
    """Uso real solo desde la entrada interactiva autorizada.

    Error: no continuar ni comparar observaciones parciales. Ningún resultado
    permite habilitar persistencia o verificar independientemente el rol activo.
    """
    resumen = resumen_vacio()
    if (type(total_casos) is not int or total_casos < 1
            or not all(isinstance(v, str) and v for v in (usuario, clave))):
        return resumen
    fabrica = fabrica or (lambda: _ClienteContinuidad(total_casos))
    lecturas = []
    for indice in range(2):
        resumen["sesiones"][indice]["autenticacion"] = False
        try:
            with fabrica() as cliente:
                casos = cliente.autenticar(usuario, clave, tipo="2", total_casos_esperado=total_casos)
                observados = cliente.observados
                if (not cliente.autenticada or observados is None
                        or len(observados) != total_casos
                        or tuple(o.numero for o in observados) != tuple(c.numero for c in casos)
                        or len({o.numero for o in observados}) != len(observados)):
                    raise ValueError("Listado no confirmado")
                del casos
            # Se copian únicamente representaciones, tras cerrar y limpiar.
            del cliente
            lecturas.append(observados)
            resumen["sesiones"][indice] = {
                "autenticacion": True, "cantidad_expedientes": len(observados),
                "identificadores_unicos": True,
            }
        except Exception:
            # No interpolar excepciones: pueden contener datos HTTP o internos.
            return resumen
    primera, segunda = ({o.numero: (o.texto, o.argumento) for o in lectura} for lectura in lecturas)
    comunes = primera.keys() & segunda.keys()
    iguales = primera.keys() == segunda.keys()
    representaciones_distintas = any(primera[n] != segunda[n] for n in comunes)
    resumen.update({
        "igualdad_conjuntos": iguales,
        "identificadores_anadidos": len(segunda.keys() - primera.keys()),
        "identificadores_ausentes": len(primera.keys() - segunda.keys()),
        "diferencias_representacion": representaciones_distintas,
        "clasificacion": "continuidad_observada" if iguales and not representaciones_distintas else "inconcluso",
    })
    return resumen
