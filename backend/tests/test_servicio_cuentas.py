"""Servicio de cuentas sobre un almacén en memoria. Datos ficticios; sin red ni base de datos."""

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from tinotify.real_remoto import cuentas as c
from tinotify.real_remoto.servicio_cuentas import (
    CredencialesIncorrectas, CuentaBloqueada, RegistroNoValido, ServicioCuentas)

LLAVE = b"k" * 32
CLAVE = "una-clave-ficticia-1"
CONSENT = "consentimiento-v1"


class AlmacenMemoria:
    def __init__(self):
        self.usuarios, self.invitaciones, self.sesiones = {}, {}, {}

    def crear_invitacion(self, h, expira): self.invitaciones[h] = {"expira": expira, "usada": False}

    def registrar_usuario(self, inv, ref, pass_hash, version, ahora, correo=None):
        i = self.invitaciones.get(inv)
        if i is None or i["usada"] or i["expira"] <= ahora or any(u["ref"] == ref for u in self.usuarios.values()):
            raise RegistroNoValido
        uid = str(uuid.uuid4())
        self.usuarios[uid] = {"id": uid, "ref": ref, "pass_hash": pass_hash, "activo": True, "es_admin": False,
                              "intentos_fallidos": 0, "bloqueado_hasta": None, "correo": correo}
        i["usada"] = True
        return uid

    def correo_cifrado_de(self, uid):
        u = self.usuarios.get(uid)
        return u["correo"] if u and u.get("correo") else None

    def usuario_por_correo_ref(self, ref): return next((dict(u) for u in self.usuarios.values() if u["ref"] == ref), None)
    def usuario_por_id(self, uid): return dict(self.usuarios[uid]) if uid in self.usuarios else None
    def registrar_fallo(self, uid, n, hasta): self.usuarios[uid].update(intentos_fallidos=n, bloqueado_hasta=hasta)
    def limpiar_fallos(self, uid): self.usuarios[uid].update(intentos_fallidos=0, bloqueado_hasta=None)
    def crear_sesion(self, uid, h, disp, expira): self.sesiones[h] = {"uid": uid, "expira": expira, "revocada": None}

    def usuario_por_token(self, h, ahora):
        s = self.sesiones.get(h)
        u = self.usuarios.get(s["uid"]) if s else None
        return None if not s or s["revocada"] or s["expira"] <= ahora or not u or not u["activo"] else dict(u)

    def revocar_sesion(self, h, ahora):
        if h in self.sesiones: self.sesiones[h]["revocada"] = ahora

    def revocar_todas(self, uid, ahora):
        for s in self.sesiones.values():
            if s["uid"] == uid: s["revocada"] = ahora

    def revocar_todas_menos(self, uid, h, ahora):
        for k, s in self.sesiones.items():
            if s["uid"] == uid and k != h: s["revocada"] = ahora

    def cambiar_pass(self, uid, ph): self.usuarios[uid]["pass_hash"] = ph

    def borrar_usuario(self, uid):
        self.usuarios.pop(uid, None)
        self.sesiones = {k: s for k, s in self.sesiones.items() if s["uid"] != uid}


class Reloj:
    def __init__(self): self.t = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    def __call__(self): return self.t
    def avanzar(self, **kw): self.t += timedelta(**kw)


@pytest.fixture
def mundo():
    reloj, almacen = Reloj(), AlmacenMemoria()
    return ServicioCuentas(almacen, LLAVE, reloj=reloj, n_scrypt=2**10), almacen, reloj


def registrado(s, correo="persona@ejemplo.com"):
    return s.registrar(correo, CLAVE, s.crear_invitacion(), CONSENT, "telefono")


def test_registro_con_invitacion_crea_cuenta_y_sesion(mundo):
    s, a, _ = mundo
    token, usuario = registrado(s)
    assert s.autenticar(token) == usuario
    guardado = next(iter(a.usuarios.values()))
    assert guardado["ref"] != "persona@ejemplo.com" and CLAVE not in guardado["pass_hash"]  # nada en claro


def test_la_invitacion_sirve_una_sola_vez_y_vence(mundo):
    s, _, reloj = mundo
    inv = s.crear_invitacion()
    s.registrar("a@ejemplo.com", CLAVE, inv, CONSENT)
    with pytest.raises(RegistroNoValido):
        s.registrar("b@ejemplo.com", CLAVE, inv, CONSENT)
    vieja = s.crear_invitacion()
    reloj.avanzar(days=8)
    with pytest.raises(RegistroNoValido):
        s.registrar("c@ejemplo.com", CLAVE, vieja, CONSENT)


def test_invitacion_falsa_o_correo_repetido_dan_el_mismo_error(mundo):
    s, _, _ = mundo
    registrado(s)
    for correo, inv in (("otro@ejemplo.com", "AAAA-AAAA-AAAA-AAAA"), ("persona@ejemplo.com", s.crear_invitacion())):
        with pytest.raises(RegistroNoValido):
            s.registrar(correo, CLAVE, inv, CONSENT)


