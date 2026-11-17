"""Punto de entrada manual. Sin flag y confirmación interactiva no abre conexiones."""

import argparse
import getpass
import json
import logging
import sys
import warnings

from tinotify.integrations.sigac.sigac_client import SigacClient, SigacClientError, SigacSessionExpired
from tinotify.parsers.diagnostico_historial import (
    CodigoHistorial, ContextoDiagnostico, EtapaSigac, diagnostico_seguro,
)
from tinotify.services.ensayo_sigac import ejecutar_ensayo


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ensayo SIGAC de solo lectura, sin persistencia ni notificaciones")
    parser.add_argument("--autorizar-sigac-real", action="store_true")
    parser.add_argument("--tipo", required=True, help="Valor observado de la opción cboTipo; sin adivinarlo")
    parser.add_argument("--total-casos", type=int, required=True, help="Total completo, incluidas todas las páginas")
    parser.add_argument("--indice-caso", type=int, default=1, help="Posición desde 1 en el listado contrastado")
    parser.add_argument("--total-actuaciones", type=int,
                        help="Opcional: contrastar un total conocido; sin él, completitud_no_verificada")
    parser.add_argument("--consultas", type=int, choices=[2, 3], default=2)
    parser.add_argument("--diagnostico", action="store_true", help="Solo códigos de fallo y conteos estructurales")
    parser.add_argument("--contenedor-historial", help="ID real del ámbito completo, si está demostrado")
    parser.add_argument("--pedir-caso-login", action="store_true", help="Pedir txtCaso sin eco; por defecto usar el formulario")
    args = parser.parse_args(argv)
    if not args.autorizar_sigac_real:
        parser.error("Sin autorización explícita no se ejecutan solicitudes SIGAC")
    if (args.total_casos < 1 or (args.total_actuaciones is not None and args.total_actuaciones < 1)
            or not 1 <= args.indice_caso <= args.total_casos):
        parser.error("Totales o posición no válidos")
    if not sys.stdin.isatty():
        parser.error("Se requiere una terminal interactiva; no canalizar credenciales")
    # También bloquea loggers hijos httpcore.* que podrían registrar Set-Cookie.
    # Este ejecutable es un proceso dedicado, no una configuración de FastAPI.
    logging.disable(logging.CRITICAL)
    contexto = ContextoDiagnostico()
    try:
        if input("Escribe SIGAC-LECTURA para confirmar el ensayo autorizado: ") != "SIGAC-LECTURA":
            print("Cancelado sin conexión.")
            return 2
        with warnings.catch_warnings():
            contexto.marcar(EtapaSigac.CREDENCIALES)
            warnings.simplefilter("error", getpass.GetPassWarning)
            usuario = getpass.getpass("Usuario SIGAC (sin eco): ")
            clave = getpass.getpass("Clave SIGAC (sin eco): ")
            caso_login = getpass.getpass("txtCaso (sin eco): ") if args.pedir_caso_login else None
        with warnings.catch_warnings():
            if args.diagnostico:
                # Una advertencia de biblioteca tampoco puede imprimir contenido.
                warnings.simplefilter("error")
            contexto.marcar(EtapaSigac.CREACION_CLIENTE)
            cliente = SigacClient()
            cliente.contexto = contexto
            with cliente:
                resumen = ejecutar_ensayo(cliente, usuario, clave, tipo=args.tipo, total_casos=args.total_casos,
                                          total_actuaciones=args.total_actuaciones, indice_caso=args.indice_caso,
                                          repeticiones=args.consultas, contenedor_id=args.contenedor_historial,
                                          caso_login=caso_login, diagnostico=args.diagnostico)
        contexto.marcar(EtapaSigac.SALIDA)
        if args.diagnostico:
            codigo = CodigoHistorial.LECTURA_ESTABLE if resumen["resultado"] == "estable" else CodigoHistorial.LECTURA_CON_CAMBIOS
            resumen = {**resumen, **diagnostico_seguro(codigo, etapa=EtapaSigac.FINALIZADO)}
        print(json.dumps(resumen, ensure_ascii=True, sort_keys=True))
        contexto.marcar(EtapaSigac.FINALIZADO)
        return 0 if resumen["resultado"] == "estable" else 3
    except KeyboardInterrupt:
        print("Ensayo interrumpido; no se guardó estado.")
        return 130
    except SigacClientError as error:
        if args.diagnostico:
            codigo = error.codigo
            if codigo is CodigoHistorial.NO_CLASIFICADO:
                codigo = CodigoHistorial.SESION_NO_CONFIRMADA if isinstance(error, SigacSessionExpired) else CodigoHistorial.ERROR_INTERNO
            datos = error.diagnostico if isinstance(error.diagnostico, dict) else {}
            etapa = error.etapa if error.etapa is not EtapaSigac.NO_DETERMINADA else contexto.etapa
            print(json.dumps(diagnostico_seguro(codigo, datos.get("estadisticas_estructurales"), etapa=etapa),
                             ensure_ascii=True, sort_keys=True))
        else:
            print(str(error))
        return 1
    except Warning:
        if args.diagnostico:
            print(json.dumps(diagnostico_seguro(CodigoHistorial.ADVERTENCIA_BIBLIOTECA, etapa=contexto.etapa), sort_keys=True))
        else:
            print("Ensayo detenido por una advertencia; no se muestran detalles sensibles.")
        return 1
    except Exception:
        if args.diagnostico:
            print(json.dumps(diagnostico_seguro(CodigoHistorial.ERROR_INTERNO, etapa=contexto.etapa), sort_keys=True))
        else:
            print("Ensayo detenido por un error inesperado; no se muestran detalles sensibles.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
