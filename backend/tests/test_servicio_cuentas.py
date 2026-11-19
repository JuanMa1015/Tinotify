"""Servicio de cuentas sobre un almacén en memoria. Datos ficticios; sin red ni base de datos."""

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from tinotify.real_remoto import cuentas as c
from backend.tests.helpers.correo_falso import CorreoFalso
from tinotify.real_remoto.servicio_cuentas import (
    CodigoNoValido, ConfirmacionIncorrecta, RegistroNoValido, ServicioCuentas)

LLAVE = b"k" * 32
CONSENT = "consentimiento-v1"


class AlmacenMemoria:
    def __init__(self):
        self.usuarios, self.invitaciones, self.sesiones = {}, {}, {}

    def crear_invitacion(self, h, expira): self.invitaciones[h] = {"expira": expira, "usada": False}

    def invitacion_vigente(self, h, ahora):
        i = self.invitaciones.get(h)
        return i is not None and not i["usada"] and i["expira"] > ahora

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

    def listar_usuarios(self):
        return [{"id": u["id"], "activo": u["activo"], "es_admin": u["es_admin"], "desde": "2026-11-18T12:00:00+00:00", "correo": u.get("correo"),
                 "con_credenciales": u["id"] in getattr(self, "con_datos", ()), "expedientes": 3 if u["id"] in getattr(self, "con_datos", ()) else 0,
                 "ultima_resultado": None, "ultima_inicio": None} for u in self.usuarios.values()]

    def fijar_activo(self, uid, activo): self.usuarios[uid]["activo"] = activo
    def fijar_admin(self, uid, valor): self.usuarios[uid]["es_admin"] = valor

    def borrar_datos_de(self, uid):
        self.__dict__.setdefault("borrados", []).append(uid)
        if hasattr(self, "con_datos"): self.con_datos.discard(uid)

    def crear_recuperacion(self, uid, h, expira, ahora, maximo=3):
        filas = self.__dict__.setdefault("recuperaciones", [])
        if sum(1 for f in filas if f["uid"] == uid and f["creada"] > ahora - timedelta(hours=1)) >= maximo:
            return False
        for f in filas:
            if f["uid"] == uid and f["usado"] is None:
                f["usado"] = ahora
        filas.append({"uid": uid, "hash": h, "expira": expira, "usado": None, "intentos": 0, "creada": ahora})
        return True

    def consumir_recuperacion(self, uid, h, ahora, max_intentos=5):
        vigentes = [f for f in self.__dict__.get("recuperaciones", []) if f["uid"] == uid and f["usado"] is None and f["expira"] > ahora]
        if not vigentes or vigentes[-1]["intentos"] >= max_intentos:
            return False
        f = vigentes[-1]
        if f["hash"] == h:
            f["usado"] = ahora
            return True
        f["intentos"] += 1
        return False

    def borrar_usuario(self, uid):
        self.usuarios.pop(uid, None)
        self.sesiones = {k: s for k, s in self.sesiones.items() if s["uid"] != uid}


class Reloj:
    def __init__(self): self.t = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    def __call__(self): return self.t
    def avanzar(self, **kw): self.t += timedelta(**kw)


@pytest.fixture
def mundo():
    reloj, almacen, correo = Reloj(), AlmacenMemoria(), CorreoFalso()
    return ServicioCuentas(almacen, LLAVE, reloj=reloj, llave_correo=b"c" * 32, correo=correo), almacen, reloj, correo


def registrado(mundo, correo_usuario="persona@ejemplo.com", invitacion=None):
    s, _, _, correo = mundo
    inv = invitacion or s.crear_invitacion()
    assert s.solicitar_codigo_registro(correo_usuario, inv) == "enviado"
    return s.registrar(correo_usuario, correo.codigo(), inv, CONSENT, "telefono")


def test_registro_con_codigo_del_correo_crea_cuenta_y_sesion(mundo):
    s, a, _, correo = mundo
    token, usuario = registrado(mundo)
    assert s.autenticar(token) == usuario
    guardado = next(iter(a.usuarios.values()))
    assert guardado["ref"] != "persona@ejemplo.com" and "persona" not in guardado["pass_hash"]  # nada en claro
    assert correo.enviados[0]["destino"] == "persona@ejemplo.com" and "10 minutos" in correo.enviados[0]["texto"]


