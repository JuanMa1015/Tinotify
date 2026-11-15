"""Configuracion, aislamiento y comportamiento sin base de datos del almacen sintetico PostgreSQL. Sin red ni Docker."""

from ipaddress import ip_network
import logging
from pathlib import Path
import re
import subprocess
import sys
import threading
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from tinotify.sintetico_remoto.datos import CASO_OBSERVADO
from tinotify.sintetico_remoto import app as modulo_app
from tinotify.sintetico_remoto.app import crear_app, evaluar_transporte
from tinotify.sintetico_remoto.config import Config, ConfigPg, ConfiguracionInsegura, REDES_PRIVADAS
from tinotify.sintetico_remoto.errores import AlmacenIncompatible, AlmacenNoDisponible
from tinotify.sintetico_remoto.monitor import MonitorSintetico
from tinotify.sintetico_remoto.postgres import verificar_conexion

TOKEN = "Zq8rT2vLw9XkB4nM7pD1sHf6Jc3GyUaE5oR0"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PASSWORD = "Contrasena-Larga-De-Prueba-1234"
RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def ca(tmp_path):
    ruta = tmp_path / "ca.crt"
    ruta.write_text("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n", encoding="utf-8")
    return ruta


def entorno_pg(ca, **extra):
    base = {"TINOTIFY_SR_MODO": "pruebas-locales", "TINOTIFY_SR_TOKEN": TOKEN, "TINOTIFY_SR_ALMACEN": "postgres",
            "TINOTIFY_SR_PG_HOST": "aws-0-sa-east-1.pooler.supabase.com", "TINOTIFY_SR_PG_PORT": "5432",
            "TINOTIFY_SR_PG_USER": "tinotify_sintetico_app_login.abcdefghijklmnopqrst",
            "TINOTIFY_SR_PG_PASSWORD": PASSWORD, "TINOTIFY_SR_PG_CA_FILE": str(ca)}
    base.update(extra)
    return {k: v for k, v in base.items() if v is not None}


# --- Configuracion -------------------------------------------------------------------------------------------------------

def test_configuracion_postgres_valida_no_expone_secretos(ca):
    c = Config.desde_entorno(entorno_pg(ca))
    assert c.almacenamiento == "postgres" and c.ruta_bd is None and c.pg.modo == "sesion" and c.pg.max_conexiones == 3
    for texto in (repr(c), repr(c.pg), str(c.pg)):
        assert PASSWORD not in texto and "supabase.com" not in texto and "abcdefghij" not in texto and TOKEN not in texto


