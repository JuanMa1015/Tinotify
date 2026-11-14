"""Ejecuta el preflight solo en el contenedor nuevo del fixture, nunca remoto."""

from pathlib import Path

import pytest


CHECKS = Path(__file__).resolve().parents[3]/"supabase/checks"


def consultar(admin,nombre="4b3_preflight.sql"):
    return admin.execute((CHECKS/nombre).read_text(encoding="utf-8")).fetchone()[0]


def test_inventario_con_rol_sin_acceso_a_datos_y_transaccion_read_only(postgres_aislado):
    admin,_,_ = postgres_aislado
    admin.execute("CREATE ROLE supabase_read_only_user NOLOGIN")
    try:
        with admin.transaction():
            admin.execute("SET TRANSACTION READ ONLY")
            admin.execute("SET LOCAL ROLE supabase_read_only_user")
            datos=consultar(admin)
            assert datos["ejecucion"]["rol"]=="supabase_read_only_user"
            assert datos["ejecucion"]["transaction_read_only"]=="on"
            assert datos["catalogo"]["tablas"]==8 and datos["catalogo"]["funciones"]==10
            assert datos["catalogo"]["objetos_ajenos"]==0
            assert datos["privilegios_directos_de_cliente"]==[]
            # 4B.4-A agrega UPDATE(id) interno para bloquear solo sus perfiles.
            assert datos["acl_columnas_no_propietario"]==3
            assert all(f["rol"] not in ("anon","authenticated","service_role") for f in datos["funciones_acceso_efectivo"])
            assert datos["clientes_pueden_asumir_propietarios"]==[]
            assert datos["auth_id_referenciable"]
            assert not datos["historial"]["existe"]
            # Las 25 originales y 17 politicas exclusivas del propietario fixture.
            assert len(datos["politicas"])==42
            for funcion in datos["funciones"]:
                assert funcion["propietario_correcto"] and funcion["security_correcta"]
                assert funcion["search_path_fijo"] and not funcion["public_execute"]
    finally:
        admin.execute("DROP ROLE supabase_read_only_user")


@pytest.mark.parametrize("cambio,comprobar",[
    ("GRANT SELECT(local_id) ON app.actuaciones TO tinotify_api", "columna"),
    ("ALTER TABLE app.actuaciones NO FORCE ROW LEVEL SECURITY", "rls"),
    ("GRANT EXECUTE ON FUNCTION app_private.actor() TO PUBLIC", "funcion"),
    ("GRANT tinotify_api TO anon", "heredado"),
])
def test_detecta_desviaciones_y_revierte_fixture(postgres_aislado,cambio,comprobar):
    admin,_,_=postgres_aislado
    class RevertirFixture(Exception): pass
    with pytest.raises(RevertirFixture):
        with admin.transaction():
            admin.execute(cambio)
            datos=consultar(admin)
            if comprobar=="columna":
                assert any(f["rol"]=="tinotify_api" and f["columna"] for f in datos["privilegios_directos_de_cliente"])
            elif comprobar=="rls":
                assert any(t["nombre"]=="actuaciones" and not t["force_rls"] for t in datos["tablas"])
            elif comprobar=="funcion":
                assert any(f["firma"]=="actor()" and f["public_execute"] for f in datos["funciones"])
            else:
                assert any(f["rol"]=="anon" for f in datos["funciones_acceso_efectivo"])
            raise RevertirFixture
    assert consultar(admin)["privilegios_directos_de_cliente"]==[]


def test_historial_ausente_y_duplicados_huecos_sin_leer_cuerpos(postgres_aislado):
    admin,_,_=postgres_aislado
    class RevertirFixture(Exception): pass
    with pytest.raises(RevertirFixture):
        with admin.transaction():
            admin.execute("CREATE SCHEMA supabase_migrations; CREATE TABLE supabase_migrations.schema_migrations(version text,statements text)")
            admin.execute("""INSERT INTO supabase_migrations.schema_migrations VALUES
                ('20261112050000','CONTENIDO_FICTICIO_NO_LEER'),
                ('20261112050000','CONTENIDO_FICTICIO_NO_LEER'),
                ('20261114010000','CONTENIDO_FICTICIO_NO_LEER'),('999','CONTENIDO_FICTICIO_NO_LEER')""")
            datos=consultar(admin,"4b3_historial.sql")
            assert datos["versiones"][0]["aplicaciones"]==2
            assert datos["versiones"][1]["aplicaciones"]==0
            assert datos["filas_no_previstas"]==1 and datos["orden_invalido"]
            assert "CONTENIDO_FICTICIO_NO_LEER" not in str(datos)
            raise RevertirFixture
    assert not consultar(admin)["historial"]["existe"]
