"""Exporta la referencia portable (huellas con clave) desde v2, solo lectura. Imprime solo conteos.

  python backend/scripts/exportar_referencia_portable.py [--db backend/.local/real_v2.sqlite3]
      [--acreditacion backend/.local/acreditacion_sigac.json] [--salida backend/.local/referencia_portable.json]

El archivo resultante es un secreto (contiene el número de caso): súbelo como Secret File, nunca al repositorio.
"""

import argparse
import json
import logging
from pathlib import Path

from tinotify.services.exportar_referencia import exportar
from tinotify.services.politica_real_local import RUTA_ACREDITACION, RUTA_V2_PREDETERMINADA


def main(argv=None):
    parser = argparse.ArgumentParser(description="Exportador local de la referencia portable")
    parser.add_argument("--db", type=Path, default=RUTA_V2_PREDETERMINADA)
    parser.add_argument("--acreditacion", type=Path, default=RUTA_ACREDITACION)
    parser.add_argument("--salida", type=Path, default=Path("backend/.local/referencia_portable.json"))
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        print(json.dumps(exportar(args.db, args.acreditacion, args.salida), sort_keys=True))
        return 0
    except Exception as error:
        propio = type(error).__name__ in ("ReferenciaPortableInvalida", "IdentidadExpedienteNoVerificada", "FileExistsError")
        print(json.dumps({"error": str(error) if propio else "exportacion_detenida_por_error_inesperado"}))
        return 4 if propio else 1


if __name__ == "__main__":
    raise SystemExit(main())
