"""Referencia REAL de tres migraciones, nunca derivada del estado posterior."""

from copy import deepcopy
from pathlib import Path

import psycopg
import pytest

from ..test_comparador_catalogos import comp


pytestmark = pytest.mark.parametrize("postgres_aislado", [3], indirect=True)
CHECKS = Path(__file__).resolve().parents[3]/"supabase/checks"


def consulta(conexion,nombre):
    return conexion.execute((CHECKS/nombre).read_text(encoding="utf-8")).fetchone()[0]


def captura(admin,roles):
    with admin.transaction():
        admin.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        preflight=consulta(admin,"4b4b_preflight.sql")
        assert all(preflight["historial"].values())
        historial=consulta(admin,"4b3_historial.sql")
        catalogo=consulta(admin,"4b4a_inventario.sql")
    return comp.empaquetar(preflight,catalogo,historial,"local",roles["imagen_digest"])


def test_referencia_real_tres_migraciones_reproducible(postgres_aislado,tmp_path):
    admin,roles,_=postgres_aislado
    assert not admin.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()[0]
    primera=captura(admin,roles)
    segunda=captura(admin,roles)
    assert primera==segunda
    assert [v["aplicaciones"] for v in primera["historial"]["versiones"]]==[1,1,1,0]
    assert all(v==0 for v in primera["preflight"]["colisiones"].values())
    assert len(primera["catalogo"]["politicas"])==25
    assert [e["nombre"] for e in primera["catalogo"]["esquemas"]]==["app","app_private"]
    # Este artefacto es local, sin DSN, Auth ni datos de negocio. Su commit es el checkout real.
    (tmp_path/"referencia-tres.json").write_text(comp.canonico(primera)+"\n",encoding="utf-8")
    espejo=comp.sellar({**primera,"origen":"remoto","imagen_digest":None})
    assert comp.comparar(primera,espejo)["veredicto"]=="evidencia_insuficiente"


@pytest.mark.parametrize("cambio,categoria",[
    ("ALTER TABLE app.estudiantes NO FORCE ROW LEVEL SECURITY","tablas"),
    ("ALTER TABLE app.estudiantes OWNER TO fixture_harness","tablas"),
    ("GRANT SELECT(id) ON app.estudiantes TO anon","acl_columnas"),
    ("ALTER FUNCTION app_private.actor() SECURITY INVOKER","funciones"),
    ("ALTER TABLE app.actuaciones RENAME CONSTRAINT actuaciones_orden_uq TO orden_alternativo","constraints"),
    ("ALTER ROLE tinotify_api LOGIN","roles"),
    ("CREATE TABLE app.objeto_ficticio_extra(id integer)","extras"),
])
def test_comparador_detecta_drift_real_y_revierte(postgres_aislado,cambio,categoria):
    admin,roles,_=postgres_aislado
    referencia=captura(admin,roles)

    class RevertirDrift(Exception): pass

    with psycopg.connect(roles["bootstrap_local"],autocommit=True) as bootstrap:
        with pytest.raises(RevertirDrift):
            with bootstrap.transaction():
                bootstrap.execute(cambio)
                remoto=deepcopy(referencia)
                remoto.update(origen="remoto",imagen_digest=None)
                remoto["catalogo"]=consulta(bootstrap,"4b4a_inventario.sql")
                assert remoto["catalogo"][categoria]!=referencia["catalogo"][categoria]
                resultado=comp.comparar(referencia,comp.sellar(remoto))
                assert resultado["veredicto"]=="bloqueado"
                assert any(h["campo"].startswith("/catalogo/"+categoria) for h in resultado["hallazgos"])
                raise RevertirDrift
    assert captura(admin,roles)==referencia


@pytest.mark.parametrize("cambio,campo",[
    ("CREATE ROLE tinotify_fixture_control NOLOGIN","roles_fixture"),
    ("CREATE SCHEMA app_fixture","esquema_fixture"),
    ("CREATE POLICY fixture_insercion ON app.estudiantes FOR INSERT WITH CHECK(true)","politicas_reservadas"),
    ("CREATE FUNCTION public.fixture_trigger_test() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RETURN NEW; END'; CREATE TRIGGER fixture_perfil_inerte BEFORE UPDATE ON app.estudiantes FOR EACH ROW EXECUTE FUNCTION public.fixture_trigger_test()","trigger_reservado"),
])
def test_preflight_detecta_colisiones_pendientes_sin_reparar(postgres_aislado,cambio,campo):
    _,roles,_=postgres_aislado

    class RevertirColision(Exception): pass

    with psycopg.connect(roles["bootstrap_local"],autocommit=True) as bootstrap:
        with pytest.raises(RevertirColision):
            with bootstrap.transaction():
                bootstrap.execute(cambio)
                assert consulta(bootstrap,"4b4b_preflight.sql")["colisiones"][campo]==1
                raise RevertirColision
        assert all(v==0 for v in consulta(bootstrap,"4b4b_preflight.sql")["colisiones"].values())


def test_lector_sin_historial_no_se_interpreta_como_vacio(postgres_aislado):
    _,roles,_=postgres_aislado

    class RevertirLector(Exception): pass

    with psycopg.connect(roles["bootstrap_local"],autocommit=True) as bootstrap:
        with pytest.raises(RevertirLector):
            with bootstrap.transaction():
                bootstrap.execute("CREATE ROLE lector_preflight_ficticio NOLOGIN")
                bootstrap.execute("SET LOCAL ROLE lector_preflight_ficticio")
                preflight=consulta(bootstrap,"4b4b_preflight.sql")
                assert preflight["historial"]["existe"] and not preflight["historial"]["select_version"]
                assert len(consulta(bootstrap,"4b4a_inventario.sql")["tablas"])==11
                raise RevertirLector