def test_el_codigo_de_registro_depende_del_correo_y_de_la_invitacion_y_vence(mundo):
    s, _, reloj, correo = mundo
    inv, otra = s.crear_invitacion(), s.crear_invitacion()
    s.solicitar_codigo_registro("a@ejemplo.com", inv)
    codigo = correo.codigo()
    for correo_malo, inv_mala in (("b@ejemplo.com", inv), ("a@ejemplo.com", otra)):
        with pytest.raises(RegistroNoValido):
            s.registrar(correo_malo, codigo, inv_mala, CONSENT)
    with pytest.raises(RegistroNoValido):
        s.registrar("a@ejemplo.com", "AAAA-AAAA", inv, CONSENT)
    reloj.avanzar(minutes=25)                                               # vale entre 10 y 20 minutos
    with pytest.raises(RegistroNoValido):
        s.registrar("a@ejemplo.com", codigo, inv, CONSENT)


def test_pedir_el_codigo_de_registro_dice_que_pasa_y_no_consume_la_invitacion(mundo):
    s, a, _, correo = mundo
    inv = s.crear_invitacion()
    assert s.solicitar_codigo_registro("no-es-correo", inv) == "correo_invalido"
    assert s.solicitar_codigo_registro("a@ejemplo.com", "AAAA-AAAA-AAAA-AAAA") == "invitacion_invalida"
    assert not correo.enviados
    assert s.solicitar_codigo_registro("a@ejemplo.com", inv) == "enviado" and not any(i["usada"] for i in a.invitaciones.values())
    registrado(mundo, "a@ejemplo.com", inv)
    assert s.solicitar_codigo_registro("a@ejemplo.com", s.crear_invitacion()) == "ya_registrado"
    assert ServicioCuentas(a, LLAVE, correo=CorreoFalso(motivo="http_401:x")).solicitar_codigo_registro("z@ejemplo.com", s.crear_invitacion()) == "fallo_envio"
    assert ServicioCuentas(a, LLAVE).solicitar_codigo_registro("y@ejemplo.com", s.crear_invitacion()) == "fallo_envio"      # sin correo configurado


def test_la_invitacion_sirve_una_sola_vez_y_vence(mundo):
    s, _, reloj, correo = mundo
    inv = s.crear_invitacion()
    registrado(mundo, "a@ejemplo.com", inv)
    s.solicitar_codigo_registro("b@ejemplo.com", inv)                        # ya usada: no se puede ni pedir el código
    assert len(correo.enviados) == 1
    with pytest.raises(RegistroNoValido):
        s.registrar("b@ejemplo.com", c.codigo_registro(LLAVE, "b@ejemplo.com", inv, c.ventana_registro(reloj())), inv, CONSENT)
    vieja = s.crear_invitacion()
    reloj.avanzar(days=8)
    assert s.solicitar_codigo_registro("c@ejemplo.com", vieja) == "invitacion_invalida"


def test_entrar_con_codigo_abre_sesion_y_el_codigo_sirve_una_vez(mundo):
    s, _, _, correo = mundo
    registrado(mundo)
    assert s.solicitar_codigo_acceso(" Persona@Ejemplo.com ") == "enviado"
    token, usuario = s.entrar("persona@ejemplo.com", correo.codigo(), "otro-telefono")
    assert s.autenticar(token) == usuario
    with pytest.raises(CodigoNoValido):
        s.entrar("persona@ejemplo.com", correo.codigo(), "otro-telefono")


def test_pedir_acceso_dice_que_paso(mundo):
    s, a, reloj, correo = mundo
    registrado(mundo)
    assert s.solicitar_codigo_acceso("nadie@ejemplo.com") == "no_registrado" and s.solicitar_codigo_acceso("basura") == "no_registrado"
    estados = [s.solicitar_codigo_acceso("persona@ejemplo.com") for _ in range(5)]
    assert estados == ["enviado"] * 3 + ["limite"] * 2
    assert ServicioCuentas(a, LLAVE).solicitar_codigo_acceso("persona@ejemplo.com") == "fallo_envio"