@pytest.mark.parametrize("extra,codigo", [
    ({"TINOTIFY_SR_PG_USER": "postgres"}, "pg_usuario_no_restringido"),
    ({"TINOTIFY_SR_PG_USER": "postgres.abcdefghijklmnopqrst"}, "pg_usuario_no_restringido"),
    ({"TINOTIFY_SR_PG_USER": "service_role"}, "pg_usuario_no_restringido"),
    ({"TINOTIFY_SR_PG_USER": "supabase_admin"}, "pg_usuario_no_restringido"),
    ({"TINOTIFY_SR_PG_USER": "tinotify_api"}, "pg_usuario_no_restringido"),
    ({"TINOTIFY_SR_PG_USER": None}, "pg_usuario_no_restringido"),
    ({"TINOTIFY_SR_PG_PASSWORD": None}, "pg_password_ausente_o_insegura"),
    ({"TINOTIFY_SR_PG_PASSWORD": "corta"}, "pg_password_ausente_o_insegura"),
    ({"TINOTIFY_SR_PG_PASSWORD": " " + PASSWORD}, "pg_password_ausente_o_insegura"),
    ({"TINOTIFY_SR_PG_HOST": None}, "pg_host_no_valido"),
    ({"TINOTIFY_SR_PG_HOST": "host con espacios"}, "pg_host_no_valido"),
    ({"TINOTIFY_SR_PG_HOST": "-oops"}, "pg_host_no_valido"),
    ({"TINOTIFY_SR_PG_HOST": "a.example.com,b.example.com"}, "pg_host_no_valido"),
    ({"TINOTIFY_SR_PG_PORT": "6543"}, "pg_pooler_transaccional_no_admitido"),
    ({"TINOTIFY_SR_PG_PORT": "abc"}, "pg_puerto_no_valido"),
    ({"TINOTIFY_SR_PG_PORT": "70000"}, "pg_puerto_no_valido"),
    ({"TINOTIFY_SR_PG_MODO": "transaccion"}, "pg_modo_no_valido"),
    ({"TINOTIFY_SR_PG_CA_FILE": None}, "pg_ca_ausente_o_invalida"),
    ({"TINOTIFY_SR_PG_CA_FILE": "/no/existe.crt"}, "pg_ca_ausente_o_invalida"),
    ({"TINOTIFY_SR_PG_MAX_CONEXIONES": "50"}, "pg_max_conexiones_no_valido"),
    ({"TINOTIFY_SR_PG_SSLMODE": "disable"}, "opcion_postgres_desconocida"),
    ({"TINOTIFY_SR_PG_SSLMODE": "verify-full"}, "opcion_postgres_desconocida"),
    ({"PGSSLMODE": "disable"}, "variables_libpq_presentes"),
    ({"PGPASSWORD": "otra"}, "variables_libpq_presentes"),
    ({"PGOPTIONS": "-c role=postgres"}, "variables_libpq_presentes"),
    ({"DATABASE_URL": "postgresql://x"}, "credencial_ajena_presente"),
    ({"SUPABASE_SERVICE_ROLE_KEY": "x"}, "credencial_ajena_presente"),
    ({"TINOTIFY_SR_DB": "/tmp/x.sqlite3"}, "almacenamiento_ambiguo"),
    ({"TINOTIFY_REAL_DB": "x"}, "variable_del_entorno_real_presente"),
    ({"TINOTIFY_SR_ALMACEN": "mongo"}, "almacenamiento_no_valido"),
])
def test_configuraciones_postgres_inseguras_se_rechazan(ca, extra, codigo):
    with pytest.raises(ConfiguracionInsegura) as error:
        Config.desde_entorno(entorno_pg(ca, **extra))
    assert error.value.codigo == codigo
    assert PASSWORD not in str(error.value) and "supabase.com" not in str(error.value)


def test_el_archivo_ca_debe_ser_un_certificado(tmp_path):
    falso = tmp_path / "no_cert.txt"
    falso.write_text("hola", encoding="utf-8")
    with pytest.raises(ConfiguracionInsegura):
        Config.desde_entorno(entorno_pg(falso))


def test_opciones_postgres_con_almacen_sqlite_se_rechazan(tmp_path, ca):
    e = {"TINOTIFY_SR_MODO": "pruebas-locales", "TINOTIFY_SR_TOKEN": TOKEN, "TINOTIFY_SR_DB": str(tmp_path / "x.sqlite3"),
         "TINOTIFY_SR_PG_HOST": "localhost"}
    with pytest.raises(ConfiguracionInsegura) as error:
        Config.desde_entorno(e)
    assert error.value.codigo == "opciones_postgres_con_almacen_sqlite"


def test_remoto_con_postgres_exige_tls_y_acepta_proxies_privadas(ca):
    remoto = entorno_pg(ca, TINOTIFY_SR_MODO="remoto", TINOTIFY_SR_INTERVALO_S="300")
    with pytest.raises(ConfiguracionInsegura) as error:
        Config.desde_entorno(remoto)
    assert error.value.codigo == "tls_obligatorio_en_remoto"
    c = Config.desde_entorno({**remoto, "TINOTIFY_SR_TLS": "proxy", "TINOTIFY_SR_PROXIES_CONFIABLES": "privadas"})
    assert c.proxies_confiables == REDES_PRIVADAS and c.remoto and c.tls == "proxy"


# --- Proxy de Render: solo pares TCP privados, nunca encabezados de clientes ---------------------------------------------------

def _cfg_privadas(tmp_path):
    return Config(modo="remoto", token=TOKEN, ruta_bd=tmp_path / "x.sqlite3", tls="proxy", proxies_confiables=REDES_PRIVADAS,
                  monitor_activo=False, intervalo_s=60.0)


