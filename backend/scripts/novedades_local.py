"""Herramienta LOCAL para simular observaciones sintéticas y consultar el estado persistido.

No consulta SIGAC, no acepta credenciales y no usa red. Cada ejecución es un proceso nuevo, así que
reiniciar el backend o esta herramienta no pierde nada: el estado vive en el archivo SQLite.

Uso (desde la raíz del repositorio):
  python backend/scripts/novedades_local.py observar --actuaciones 3     # baseline
  python backend/scripts/novedades_local.py observar --actuaciones 4     # exactamente 1 novedad
  python backend/scripts/novedades_local.py observar --actuaciones 4     # repetición: 0 novedades
  python backend/scripts/novedades_local.py estado
  Para otro ensayo: usar --db con una ruta nueva; no se borran archivos previos.
"""

import argparse
import json
from pathlib import Path
import sys

from tinotify.demo.novedades import (
    CASO_OBSERVADO, ObservacionRechazada, ServicioNovedadesLocal, html_historial_sintetico,
)
from tinotify.persistence.sqlite_local import AlmacenLocalNoDisponible, AlmacenSqliteLocal

RUTA_PREDETERMINADA = Path("backend/.local/novedades.sqlite3")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Observaciones sintéticas locales; sin SIGAC ni red.")
    parser.add_argument("--db", type=Path, default=RUTA_PREDETERMINADA)
    sub = parser.add_subparsers(dest="orden", required=True)
    observar = sub.add_parser("observar")
    observar.add_argument("--actuaciones", type=int, required=True)
    sub.add_parser("estado")
    reiniciar = sub.add_parser("reiniciar")
    reiniciar.add_argument("--confirmar", action="store_true")
    args = parser.parse_args(argv)

    if args.orden == "reiniciar":
        print(json.dumps({'error': 'Reinicio deshabilitado; conservar archivos existentes y usar una ruta nueva'}))
        return 2
    try:
        servicio = ServicioNovedadesLocal(AlmacenSqliteLocal(args.db))
        if args.orden == "observar":
            resultado = servicio.observar_html(CASO_OBSERVADO, html_historial_sintetico(args.actuaciones))
        else:
            resultado = {"casos": servicio.listar_casos(), "novedades_pendientes": len(servicio.novedades())}
    except (ObservacionRechazada, ValueError) as error:
        print(json.dumps({"error": str(error)}))
        return 1
    except AlmacenLocalNoDisponible as error:
        print(json.dumps({"error": str(error)}))
        return 1
    print(json.dumps(resultado, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
