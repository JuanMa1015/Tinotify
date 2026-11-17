"""Invariantes estáticos de la propuesta SQL del almacén real (sin base de datos). La validación contra PostgreSQL es aparte."""

from pathlib import Path
import re

RAIZ = Path(__file__).resolve().parents[2]
ALTA = (RAIZ / "supabase/propuestas/20261117000000_crear_almacen_real.sql").read_text(encoding="utf-8")
BAJA = (RAIZ / "supabase/propuestas/20261117000000_crear_almacen_real_down.sql").read_text(encoding="utf-8")
TABLAS = ["avisos", "credenciales", "dispositivos", "ejecuciones", "entorno", "estado_expediente", "huellas"]


def sin_comentarios(sql):
    return "\n".join(l.split("--")[0] for l in sql.splitlines())


def test_crea_exactamente_las_siete_tablas_y_la_baja_las_elimina_a_todas():
    creadas = sorted(re.findall(r"CREATE TABLE tinotify_real\.(\w+)", ALTA))
    assert creadas == TABLAS
    assert all(f"tinotify_real.{t}" in BAJA for t in TABLAS)
    assert re.search(r"ARRAY\['avisos', 'credenciales', 'dispositivos', 'ejecuciones', 'entorno', 'estado_expediente', 'huellas'\]", BAJA)
    assert "<> 7 THEN" in ALTA


def test_cada_tabla_cierra_rls_y_el_acceso_de_los_clientes_de_supabase():
    codigo = sin_comentarios(ALTA)
    assert re.search(r"FOREACH t IN ARRAY ARRAY\['entorno','credenciales','estado_expediente','huellas','avisos','ejecuciones','dispositivos'\]", codigo)
    assert "ENABLE ROW LEVEL SECURITY" in codigo and "FORCE ROW LEVEL SECURITY" in codigo
    assert "REVOKE ALL ON tinotify_real.%I FROM PUBLIC, anon, authenticated, service_role" in codigo
    assert "FROM PUBLIC, anon, authenticated, service_role" in codigo
    assert not re.search(r"GRANT[^;]*\b(PUBLIC|anon|authenticated|service_role)\b", codigo)
    assert not re.search(r"FOR ALL", codigo)                                     # una política por orden
    assert not re.search(r"TRUNCATE|GRANT ALL|WITH GRANT OPTION", codigo.replace("TRUNCATE,REFERENCES", ""))
    assert ALTA.count("CREATE POLICY") == 22          # 1 + 4 + 3 + 4 + 3 + 3 + 4, una por orden y tabla


def test_no_crea_logins_ni_contrasenas_ni_toca_otros_esquemas():
    codigo = sin_comentarios(ALTA)
    assert re.findall(r"CREATE ROLE (\w+) ([^;]*);", codigo) == [("tinotify_real_app", "NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")]
    assert "PASSWORD" not in codigo.upper() and "LOGIN " not in codigo.replace("NOLOGIN", "")
    assert not re.search(r"CREATE (TABLE|SCHEMA|ROLE|INDEX) IF NOT EXISTS", codigo.upper())  # un objeto previo exige revisión
    assert "CASCADE" not in sin_comentarios(BAJA).upper().replace("ON DELETE CASCADE", "")
    for ajeno in ("DROP SCHEMA app", "DROP SCHEMA tinotify_sintetico", "DROP SCHEMA public"):
        assert ajeno not in BAJA
    assert ALTA.count("BEGIN;") == 1 and ALTA.rstrip().endswith("COMMIT;") and BAJA.rstrip().endswith("COMMIT;")


def test_las_columnas_sensibles_tienen_formato_cerrado_y_no_hay_texto_libre_judicial():
    codigo = sin_comentarios(ALTA)
    assert "caso_ref ~ '^[0-9a-f]{64}$'" in codigo and "huella ~ '^[0-9a-f]{64}$'" in codigo
    assert "octet_length(nonce) = 12" in codigo and "octet_length(cifrado) BETWEEN 17 AND 2048" in codigo
    columnas = re.findall(r"^\s+(\w+) (?:text|jsonb|varchar)\b", codigo, re.M)
    assert sorted(columnas) == ["caso_ref", "caso_ref", "codigo", "huella", "plataforma", "proposito", "resultado", "token"]  # caso_ref: PK y FK
    # ninguna columna podría recibir descripciones, remitentes o nombres
    assert not re.search(r"\b(descripcion|remitente|mensaje|titulo|contenido|nombre|usuario|clave)\b\s+(text|jsonb)", codigo)