@pytest.mark.parametrize("par,cabecera,esperado", [
    ("10.20.30.40", "https", None), ("172.20.0.9", "https", None), ("192.168.1.5", "HTTPS", None),
    ("fd12:3456::1", "https", None), ("::ffff:10.0.0.7", "https", None),
    ("10.20.30.40", "http", 403), ("10.20.30.40", "", 403), ("10.20.30.40", "https, http", 403),
    ("203.0.113.5", "https", 403), ("8.8.8.8", "https", 403), ("127.0.0.1", "https", 403), ("::1", "https", 403),
    ("172.32.0.1", "https", 403), (None, "https", 403), ("no-es-ip", "https", 403),
])
def test_proxy_privadas_solo_confia_en_pares_privados(tmp_path, par, cabecera, esperado):
    cabeceras = {"x-forwarded-proto": cabecera} if cabecera else {}
    resultado = evaluar_transporte(_cfg_privadas(tmp_path), par, "http", cabeceras)
    assert (None if resultado is None else resultado[0]) == esperado


def test_un_cliente_publico_no_puede_afirmar_https_con_proxies_privadas(tmp_path):
    class ServicioSimulado:
        sintetico = True

        def listar_casos(self):
            return []

    config = _cfg_privadas(tmp_path)

    c = TestClient(
        crear_app(config, servicio=ServicioSimulado()),
        client=("203.0.113.9", 4000),
        raise_server_exceptions=False,
    )
    r = c.get("/sintetico/casos", headers={**AUTH, "X-Forwarded-Proto": "https", "X-Forwarded-For": "10.0.0.1"})
    assert r.status_code == 403

    c_privado = TestClient(
        crear_app(config, servicio=ServicioSimulado()),
        client=("10.1.2.3", 4000),
    )
    respuesta = c_privado.get(
        "/sintetico/casos",
        headers={**AUTH, "X-Forwarded-Proto": "https"},
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == []


def test_las_redes_privadas_son_exactamente_las_rfc1918_y_ula():
    assert {str(r) for r in REDES_PRIVADAS} == {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"}
    assert not any(ip_network("203.0.113.0/24").overlaps(r) for r in REDES_PRIVADAS)


# --- Monitor con almacen no disponible, exclusion y persistencia (dobles de prueba) ----------------------------------------------

class ServicioCaido:
    sintetico = True

    def __init__(self):
        self.llamadas = 0

    def detalle(self, caso):
        self.llamadas += 1
        raise AlmacenNoDisponible("PostgreSQL no disponible")


def test_el_monitor_no_se_detiene_cuando_postgresql_no_esta_disponible():
    m = MonitorSintetico(ServicioCaido(), intervalo_s=0.01, max_actuaciones=10, max_bd_bytes=10**6)
    assert [m.ejecutar_ciclo() for _ in range(20)] == ["fallo"] * 20
    estado = m.snapshot()
    assert estado["motivo"] == "almacen_no_disponible" and estado["ciclos_fallidos"] == 20 and m._seguidos == 0


def test_el_hilo_del_monitor_reintenta_con_espera_creciente_sin_pasar_a_error():
    servicio = ServicioCaido()
    m = MonitorSintetico(servicio, intervalo_s=0.01, max_actuaciones=10, max_bd_bytes=10**6)
    m.iniciar()
    for _ in range(200):
        if servicio.llamadas >= 3:
            break
        threading.Event().wait(0.02)
    assert m.snapshot()["estado"] == "activo" and servicio.llamadas >= 3
    m.detener(1)


class ExclusionFalsa:
    def __init__(self, libre=True):
        self.libre, self.tengo, self.liberada = libre, False, 0

    def adquirir(self):
        if self.libre:
            self.tengo = True
        return self.libre

    def mantiene(self):
        return self.tengo

    def liberar(self):
        self.tengo, self.liberada = False, self.liberada + 1


class PersistenciaFalsa:
    def __init__(self, previo=None, falla=False):
        self.previo, self.guardados, self.falla = previo, [], falla

    def cargar(self):
        if self.falla:
            raise RuntimeError("detalle interno confidencial")
        return self.previo

    def guardar(self, estado):
        if self.falla:
            raise RuntimeError("detalle interno confidencial")
        self.guardados.append(dict(estado))


class ServicioMemoria:
    sintetico = True

    def __init__(self):
        self.n = 0

    def detalle(self, caso):
        if self.n == 0:
            raise KeyError(caso)
        return {"total_actuaciones": self.n}

    def observar_html(self, caso, html, titulo=None):
        self.n += 1
        return {"baseline": self.n == 1, "novedades_nuevas": 1, "actuaciones": self.n, "generacion": self.n}

    def tamano_bytes(self):
        return 0


def _esperar(condicion, veces=200):
    for _ in range(veces):
        if condicion():
            return True
        threading.Event().wait(0.02)
    return False


def test_sin_el_bloqueo_el_monitor_espera_sin_escribir_y_libera_al_detenerse():
    exclusion, servicio = ExclusionFalsa(libre=False), ServicioMemoria()
    m = MonitorSintetico(servicio, intervalo_s=0.01, max_actuaciones=10, max_bd_bytes=10**6, exclusion=exclusion)
    m.iniciar()
    assert _esperar(lambda: m.snapshot()["estado"] == "en_espera")
    threading.Event().wait(0.1)
    assert servicio.n == 0
    exclusion.libre = True
    assert _esperar(lambda: servicio.n >= 2) and m.snapshot()["estado"] == "activo"
    m.detener(1)
    assert exclusion.liberada >= 1


def test_el_monitor_restaura_y_guarda_su_estado_y_tolera_fallos_de_persistencia(caplog):
    previo = {"ciclos_correctos": 7, "ciclos_fallidos": 2, "motivo": None,
              "ultimo_ciclo": {"hora": 1.0, "actuaciones": 3, "novedades_nuevas": 0, "generacion": 1}}
    p = PersistenciaFalsa(previo)
    m = MonitorSintetico(ServicioMemoria(), intervalo_s=0.01, max_actuaciones=10, max_bd_bytes=10**6, persistencia=p)
    m._restaurar_estado()
    assert m.snapshot()["ciclos_correctos"] == 7 and m.snapshot()["ultimo_ciclo"]["actuaciones"] == 3
    assert m.ejecutar_ciclo() == "ok"
    assert p.guardados[-1]["ciclos_correctos"] == 8
    rota = MonitorSintetico(ServicioMemoria(), intervalo_s=0.01, max_actuaciones=10, max_bd_bytes=10**6,
                            persistencia=PersistenciaFalsa(falla=True))
    with caplog.at_level(logging.DEBUG):
        rota._restaurar_estado()
        assert rota.ejecutar_ciclo() == "ok"
    assert "confidencial" not in caplog.text


# --- API: 503 genericos ---------------------------------------------------------------------------------------------------------

class ServicioApiCaido:
    sintetico = True

    def __init__(self, error):
        self.error = error

    def _falla(self, *_):
        raise self.error

    listar_casos = novedades = detalle = _falla


@pytest.mark.parametrize("error", [AlmacenNoDisponible("host db.interno:5432 usuario secreto"),
                                   AlmacenIncompatible("detalle de privilegios")])
def test_la_api_responde_503_generico_sin_detalles(tmp_path, error, caplog):
    cfg = Config(modo="pruebas-locales", token=TOKEN, ruta_bd=tmp_path / "x.sqlite3", monitor_activo=False)
    c = TestClient(crear_app(cfg, servicio=ServicioApiCaido(error)), client=("127.0.0.1", 1), raise_server_exceptions=False)
    with caplog.at_level(logging.DEBUG):
        for ruta in ("/sintetico/casos", "/sintetico/novedades", f"/sintetico/casos/{CASO_OBSERVADO}"):
            r = c.get(ruta, headers=AUTH)
            assert r.status_code == 503 and r.json() == {"detail": "Almacen no disponible"}
            assert r.headers["retry-after"] == "30" and "secreto" not in r.text and "db.interno" not in r.text
    assert "secreto" not in caplog.text and "db.interno" not in caplog.text and TOKEN not in caplog.text
    assert c.get("/health").json() == {"estado": "ok"}


# --- Verificacion de la conexion y aislamiento --------------------------------------------------------------------------------------

def test_una_conexion_sin_tls_verificado_se_rechaza():
    sin_tls = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=False), info=SimpleNamespace(get_parameters=lambda: {}))
    with pytest.raises(AlmacenIncompatible):
        verificar_conexion(sin_tls)
    modo_debil = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True),
                                 info=SimpleNamespace(get_parameters=lambda: {"sslmode": "require"}))
    with pytest.raises(AlmacenIncompatible):
        verificar_conexion(modo_debil)