def test_un_codigo_equivocado_cinco_veces_lo_inutiliza_y_el_de_otra_cuenta_no_sirve(mundo):
    s, _, _, correo = mundo
    registrado(mundo)
    registrado(mundo, "otra@ejemplo.com")
    s.solicitar_codigo_acceso("persona@ejemplo.com")
    bueno = correo.codigo()
    with pytest.raises(CodigoNoValido):
        s.entrar("otra@ejemplo.com", bueno)                                   # ligado a su cuenta
    for _ in range(5):
        with pytest.raises(CodigoNoValido):
            s.entrar("persona@ejemplo.com", "AAAA-AAAA")
    with pytest.raises(CodigoNoValido):
        s.entrar("persona@ejemplo.com", bueno)


def test_el_codigo_de_acceso_vence_a_los_quince_minutos(mundo):
    s, _, reloj, correo = mundo
    registrado(mundo)
    s.solicitar_codigo_acceso("persona@ejemplo.com")
    reloj.avanzar(minutes=16)
    with pytest.raises(CodigoNoValido):
        s.entrar("persona@ejemplo.com", correo.codigo())


def test_una_cuenta_suspendida_no_entra(mundo):
    s, a, _, correo = mundo
    _, u = registrado(mundo)
    s.solicitar_codigo_acceso("persona@ejemplo.com")
    s.fijar_activo(u.id, False, None)
    with pytest.raises(CodigoNoValido):
        s.entrar("persona@ejemplo.com", correo.codigo())
    assert s.solicitar_codigo_acceso("persona@ejemplo.com") == "no_registrado"


def test_sesiones_expiran_y_se_revocan(mundo):
    s, _, reloj, correo = mundo
    t1, u = registrado(mundo)
    s.solicitar_codigo_acceso("persona@ejemplo.com")
    t2, _ = s.entrar("persona@ejemplo.com", correo.codigo())
    s.cerrar_sesion(t1)
    assert s.autenticar(t1) is None and s.autenticar(t2) == u
    reloj.avanzar(days=31)
    assert s.autenticar(t2) is None


@pytest.mark.parametrize("token", [None, "", "sin-prefijo", "tn_" + "x" * 300, "tn_inexistente"])
def test_tokens_invalidos_no_autentican(mundo, token):
    assert mundo[0].autenticar(token) is None


def test_eliminar_cuenta_exige_escribir_el_correo_y_borra_todo(mundo):
    s, a, _, _ = mundo
    t, u = registrado(mundo)
    for mal in ("otra@ejemplo.com", "basura", ""):
        with pytest.raises(ConfirmacionIncorrecta):
            s.eliminar_cuenta(u.id, mal)
    s.eliminar_cuenta(u.id, " Persona@Ejemplo.com ")
    assert not a.usuarios and not a.sesiones and s.autenticar(t) is None


def test_llave_corta_se_rechaza():
    with pytest.raises(ValueError):
        ServicioCuentas(AlmacenMemoria(), b"corta")


def test_el_correo_de_aviso_se_guarda_cifrado_y_se_descifra_solo_para_avisar(mundo):
    s, a, _, _ = mundo
    _, usuario = registrado(mundo, "Persona@Ejemplo.com")
    nonce, cifrado = a.usuarios[usuario.id]["correo"]
    assert b"persona" not in cifrado and b"ejemplo" not in cifrado
    assert s.correo_de(usuario.id) == "persona@ejemplo.com"
    assert ServicioCuentas(a, LLAVE, llave_correo=b"z" * 32).correo_de(usuario.id) is None        # otra llave: no se lee
    assert ServicioCuentas(a, LLAVE).correo_de(usuario.id) is None                                  # sin llave configurada: no se lee
    assert s.correo_de("no-existe") is None


def test_sin_llave_de_correo_el_registro_funciona_sin_guardar_correo():
    a, reloj, correo = AlmacenMemoria(), Reloj(), CorreoFalso()
    s = ServicioCuentas(a, LLAVE, reloj=reloj, correo=correo)
    inv = s.crear_invitacion()
    s.solicitar_codigo_registro("persona@ejemplo.com", inv)
    _, usuario = s.registrar("persona@ejemplo.com", correo.codigo(), inv, CONSENT)
    assert a.usuarios[usuario.id]["correo"] is None
