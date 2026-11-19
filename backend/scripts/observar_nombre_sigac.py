"""Observación manual: ¿dónde muestra SIGAC el nombre de la persona que inició sesión? Un único inicio de sesión (el mismo del monitor).

Imprime SOLO la estructura de la página principal con el texto ENMASCARADO (las letras se vuelven «x» y los dígitos «9», salvo un
vocabulario público de la interfaz). Nada se guarda en disco ni se envía a ningún sitio. Las credenciales se piden sin eco.
"""

import argparse
import getpass
import logging
import re
import sys
import warnings

from bs4 import BeautifulSoup, NavigableString

from tinotify.integrations.sigac.sigac_client import SigacClient, SigacClientError

PUBLICAS = {
    "bienvenido", "bienvenida", "usuario", "usuaria", "sesion", "sesión", "cerrar", "salir", "inicio", "casos", "caso", "estudiante", "asesor",
    "hola", "nombre", "perfil", "cambiar", "rol", "tipo", "menu", "menú", "ayuda", "consultas", "consulta", "actuaciones", "reportes", "de",
    "del", "la", "el", "los", "las", "en", "y", "su", "mis", "mi", "conectado", "conectada", "como", "como:", "bienvenido(a)",
}
CLAVES_ATRIBUTO = re.compile(r"usuario|user|nombre|name|bienvenid|welcome|perfil|sesion", re.I)


def enmascarar(texto):
    def palabra(m):
        return m.group() if m.group().lower() in PUBLICAS else "x" * len(m.group())
    return re.sub(r"\d", "9", re.sub(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", palabra, " ".join(texto.split())))


def ruta_corta(nodo):
    partes = []
    while nodo is not None and getattr(nodo, "name", None) and nodo.name not in ("[document]", "html"):
        etiqueta = nodo.name + (f"#{nodo.get('id')}" if nodo.get("id") else "") + "".join(f".{c}" for c in (nodo.get("class") or [])[:2])
        partes.append(etiqueta)
        nodo = nodo.parent
    return " > ".join(reversed(partes[:4]))


def describir(html, maximo=70):
    sopa = BeautifulSoup(html, "html.parser")
    for oculto in sopa(["script", "style"]):
        oculto.decompose()
    lineas = []
    for nodo in sopa.find_all(string=True):
        if not isinstance(nodo, NavigableString) or nodo.parent.name in ("title", "option"):
            continue
        texto = " ".join(str(nodo).split())
        if 2 <= len(texto) <= 100:
            lineas.append(f"{ruta_corta(nodo.parent)} | {enmascarar(texto)}")
    atributos = []
    for el in sopa.find_all(True):
        for k in ("id", "class", "name"):
            v = el.get(k)
            v = " ".join(v) if isinstance(v, list) else v
            if v and CLAVES_ATRIBUTO.search(v) and not el.find(True):
                atributos.append(f"<{el.name} {k}={v!r}> texto: {enmascarar(el.get_text())[:60]}")
    return lineas[:maximo], atributos[:20]


def marcos(html):
    """Rutas relativas de los marcos de la página (sin esquema ni barra inicial)."""
    sopa = BeautifulSoup(html, "html.parser")
    salida = []
    for el in sopa.find_all(["frame", "iframe"]):
        src = (el.get("src") or "").strip()
        if src and "://" not in src and not src.startswith(("/", "#", "javascript")) and src not in salida:
            salida.append(src)
    return salida


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--autorizar-sigac-real", action="store_true")
    parser.add_argument("--tipo", default="2")
    parser.add_argument("--pedir-caso-login", action="store_true")
    args = parser.parse_args()
    if not args.autorizar_sigac_real or not sys.stdin.isatty():
        print("Se requiere --autorizar-sigac-real y una terminal interactiva.")
        return 2
    if input("Escribe SIGAC-OBSERVAR-NOMBRE para confirmar UN inicio de sesión autorizado: ") != "SIGAC-OBSERVAR-NOMBRE":
        return 2
    logging.disable(logging.CRITICAL)
    capturadas, fuentes = [], []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            usuario = getpass.getpass("Usuario SIGAC (sin eco): ")
            clave = getpass.getpass("Clave SIGAC (sin eco): ")
            caso_login = getpass.getpass("txtCaso (sin eco): ") if args.pedir_caso_login else None
            with SigacClient() as cliente:
                original = cliente.obtener_html

                def captura(ruta):
                    html = original(ruta)
                    capturadas.append(html)
                    return html
                cliente.obtener_html = captura
                cliente.autenticar(usuario, clave, tipo=args.tipo, total_casos_esperado=None, caso_login=caso_login, listado_estructural=True)
                del usuario, clave, caso_login
                # La principal es un conjunto de marcos (frames): el nombre suele estar en uno de ellos. Se leen (GET) como lo hace un navegador.
                for src in marcos(capturadas[0] if capturadas else "")[:5]:
                    try:
                        capturadas.append(original(src))
                        fuentes.append(src)
                    except Exception as error:  # noqa: BLE001
                        fuentes.append(f"{src} (fallo: {type(error).__name__})")
    except SigacClientError as error:
        print(f"fallo: {error.codigo.value}")
        return 1
    except Exception as error:  # noqa: BLE001
        print(f"fallo: {type(error).__name__}")
        return 1
    if not capturadas:
        print("fallo: sin_pagina_principal")
        return 1
    print("== Marcos de la principal ==")
    print("\n".join(re.sub(r"\d", "9", f) for f in fuentes) or "(ninguno)")
    for i, html in enumerate(capturadas):
        lineas, atributos = describir(html)
        print(f"== Página {i} (0 = principal) · texto enmascarado ==")
        print("\n".join(lineas) or "(vacío)")
        print("-- elementos con id/clase/nombre relacionados con usuario --")
        print("\n".join(atributos) or "(ninguno)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