PROHIBIDOS = ("tinotify.integrations.sigac", "tinotify.services.monitor_local", "tinotify.services.sesion_sigac_local",
              "tinotify.services.consulta_real_local", "tinotify.api.real_local", "tinotify.api.demo",
              "tinotify.persistence.postgres", "tinotify.services.ensayo_sigac", "tinotify.demo.push")


def _modulos_cargados(importar):
    codigo = (f"import sys, {importar}\n"
              f"print(sorted(m for m in sys.modules if m.startswith({PROHIBIDOS!r})))\n"
              "print('psycopg' in sys.modules)")
    salida = subprocess.run([sys.executable, "-I", "-c", codigo], capture_output=True, text=True, timeout=120)
    assert salida.returncode == 0, salida.stderr[-400:]
    prohibidos, psycopg_cargado = salida.stdout.strip().splitlines()
    return prohibidos, psycopg_cargado == "True"


def test_ni_la_app_ni_el_almacen_postgres_importan_sigac_ni_la_persistencia_institucional():
    prohibidos, psycopg_cargado = _modulos_cargados("tinotify.sintetico_remoto.app")
    assert prohibidos == "[]" and psycopg_cargado is False     # con SQLite no se carga el driver
    prohibidos, psycopg_cargado = _modulos_cargados("tinotify.sintetico_remoto.postgres")
    assert prohibidos == "[]" and psycopg_cargado is True


