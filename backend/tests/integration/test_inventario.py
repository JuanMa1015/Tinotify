"""Inventario real PG17: orden, roles RLS, nombres y drift dentro de rollback."""

import hashlib
import json
from pathlib import Path

import pytest


RAIZ=Path(__file__).resolve().parents[3]
CONSULTA=(RAIZ/"supabase/checks/4b4a_inventario.sql").read_text(encoding="utf-8")


def inventario(conexion):
    return conexion.execute(CONSULTA).fetchone()[0]


@pytest.fixture(scope="session")
def lector_catalogo(postgres_aislado):
    admin,_,_=postgres_aislado
    admin.execute("CREATE ROLE fixture_lector_catalogo NOLOGIN")
    return "fixture_lector_catalogo"


def test_determinismo_y_lectura_sin_acceso_a_datos(postgres_aislado,lector_catalogo):
    admin,_,_=postgres_aislado
    with admin.transaction():
        admin.execute("SET TRANSACTION READ ONLY")
        admin.execute("SET LOCAL ROLE fixture_lector_catalogo")
        primero=inventario(admin)
        segundo=inventario(admin)
    assert json.dumps(primero,sort_keys=True,ensure_ascii=True)==json.dumps(segundo,sort_keys=True,ensure_ascii=True)
    assert len(primero["tablas"])==11 and all(t["presente"] and t["rls"] and t["force_rls"] for t in primero["tablas"])
    assert len(primero["funciones"])==22 and all(f["presente"] for f in primero["funciones"])
    assert primero["extras"]=={"relaciones":0,"rutinas":0}
    columnas=[c for c in primero["columnas"] if c["esquema"]=="app" and c["tabla"]=="actuaciones"]
    assert [c["orden"] for c in columnas]==list(range(1,14))
    assert [c["nombre"] for c in columnas][:4]==["estudiante_id","estado_id","expediente_id","local_id"]
    assert all(c["not_null"] for c in columnas[:4])
    assert "fixture_lector_catalogo" not in str(primero)


@pytest.mark.parametrize("cambio,categoria",[
    ("ALTER TABLE app.actuaciones ALTER COLUMN version_hash DROP NOT NULL","columnas"),
    ("ALTER TABLE app.expedientes ALTER COLUMN generacion SET DEFAULT 7","columnas"),
    ("ALTER TABLE app.actuaciones RENAME CONSTRAINT actuaciones_orden_uq TO orden_sintetico_alternativo","constraints"),
    ("ALTER POLICY fixture_lectura ON app.actuaciones TO tinotify_guard_reader","politicas"),
    ("GRANT SELECT(local_id) ON app.actuaciones TO anon","permisos_columna_efectivos"),
    ("GRANT tinotify_fixture_control TO tinotify_api","membresias"),
])
def test_detecta_drift_antes_invisible_y_revierte(postgres_aislado,cambio,categoria):
    admin,_,_=postgres_aislado
    anterior=inventario(admin)
    class Revertir(Exception): pass
    with pytest.raises(Revertir):
        with admin.transaction():
            admin.execute(cambio)
            nuevo=inventario(admin)
            assert nuevo[categoria]!=anterior[categoria]
            raise Revertir
    assert inventario(admin)==anterior


def test_roles_exactos_de_politicas_y_constraints_nominales(postgres_aislado):
    admin,_,_=postgres_aislado
    datos=inventario(admin)
    nombre=hashlib.sha256(b"fixture_lectura").hexdigest()
    politica=next(p for p in datos["politicas"] if p["tabla"]=="actuaciones" and p["nombre_sha256"]==nombre)
    assert [r["nombre"] for r in politica["roles"]]==["tinotify_fixture_owner"]
    constraint=next(c for c in datos["constraints"] if c["nombre"]=="actuaciones_orden_uq")
    assert constraint["nombre_sha256"]==hashlib.sha256(b"actuaciones_orden_uq").hexdigest()
