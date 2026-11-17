"""Listado cifrado de expedientes contra PostgreSQL REAL desechable (solo con las variables de validar_cuentas_real_python.sh)."""

import os

import pytest

from tinotify.real_remoto import cifrado

LLAVE = b"k" * 32
R1, R2 = "a" * 64, "b" * 64


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
    admin.execute("TRUNCATE tinotify_real.huellas, tinotify_real.estado_expediente CASCADE")
    for ref in (R1, R2):
        admin.execute("INSERT INTO tinotify_real.estado_expediente (caso_ref, actuaciones) VALUES (%s, 0)", (ref,))
    yield AlmacenPg(cfg), admin
    admin.close()


def fila(ref, numero, sumar=0, nuevo=False):
    nonce, c = cifrado.cifrar_expediente(LLAVE, ref, numero, "CLIENTE_FICTICIO", "Activo")
    return (ref, 1, nonce, c, sumar, nuevo)


def test_guarda_actualiza_acumula_y_marca_vistos(mundo):
    a, _ = mundo
    a.guardar_expedientes([fila(R1, 101), fila(R2, 202)])
    assert sorted(f[0] for f in a.expedientes()) == [R1, R2]
    a.guardar_expedientes([fila(R1, 101, sumar=2), fila(R2, 202, nuevo=True)])
    a.guardar_expedientes([fila(R1, 101, sumar=1)])
    por_ref = {f[0]: f for f in a.expedientes()}
    assert por_ref[R1][4] == 3 and por_ref[R1][5] is False and por_ref[R1][6] is not None
    assert por_ref[R2][4] == 0 and por_ref[R2][5] is True
    assert cifrado.descifrar_expediente(LLAVE, R1, por_ref[R1][2], por_ref[R1][3]) == (101, "CLIENTE_FICTICIO", "Activo")
    assert a.marcar_vistos(R1) == 1
    assert {f[0]: (f[4], f[5]) for f in a.expedientes()} == {R1: (0, False), R2: (0, True)}
    assert a.marcar_vistos() == 1 and all(f[4] == 0 and not f[5] for f in a.expedientes())


def test_la_base_solo_contiene_cifrado_y_se_borra_en_cascada(mundo):
    a, admin = mundo
    a.guardar_expedientes([fila(R1, 123456)])
    bruto = admin.execute("SELECT nonce, cifrado FROM tinotify_real.expedientes").fetchone()
    assert b"CLIENTE_FICTICIO" not in bytes(bruto[1]) and b"123456" not in bytes(bruto[1])
    admin.execute("DELETE FROM tinotify_real.estado_expediente WHERE caso_ref = %s", (R1,))
    assert a.expedientes() == []
    assert admin.execute("SELECT relforcerowsecurity FROM pg_class WHERE oid = 'tinotify_real.expedientes'::regclass").fetchone()[0] is True
