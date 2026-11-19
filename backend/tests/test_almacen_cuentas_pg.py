"""AlmacenCuentasPg contra PostgreSQL REAL desechable (solo con las variables de supabase/checks/validar_cuentas_real_python.sh).

Sin esas variables todo se omite. Reutiliza el ServicioCuentas con datos ficticios y comprueba además lo que solo la base garantiza:
unicidad, un solo uso de la invitación bajo concurrencia, cascada al borrar la cuenta y RLS forzado.
"""

import os
import threading

import pytest

from backend.tests.helpers.correo_falso import CorreoFalso
from tinotify.real_remoto.servicio_cuentas import CodigoNoValido, RegistroNoValido, ServicioCuentas

CONSENT = "consentimiento-v1"


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
    admin.execute("TRUNCATE tinotify_real.recuperaciones, tinotify_real.sesiones, tinotify_real.invitaciones, tinotify_real.usuarios CASCADE")
    correo = CorreoFalso()
    servicio = ServicioCuentas(AlmacenCuentasPg(cfg), b"k" * 32, correo=correo)
    servicio.correo_falso = correo
    yield servicio, admin
    admin.close()


def nueva(s, correo="persona@ejemplo.com", invitacion=None):
    inv = invitacion or s.crear_invitacion()
    assert s.solicitar_codigo_registro(correo, inv) == "enviado"
    return s.registrar(correo, s.correo_falso.codigo(), inv, CONSENT, "telefono")


def test_ciclo_completo_de_cuenta_contra_postgres(mundo):
    s, admin = mundo
    token, usuario = nueva(s)
    assert s.autenticar(token) == usuario
    fila = admin.execute("SELECT correo_ref, pass_hash FROM tinotify_real.usuarios").fetchone()
    assert "persona" not in fila[0] and fila[1] == "scrypt$0$0$0$SIN$CLAVE"            # sin contraseña: nada que verificar
    assert s.solicitar_codigo_acceso("persona@ejemplo.com") == "enviado"
    t2, _ = s.entrar("persona@ejemplo.com", s.correo_falso.codigo(), "otro-telefono")
    assert s.autenticar(t2) == usuario
    with pytest.raises(CodigoNoValido):
        s.entrar("persona@ejemplo.com", s.correo_falso.codigo())                       # un solo uso
    s.cerrar_sesion(token)
    assert s.autenticar(token) is None
    s.eliminar_cuenta(usuario.id, "persona@ejemplo.com")
    assert s.autenticar(t2) is None
    assert admin.execute("SELECT (SELECT count(*) FROM tinotify_real.usuarios), (SELECT count(*) FROM tinotify_real.sesiones), "
                         "(SELECT count(*) FROM tinotify_real.recuperaciones)").fetchone() == (0, 0, 0)


def test_una_invitacion_solo_sirve_una_vez_aun_con_peticiones_simultaneas(mundo):
    s, admin = mundo
    codigo = s.crear_invitacion()
    import tinotify.real_remoto.cuentas as c
    from datetime import datetime, timezone
    resultados = []

    def intentar(n):
        correo = f"persona{n}@ejemplo.com"
        codigo_correo = c.codigo_registro(b"k" * 32, correo, codigo, c.ventana_registro(datetime.now(timezone.utc)))
        try:
            s.registrar(correo, codigo_correo, codigo, CONSENT)
            resultados.append("ok")
        except RegistroNoValido:
            resultados.append("rechazado")
    hilos = [threading.Thread(target=intentar, args=(n,)) for n in range(6)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert resultados.count("ok") == 1 and resultados.count("rechazado") == 5
    assert admin.execute("SELECT count(*) FROM tinotify_real.usuarios").fetchone()[0] == 1


def test_correo_repetido_se_dice_antes_de_enviar_nada(mundo):
    s, _ = mundo
    nueva(s)
    assert s.solicitar_codigo_registro("PERSONA@ejemplo.com", s.crear_invitacion()) == "ya_registrado"


def test_las_tablas_tienen_rls_forzado_y_los_clientes_de_supabase_no_entran(mundo):
    _, admin = mundo
    for tabla in ("usuarios", "invitaciones", "sesiones", "recuperaciones"):
        assert admin.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass",
                             (f"tinotify_real.{tabla}",)).fetchone() == (True, True)
        for rol in ("anon", "authenticated", "service_role"):
            assert admin.execute("SELECT has_table_privilege(%s, %s, 'SELECT,INSERT,UPDATE,DELETE')", (rol, f"tinotify_real.{tabla}")).fetchone()[0] is False


def test_el_correo_de_aviso_se_guarda_cifrado_y_solo_se_lee_con_la_llave(mundo):
    from tinotify.real_remoto.almacen_cuentas import AlmacenCuentasPg
    s, admin = mundo
    a = s._a
    assert isinstance(a, AlmacenCuentasPg)
    con_llave = ServicioCuentas(a, b"k" * 32, llave_correo=b"c" * 32, correo=s.correo_falso)
    inv = con_llave.crear_invitacion()
    con_llave.solicitar_codigo_registro("destino@ejemplo.com", inv)
    _, usuario = con_llave.registrar("destino@ejemplo.com", s.correo_falso.codigo(), inv, CONSENT)
    bruto = admin.execute("SELECT correo_nonce, correo_cifrado FROM tinotify_real.usuarios WHERE id = %s", (usuario.id,)).fetchone()
    assert b"destino" not in bytes(bruto[1]) and b"ejemplo" not in bytes(bruto[1])
    assert con_llave.correo_de(usuario.id) == "destino@ejemplo.com"
    assert ServicioCuentas(a, b"k" * 32, llave_correo=b"z" * 32).correo_de(usuario.id) is None
    _, sin = nueva(s, "otra@ejemplo.com")                                              # el servicio del fixture no guarda correo
    assert admin.execute("SELECT correo_cifrado IS NULL FROM tinotify_real.usuarios WHERE id = %s", (sin.id,)).fetchone()[0] is True
    with pytest.raises(Exception):
        admin.execute("UPDATE tinotify_real.usuarios SET correo_nonce = '\\x00'::bytea WHERE id = %s", (sin.id,))   # nonce sin cifrado: lo impide la restricción


def test_la_invitacion_vigente_se_consulta_sin_consumirla(mundo):
    from datetime import datetime, timedelta, timezone
    import tinotify.real_remoto.cuentas as c
    s, admin = mundo
    inv = s.crear_invitacion()
    ahora = datetime.now(timezone.utc)
    assert s._a.invitacion_vigente(c.hash_invitacion(inv), ahora) is True and s._a.invitacion_vigente(c.hash_invitacion(inv), ahora) is True
    assert s._a.invitacion_vigente(c.hash_invitacion(inv), ahora + timedelta(days=8)) is False
    assert s._a.invitacion_vigente(c.hash_invitacion("AAAA-AAAA-AAAA-AAAA"), ahora) is False
