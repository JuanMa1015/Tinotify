"""Entrada persistente SIGAC: `consultar` solo para expedientes acreditados; `monitorear` deshabilitado.

Solo la ejecuta la persona autorizada; la API nunca inicia consultas. Sin la bandera y la confirmación
interactiva no abre conexiones. Las credenciales se piden sin eco, viven solo en memoria y no se guardan
ni se imprimen. `consultar` exige `--caso-numero` de un expediente acreditado por el contrato de continuidad
observada y la clave local de acreditación; usa el almacén v2 (`--db`, por defecto backend/.local/real_v2.sqlite3).
No transfiere nada a Render ni a Supabase ni activa avisos. `monitorear` sigue deshabilitado.

  python backend/scripts/sigac_local.py consultar --autorizar-sigac-real --tipo <cboTipo> --total-casos 15 --caso-numero N
  python backend/scripts/sigac_local.py monitorear --autorizar-sigac-real --tipo <cboTipo> --total-casos 15 --caso-numero N
  python backend/scripts/sigac_local.py estado

`monitorear` mantiene UNA sesión autorizada y consulta cada 30 minutos (mínimo 10, máximo 240) hasta Ctrl+C. Si la
sesión vence o SIGAC restringe el acceso, se detiene: hay que volver a autorizar. No hay reautenticación automática.
"""

import argparse
import getpass
import json
import logging
from pathlib import Path
import sys
import warnings

from tinotify.demo.novedades import ObservacionRechazada, ServicioNovedadesLocal
from tinotify.integrations.sigac.sigac_client import SigacClient, SigacClientError
from tinotify.persistence.sqlite_local import AlmacenLocalNoDisponible, AlmacenSqliteLocal
from tinotify.demo.novedades import INSTANCIA_REAL
from tinotify.services.consulta_real_local import (
    IdentidadExpedienteNoVerificada, consultar_caso_acreditado, consultar_expediente, exigir_identidad_expediente,
)
from tinotify.services.politica_real_local import RUTA_V2_PREDETERMINADA, politica_real_local
from tinotify.services.monitor_local import (
    INTERVALO_MAXIMO_S, INTERVALO_MINIMO_S, INTERVALO_PREDETERMINADO_S, BloqueoMonitor, MonitorEnEjecucion, monitorear,
)

RUTA_PREDETERMINADA = RUTA_V2_PREDETERMINADA
CONFIRMACION = "SIGAC-CONSULTA-LOCAL"
CONFIRMACION_MONITOR = "SIGAC-MONITOR-LOCAL"


def _imprimir(evento):
    """Solo estado operativo, cantidades, códigos y horas."""
    print(json.dumps(evento, ensure_ascii=True, sort_keys=True), flush=True)


