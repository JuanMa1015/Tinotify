"""UNA lectura real, de solo lectura, contra las huellas del almacén v1. Requiere autorización específica.

  python backend/scripts/comparar_v1_sigac.py --autorizar-sigac-real --tipo <cboTipo> --total-casos <N> --caso-numero <N> [--db backend/.local/real.sqlite3]

No guarda nada, no migra ni modifica el archivo v1 (se abre inmutable y solo lectura), no activa monitor ni
avisos. Credenciales sin eco y solo en memoria. Imprime únicamente conteos y un veredicto.
Códigos de salida: 0 continuidad observada; 3 rechazada; 1 error; 2 cancelado; 130 interrumpido.
"""

import argparse
import getpass
import json
import logging
from pathlib import Path
import sys
import warnings

from tinotify.integrations.sigac.sigac_client import SigacClient, SigacClientError
from tinotify.services.comparacion_v1_sigac import ComparacionNoPosible, ejecutar_comparacion, leer_huellas_v1

CONFIRMACION = "SIGAC-COMPARAR-V1"
RUTA_PREDETERMINADA = Path("backend/.local/real.sqlite3")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Comparación de una lectura real con v1; sin persistencia")
    parser.add_argument("--db", type=Path, default=RUTA_PREDETERMINADA)
    parser.add_argument("--autorizar-sigac-real", action="store_true")
    parser.add_argument("--tipo", required=True, help="Valor observado de la opción cboTipo; sin adivinarlo")
    parser.add_argument("--total-casos", type=int, required=True, help="Total completo, incluidas todas las páginas")
    parser.add_argument("--caso-numero", type=int, required=True, help="Número de caso (Caso Nro.)")
    parser.add_argument("--total-actuaciones", type=int, help="Opcional: contrastar un total conocido")
    parser.add_argument("--contenedor-historial", help="ID real del ámbito completo, si está demostrado")
    parser.add_argument("--pedir-caso-login", action="store_true", help="Pedir txtCaso sin eco")
    args = parser.parse_args(argv)
    if not args.autorizar_sigac_real:
        parser.error("Sin autorización explícita no se ejecutan solicitudes SIGAC")
    if args.total_casos < 1 or args.caso_numero < 1 or (args.total_actuaciones is not None and args.total_actuaciones < 1):
        parser.error("Totales o número de caso no válidos")
    if not sys.stdin.isatty():
        parser.error("Se requiere una terminal interactiva; no canalizar credenciales")
    logging.disable(logging.CRITICAL)
    try:
        leer_huellas_v1(args.db)  # valida v1 ANTES de pedir credenciales o abrir conexiones
        if input(f"Escribe {CONFIRMACION} para autorizar UNA lectura de solo lectura: ") != CONFIRMACION:
            print("Cancelado sin conexión.")
            return 2
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            usuario = getpass.getpass("Usuario SIGAC (sin eco): ")
            clave = getpass.getpass("Clave SIGAC (sin eco): ")
            caso_login = getpass.getpass("txtCaso (sin eco): ") if args.pedir_caso_login else None
            with SigacClient() as cliente:
                resumen = ejecutar_comparacion(
                    cliente, usuario, clave, tipo=args.tipo, total_casos=args.total_casos, caso_numero=args.caso_numero,
                    ruta_v1=args.db, total_actuaciones=args.total_actuaciones,
                    contenedor_id=args.contenedor_historial, caso_login=caso_login)
        print(json.dumps(resumen, ensure_ascii=True, sort_keys=True))
        return 0 if resumen.get("veredicto") == "continuidad_observada" else 3
    except KeyboardInterrupt:
        print("Comparación interrumpida; no se guardó nada.")
        return 130
    except ComparacionNoPosible as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True))
        return 1
    except SigacClientError as error:
        print(json.dumps({"error": "lectura_rechazada", "codigo": getattr(error.codigo, "value", None)}, ensure_ascii=True))
        return 1
    except Exception:
        print("Comparación detenida por un error inesperado; no se muestran detalles sensibles.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
