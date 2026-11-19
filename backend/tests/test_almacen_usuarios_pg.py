"""Datos por usuario contra PostgreSQL REAL desechable (variables de supabase/checks/validar_cuentas_real_python.sh): aislamiento, propietario
intacto, reasignación de dispositivos y borrado en cascada al eliminar una cuenta."""

from collections import Counter
import os

import pytest

from tinotify.real_remoto import cifrado

H = lambda n: f"{n:064x}"  # noqa: E731
LLAVE = b"k" * 32
HASH_CLAVE = "scrypt$1024$8$1$" + "QUFB" * 6 + "$" + "QUFB" * 12


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
    admin.execute("TRUNCATE tinotify_real.huellas, tinotify_real.estado_expediente, tinotify_real.avisos, tinotify_real.ejecuciones, "
                  "tinotify_real.dispositivos, tinotify_real.credenciales, tinotify_real.sesiones, tinotify_real.invitaciones, "
                  "tinotify_real.usuarios CASCADE")
    usuarios = []
    for n in (1, 2):
        usuarios.append(str(admin.execute(
            "INSERT INTO tinotify_real.usuarios (correo_ref, pass_hash, consentimiento_version, consentimiento_en) "
            "VALUES (%s, %s, 'consentimiento-v1', now()) RETURNING id", (H(900 + n), HASH_CLAVE)).fetchone()[0]))
    yield AlmacenPg(cfg), admin, usuarios
    admin.close()


def exp(a, ref, numero):
    nonce, c = cifrado.cifrar_expediente(LLAVE, ref, numero, "CLIENTE_FICTICIO", "Activo")
    a.guardar_expedientes([(ref, 1, nonce, c, 0, False)])


def test_cada_usuario_ve_solo_sus_datos_y_el_propietario_no_se_mueve(mundo):
    a, admin, (u1, u2) = mundo
    prop, v1, v2 = a.de(None), a.de(u1), a.de(u2)
    for vista, ref in ((prop, H(1)), (v1, H(2)), (v2, H(3))):
        vista.aplicar({ref: Counter({H(50): 1})}, {})
        exp(vista, ref, 10)
    assert [f[0] for f in prop.expedientes()] == [H(1)] and [f[0] for f in v1.expedientes()] == [H(2)] and [f[0] for f in v2.expedientes()] == [H(3)]
    assert prop.estado()["expedientes_en_estado"] == v1.estado()["expedientes_en_estado"] == 1
    # una segunda lectura con una huella nueva crea el aviso solo del dueño
    plan, aviso = v1.aplicar({H(2): Counter({H(50): 1, H(51): 1})}, {})
    assert plan.novedades == 1 and aviso
    assert [x["id"] for x in v1.avisos_pendientes()] == [aviso] and prop.avisos_pendientes() == [] and v2.avisos_pendientes() == []
    todos = a.avisos_pendientes_todos()
    assert [(x["id"], x["usuario"]) for x in todos] == [(aviso, u1)]
    # marcar vistos / dispositivos / ejecuciones son del dueño
    assert v2.marcar_vistos(H(2)) == 0 and v1.marcar_vistos(H(2)) >= 0
    v1.registrar_dispositivo("t" * 30)
    assert v1.dispositivos() == ["t" * 30] and v2.dispositivos() == [] and prop.dispositivos() == []
    v2.registrar_dispositivo("t" * 30)                       # el mismo teléfono pasa a otra cuenta
    assert v1.dispositivos() == [] and v2.dispositivos() == ["t" * 30]
    assert v1.borrar_dispositivo("t" * 30) is False and v2.borrar_dispositivo("t" * 30) is True
    e1 = v1.iniciar_ejecucion(); v1.cerrar_ejecucion(e1, "ok", expedientes=1, novedades=1)
    assert len(v1.ejecuciones_recientes(10)) == 1 and prop.ejecuciones_recientes(10) == [] and v2.ejecuciones_recientes(10) == []


