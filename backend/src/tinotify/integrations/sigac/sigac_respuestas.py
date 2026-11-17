"""Validaciones del contrato observado. Sin red, registros ni persistencia."""

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from tinotify.parsers.diagnostico_historial import CodigoHistorial


class RespuestaIncompleta(ValueError):
    """La respuesta no acredita el contrato mínimo esperado."""

    def __init__(self, mensaje, *, codigo=CodigoHistorial.NO_CLASIFICADO):
        super().__init__(mensaje)
        self.codigo = codigo if isinstance(codigo, CodigoHistorial) else CodigoHistorial.NO_CLASIFICADO


def destino_confirmado(valor, permitidos, *, diagnostico_login=False):
    def rechazo(codigo):
        return RespuestaIncompleta(
            "Redirección o acción no admitida.",
            codigo=codigo if diagnostico_login else CodigoHistorial.REDIRECCION_NO_CONFIRMADA,
        )

    if not isinstance(valor, str) or not valor or any(ord(c) <= 32 for c in valor):
        raise rechazo(CodigoHistorial.REDIRECCION_FORMATO)
    try:
        partes = urlsplit(valor)
    except ValueError:
        raise rechazo(CodigoHistorial.REDIRECCION_FORMATO) from None
    if partes.netloc and (partes.scheme != "https" or partes.netloc != "sigac.udea.edu.co"):
        raise rechazo(CodigoHistorial.REDIRECCION_ORIGEN)
    if partes.scheme and not partes.netloc:
        raise rechazo(CodigoHistorial.REDIRECCION_FORMATO)
    if partes.query or partes.fragment or "\\" in valor or "%" in valor:
        raise rechazo(CodigoHistorial.REDIRECCION_FORMATO)
    ruta = partes.path
    if ruta.startswith("/sigac/"):
        ruta = ruta[len("/sigac/"):]
    if ruta not in permitidos:
        codigo = CodigoHistorial.REDIRECCION_ACCESO if ruta == "index.jsp" else CodigoHistorial.REDIRECCION_DESTINO
        raise rechazo(codigo)
    return ruta


def destino_login_confirmado(cabeceras):
    """Distingue fallos sin conservar ni mostrar el valor de Location.

    HTTPX combina encabezados repetidos con coma y espacio: ya eran rechazados
    por destino_confirmado. La comprobación explícita conserva ese rechazo.
    """
    valores = cabeceras.get_list("location")
    if len(valores) > 1:
        raise RespuestaIncompleta("Redirección de acceso no confirmada.", codigo=CodigoHistorial.LOCATION_MULTIPLE)
    if not valores or not valores[0]:
        raise RespuestaIncompleta("Redirección de acceso no confirmada.", codigo=CodigoHistorial.LOCATION_AUSENTE)
    return destino_confirmado(
        valores[0], {"general.formCambiarTipoUsuario.con", "general.principal.con"}, diagnostico_login=True,
    )


def es_acceso(html):
    soup = BeautifulSoup(html, "html.parser")
    return bool(soup.find(attrs={"name": "txtClave"}) or any(
        "sesion.validar.ses" in str(f.get("action", "")).lower() for f in soup.find_all("form")
    ))


def es_selector(html):
    soup = BeautifulSoup(html, "html.parser")
    return any("sesion.cambiar.ses" in str(f.get("action", "")).lower() for f in soup.find_all("form"))


def estructura_documento(html):
    """Rasgos ESTRUCTURALES de un documento (booleanos y conteos). Nunca texto, atributos, URLs ni cabeceras."""
    if not isinstance(html, str):
        return {"tipo": type(html).__name__}
    fin = list(re.finditer(r"</html\s*>", html, re.I))
    resto = re.sub(r"<!--.*?-->|\s+", "", html[fin[-1].end():], flags=re.S) if fin else ""
    cuenta = lambda patron: len(re.findall(patron, html, re.I))
    primero = re.search(r"<\s*([a-zA-Z][a-zA-Z0-9]*)", html)
    return {"largo": len(html), "html_abre": cuenta(r"<html"), "html_cierra": len(fin), "body_abre": cuenta(r"<body"),
            "body_cierra": cuenta(r"</body\s*>"), "caracteres_tras_html": len(resto), "formularios": cuenta(r"<form"),
            "tablas": cuenta(r"<table"), "scripts": cuenta(r"<script"), "enlaces": cuenta(r"<a"),
            "primer_elemento": primero.group(1).lower() if primero else None, "vacio": not html.strip()}


def documento_completo(html):
    soup = BeautifulSoup(html, "html.parser")
    if (soup.html is None or soup.body is None or not re.search(r"</body\s*>", html, re.I)
            or not re.search(r"</html\s*>\s*(?:<!--.*?-->\s*)*$", html, re.I | re.S)):
        raise RespuestaIncompleta("Documento incompleto o estructura no confirmada.",
                                 codigo=CodigoHistorial.DOCUMENTO_INCOMPLETO)
    return soup


