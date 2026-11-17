"""Regresiones de los cuatro bloqueos confirmados en la auditoría.

No xfail ni excepciones de seguridad. Solo bases nuevas temporales y datos ficticios.
El contrato público corregido debe rechazarlos, sin migración de archivos.
"""

import socket
from uuid import uuid4

import pytest

from backend.tests.helpers.sigac_detalle import detalle
from backend.tests.test_sigac_flujo import historial_generico
from backend.tests.test_sqlite_local_v2 import lote
from tinotify.demo.novedades import CASO_OBSERVADO, ServicioNovedadesLocal, INSTANCIA_REAL
from tinotify.integrations.sigac.sigac_client import SigacIdentityError
from tinotify.persistence.sqlite_local import (
    AlmacenSqliteLocal, CREDENCIAL_LOCAL, WORKER_LOCAL, BINDING_LOCAL, ConflictoPersistenciaLocal,
)
from tinotify.services.observacion_local import ObservacionRechazada
from tinotify.services.seguimiento import ServicioSeguimiento


@pytest.mark.parametrize('entrada', ['html', 'actuaciones', 'seguimiento'])
def test_perfil_real_debe_rechazar_entradas_sin_validacion_sigac(tmp_path, monkeypatch, entrada):
    def prohibido(*args, **kwargs):
        pytest.fail('No se permite red')
    monkeypatch.setattr(socket, 'create_connection', prohibido)
    monkeypatch.setattr(socket.socket, 'connect', prohibido)
    almacen = AlmacenSqliteLocal(tmp_path/'perfil-real-solo-datos-sinteticos.sqlite3', perfil='real')
    s = ServicioNovedadesLocal(almacen, instancia=INSTANCIA_REAL)
    with pytest.raises((SigacIdentityError, ObservacionRechazada, PermissionError)):
        if entrada == 'html':
            # Contradicción conocida que el cliente HTTP rechazaría.
            s.observar_html(CASO_OBSERVADO, detalle(historial_generico(), cabecera='202'),
                            clave=uuid4(), generacion_esperada=0)
        elif entrada == 'actuaciones':
            s.observar(CASO_OBSERVADO, lote(), clave=uuid4(), generacion_esperada=0)
        else:
            ServicioSeguimiento(almacen, instancia=INSTANCIA_REAL).sincronizar(
                CREDENCIAL_LOCAL, CASO_OBSERVADO, lote(), clave=uuid4(), worker=WORKER_LOCAL, binding=BINDING_LOCAL)


def test_seguimiento_sqlite_debe_rechazar_misma_clave_con_contenido_distinto(tmp_path):
    almacen = AlmacenSqliteLocal(tmp_path/'solo-sintetico.sqlite3')
    seguimiento = ServicioSeguimiento(almacen)
    clave = uuid4()
    seguimiento.sincronizar(CREDENCIAL_LOCAL, CASO_OBSERVADO, lote(), clave=clave,
                            worker=WORKER_LOCAL, binding=BINDING_LOCAL)
    with pytest.raises(ConflictoPersistenciaLocal):
        seguimiento.sincronizar(CREDENCIAL_LOCAL, CASO_OBSERVADO, lote(3), clave=clave,
                                worker=WORKER_LOCAL, binding=BINDING_LOCAL)
