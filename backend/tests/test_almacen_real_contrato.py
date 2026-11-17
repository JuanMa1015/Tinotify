"""Contrato del almacén del monitor: las MISMAS pruebas contra el almacén en memoria y contra PostgreSQL real.

PostgreSQL (contenedor desechable con el esquema `tinotify_real` ya aplicado) solo se usa si están estas variables, que pone
`supabase/checks/validar_almacen_real_python.sh`: TINOTIFY_TEST_PG_HOST, _PORT, _USER, _PASSWORD (login restringido) y
TINOTIFY_TEST_PG_ADMIN_USER y _ADMIN_PASSWORD (administrador del contenedor, solo para limpiar entre pruebas). TLS desactivado: solo existe en pruebas, en código.
"""

from collections import Counter
import os
import threading

import pytest

from backend.tests.helpers.monitor_real import AlmacenMemoria
from tinotify.real_remoto.config import ConfigPg
from tinotify.real_remoto.monitor import planificar

H = lambda n: f"{n:064x}"  # noqa: E731
R = lambda n: f"{n + 10**20:064x}"  # noqa: E731
NONCE, CIFRADO = bytes(12), bytes(range(40))


def _pg():
    if not os.environ.get("TINOTIFY_TEST_PG_HOST"):
        pytest.skip("PostgreSQL desechable no configurado (ver supabase/checks/validar_almacen_real_python.sh)")
    import psycopg
    from tinotify.real_remoto.almacen import AlmacenPg
    e = os.environ
    cfg = ConfigPg(e["TINOTIFY_TEST_PG_HOST"], int(e.get("TINOTIFY_TEST_PG_PORT", "5432")), "postgres", e["TINOTIFY_TEST_PG_USER"],
                   e["TINOTIFY_TEST_PG_PASSWORD"], None, tls=False)
    with psycopg.connect(host=cfg.host, port=cfg.puerto, dbname="postgres", user=e["TINOTIFY_TEST_PG_ADMIN_USER"],
                       password=e["TINOTIFY_TEST_PG_ADMIN_PASSWORD"], autocommit=True) as admin:
        admin.execute("TRUNCATE tinotify_real.huellas, tinotify_real.estado_expediente, tinotify_real.avisos, "
                      "tinotify_real.ejecuciones, tinotify_real.credenciales, tinotify_real.dispositivos CASCADE")
    return AlmacenPg(cfg)


@pytest.fixture(params=["memoria", "postgres"])
def almacen(request):
    return AlmacenMemoria() if request.param == "memoria" else _pg()


def test_la_marca_de_entorno_y_las_credenciales_cifradas_se_guardan_actualizan_y_olvidan(almacen):
    almacen.verificar()
    assert almacen.credenciales() is None and almacen.estado()["credenciales_guardadas"] is False
    almacen.guardar_credenciales(1, NONCE, CIFRADO)
    assert almacen.credenciales() == (1, NONCE, CIFRADO) and almacen.estado()["credenciales_guardadas"] is True
    almacen.guardar_credenciales(1, bytes([7]) * 12, bytes([9]) * 41)                     # sustituye, no duplica
    assert almacen.credenciales() == (1, bytes([7]) * 12, bytes([9]) * 41)
    assert almacen.olvidar_credenciales() is True and almacen.olvidar_credenciales() is False and almacen.credenciales() is None


def test_las_ejecuciones_se_registran_con_resultado_y_el_estado_muestra_la_ultima(almacen):
    assert almacen.estado()["ultima_ejecucion"] is None
    ejecucion = almacen.iniciar_ejecucion()
    assert almacen.estado()["ultima_ejecucion"]["resultado"] == "en_curso"
    almacen.cerrar_ejecucion(ejecucion, "ok", expedientes=15, novedades=2, codigo="casos_fallidos")
    ultima = almacen.estado()["ultima_ejecucion"]
    assert ultima["resultado"] == "ok" and ultima["fin"] is not None


