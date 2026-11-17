"""Primitivas de cuentas (sin red ni base de datos). Datos ficticios."""

import pytest

from tinotify.real_remoto import cuentas as c

N_RAPIDO = 2**10  # solo para que las pruebas sean veloces


def test_hash_de_clave_se_verifica_y_no_contiene_la_clave():
    h = c.hash_clave("clave-ficticia-segura", n=N_RAPIDO)
    assert h.startswith("scrypt$") and "clave-ficticia" not in h
    assert c.verificar_clave("clave-ficticia-segura", h)
    assert not c.verificar_clave("otra-clave-ficticia", h)


def test_dos_hashes_de_la_misma_clave_difieren_por_la_sal():
    assert c.hash_clave("clave-ficticia-segura", n=N_RAPIDO) != c.hash_clave("clave-ficticia-segura", n=N_RAPIDO)


@pytest.mark.parametrize("guardado", ["", "basura", "md5$1$2$3$a$b", "scrypt$x$8$1$AAAA$AAAA", "scrypt$1024$8$1$%%%$%%%"])
def test_hash_malformado_nunca_verifica_ni_lanza(guardado):
    assert c.verificar_clave("clave-ficticia-segura", guardado) is False


def test_usuario_inexistente_devuelve_falso_sin_lanzar():
    assert c.verificar_clave_inexistente("cualquiera") is False


def test_correo_se_normaliza_y_se_valida():
    assert c.normalizar_correo("  Persona.Ficticia@Ejemplo.COM ") == "persona.ficticia@ejemplo.com"
    for malo in ["", "sin-arroba", "a@b", "a@@b.com", "a..b@c.com", "a b@c.com", "a@" + "b" * 260 + ".com"]:
        with pytest.raises(c.DatosNoValidos):
            c.normalizar_correo(malo)


def test_reglas_de_clave():
    c.validar_clave("una-clave-razonable-1")
    for mala, motivo in [("corta", "clave_longitud"), ("x" * 200, "clave_longitud"), ("aaaaaaaaaaaa", "clave_muy_simple")]:
        with pytest.raises(c.DatosNoValidos, match=motivo):
            c.validar_clave(mala)
    with pytest.raises(c.DatosNoValidos, match="clave_igual_al_correo"):
        c.validar_clave("persona@ejemplo.com", "Persona@Ejemplo.com")


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
