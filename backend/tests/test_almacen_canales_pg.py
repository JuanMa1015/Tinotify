"""Estado de canales de avisos y unión con las ejecuciones contra PostgreSQL REAL desechable (variables de validar_cuentas_real_python.sh)."""

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
    admin.execute("TRUNCATE tinotify_real.avisos, tinotify_real.ejecuciones CASCADE")
    yield AlmacenPg(cfg), admin
    admin.close()


def test_los_canales_se_registran_y_la_actividad_los_une_a_su_ejecucion(mundo):
    a, admin = mundo
    sin_aviso = a.iniciar_ejecucion()
    a.cerrar_ejecucion(sin_aviso, "ok", expedientes=15, novedades=0)
    con_aviso = a.iniciar_ejecucion()
    aviso = str(admin.execute("INSERT INTO tinotify_real.avisos (novedades, expedientes_con_novedades) VALUES (2, 1) RETURNING id").fetchone()[0])
    a.cerrar_ejecucion(con_aviso, "ok", expedientes=15, novedades=2)
    assert a.fijar_canal_aviso(aviso, "push", "enviado") is True
    assert a.fijar_canal_aviso(aviso, "correo", "fallido") is True
    assert a.fijar_canal_aviso("00000000-0000-0000-0000-000000000000", "push", "enviado") is False
    filas = a.ejecuciones_recientes(10)
    assert [f["aviso"] for f in filas] == [{"push": "enviado", "correo": "fallido"}, None]
    assert filas[0]["novedades"] == 2 and filas[1]["aviso"] is None
    with pytest.raises(KeyError):
        a.fijar_canal_aviso(aviso, "sms", "enviado")        # lista cerrada de canales: nunca llega al SQL


def test_la_base_rechaza_estados_fuera_del_catalogo(mundo):
    import psycopg
    _, admin = mundo
    aviso = admin.execute("INSERT INTO tinotify_real.avisos (novedades, expedientes_con_novedades) VALUES (1, 1) RETURNING id").fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute("UPDATE tinotify_real.avisos SET push_estado = 'quizas' WHERE id = %s", (aviso,))


def test_una_ejecucion_que_quedo_en_curso_se_cierra_como_interrumpida_solo_si_es_antigua(mundo):
    a, admin = mundo
    vieja = admin.execute("INSERT INTO tinotify_real.ejecuciones (inicio) VALUES (now() - interval '1 hour') RETURNING id").fetchone()[0]
    reciente = admin.execute("INSERT INTO tinotify_real.ejecuciones (inicio) VALUES (now() - interval '2 minutes') RETURNING id").fetchone()[0]
    a.iniciar_ejecucion()
    estado = lambda i: admin.execute("SELECT resultado, codigo, fin IS NOT NULL FROM tinotify_real.ejecuciones WHERE id = %s", (i,)).fetchone()  # noqa: E731
    assert estado(vieja) == ("error_interno", "interrumpida", True)
    assert estado(reciente) == ("en_curso", None, False)                                      # una revisión en marcha no se toca
