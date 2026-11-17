"""Backend LOCAL de solo lectura sobre el almacén real v2, solo en loopback (127.0.0.1:8000).

  python backend/scripts/servir_real_local.py [--db backend/.local/real_v2.sqlite3]
  python backend/scripts/servir_real_local.py --leer-historial --autorizar-sigac-real --tipo 2 --total-casos 15       --caso-numero N [--minutos 20]

Con `--leer-historial` hace UNA lectura manual de SIGAC en esta terminal (credenciales sin eco, solo en memoria),
verifica el expediente y las huellas de v2 y conserva el historial completo SOLO en memoria de este proceso
durante `--minutos` (20 por defecto, máximo 60). Se invalida al vencer, con DELETE /real/historial o al detener el
proceso. No escribe en SQLite ni cambia la línea base.

Sirve únicamente /real/cases, /real/cases/{id} y /real/observaciones (más /health y las rutas demo sintéticas
existentes). No consulta SIGAC, no recibe credenciales, no habilita /real/sesion ni monitor, no registra envíos
push ni transfiere nada. El código de acceso local se guarda en backend/.local/codigo_acceso_real.txt (ignorado
por git; no se imprime): cópialo al teléfono. `adb reverse` es solo transporte, no autenticación.
"""

import argparse
import getpass
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import warnings

from tinotify.api.demo import crear_app
from tinotify.api.real_local import AccesoLocal
from tinotify.demo.novedades import INSTANCIA_REAL, ServicioNovedadesLocal
from tinotify.demo.servicio import ServicioDemo
from tinotify.persistence.sqlite_local import AlmacenSqliteLocal
from tinotify.services.historial_temporal import HistorialTemporal, TTL_MAXIMO_S, leer_historial_temporal
from tinotify.services.politica_real_local import RUTA_V2_PREDETERMINADA, politica_real_local

RUTA_CODIGO = Path("backend/.local/codigo_acceso_real.txt")
HOST, PUERTO = "127.0.0.1", 8000


def codigo_local(ruta=RUTA_CODIGO):
    ruta = Path(ruta)
    if not ruta.exists():
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(secrets.token_urlsafe(32), encoding="utf-8", newline="\n")
    codigo = ruta.read_text(encoding="utf-8").strip()
    AccesoLocal(codigo)  # valida longitud mínima
    return codigo


CONFIRMACION = "SIGAC-HISTORIAL-TEMPORAL"


def construir_app(db, ruta_codigo=RUTA_CODIGO, historial=None, politica=None):
    db = Path(db)
    if db.suffix != ".sqlite3" or not db.is_file():
        raise SystemExit("El almacén v2 no existe; ejecuta antes la consulta manual.")
    real = ServicioNovedadesLocal(AlmacenSqliteLocal(db, politica=politica, perfil="real"), instancia=INSTANCIA_REAL)  # rechaza v1
    for nombre in ("TINOTIFY_REAL_SESSION", "TINOTIFY_LOCAL_DB", "TINOTIFY_EXPO_ACCESS_TOKEN"):
        os.environ.pop(nombre, None)  # sin sesión SIGAC, sin base sintética y sin token de push
    demo = ServicioDemo([secrets.token_urlsafe(24), secrets.token_urlsafe(24)])  # códigos efímeros, inutilizables
    return crear_app(servicio=demo, real=real, acceso_real=AccesoLocal(codigo_local(ruta_codigo)), gestor=None, historial=historial)


def _leer(args, historial, politica):
    """Lectura manual única. Devuelve el código de salida; los secretos no salen de esta función."""
    from tinotify.integrations.sigac.sigac_client import SigacClient, SigacClientError
    try:
        servicio = ServicioNovedadesLocal(AlmacenSqliteLocal(args.db, politica=politica, perfil="real"), instancia=INSTANCIA_REAL)
        if input(f"Escribe {CONFIRMACION} para autorizar UNA lectura temporal en memoria: ") != CONFIRMACION:
            print("Cancelado sin conexión.")
            return 2
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            usuario = getpass.getpass("Usuario SIGAC (sin eco): ")
            clave = getpass.getpass("Clave SIGAC (sin eco): ")
            caso_login = getpass.getpass("txtCaso (sin eco): ") if args.pedir_caso_login else None
            with SigacClient() as cliente:
                resumen = leer_historial_temporal(
                    cliente, usuario, clave, tipo=args.tipo, total_casos=args.total_casos, caso_numero=args.caso_numero,
                    servicio=servicio, historial=historial, ttl_s=args.minutos * 60,
                    total_actuaciones=args.total_actuaciones, contenedor_id=args.contenedor_historial, caso_login=caso_login)
            del usuario, clave, caso_login
        print(json.dumps(resumen, ensure_ascii=True, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print("Lectura interrumpida; no se conservó nada.")
        return 130
    except SigacClientError as error:
        print(json.dumps({"error": "lectura_rechazada", "codigo": getattr(error.codigo, "value", None)}))
        return 1
    except Exception as error:  # mensajes propios o genéricos: nunca contenido, rutas ni credenciales
        propio = type(error).__name__ in ("HistorialNoCorresponde", "IdentidadExpedienteNoVerificada", "AlmacenLocalNoDisponible")
        print(json.dumps({"error": str(error) if propio else "lectura_detenida_por_error_inesperado"}, ensure_ascii=True))
        return 4 if propio else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backend local de solo lectura sobre el almacén real v2")
    parser.add_argument("--db", type=Path, default=RUTA_V2_PREDETERMINADA)
    parser.add_argument("--leer-historial", action="store_true", help="UNA lectura manual de SIGAC conservada solo en memoria")
    parser.add_argument("--autorizar-sigac-real", action="store_true")
    parser.add_argument("--tipo")
    parser.add_argument("--total-casos", type=int)
    parser.add_argument("--caso-numero", type=int)
    parser.add_argument("--total-actuaciones", type=int)
    parser.add_argument("--contenedor-historial")
    parser.add_argument("--pedir-caso-login", action="store_true")
    parser.add_argument("--minutos", type=int, default=20)
    parser.add_argument("--acreditacion", type=Path)
    args = parser.parse_args(argv)
    historial = politica = None
    if args.leer_historial:
        if not args.autorizar_sigac_real:
            parser.error("Sin autorización explícita no se ejecutan solicitudes SIGAC")
        if not args.tipo or args.total_casos is None or args.total_casos < 1 or args.caso_numero is None or args.caso_numero < 1                 or not 1 <= args.minutos <= TTL_MAXIMO_S // 60 or (args.total_actuaciones is not None and args.total_actuaciones < 1):
            parser.error("Faltan o no son válidos --tipo, --total-casos, --caso-numero o --minutos")
        if not sys.stdin.isatty():
            parser.error("Se requiere una terminal interactiva; no canalizar credenciales")
        logging.disable(logging.CRITICAL)
        try:
            politica = politica_real_local(args.acreditacion)
        except Exception as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=True))
            return 4
        historial = HistorialTemporal(temporizador=True)
    app = construir_app(args.db, politica=politica, historial=historial)
    try:
        if args.leer_historial:
            codigo = _leer(args, historial, politica)
            if codigo != 0:
                return codigo
        import uvicorn
        uvicorn.run(app, host=HOST, port=PUERTO, log_level="warning", access_log=False)
    finally:
        if historial is not None:
            historial.invalidar()  # al detener el proceso no queda contenido


if __name__ == "__main__":
    raise SystemExit(main())
