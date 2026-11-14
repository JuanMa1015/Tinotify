"""Guardas de seguridad de las consultas de catalogo; no emulan PostgreSQL."""

from pathlib import Path
import re

import pytest


CHECKS = Path(__file__).resolve().parents[2]/"supabase/checks"
CONSULTAS = ("4b3_preflight.sql", "4b3_historial.sql", "4b4a_inventario.sql")
FUNCIONES = {
    "jsonb_build_object", "jsonb_agg", "to_jsonb", "to_regrole", "to_regclass",
    "to_regnamespace", "to_regprocedure", "replace", "oidvectortypes",
    "aclexplode", "acldefault", "has_table_privilege", "has_any_column_privilege",
    "has_column_privilege", "has_schema_privilege", "has_database_privilege", "has_function_privilege",
    "has_language_privilege", "pg_has_role", "current_setting", "encode", "sha256", "convert_to",
    "pg_get_indexdef", "pg_get_functiondef", "pg_get_constraintdef", "pg_get_expr",
    "unnest", "count", "sum", "current_database",
    "format_type", "pg_get_triggerdef",
}


def comprobar_consulta(texto):
    # Estos scripts no admiten bloques, dollar quotes, identificadores entre
    # comillas ni comandos psql. Evita ocultar una segunda sentencia al revisar.
    # Solo el nombre builtin calificado de la collation C admite comillas.
    texto=texto.replace('pg_catalog."C"','pg_catalog.C')
    assert not re.search(r'/\*|\*/|\$|"|^\s*\\', texto, re.M)
    codigo = re.sub(r"--[^\n]*|'(?:''|[^'])*'", " ", texto)
    assert codigo.strip().startswith("WITH ")
    assert codigo.count(";")==1 and codigo.rstrip().endswith(";")
    assert not re.search(r"\b(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|GRANT|REVOKE|TRUNCATE|DO|CALL|COPY|SET|INTO|LOCK)\b",codigo,re.I)
    assert set(re.findall(r"pg_catalog\.(\w+)\s*\(",codigo)) <= FUNCIONES
    # Las coincidencias sin esquema deben ser sintaxis/aliases SQL, no funciones
    # ejecutables resueltas por search_path. Esta guarda no sustituye la revision.
    sin_esquema={n.lower() for n in re.findall(r"(?<![\w.])([A-Za-z_]\w*)\s*\(",codigo)}
    assert sin_esquema <= {
        "as","exists","values","coalesce","and","any","in","on","select","when","where",
        "previstas","funciones_esperadas","r","roles_esperados","tablas",
        "objetivos","firmas","nombres_roles","permisos","x",
    }
    fuentes=re.findall(r"\b(?:FROM|JOIN)\s+([a-z_][a-z_0-9.]+)",codigo,re.I)
    assert all("." not in f or f.startswith("pg_catalog.") or f=="supabase_migrations.schema_migrations" for f in fuentes)
    assert not re.search(r"\b(?:FROM|JOIN)\s+(?:app|app_private|auth)\.",codigo,re.I)
    assert not re.search(r"\b(?:rolpassword|pg_authid|pg_stat_activity|pg_file_read|pg_read_file)\b",codigo,re.I)


@pytest.mark.parametrize("nombre",CONSULTAS)
def test_consulta_es_inspeccion_sin_datos_ni_efectos(nombre):
    comprobar_consulta((CHECKS/nombre).read_text(encoding="utf-8"))


@pytest.mark.parametrize("inseguro",[
    "WITH x AS (DELETE FROM app.actuaciones RETURNING *) SELECT * FROM x;",
    "WITH x AS (SELECT 1) SELECT pg_catalog.pg_terminate_backend(1);",
    "WITH x AS (SELECT 1) SELECT pg_terminate_backend(1);",
    "WITH x AS (SELECT 1) SELECT * FROM vault.decrypted_secrets;",
    "WITH x AS (SELECT 1) SELECT * FROM auth.users;",
    "WITH x AS (SELECT 1) SELECT rolpassword FROM pg_catalog.pg_authid;",
    "WITH x AS (SELECT 1) SELECT 1; GRANT SELECT ON app.actuaciones TO PUBLIC;",
])
def test_guarda_rechaza_regresiones_de_seguridad(inseguro):
    with pytest.raises(AssertionError):
        comprobar_consulta(inseguro)
