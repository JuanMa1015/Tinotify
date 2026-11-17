"""Reinicio de la frontera: solo MockTransport y SQLite temporal con datos ficticios."""

import json
from pathlib import Path
import socket
import sys
from uuid import UUID, uuid4

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))


def sin_red(*args, **kwargs):
    raise RuntimeError('Red real bloqueada')


socket.create_connection = socket.getaddrinfo = socket.socket.connect = sin_red

from backend.tests.test_frontera_persistencia_sigac import leer, servicio
from backend.tests.test_sqlite_local_v2 import snapshot


ruta, modo, clave = sys.argv[1:]
s = servicio(Path(ruta))
if modo == 'crear':
    s.observar_validada(leer(2), clave=uuid4(), generacion_esperada=0)
    resultado = s.observar_validada(leer(3), clave=UUID(clave), generacion_esperada=1)
elif modo == 'reabrir':
    antes, raw = snapshot(s), Path(ruta).read_bytes()
    # Este proceso no conserva el registro ni objetos del emisor anterior.
    # Obtiene otra lectura mediante HTTP simulado y recupera el recibo persistido.
    resultado = s.observar_validada(leer(3), clave=UUID(clave), generacion_esperada=1)
    assert snapshot(s) == antes and Path(ruta).read_bytes() == raw
else:
    raise ValueError('Modo de prueba no permitido')

estado = snapshot(s)
print(json.dumps({'resultado': resultado, 'eventos': len(estado['eventos']),
                  'recibos': len(estado['sincronizaciones']),
                  'identidades': sorted(f[1] for f in estado['actuaciones'])}))
