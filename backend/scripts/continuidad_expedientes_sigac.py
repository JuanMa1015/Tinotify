"""Entrada manual independiente: dos sesiones, sin historiales ni persistencia."""

import argparse
import getpass
import json
import logging
import sys
import warnings

from tinotify.services.continuidad_expedientes_sigac import ejecutar_continuidad, resumen_vacio


def main(argv=None):
    parser = argparse.ArgumentParser(description="Continuidad observada de expedientes entre dos sesiones SIGAC")
    parser.add_argument("--autorizar-sigac-real", action="store_true")
    parser.add_argument("--tipo", choices=["2"], required=True, help="Consultorio; selección posterior ESTUDIANTE")
    parser.add_argument("--total-casos", type=int, required=True, help="Total completo contrastado por el operador")
    args = parser.parse_args(argv)
    if not args.autorizar_sigac_real:
        parser.error("Se requiere autorización explícita; no se abrió ninguna conexión")
    if args.total_casos < 1:
        parser.error("El total debe ser positivo")
    if not sys.stdin.isatty():
        parser.error("Se requiere terminal interactiva; no canalizar credenciales")
    anterior = logging.root.manager.disable
    logging.disable(sys.maxsize)
    resumen = resumen_vacio()
    try:
        if input("Escribe SIGAC-CONTINUIDAD para autorizar dos sesiones: ") != "SIGAC-CONTINUIDAD":
            print(json.dumps(resumen, sort_keys=True))
            return 2
        with warnings.catch_warnings():
            # Sin fallback con eco ni mensajes arbitrarios de bibliotecas.
            warnings.simplefilter("error")
            usuario = getpass.getpass("Usuario SIGAC (sin eco): ")
            clave = getpass.getpass("Clave SIGAC (sin eco): ")
            try:
                resumen = ejecutar_continuidad(usuario, clave, total_casos=args.total_casos)
            finally:
                del usuario, clave
        print(json.dumps(resumen, sort_keys=True))
        return {"continuidad_observada": 0, "inconcluso": 3, "error": 1}[resumen["clasificacion"]]
    except KeyboardInterrupt:
        print(json.dumps(resumen_vacio(), sort_keys=True))
        return 130
    except Exception:
        print(json.dumps(resumen_vacio(), sort_keys=True))
        return 1
    finally:
        logging.disable(anterior)


if __name__ == "__main__":
    raise SystemExit(main())