def test_el_codigo_del_almacen_no_debilita_tls_ni_usa_claves_ajenas():
    texto = (Path(modulo_app.__file__).parent / "postgres.py").read_text(encoding="utf-8")
    assert 'sslmode="verify-full"' in texto
    for prohibido in ("sslmode=disable", "sslmode='disable'", '"require"', "service_role_key", "SERVICE_ROLE", "6543"):
        assert prohibido not in texto, prohibido
    import ast
    for nodo in ast.walk(ast.parse(texto)):
        modulos = [a.name for a in nodo.names] if isinstance(nodo, ast.Import) else [nodo.module or ""] if isinstance(nodo, ast.ImportFrom) else []
        assert not any("sigac" in m.lower() or m.startswith(("tinotify.persistence.postgres", "tinotify.api")) for m in modulos), modulos
    assert "print(" not in texto
    for archivo in (Path(modulo_app.__file__).parent).glob("*.py"):
        assert "console.log" not in archivo.read_text(encoding="utf-8")


# --- Migracion SQL (estatico; la ejecucion real esta en integration/) -----------------------------------------------------------------

MIGRACION = RAIZ / "supabase/propuestas/20261115000000_crear_almacen_sintetico.sql"
BAJA = RAIZ / "supabase/propuestas/20261115000000_crear_almacen_sintetico_down.sql"


def test_la_migracion_sintetica_es_independiente_sin_secretos_y_tiene_reversion():
    sql = MIGRACION.read_text(encoding="utf-8")
    assert BAJA.is_file() and "DROP SCHEMA tinotify_sintetico;" in BAJA.read_text(encoding="utf-8")
    codigo = chr(10).join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))   # sin comentarios
    assert not re.search(r"CREATE\s+\w+\s+IF\s+NOT\s+EXISTS", codigo, re.I)
    assert not re.search(r"PASSWORD", codigo, re.I)
    assert not re.search(r"CREATE\s+ROLE[^;]*\bLOGIN\b", codigo.replace("NOLOGIN", ""), re.I)
    assert "CREATE ROLE tinotify_sintetico_app NOLOGIN" in sql
    # Ninguna sentencia toca esquemas ajenos (las auditorias solo los consultan por nombre).
    assert not re.search(r"(GRANT|REVOKE|CREATE|ALTER|DROP|INSERT|UPDATE|DELETE)[^;]*\b(app|app_private|app_fixture|auth)\.", codigo, re.I)
    for ajeno in ("ALTER DEFAULT PRIVILEGES", "GRANT ALL", "SUPERUSER"):
        assert ajeno not in codigo.replace("NOSUPERUSER", ""), ajeno
    # Solo toca su propio esquema.
    assert set(re.findall(r"\b(?:CREATE|ALTER|DROP)\s+(?:TABLE|SCHEMA|FUNCTION)\s+(?:IF EXISTS\s+)?([a-z_]+)\.", sql)) <= {"tinotify_sintetico"}