def test_credenciales_por_usuario_y_propietario_en_tablas_distintas(mundo):
    a, admin, (u1, u2) = mundo
    nonce, c = cifrado.cifrar_credenciales(LLAVE, "USUARIO_FICTICIO", "CLAVE_FICTICIA")
    a.de(u1).guardar_credenciales(1, nonce, c)
    a.de(None).guardar_credenciales(1, nonce, c)
    assert a.de(u1).credenciales() is not None and a.de(u2).credenciales() is None and a.de(None).credenciales() is not None
    assert a.usuarios_con_credenciales() == [u1]
    assert a.de(u1).estado()["credenciales_guardadas"] is True and a.de(u2).estado()["credenciales_guardadas"] is False
    assert a.de(u1).olvidar_credenciales() is True and a.usuarios_con_credenciales() == [] and a.de(None).credenciales() is not None


def test_borrar_una_cuenta_borra_en_cascada_todos_sus_datos_y_no_los_del_propietario(mundo):
    a, admin, (u1, u2) = mundo
    prop, v1 = a.de(None), a.de(u1)
    prop.aplicar({H(1): Counter({H(50): 1})}, {})
    exp(prop, H(1), 10)
    v1.aplicar({H(2): Counter({H(50): 1})}, {})
    v1.aplicar({H(2): Counter({H(50): 1, H(51): 1})}, {})
    exp(v1, H(2), 11)
    nonce, c = cifrado.cifrar_credenciales(LLAVE, "USUARIO_FICTICIO", "CLAVE_FICTICIA")
    v1.guardar_credenciales(1, nonce, c)
    v1.registrar_dispositivo("u" * 30)
    v1.cerrar_ejecucion(v1.iniciar_ejecucion(), "ok", expedientes=1, novedades=1)
    admin.execute("DELETE FROM tinotify_real.usuarios WHERE id = %s", (u1,))
    for tabla in ("estado_expediente", "avisos", "ejecuciones", "dispositivos", "credenciales_usuario"):
        n = admin.execute(f"SELECT count(*) FROM tinotify_real.{tabla} WHERE usuario_id = %s" if tabla != "credenciales_usuario"
                          else "SELECT count(*) FROM tinotify_real.credenciales_usuario WHERE usuario_id = %s", (u1,)).fetchone()[0]
        assert n == 0, tabla
    assert admin.execute("SELECT count(*) FROM tinotify_real.huellas WHERE caso_ref = %s", (H(2),)).fetchone()[0] == 0
    assert admin.execute("SELECT count(*) FROM tinotify_real.expedientes WHERE caso_ref = %s", (H(2),)).fetchone()[0] == 0
    assert [f[0] for f in prop.expedientes()] == [H(1)] and admin.execute("SELECT count(*) FROM tinotify_real.huellas WHERE caso_ref = %s", (H(1),)).fetchone()[0] == 1


def test_las_novedades_son_de_su_dueno_se_marcan_vistas_y_caen_con_la_cuenta(mundo):
    a, admin, (u1, u2) = mundo
    v1, v2 = a.de(u1), a.de(u2)
    for vista, ref in ((v1, H(2)), (v2, H(3))):
        vista.aplicar({ref: Counter({H(50): 1})}, {})
    nonce, c = cifrado.cifrar_novedad(LLAVE, H(2), {"fecha": "2026-11-18T10:00:00", "etapa": "ETAPA_FICTICIA"})
    v1.guardar_novedades([(H(2), 1, nonce, c)])
    assert [(f[1], f[5]) for f in v1.novedades()] == [(H(2), False)] and v2.novedades() == []
    assert cifrado.descifrar_novedad(LLAVE, H(2), v1.novedades()[0][3], v1.novedades()[0][4])["etapa"] == "ETAPA_FICTICIA"
    assert v2.marcar_vistos(None) is not None and v1.novedades()[0][5] is False   # otro usuario no las marca
    v1.marcar_vistos(H(2))
    assert v1.novedades()[0][5] is True
    # las de más de 90 días se limpian al guardar nuevas
    admin.execute("UPDATE tinotify_real.novedades SET detectada_en = now() - interval '100 days'")
    v1.guardar_novedades([(H(2), 1, nonce, c)])
    assert len(v1.novedades()) == 1
    admin.execute("DELETE FROM tinotify_real.usuarios WHERE id = %s::uuid", (u1,))
    assert admin.execute("SELECT count(*) FROM tinotify_real.novedades").fetchone()[0] == 0
