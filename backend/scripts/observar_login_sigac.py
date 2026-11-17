"""Observación manual aislada: hasta dos solicitudes, sin navegación posterior."""

import argparse
import getpass
import json
import logging
import sys
import warnings

from tinotify.integrations.sigac.sigac_client import SigacClient, SigacClientError
from tinotify.parsers.diagnostico_historial import (
    CodigoHistorial, ContextoDiagnostico, EtapaSigac, diagnostico_seguro,
)


def emitir(codigo, contexto, conteos=None):
    print(json.dumps(diagnostico_seguro(codigo, conteos, etapa=contexto.etapa), sort_keys=True))


class ArgumentosSeguros(argparse.ArgumentParser):
    def error(self, message):
        # argparse normalmente reproduce argumentos desconocidos: no mostrarlos.
        emitir(CodigoHistorial.ENTRADA_INVALIDA, ContextoDiagnostico())
        raise SystemExit(2)


def main(argv=None):
    parser = ArgumentosSeguros(description="Observar solo la redirección de login, sin autenticar una sesión de lectura")
    parser.add_argument("--autorizar-sigac-real", action="store_true")
    parser.add_argument("--tipo", required=True, help="Valor de cboTipo previamente observado")
    parser.add_argument("--pedir-caso-login", action="store_true", help="Pedir txtCaso sin eco si es necesario")
    args = parser.parse_args(argv)
    if not args.autorizar_sigac_real or not sys.stdin.isatty():
        parser.error("Autorización y terminal interactiva requeridas")
    contexto = ContextoDiagnostico()
    nivel_anterior = logging.root.manager.disable
    # Proceso dedicado: también bloquea httpx/httpcore y sus loggers hijos.
    logging.disable(logging.CRITICAL)
    try:
        if input("Escribe SIGAC-OBSERVAR-LOGIN para confirmar un único intento autorizado: ") != "SIGAC-OBSERVAR-LOGIN":
            emitir(CodigoHistorial.ENTRADA_INVALIDA, contexto)
            return 2
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            contexto.marcar(EtapaSigac.CREDENCIALES)
            usuario = getpass.getpass("Usuario SIGAC (sin eco): ")
            clave = getpass.getpass("Clave SIGAC (sin eco): ")
            caso_login = getpass.getpass("txtCaso (sin eco): ") if args.pedir_caso_login else None
            contexto.marcar(EtapaSigac.CREACION_CLIENTE)
            with SigacClient() as cliente:
                cliente.contexto = contexto
                resumen = cliente.observar_redireccion_login(usuario, clave, tipo=args.tipo, caso_login=caso_login)
        print(json.dumps(resumen, ensure_ascii=True, sort_keys=True))
        return 0  # Observación terminada, NO autenticación ni destino autorizado.
    except SigacClientError as error:
        datos = error.diagnostico if isinstance(error.diagnostico, dict) else {}
        etapa = error.etapa if error.etapa is not EtapaSigac.NO_DETERMINADA else contexto.etapa
        print(json.dumps(diagnostico_seguro(error.codigo, datos.get("estadisticas_estructurales"), etapa=etapa), sort_keys=True))
        return 1
    except Warning:
        emitir(CodigoHistorial.ADVERTENCIA_BIBLIOTECA, contexto)
        return 1
    except KeyboardInterrupt:
        emitir(CodigoHistorial.ENTRADA_INVALIDA, contexto)
        return 130
    except Exception:
        emitir(CodigoHistorial.ERROR_INTERNO, contexto)
        return 1
    finally:
        logging.disable(nivel_anterior)


if __name__ == "__main__":
    raise SystemExit(main())