def test_las_migraciones_originales_siguen_siendo_cuatro_y_sin_cambios():
    nombres = sorted(p.name for p in (RAIZ / "supabase/migrations").glob("*.sql"))
    assert nombres[:4] == ["20261112050000_preparar_esquemas_privados.sql", "20261112160000_crear_nucleo_reconciliacion.sql",
                           "20261114010000_habilitar_persistencia_sintetica.sql", "20261114020000_controlar_fixtures_inertes.sql"]
    assert len(nombres) == 4   # la propuesta sintetica vive en supabase/propuestas hasta que se autorice moverla


def _literales(texto):
    """Literales '...' y U&'...' de un trozo de SQL, con los escapes \\00e9 ya decodificados."""
    for m in re.finditer(r"(U&)?'([^']*)'", texto):
        valor = m.group(2)
        if m.group(1):
            valor = re.sub(r"\\([0-9a-fA-F]{4})", lambda x: chr(int(x.group(1), 16)), valor)
        yield valor


def test_los_textos_cerrados_de_la_migracion_coinciden_con_el_dominio_y_el_generador():
    import dataclasses
    from tinotify.sintetico_remoto.datos import TITULO_OBSERVADO
    from tinotify.domain.actuaciones import TipoCambio
    from tinotify.domain.notificaciones import Prioridad, crear_notificacion

    sql = MIGRACION.read_text(encoding="utf-8")
    codigo = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
    tipos = {t.value for t in TipoCambio}
    esperados, pares = set(), set()
    for tipo in TipoCambio:
        for direccion in ("", "ASESOR-->ESTUDIANTE"):
            n = crear_notificacion(0, direccion, tipo)
            esperados |= {n.titulo, n.mensaje}
            pares.add((tipo.value, n.titulo, n.mensaje))
        for prioridad in Prioridad:   # el adaptador conserva el texto del caso normal
            n = dataclasses.replace(crear_notificacion(0, "", tipo), prioridad=prioridad)
            esperados |= {n.titulo, n.mensaje}
            pares.add((tipo.value, n.titulo, n.mensaje))
    inicio = codigo.index("CONSTRAINT textos_del_dominio CHECK (")
    bloque = codigo[inicio:codigo.index("disposicion text", inicio)]
    en_sql = {v for v in _literales(bloque)} - tipos
    assert en_sql == esperados, (en_sql ^ esperados)
    # Cada par (tipo, titulo, mensaje) del dominio aparece en el mismo tramo OR del CHECK.
    tramos = re.split(r"\n\s*OR \(", bloque)
    for tipo, titulo, mensaje in pares:
        tramo = next(t for t in tramos if f"'{tipo}'" in t)
        assert titulo in set(_literales(tramo)) and mensaje in set(_literales(tramo)), (tipo, titulo)
    titulo_caso = codigo[codigo.index("CONSTRAINT titulo_del_generador"):]
    assert next(_literales(titulo_caso.split("CHECK", 1)[1])) == TITULO_OBSERVADO


def test_los_limites_y_el_bloqueo_exigen_read_committed_y_un_solo_bloqueo_global():
    sql = MIGRACION.read_text(encoding="utf-8")
    for funcion in ("limitar_casos", "limitar_novedades"):
        cuerpo = sql[sql.index(f"FUNCTION tinotify_sintetico.{funcion}()"):]
        cuerpo = cuerpo[:cuerpo.index("$fn$;")]
        assert "transaction_isolation" in cuerpo and "'read committed'" in cuerpo
        assert cuerpo.index("transaction_isolation") < cuerpo.index("pg_advisory_xact_lock(7402100002)")
    # La clave del bloqueo de transaccion no puede coincidir con la del monitor (bloqueo de sesion).
    from tinotify.sintetico_remoto.postgres import CLAVE_EXCLUSION_MONITOR
    assert CLAVE_EXCLUSION_MONITOR != 7402100002