def test_aplicar_guarda_la_linea_base_las_novedades_y_los_avisos_con_multiplicidad(almacen):
    semillas = {R(1): Counter({H(1): 2, H(2): 1})}
    plan, aviso = almacen.aplicar({R(1): Counter({H(1): 2, H(2): 1}), R(2): Counter({H(5): 1}), R(3): Counter()}, semillas)
    assert plan.primera_ejecucion and aviso is None and almacen.avisos_pendientes() == []
    e = almacen.estado()
    assert e["expedientes_en_estado"] == 3 and e["avisos_pendientes"] == 0

    plan, aviso = almacen.aplicar({R(1): Counter({H(1): 3, H(2): 1, H(7): 1}), R(2): Counter({H(5): 1}), R(3): Counter({H(8): 1}),
                                   R(4): Counter({H(9): 30})}, semillas)
    assert plan.novedades == 3 and plan.expedientes_con_novedades == 2 and plan.expedientes_nuevos == 1 and aviso
    pendientes = almacen.avisos_pendientes()
    assert [(a["id"], a["novedades"], a["expedientes_con_novedades"], a["expedientes_nuevos"], a["anomalias"]) for a in pendientes] == [
        (aviso, 3, 2, 1, 0)]
    # El estado guardado refleja las multiplicidades: repetir exactamente la misma lectura ya no produce novedades ni avisos.
    plan, aviso2 = almacen.aplicar({R(1): Counter({H(1): 3, H(2): 1, H(7): 1}), R(2): Counter({H(5): 1}), R(3): Counter({H(8): 1}),
                                    R(4): Counter({H(9): 30})}, semillas)
    assert plan.novedades == 0 and plan.expedientes_nuevos == 0 and aviso2 is None and len(almacen.avisos_pendientes()) == 1
    assert almacen.marcar_entregado(aviso) is True and almacen.marcar_entregado(aviso) is False and almacen.avisos_pendientes() == []
    assert almacen.marcar_entregado("00000000-0000-4000-8000-000000000000") is False


def test_una_anomalia_conserva_el_estado_y_se_avisa_una_sola_vez(almacen):
    almacen.aplicar({R(1): Counter({H(1): 2, H(2): 1})}, {})
    plan, aviso = almacen.aplicar({R(1): Counter({H(1): 1, H(9): 4})}, {})
    assert plan.anomalias == 1 and plan.novedades == 0 and aviso
    plan, otro = almacen.aplicar({R(1): Counter({H(1): 1, H(9): 4})}, {})
    assert plan.anomalias == 0 and otro is None                                    # persistente: sin repetir
    plan, _ = almacen.aplicar({R(1): Counter({H(1): 2, H(2): 1, H(3): 1})}, {})   # el estado previo NO se había pisado
    assert plan.novedades == 1 and plan.anomalias == 0


def test_dos_aplicaciones_simultaneas_de_la_misma_novedad_producen_un_solo_aviso(almacen):
    almacen.aplicar({R(1): Counter({H(1): 1})}, {})
    resultados, errores = [], []

    def aplicar():
        try:
            resultados.append(almacen.aplicar({R(1): Counter({H(1): 1, H(2): 1})}, {}))
        except Exception as error:  # noqa: BLE001
            errores.append(type(error).__name__)
    hilos = [threading.Thread(target=aplicar) for _ in range(4)]
    [h.start() for h in hilos]
    [h.join(30) for h in hilos]
    assert not errores and len(resultados) == 4
    assert sum(plan.novedades for plan, _ in resultados) == 1 and sum(1 for _, a in resultados if a) == 1
    assert len(almacen.avisos_pendientes()) == 1 and almacen.avisos_pendientes()[0]["novedades"] == 1


def test_un_expediente_grande_se_guarda_y_se_compara_sin_cambios(almacen):
    grande = Counter({H(n): 1 + n % 3 for n in range(1, 801)})
    almacen.aplicar({R(1): grande}, {})
    plan, aviso = almacen.aplicar({R(1): grande}, {})
    assert plan.novedades == 0 and aviso is None and almacen.estado()["expedientes_en_estado"] == 1


def test_el_almacen_en_memoria_y_la_logica_comparten_el_mismo_plan():
    previos = {}
    plan = planificar(previos, {R(1): Counter({H(1): 1})}, {})
    assert plan.primera_ejecucion and plan.resultado == "linea_base"
