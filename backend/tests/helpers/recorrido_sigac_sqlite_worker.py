"""Proceso desechable de prueba: HTTP simulado -> identidad -> SQLite sintético.

No es una herramienta de consulta real ni acepta credenciales. Solo usa los
servidores y contenidos ficticios de las pruebas del repositorio.
"""

import json
from pathlib import Path
import socket
import sqlite3
import sys
import time
from uuid import UUID

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))


def sin_red(*args, **kwargs):
    raise RuntimeError('Solo HTTP simulado')


socket.create_connection = socket.getaddrinfo = socket.socket.connect = sin_red

from backend.tests.test_integridad_historial_sigac import bloque, pagina, cliente_sintetico, USUARIO, CLAVE
from tinotify.demo.novedades import CASO_OBSERVADO, ServicioNovedadesLocal
from tinotify.persistence.sqlite_local import AlmacenSqliteLocal, CREDENCIAL_LOCAL, ConflictoPersistenciaLocal


ruta, cantidad, generacion, clave, modo, *extras = sys.argv[1:]
contenido = pagina(*(bloque(f'CONTENIDO_SINTETICO_{n}') for n in range(int(cantidad))))
almacen = AlmacenSqliteLocal(ruta, perfil='sintetico')
servicio = ServicioNovedadesLocal(almacen)
with cliente_sintetico([contenido]) as (cliente, llamadas):
    cliente.autenticar(USUARIO, CLAVE, tipo='2', total_casos_esperado=1)
    actuaciones = cliente.consultar_historial(101)
    assert len(llamadas) == 7
    # Este harness opera solo con su fixture conocida y sintética. El código
    # de aplicación real debe usar leer_historial_validado/observar_validada.
    actuaciones = list(actuaciones)

if modo == 'barrera':
    listo, salida = map(Path, extras)
    listo.write_text('listo', encoding='utf-8')
    limite = time.monotonic() + 15
    while not salida.exists():
        if time.monotonic() > limite:
            raise RuntimeError('Barrera agotada')
        time.sleep(0.01)

if modo == 'incierto':
    commit_original = almacen._commit
    perdido = False
    def perder_respuesta(conexion):
        global perdido
        commit_original(conexion)
        if not perdido:
            perdido = True
            raise sqlite3.OperationalError('Fallo sintetico despues de COMMIT')
    almacen._commit = perder_respuesta

try:
    if modo == 'recibo':
        r = servicio.consultar_recibo(CASO_OBSERVADO, actuaciones, clave=UUID(clave),
                                     generacion_esperada=int(generacion))
        resultado = {'recibo_encontrado': r is not None, 'repetido': r.repetido if r else None}
    else:
        resultado = servicio.observar(CASO_OBSERVADO, actuaciones, clave=UUID(clave),
                                      generacion_esperada=int(generacion))
except ConflictoPersistenciaLocal:
    resultado = {'conflicto': True}

with almacen.transaccion(CREDENCIAL_LOCAL, lectura=True) as unidad:
    vista = unidad.vista(CASO_OBSERVADO)
    recibos = [tuple(f) for f in unidad._c.execute(
        'SELECT clave, id, generacion_confirmada FROM sincronizaciones ORDER BY rowid')]
    eventos = [tuple(f) for f in unidad._c.execute(
        'SELECT id, local_id, tipo, disposicion FROM eventos ORDER BY rowid')]
print(json.dumps({'resultado': resultado, 'generacion': vista['generacion'],
                  'identidades': [a['local_id'] for a in vista['actuaciones']],
                  'recibos': recibos, 'eventos': eventos, 'solicitudes': len(llamadas)}))