def _ejecutar_monitor(parser, args):
    minutos = args.intervalo_minutos
    if not INTERVALO_MINIMO_S // 60 <= minutos <= INTERVALO_MAXIMO_S // 60:
        parser.error(f"El intervalo debe estar entre {INTERVALO_MINIMO_S // 60} y {INTERVALO_MAXIMO_S // 60} minutos")
    if args.max_ciclos is not None and args.max_ciclos < 1:
        parser.error("El máximo de ciclos debe ser positivo")
    try:
        print(f"Este monitor consultará SIGAC cada {minutos} minutos mientras siga activo. Ctrl+C lo detiene.")
        if input(f"Escribe {CONFIRMACION_MONITOR} para autorizar el monitor: ") != CONFIRMACION_MONITOR:
            print("Cancelado sin conexión.")
            return 2
        servicio = _servicio(args.db)  # valida archivo y perfil ANTES de pedir credenciales
        with BloqueoMonitor(args.db):
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                secretos = {"usuario": getpass.getpass("Usuario SIGAC (sin eco): "),
                            "clave": getpass.getpass("Clave SIGAC (sin eco): "),
                            "caso_login": getpass.getpass("txtCaso (sin eco): ") if args.pedir_caso_login else None}
                with SigacClient() as cliente:
                    def entrar():
                        # Única autenticación del monitor; los secretos se descartan en cuanto se usan.
                        try:
                            return cliente.autenticar(
                                secretos["usuario"], secretos["clave"], tipo=args.tipo,
                                total_casos_esperado=args.total_casos, caso_login=secretos["caso_login"])
                        finally:
                            secretos.clear()
                    resultado = monitorear(
                        cliente, entrar, total_casos=args.total_casos, caso_numero=args.caso_numero, servicio=servicio,
                        etiqueta=args.etiqueta, total_actuaciones=args.total_actuaciones,
                        contenedor_id=args.contenedor_historial, intervalo_s=minutos * 60,
                        max_ciclos=args.max_ciclos, emitir=_imprimir)
        return resultado.codigo_salida
    except KeyboardInterrupt:
        print("Monitor interrumpido; no quedan consultas en curso.")
        return 130
    except MonitorEnEjecucion as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True))
        return 1
    except AlmacenLocalNoDisponible as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True))
        return 1
    except ValueError:
        print(json.dumps({"error": "Argumentos locales no válidos (revisa el archivo .sqlite3 y la etiqueta)."},
                         ensure_ascii=True))
        return 1
    except Exception:
        print("Monitor detenido por un error inesperado; no se muestran detalles sensibles.")
        return 1


def _servicio(ruta, politica=None):
    if ruta.suffix != ".sqlite3":
        raise ValueError("El archivo local debe terminar en .sqlite3")
    return ServicioNovedadesLocal(AlmacenSqliteLocal(ruta, politica=politica, perfil="real"), instancia=INSTANCIA_REAL)


