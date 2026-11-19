"""Primitivas de cuentas (sin red ni base de datos). Datos ficticios."""

from datetime import datetime, timedelta, timezone

import pytest

from tinotify.real_remoto import cuentas as c


def test_correo_se_normaliza_y_se_valida():
    assert c.normalizar_correo("  Persona.Ficticia@Ejemplo.COM ") == "persona.ficticia@ejemplo.com"
    for malo in ["", "sin-arroba", "a@b", "a@@b.com", "a..b@c.com", "a b@c.com", "a@" + "b" * 260 + ".com"]:
        with pytest.raises(c.DatosNoValidos):
            c.normalizar_correo(malo)


def test_el_mensaje_de_error_no_incluye_el_valor():
    with pytest.raises(c.DatosNoValidos) as e:
        c.normalizar_correo("dato-privado-ficticio")
    assert "privado" not in str(e.value)


def test_token_aleatorio_y_solo_se_guarda_su_hash():
    t1, h1 = c.nuevo_token()
    t2, _ = c.nuevo_token()
    assert t1 != t2 and t1.startswith("tn_") and len(t1) > 40
    assert h1 == c.sha256_hex(t1) and t1 not in h1
    assert c.hashes_iguales(h1, c.sha256_hex(t1)) and not c.hashes_iguales(h1, c.sha256_hex(t2))


def test_invitacion_legible_y_tolerante_a_formato():
    codigo, h = c.nueva_invitacion()
    assert len(codigo) == 19 and codigo.count("-") == 3
    assert not set(codigo.replace("-", "")) & set("01OIL")
    for variante in (codigo, codigo.lower(), codigo.replace("-", ""), f" {codigo} "):
        assert c.hash_invitacion(variante) == h
    assert c.hash_invitacion("AAAA-AAAA-AAAA-AAAA") != h


def test_correo_ref_depende_de_la_llave_y_no_es_el_correo():
    a, b = b"l" * 32, b"m" * 32
    r = c.correo_ref(a, "persona@ejemplo.com")
    assert len(r) == 64 and "persona" not in r
    assert r == c.correo_ref(a, "persona@ejemplo.com") and r != c.correo_ref(b, "persona@ejemplo.com")


def test_el_codigo_de_registro_es_estable_en_la_ventana_y_depende_de_todo():
    llave = b"k" * 32
    ahora = datetime(2026, 11, 18, 12, 3, tzinfo=timezone.utc)
    v = c.ventana_registro(ahora)
    codigo = c.codigo_registro(llave, "a@ejemplo.com", "AAAA-BBBB-CCCC-DDDD", v)
    assert len(codigo) == 9 and codigo[4] == "-" and not set(codigo.replace("-", "")) & set("01OIL")
    assert codigo == c.codigo_registro(llave, "a@ejemplo.com", "aaaa bbbb cccc dddd", v)          # tolera el formato de la invitación
    for otro in (c.codigo_registro(llave, "b@ejemplo.com", "AAAA-BBBB-CCCC-DDDD", v), c.codigo_registro(llave, "a@ejemplo.com", "AAAA-BBBB-CCCC-DDDE", v),
                 c.codigo_registro(llave, "a@ejemplo.com", "AAAA-BBBB-CCCC-DDDD", v + 1), c.codigo_registro(b"m" * 32, "a@ejemplo.com", "AAAA-BBBB-CCCC-DDDD", v)):
        assert otro != codigo
    assert c.codigo_registro_valido(llave, "a@ejemplo.com", "AAAA-BBBB-CCCC-DDDD", codigo.lower(), ahora)
    assert c.codigo_registro_valido(llave, "a@ejemplo.com", "AAAA-BBBB-CCCC-DDDD", codigo, ahora + timedelta(minutes=10))
    assert not c.codigo_registro_valido(llave, "a@ejemplo.com", "AAAA-BBBB-CCCC-DDDD", codigo, ahora + timedelta(minutes=25))
    assert not c.codigo_registro_valido(llave, "a@ejemplo.com", "AAAA-BBBB-CCCC-DDDD", "AAAA-AAAA", ahora)


def test_el_codigo_de_acceso_esta_ligado_al_usuario_y_normaliza():
    assert len(c.nuevo_codigo_acceso()) == 9
    assert c.hash_codigo_acceso("u1", "abcd-efgh") == c.hash_codigo_acceso("u1", " ABCD EFGH ")
    assert c.hash_codigo_acceso("u1", "ABCD-EFGH") != c.hash_codigo_acceso("u2", "ABCD-EFGH")