def _formulario(html, accion, nombres):
    soup = documento_completo(html)
    formularios = []
    for formulario in soup.find_all("form"):
        try:
            destino_confirmado(formulario.get("action", ""), {accion})
        except RespuestaIncompleta:
            continue
        formularios.append(formulario)
    if len(formularios) != 1:
        raise RespuestaIncompleta("Formulario esperado ausente o ambiguo.", codigo=CodigoHistorial.FORMULARIO_AMBIGUO)
    formulario = formularios[0]
    if (formulario.get("method", "get").lower() != "post"
            or formulario.get("enctype", "application/x-www-form-urlencoded").lower()
            != "application/x-www-form-urlencoded"):
        raise RespuestaIncompleta("Método o codificación del formulario no confirmados.", codigo=CodigoHistorial.FORMULARIO_METODO_INVALIDO)
    controles = formulario.find_all(["input", "select", "button", "textarea"])
    presentes = [c.get("name") for c in controles if c.get("name")]
    if set(presentes) != set(nombres) or any(c.has_attr("disabled") for c in controles if c.get("name")):
        raise RespuestaIncompleta("Campos del formulario distintos del contrato confirmado.", codigo=CodigoHistorial.FORMULARIO_CAMPOS_INVALIDOS)
    if any(c.has_attr("form") or c.find_parent("fieldset", disabled=True) for c in controles):
        raise RespuestaIncompleta("Controles de formulario no admitidos.", codigo=CodigoHistorial.FORMULARIO_CONTROLES_INVALIDOS)
    return formulario, controles


@dataclass(frozen=True, repr=False)
class FormularioAcceso:
    tipos: tuple[str, ...]
    caso: str
    ingresar: str


def leer_acceso(html):
    nombres = {"cboTipo", "txtUsuario", "txtCaso", "txtClave", "cmdIngresar"}
    _, controles = _formulario(html, "sesion.validar.ses", nombres)
    campos = {nombre: [c for c in controles if c.get("name") == nombre] for nombre in nombres}
    if any(len(valores) != 1 for valores in campos.values()):
        raise RespuestaIncompleta("Campos duplicados en el formulario de acceso.", codigo=CodigoHistorial.FORMULARIO_DUPLICADO)
    campos = {nombre: valores[0] for nombre, valores in campos.items()}
    selector = campos["cboTipo"]
    if selector.name != "select" or selector.has_attr("multiple"):
        raise RespuestaIncompleta("Selector de tipo de acceso no confirmado.", codigo=CodigoHistorial.FORMULARIO_SELECTOR_INVALIDO)
    tipos = tuple(o["value"] for o in selector.find_all("option")
                  if o.get("value") and not o.has_attr("disabled")
                  and not o.find_parent("optgroup", disabled=True))
    if not tipos or len(set(tipos)) != len(tipos):
        raise RespuestaIncompleta("Opciones de acceso ausentes o ambiguas.", codigo=CodigoHistorial.FORMULARIO_OPCIONES_INVALIDAS)
    if (campos["txtClave"].get("type", "").lower() != "password"
            or any(campos[n].name != "input" for n in ("txtUsuario", "txtClave", "txtCaso"))):
        raise RespuestaIncompleta("Controles de acceso no confirmados.", codigo=CodigoHistorial.FORMULARIO_CONTROLES_INVALIDOS)
    boton = campos["cmdIngresar"]
    if boton.name not in {"input", "button"} or "value" not in boton.attrs:
        raise RespuestaIncompleta("Falta el valor explícito de cmdIngresar en el formulario.", codigo=CodigoHistorial.FORMULARIO_SUBMIT_SIN_VALOR)
    return FormularioAcceso(tipos, campos["txtCaso"].get("value", ""), boton["value"])


def verificar_selector_estudiante(html):
    _, controles = _formulario(html, "sesion.cambiar.ses", {"chkTipoUsuario", "cmdAceptar"})
    if not any(c.get("name") == "chkTipoUsuario" and c.get("value") == "ESTUDIANTE" for c in controles):
        raise RespuestaIncompleta("El formulario no ofrece el rol ESTUDIANTE.", codigo=CodigoHistorial.ROL_NO_OFRECIDO)
    botones = [c for c in controles if c.get("name") == "cmdAceptar"]
    if len(botones) != 1 or botones[0].get("value") != "Aceptar":
        raise RespuestaIncompleta("Acción de selección de rol no confirmada.", codigo=CodigoHistorial.ROL_ACCION_INVALIDA)


def pagina_protegida(html):
    soup = documento_completo(html)
    if es_acceso(html) or es_selector(html):
        raise RespuestaIncompleta("La respuesta sigue siendo una página de acceso o selección de rol.",
                                 codigo=CodigoHistorial.PAGINA_NO_PROTEGIDA)
