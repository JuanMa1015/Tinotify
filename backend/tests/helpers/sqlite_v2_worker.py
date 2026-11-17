"""Proceso de pruebas: solo SQLite temporal y actuaciones sintéticas, sin red."""

import json
import os
from pathlib import Path
import socket
import sys
import time
from uuid import UUID

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))


def prohibido(*args, **kwargs):
    raise RuntimeError('Red prohibida')


socket.create_connection = socket.getaddrinfo = socket.socket.connect = prohibido

from tinotify.demo.novedades import CASO_OBSERVADO, ServicioNovedadesLocal, html_historial_sintetico
from tinotify.parsers.parser import parse_actuaciones
from tinotify.persistence.sqlite_local import AlmacenSqliteLocal, ConflictoPersistenciaLocal


ruta, cantidad, generacion, clave, modo, *extras = sys.argv[1:]
almacen = AlmacenSqliteLocal(ruta)
servicio = ServicioNovedadesLocal(almacen)
actuaciones = parse_actuaciones(html_historial_sintetico(int(cantidad)), CASO_OBSERVADO)
if modo == 'barrera':
    listo, salida = map(Path, extras)
    listo.write_text('listo', encoding='utf-8')
    limite = time.monotonic() + 15
    while not salida.exists():
        if time.monotonic() > limite:
            raise RuntimeError('Barrera agotada')
        time.sleep(0.01)
if modo in ('antes', 'durante', 'despues'):
    abrir_original = almacen._abrir
    def abrir_con_spill():
        conexion = abrir_original()
        conexion.execute('PRAGMA cache_size=1')
        return conexion
    almacen._abrir = abrir_con_spill
    def commit(conexion):
        if modo == 'antes':
            os._exit(71)
        if modo == 'durante':
            conexion.set_progress_handler(lambda: os._exit(72), 1)
        conexion.execute('COMMIT')
        os._exit(73)
    almacen._commit = commit
try:
    if modo == 'recibo':
        recibo = servicio.consultar_recibo(CASO_OBSERVADO, actuaciones, clave=UUID(clave), generacion_esperada=int(generacion))
        print(json.dumps({'confirmado': recibo is not None, 'trabajo': str(recibo.trabajo_id) if recibo else None}))
    else:
        resultado = servicio.observar(CASO_OBSERVADO, actuaciones, clave=UUID(clave), generacion_esperada=int(generacion))
        with almacen.transaccion('tinotify-desarrollo-local', lectura=True) as unidad:
            filas = unidad.vista(CASO_OBSERVADO)['actuaciones']
            recibos = [tuple(f) for f in unidad._c.execute('SELECT clave,id,generacion_confirmada FROM sincronizaciones ORDER BY clave')]
        print(json.dumps({'resultado': resultado, 'identidades': sorted(f['local_id'] for f in filas), 'recibos': recibos}))
except ConflictoPersistenciaLocal:
    print(json.dumps({'conflicto_generacion_o_idempotencia': True}))
