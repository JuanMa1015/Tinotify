"""Preflight LOCAL del backend remoto real (sin red, sin SIGAC). Lee TINOTIFY_RR_* del entorno del proceso.

  $env:TINOTIFY_RR_MODO='remoto'; $env:TINOTIFY_RR_TOKEN='<token>'; $env:TINOTIFY_RR_TLS='proxy'
  $env:TINOTIFY_RR_PROXIES_CONFIABLES='privadas'
  $env:TINOTIFY_RR_ACREDITACION_FILE='backend/.local/acreditacion_sigac.json'
  $env:TINOTIFY_RR_REFERENCIA_FILE='backend/.local/referencia_portable.json'
  python backend/scripts/verificar_despliegue_real_remoto.py

Imprime solo booleanos, conteos y el código del primer fallo (y NOMBRES de variables ajenas, nunca valores).
Código de salida 0 si el servicio arrancaría.
"""

import json
import logging
import os

from tinotify.real_remoto.preflight import verificar


def main():
    logging.disable(logging.CRITICAL)
    resultado = verificar(os.environ)
    print(json.dumps(resultado, sort_keys=True))
    return 0 if resultado.get("aplicacion") else 4


if __name__ == "__main__":
    raise SystemExit(main())