def test_el_script_de_reversion_es_explicito_sin_cascade_ni_drop_owned_ni_lectura_de_filas():
    baja = BAJA.read_text(encoding="utf-8")
    codigo = chr(10).join(l for l in baja.splitlines() if not l.lstrip().startswith("--"))
    for prohibido in ("CASCADE", "DROP OWNED", "REASSIGN OWNED"):
        assert prohibido not in codigo, prohibido
    assert not re.search(r"DROP\s+\w+\s+IF\s+EXISTS", codigo, re.I)   # nada de borrados «si existe»: todo es explicito
    # La identidad del esquema sale de catalogos: las filas de entorno estan bajo RLS forzado y no siempre son visibles.
    assert "tinotify_sintetico.entorno WHERE" not in codigo and "FROM tinotify_sintetico." not in codigo
    assert "obj_description(" in codigo and "inherit_option" in codigo and "set_option" in codigo
    # El comentario que la reversion exige es exactamente el que escribe la migracion.
    comentario = "Tinotify: datos FICTICIOS del backend sintetico. Nunca expuesto por la Data API."
    assert comentario in baja and f"COMMENT ON SCHEMA tinotify_sintetico IS '{comentario}'" in MIGRACION.read_text(encoding="utf-8")
    # Una sola transaccion, con verificacion final antes del COMMIT, y todas las tablas/funciones nombradas explicitamente.
    assert codigo.count("BEGIN;") == 1 and codigo.rstrip().endswith("COMMIT;") and codigo.index("verificacion") < codigo.rindex("COMMIT;")
    for nombre in ("novedades", "actuaciones", "casos", "monitor_estado", "entorno"):
        assert f"tinotify_sintetico.{nombre}" in codigo
    assert "DROP ROLE tinotify_sintetico_app;" in codigo and "DROP SCHEMA tinotify_sintetico;" in codigo


def test_lifespan_limpia_si_falla_inicio_monitor():
    import asyncio

    class Servicio:
        sintetico = True

        def __init__(self):
            self.cierres = 0

        def cerrar(self):
            self.cierres += 1

    class Monitor:
        def __init__(self):
            self.inicios = 0
            self.detenciones = 0

        def iniciar(self):
            self.inicios += 1
            raise RuntimeError("fallo_inicio_controlado")

        def detener(self):
            self.detenciones += 1

    servicio = Servicio()
    monitor = Monitor()
    config = Config(modo="remoto", token=TOKEN, monitor_activo=True)
    app = crear_app(config, servicio=servicio, monitor=monitor)

    async def ejecutar():
        async with app.router.lifespan_context(app):
            pass

    with pytest.raises(RuntimeError, match="fallo_inicio_controlado"):
        asyncio.run(ejecutar())

    assert monitor.inicios == 1
    assert monitor.detenciones == 1
    assert servicio.cierres == 1


def test_lifespan_cierra_servicio_aunque_falle_detener_monitor():
    import asyncio

    class Servicio:
        sintetico = True

        def __init__(self):
            self.cierres = 0

        def cerrar(self):
            self.cierres += 1

    class Monitor:
        def __init__(self):
            self.inicios = 0
            self.detenciones = 0

        def iniciar(self):
            self.inicios += 1

        def detener(self):
            self.detenciones += 1
            raise RuntimeError("fallo_detencion_controlado")

    servicio = Servicio()
    monitor = Monitor()
    config = Config(modo="remoto", token=TOKEN, monitor_activo=True)
    app = crear_app(config, servicio=servicio, monitor=monitor)

    async def ejecutar():
        async with app.router.lifespan_context(app):
            pass

    with pytest.raises(RuntimeError, match="fallo_detencion_controlado"):
        asyncio.run(ejecutar())

    assert monitor.inicios == 1
    assert monitor.detenciones == 1
    assert servicio.cierres == 1