def test_formato_invalido_se_rechaza_antes_de_tocar_la_invitacion(mundo):
    s, a, _ = mundo
    inv = s.crear_invitacion()
    with pytest.raises(c.DatosNoValidos):
        s.registrar("no-es-correo", CLAVE, inv, CONSENT)
    with pytest.raises(c.DatosNoValidos):
        s.registrar("ok@ejemplo.com", "corta", inv, CONSENT)
    assert not any(i["usada"] for i in a.invitaciones.values())


def test_login_correcto_e_incorrecto_son_indistinguibles_para_correo_inexistente(mundo):
    s, _, _ = mundo
    registrado(s)
    token, _ = s.iniciar_sesion(" Persona@Ejemplo.com ", CLAVE, "otro-telefono")
    assert s.autenticar(token)
    for correo, clave in (("persona@ejemplo.com", "clave-mala-ficticia"), ("nadie@ejemplo.com", CLAVE), ("basura", CLAVE)):
        with pytest.raises(CredencialesIncorrectas):
            s.iniciar_sesion(correo, clave)


def test_bloqueo_tras_cinco_fallos_y_se_libera_con_el_tiempo(mundo):
    s, _, reloj = mundo
    registrado(s)
    for _ in range(5):
        with pytest.raises(CredencialesIncorrectas):
            s.iniciar_sesion("persona@ejemplo.com", "clave-mala-ficticia")
    with pytest.raises(CuentaBloqueada) as e:
        s.iniciar_sesion("persona@ejemplo.com", CLAVE)  # ni con la clave correcta mientras dure el bloqueo
    assert e.value.espera_s > 0
    reloj.avanzar(minutes=16)
    assert s.autenticar(s.iniciar_sesion("persona@ejemplo.com", CLAVE)[0])


def test_sesiones_expiran_y_se_revocan(mundo):
    s, _, reloj = mundo
    t1, u = registrado(s)
    t2, _ = s.iniciar_sesion("persona@ejemplo.com", CLAVE)
    s.cerrar_sesion(t1)
    assert s.autenticar(t1) is None and s.autenticar(t2) == u
    reloj.avanzar(days=31)
    assert s.autenticar(t2) is None


@pytest.mark.parametrize("token", [None, "", "sin-prefijo", "tn_" + "x" * 300, "tn_inexistente"])
def test_tokens_invalidos_no_autentican(mundo, token):
    assert mundo[0].autenticar(token) is None


def test_cambiar_clave_cierra_las_otras_sesiones(mundo):
    s, _, _ = mundo
    t1, u = registrado(s)
    t2, _ = s.iniciar_sesion("persona@ejemplo.com", CLAVE)
    with pytest.raises(CredencialesIncorrectas):
        s.cambiar_clave(u.id, "no-es-la-actual", "otra-clave-ficticia-2", t1)
    s.cambiar_clave(u.id, CLAVE, "otra-clave-ficticia-2", t1)
    assert s.autenticar(t1) == u and s.autenticar(t2) is None
    with pytest.raises(CredencialesIncorrectas):
        s.iniciar_sesion("persona@ejemplo.com", CLAVE)
    assert s.iniciar_sesion("persona@ejemplo.com", "otra-clave-ficticia-2")


def test_eliminar_cuenta_exige_la_clave_y_borra_todo(mundo):
    s, a, _ = mundo
    t, u = registrado(s)
    with pytest.raises(CredencialesIncorrectas):
        s.eliminar_cuenta(u.id, "no-es-la-clave")
    s.eliminar_cuenta(u.id, CLAVE)
    assert not a.usuarios and not a.sesiones and s.autenticar(t) is None


def test_llave_corta_se_rechaza():
    with pytest.raises(ValueError):
        ServicioCuentas(AlmacenMemoria(), b"corta")


def test_el_correo_de_aviso_se_guarda_cifrado_y_se_descifra_solo_para_avisar():
    a = AlmacenMemoria()
    reloj = Reloj()
    s = ServicioCuentas(a, LLAVE, reloj=reloj, n_scrypt=2**10, llave_correo=b"c" * 32)
    token, usuario = s.registrar("Persona@Ejemplo.com", CLAVE, s.crear_invitacion(), CONSENT)
    nonce, cifrado = a.usuarios[usuario.id]["correo"]
    assert b"persona" not in cifrado and b"ejemplo" not in cifrado
    assert s.correo_de(usuario.id) == "persona@ejemplo.com"
    assert ServicioCuentas(a, LLAVE, llave_correo=b"z" * 32).correo_de(usuario.id) is None        # otra llave: no se lee
    assert ServicioCuentas(a, LLAVE).correo_de(usuario.id) is None                                  # sin llave configurada: no se lee
    assert s.correo_de("no-existe") is None


def test_sin_llave_de_correo_el_registro_funciona_sin_guardar_correo():
    a = AlmacenMemoria()
    s = ServicioCuentas(a, LLAVE, reloj=Reloj(), n_scrypt=2**10)
    _, usuario = s.registrar("persona@ejemplo.com", CLAVE, s.crear_invitacion(), CONSENT)
    assert a.usuarios[usuario.id]["correo"] is None