def _ejecutar_consulta(parser, args, politica):
    try:
        if input(f"Escribe {CONFIRMACION} para autorizar UNA consulta manual: ") != CONFIRMACION:
            print("Cancelado sin conexión.")
            return 2
        servicio = _servicio(args.db, politica)  # valida archivo y perfil ANTES de pedir credenciales
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            usuario = getpass.getpass("Usuario SIGAC (sin eco): ")
            clave = getpass.getpass("Clave SIGAC (sin eco): ")
            caso_login = getpass.getpass("txtCaso (sin eco): ") if args.pedir_caso_login else None
            with SigacClient() as cliente:
                resultado = consultar_caso_acreditado(
                    cliente, usuario, clave, tipo=args.tipo, total_casos=args.total_casos, caso_numero=args.caso_numero,
                    servicio=servicio, total_actuaciones=args.total_actuaciones,
                    contenedor_id=args.contenedor_historial, caso_login=caso_login)
        print(json.dumps(resultado, ensure_ascii=True, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print("Consulta interrumpida; no quedan consultas en curso.")
        return 130
    except IdentidadExpedienteNoVerificada as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True))
        return 4
    except ObservacionRechazada:
        print(json.dumps({"error": "observacion_rechazada", "persistencia": "sin_cambios"}))
        return 3
    except SigacClientError as error:
        print(json.dumps({"error": "lectura_rechazada", "codigo": getattr(error.codigo, "value", None)}))
        return 1
    except AlmacenLocalNoDisponible as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True))
        return 1
    except Exception:
        print("Consulta detenida por un error inesperado; no se muestran detalles sensibles.")
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Consulta SIGAC manual y autorizada hacia la persistencia local")
    parser.add_argument("--db", type=Path, default=RUTA_PREDETERMINADA)
    sub = parser.add_subparsers(dest="orden", required=True)
    sub.add_parser("estado", help="Cantidades del almacén local real; no accede a SIGAC")
    c = sub.add_parser("consultar")
    c.add_argument("--autorizar-sigac-real", action="store_true")
    c.add_argument("--tipo", required=True, help="Valor observado de la opción cboTipo; sin adivinarlo")
    c.add_argument("--total-casos", type=int, required=True, help="Total completo, incluidas todas las páginas")
    c.add_argument("--caso-numero", type=int, required=True, help="Número de caso (Caso Nro.) tal como aparece en el listado")
    c.add_argument("--total-actuaciones", type=int, help="Opcional: contrastar un total conocido")
    c.add_argument("--etiqueta", help="Nombre local mostrado en la app (hasta 60 caracteres)")
    c.add_argument("--contenedor-historial", help="ID real del ámbito completo, si está demostrado")
    c.add_argument("--pedir-caso-login", action="store_true", help="Pedir txtCaso sin eco")
    c.add_argument("--acreditacion", type=Path, help="Archivo local con la clave de acreditación")
    m = sub.add_parser("monitorear", help="Consultas periódicas durante una sesión autorizada")
    for opcion, kwargs in (
        ("--autorizar-sigac-real", {"action": "store_true"}),
        ("--tipo", {"required": True, "help": "Valor observado de la opción cboTipo; sin adivinarlo"}),
        ("--total-casos", {"type": int, "required": True, "help": "Total completo, incluidas todas las páginas"}),
        ("--caso-numero", {"type": int, "required": True, "help": "Número de caso (Caso Nro.) tal como aparece en el listado"}),
        ("--total-actuaciones", {"type": int, "help": "Opcional: contrastar un total conocido"}),
        ("--etiqueta", {"help": "Nombre local mostrado en la app (hasta 60 caracteres)"}),
        ("--contenedor-historial", {"help": "ID real del ámbito completo, si está demostrado"}),
        ("--pedir-caso-login", {"action": "store_true", "help": "Pedir txtCaso sin eco"}),
        ("--intervalo-minutos", {"type": int, "default": INTERVALO_PREDETERMINADO_S // 60,
                                 "help": f"Entre {INTERVALO_MINIMO_S // 60} y {INTERVALO_MAXIMO_S // 60}; por defecto 30"}),
        ("--max-ciclos", {"type": int, "help": "Opcional: detenerse tras este número de consultas"}),
    ):
        m.add_argument(opcion, **kwargs)
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)

    if args.orden == "estado":
        try:
            servicio = _servicio(args.db)
            print(json.dumps({"casos": [{k: v for k, v in caso.items() if k != "id"}
                                        for caso in servicio.listar_casos()],
                              "observaciones_internas": len(servicio.observaciones()['observaciones']),
                              "cobertura": "desconocida", "entrega_externa": "no_autorizada"}, sort_keys=True))
            return 0
        except AlmacenLocalNoDisponible as error:
            print(json.dumps({"error": str(error)}))
            return 1
        except ValueError:
            print(json.dumps({"error": "Archivo local no válido (debe terminar en .sqlite3)."}))
            return 1

    if not args.autorizar_sigac_real:
        parser.error("Sin autorización explícita no se ejecutan solicitudes SIGAC")
    if args.total_casos < 1 or args.caso_numero < 1 or (
            args.total_actuaciones is not None and args.total_actuaciones < 1):
        parser.error("Totales o posición no válidos")
    if not sys.stdin.isatty():
        parser.error("Se requiere una terminal interactiva; no canalizar credenciales")
    if args.orden == 'monitorear' and not INTERVALO_MINIMO_S // 60 <= args.intervalo_minutos <= INTERVALO_MAXIMO_S // 60:
        parser.error('Intervalo no permitido')
    if args.orden == 'monitorear':
        print(json.dumps({'error': 'Monitor SIGAC real deshabilitado: solo se permite la consulta manual'}))
        return 4
    # Compuerta de política: sin la clave local y un compromiso que coincida con el número, no hay conexión.
    try:
        politica = politica_real_local(args.acreditacion)
        exigir_identidad_expediente(politica, args.caso_numero)
    except IdentidadExpedienteNoVerificada as error:
        print(json.dumps({'error': str(error)}))
        return 4
    return _ejecutar_consulta(parser, args, politica)


if __name__ == "__main__":
    raise SystemExit(main())
