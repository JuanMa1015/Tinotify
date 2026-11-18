"""AlmacenCuentasPg contra PostgreSQL REAL desechable (solo con las variables de supabase/checks/validar_cuentas_real_python.sh).

Sin esas variables todo se omite. Reutiliza el ServicioCuentas con datos ficticios y comprueba además lo que solo la base garantiza:
unicidad, un solo uso de la invitación bajo concurrencia, cascada al borrar la cuenta y RLS forzado.
"""

import os
import threading

import pytest

from tinotify.real_remoto.servicio_cuentas import (
    CredencialesIncorrectas, RegistroNoValido, ServicioCuentas)

CLAVE = "una-clave-ficticia-1"


def _entorno():
    if not os.environ.get("TINOTIFY_TEST_PG_HOST"):
        pytest.skip("PostgreSQL desechable no configurado (ver supabase/checks/validar_cuentas_real_python.sh)")
    return os.environ


@pytest.fixture
def mundo():
    e = _entorno()
    import psycopg
    from tinotify.real_remoto.almacen_cuentas import AlmacenCuentasPg
    from tinotify.real_remoto.config import ConfigPg
    cfg = ConfigPg(e["TINOTIFY_TEST_PG_HOST"], int(e.get("TINOTIFY_TEST_PG_PORT", "5432")), "postgres", e["TINOTIFY_TEST_PG_USER"],
                   e["TINOTIFY_TEST_PG_PASSWORD"], None, tls=False)
    admin = psycopg.connect(host=cfg.host, port=cfg.puerto, dbname="postgres", user=e["TINOTIFY_TEST_PG_ADMIN_USER"],
                            password=e["TINOTIFY_TEST_PG_ADMIN_PASSWORD"], autocommit=True)
    admin.execute("TRUNCATE tinotify_real.sesiones, tinotify_real.invitaciones, tinotify_real.usuarios CASCADE")
    servicio = ServicioCuentas(AlmacenCuentasPg(cfg), b"k" * 32, n_scrypt=2**10)
    yield servicio, admin
    admin.close()


def test_ciclo_completo_de_cuenta_contra_postgres(mundo):
    s, admin = mundo
    token, usuario = s.registrar("persona@ejemplo.com", CLAVE, s.crear_invitacion(), "consentimiento-v1", "telefono")
    assert s.autenticar(token) == usuario
    fila = admin.execute("SELECT correo_ref, pass_hash FROM tinotify_real.usuarios").fetchone()
    assert "persona" not in fila[0] and CLAVE not in fila[1]  # ni el correo ni la clave en claro
    t2, _ = s.iniciar_sesion("persona@ejemplo.com", CLAVE)
    s.cambiar_clave(usuario.id, CLAVE, "otra-clave-ficticia-2", token)
    assert s.autenticar(token) == usuario and s.autenticar(t2) is None
    with pytest.raises(CredencialesIncorrectas):
        s.iniciar_sesion("persona@ejemplo.com", CLAVE)
    s.cerrar_sesion(token)
    assert s.autenticar(token) is None
    t3, _ = s.iniciar_sesion("persona@ejemplo.com", "otra-clave-ficticia-2")
    s.eliminar_cuenta(usuario.id, "otra-clave-ficticia-2")
    assert s.autenticar(t3) is None
    assert admin.execute("SELECT (SELECT count(*) FROM tinotify_real.usuarios), (SELECT count(*) FROM tinotify_real.sesiones)").fetchone() == (0, 0)


def test_una_invitacion_solo_sirve_una_vez_aun_con_peticiones_simultaneas(mundo):
    s, admin = mundo
    codigo = s.crear_invitacion()
    resultados = []

    def intentar(n):
        try:
            s.registrar(f"persona{n}@ejemplo.com", CLAVE, codigo, "consentimiento-v1")
            resultados.append("ok")
        except RegistroNoValido:
            resultados.append("rechazado")
    hilos = [threading.Thread(target=intentar, args=(n,)) for n in range(6)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert resultados.count("ok") == 1 and resultados.count("rechazado") == 5
    assert admin.execute("SELECT count(*) FROM tinotify_real.usuarios").fetchone()[0] == 1


def test_correo_repetido_y_bloqueo_por_fallos(mundo):
    s, admin = mundo
    s.registrar("persona@ejemplo.com", CLAVE, s.crear_invitacion(), "consentimiento-v1")
    with pytest.raises(RegistroNoValido):
        s.registrar("PERSONA@ejemplo.com", CLAVE, s.crear_invitacion(), "consentimiento-v1")
    for _ in range(5):
        with pytest.raises(CredencialesIncorrectas):
            s.iniciar_sesion("persona@ejemplo.com", "clave-mala-ficticia")
    assert admin.execute("SELECT intentos_fallidos, bloqueado_hasta IS NOT NULL FROM tinotify_real.usuarios").fetchone() == (5, True)


def test_las_tres_tablas_tienen_rls_forzado_y_los_clientes_de_supabase_no_entran(mundo):
    _, admin = mundo
    for tabla in ("usuarios", "invitaciones", "sesiones"):
        assert admin.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass",
                             (f"tinotify_real.{tabla}",)).fetchone() == (True, True)
        for rol in ("anon", "authenticated", "service_role"):
            assert admin.execute("SELECT has_table_privilege(%s, %s, 'SELECT,INSERT,UPDATE,DELETE')", (rol, f"tinotify_real.{tabla}")).fetchone()[0] is False


def test_el_correo_de_aviso_se_guarda_cifrado_y_solo_se_lee_con_la_llave(mundo):
    from tinotify.real_remoto.almacen_cuentas import AlmacenCuentasPg
    s, admin = mundo
    a = s._a if hasattr(s, "_a") else None
    assert isinstance(a, AlmacenCuentasPg)
    con_llave = ServicioCuentas(a, b"k" * 32, n_scrypt=2**10, llave_correo=b"c" * 32)
    _, usuario = con_llave.registrar("destino@ejemplo.com", CLAVE, con_llave.crear_invitacion(), "consentimiento-v1")
    bruto = admin.execute("SELECT correo_nonce, correo_cifrado FROM tinotify_real.usuarios WHERE id = %s", (usuario.id,)).fetchone()
    assert b"destino" not in bytes(bruto[1]) and b"ejemplo" not in bytes(bruto[1])
    assert con_llave.correo_de(usuario.id) == "destino@ejemplo.com"
    assert ServicioCuentas(a, b"k" * 32, llave_correo=b"z" * 32).correo_de(usuario.id) is None
    _, sin = s.registrar("otra@ejemplo.com", CLAVE, s.crear_invitacion(), "consentimiento-v1")       # el servicio del fixture no guarda correo
    assert admin.execute("SELECT correo_cifrado IS NULL FROM tinotify_real.usuarios WHERE id = %s", (sin.id,)).fetchone()[0] is True
    with pytest.raises(Exception):
        admin.execute("UPDATE tinotify_real.usuarios SET correo_nonce = '\\x00'::bytea WHERE id = %s", (sin.id,))   # nonce sin cifrado: lo impide la restricción
