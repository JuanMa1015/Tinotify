"""Lanzador local del backend real: solo loopback, solo lectura, sin sesión SIGAC. Sin datos reales."""

import importlib.util
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from tinotify.persistence.sqlite_local import AlmacenSqliteLocal

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "servir_real_local.py"


@pytest.fixture
def modulo():
    spec = importlib.util.spec_from_file_location("servir_real_local_prueba", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_sirve_solo_lectura_protegida_sin_sesion_ni_monitor(modulo, tmp_path):
    db = tmp_path / "v2.sqlite3"
    AlmacenSqliteLocal(db, perfil="real")
    app = modulo.construir_app(db, tmp_path / "codigo.txt")
    codigo = (tmp_path / "codigo.txt").read_text(encoding="utf-8").strip()
    assert len(codigo) >= 32
    cliente = TestClient(app, base_url="http://127.0.0.1:8000")
    cabecera = {"Authorization": f"Bearer {codigo}"}
    assert cliente.get("/real/cases").status_code == 401
    assert cliente.get("/real/cases", headers={"Authorization": "Bearer " + "x" * 40}).status_code == 401
    assert cliente.get("/real/cases", headers=cabecera).json() == []
    assert cliente.get("/real/observaciones", headers=cabecera).status_code == 200
    assert cliente.get("/real/novedades", headers=cabecera).status_code == 410
    assert cliente.post("/real/sesion", headers=cabecera, json={}).status_code == 404  # sesión SIGAC no registrada
    assert cliente.get("/real/monitor", headers=cabecera).status_code == 404
    assert cliente.get("/health").status_code == 200


def test_rechaza_v1_o_archivos_inexistentes_y_solo_escucha_en_loopback(modulo, tmp_path):
    v1 = tmp_path / "v1.sqlite3"
    con = sqlite3.connect(v1)
    con.executescript("CREATE TABLE meta(clave TEXT PRIMARY KEY, valor TEXT NOT NULL);"
                      "INSERT INTO meta VALUES('esquema','1'),('perfil','real');")
    con.commit()
    con.close()
    with pytest.raises(Exception):
        modulo.construir_app(v1, tmp_path / "c1.txt")
    with pytest.raises(SystemExit):
        modulo.construir_app(tmp_path / "no-existe.sqlite3", tmp_path / "c2.txt")
    assert modulo.HOST == "127.0.0.1" and "0.0.0.0" not in SCRIPT.read_text(encoding="utf-8")


def test_el_codigo_local_se_conserva_y_no_se_regenera(modulo, tmp_path):
    ruta = tmp_path / "c.txt"
    primero = modulo.codigo_local(ruta)
    assert modulo.codigo_local(ruta) == primero
    ruta.write_text("corto", encoding="utf-8")
    with pytest.raises(ValueError):
        modulo.codigo_local(ruta)


def test_leer_historial_exige_autorizacion_terminal_y_acreditacion_antes_de_conectar(modulo, tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    db = tmp_path / "v2.sqlite3"
    AlmacenSqliteLocal(db, perfil="real")
    monkeypatch.setattr(modulo.getpass, "getpass", lambda _: pytest.fail("No debe pedir credenciales"))
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("No debe pedir confirmación"))
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("No debe iniciar el servidor"))
    base = ["--db", str(db), "--leer-historial", "--tipo", "2", "--total-casos", "15", "--caso-numero", "101"]
    with pytest.raises(SystemExit):  # sin autorización explícita
        modulo.main(base)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SystemExit):  # sin terminal interactiva
        modulo.main([*base, "--autorizar-sigac-real"])
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    for malo in (["--minutos", "0"], ["--minutos", "61"], ["--caso-numero", "0"]):
        with pytest.raises(SystemExit):
            modulo.main([*base, "--autorizar-sigac-real", *malo])
    # Sin clave local de acreditación, el servidor y la lectura permanecen cerrados.
    assert modulo.main([*base, "--autorizar-sigac-real", "--acreditacion", str(tmp_path / "no-existe.json")]) == 4
