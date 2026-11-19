"""Reutilización de conexiones contra PostgreSQL REAL desechable (variables de supabase/checks/validar_cuentas_real_python.sh)."""

import os

import pytest


@pytest.fixture
def mundo():
    e = os.environ
    if not e.get("TINOTIFY_TEST_PG_HOST"):
        pytest.skip("PostgreSQL desechable no configurado")
    import psycopg
    from tinotify.real_remoto.almacen import AlmacenPg
    from tinotify.real_remoto.config import ConfigPg
    cfg = ConfigPg(e["TINOTIFY_TEST_PG_HOST"], int(e.get("TINOTIFY_TEST_PG_PORT", "5432")), "postgres", e["TINOTIFY_TEST_PG_USER"],
                   e["TINOTIFY_TEST_PG_PASSWORD"], None, tls=False)
    admin = psycopg.connect(host=cfg.host, port=cfg.puerto, dbname="postgres", user=e["TINOTIFY_TEST_PG_ADMIN_USER"],
                            password=e["TINOTIFY_TEST_PG_ADMIN_PASSWORD"], autocommit=True)
    yield AlmacenPg(cfg), admin
    admin.close()


def pid(almacen):
    with almacen._tx() as con:
        return con.execute("SELECT pg_backend_pid()").fetchone()[0]


def test_las_operaciones_seguidas_reutilizan_la_conexion_y_las_vistas_de_usuario_la_comparten(mundo):
    a, _ = mundo
    primero = pid(a)
    assert pid(a) == primero and pid(a.de(None)) == primero


def test_una_conexion_que_la_base_cerro_se_reemplaza_sin_que_se_note(mundo):
    a, admin = mundo
    viejo = pid(a)
    admin.execute("SELECT pg_terminate_backend(%s)", (viejo,))
    nuevo = pid(a)                                   # la reservada estaba muerta: se abre otra y la operación sale bien
    assert nuevo != viejo and pid(a) == nuevo


def test_un_error_dentro_de_la_transaccion_la_deshace_y_la_conexion_sigue_sirviendo(mundo):
    a, admin = mundo
    antes = admin.execute("SELECT count(*) FROM tinotify_real.avisos").fetchone()[0]
    with pytest.raises(ValueError):
        with a._tx() as con:
            con.execute("INSERT INTO tinotify_real.avisos (novedades, expedientes_con_novedades) VALUES (1, 1)")
            raise ValueError("error de dominio")
    assert admin.execute("SELECT count(*) FROM tinotify_real.avisos").fetchone()[0] == antes   # se deshizo
    assert a.estado()["credenciales_guardadas"] in (True, False)                                # y la conexión sirve


def test_los_tiempos_limite_se_aplican_en_cada_transaccion_reutilizada(mundo):
    a, _ = mundo
    for _ in range(3):
        with a._tx() as con:
            assert con.execute("SHOW statement_timeout").fetchone()[0] == "30s"
    with a._tx() as con:
        assert con.execute("SHOW statement_timeout").fetchone()[0] == "30s"
