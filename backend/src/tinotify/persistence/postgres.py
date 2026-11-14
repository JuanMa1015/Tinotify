"""Adaptador sin conexiones al importar. Solo funciones SQL de capacidad finita."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from tinotify.domain.identificadores import PoliticaConfianza
from tinotify.persistence.codec_postgres import a_filas, binario, de_filas, reconstruir
from tinotify.persistence.interfaces import Autenticador, Principal, Reserva, Seguimiento


class ConexionInterrumpida(RuntimeError):
    """No repetir ciegamente: consultar/reusar la misma clave de idempotencia."""


class ConflictoPersistencia(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfiguracionPostgres:
    dsn: str = field(repr=False)
    certificado_ca: Path
    conexion: str = "directa"
    max_conexiones: int = 4

    def opciones(self):
        try:
            opciones = conninfo_to_dict(self.dsn)
        except psycopg.Error:
            raise ValueError("Configuracion PostgreSQL no valida") from None
        if self.conexion not in ("directa", "sesion") or not 1 <= self.max_conexiones <= 16:
            raise ValueError("Modalidad o cuota de conexiones no valida")
        host, usuario = opciones.get("host", ""), opciones.get("user", "")
        if not host or host.startswith(("/", "\\")) or "," in host or not usuario:
            raise ValueError("Se requiere un host TLS y usuario explicitos")
        if usuario.split(".")[0] in ("postgres", "service_role", "supabase_admin"):
            raise ValueError("Identidad administrativa no permitida")
        if opciones.get("port", "5432") == "6543" or any(k in opciones for k in ("options", "service")):
            raise ValueError("No se admite pooler transaccional ni opciones de sesion externas")
        if opciones.get("sslmode", "verify-full") != "verify-full" or not self.certificado_ca.is_file():
            raise ValueError("TLS requiere verify-full y CA explicita")
        opciones.update(sslmode="verify-full", sslrootcert=str(self.certificado_ca),
                         connect_timeout=5, application_name="tinotify-persistencia")
        return opciones


def comprobar_identidad(conexion):
    if not conexion.pgconn.ssl_in_use or conexion.info.get_parameters().get("sslmode") != "verify-full":
        raise PermissionError("La conexion requiere TLS con verificacion completa")
    fila = conexion.execute("""
        SELECT current_user=session_user AND NOT r.rolsuper AND NOT r.rolbypassrls
            AND NOT r.rolcreatedb AND NOT r.rolcreaterole AND NOT r.rolreplication
            AND r.rolname NOT IN ('postgres','service_role','supabase_admin')
            AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles p
                WHERE (p.rolsuper OR p.rolbypassrls OR p.rolcreaterole OR p.rolcreatedb
                    OR p.rolname IN ('tinotify_guard_reader','tinotify_state_writer')
                    OR p.oid IN (SELECT c.relowner FROM pg_catalog.pg_class c
                        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                        WHERE n.nspname IN ('app','app_private')))
                  AND pg_catalog.pg_has_role(session_user,p.oid,'MEMBER'))
            AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname IN ('app','app_private') AND c.relkind IN ('r','p','v','m','f')
                AND (pg_catalog.has_table_privilege(session_user,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
                  OR pg_catalog.has_any_column_privilege(session_user,c.oid,'SELECT,INSERT,UPDATE,REFERENCES')))
        FROM pg_catalog.pg_roles r WHERE r.rolname=session_user
    """).fetchone()
    if fila is None or fila[0] is not True:
        raise PermissionError("La conexion no tiene una identidad operativa restringida")


def limpiar_conexion(conexion):
    # autocommit=True; cualquier fallo hace que psycopg_pool descarte la conexion.
    conexion.execute("RESET ROLE")
    conexion.execute("RESET ALL")


def crear_pool(configuracion: ConfiguracionPostgres):
    return ConnectionPool(
        conninfo="", kwargs={**configuracion.opciones(), "autocommit": True, "prepare_threshold": None},
        min_size=0, max_size=configuracion.max_conexiones, timeout=5,
        configure=comprobar_identidad, reset=limpiar_conexion,
        check=ConnectionPool.check_connection, open=False,
    )


class UnidadPostgres:
    def __init__(self, conexion, politica):
        self._conexion, self._politica = conexion, politica

    def seguir(self, instancia, caso, politica):
        fila = self._conexion.execute("SELECT app_private.seguir(%s,%s,%s)",
                                      (binario(instancia), binario(caso), politica)).fetchone()[0]
        return Seguimiento(UUID(fila["estado_id"]), UUID(fila["expediente_id"]))

    def reservar(self, seguimiento, clave, worker, binding):
        fila = self._conexion.execute("SELECT app_private.reservar(%s,%s,%s,%s,%s)",
            (seguimiento.estado_id, seguimiento.expediente_id, clave, worker, binding)).fetchone()[0]
        return Reserva(seguimiento, UUID(fila["id"]), UUID(fila["token"]) if fila["token"] else None,
                       fila["generacion"], fila["estado"])

    def leer_caso(self, seguimiento, binding):
        filas = self._conexion.execute("SELECT app_private.leer_caso(%s,%s,%s)",
            (seguimiento.estado_id, seguimiento.expediente_id, binding)).fetchone()[0]
        return None if filas is None else de_filas(filas)

    def confirmar(self, reserva, registros, eventos, politica):
        return self._conexion.execute("SELECT app_private.confirmar(%s,%s,%s,%s,%s,%s,%s,%s)",
            (reserva.seguimiento.estado_id, reserva.seguimiento.expediente_id, reserva.trabajo_id,
             reserva.token, reserva.generacion, Jsonb(a_filas(registros)), Jsonb(eventos), politica)).fetchone()[0]

    def exportar(self, instancia, binding):
        datos = self._conexion.execute("SELECT app_private.exportar(%s,%s)", (binario(instancia), binding)).fetchone()[0]
        return None if datos is None else reconstruir(datos, instancia, self._politica)

    def pendientes(self, binding, limite=100):
        return self._conexion.execute("SELECT app_private.pendientes(%s,%s)", (binding, limite)).fetchone()[0]

    def procesar_aviso(self, evento, binding):
        self._conexion.execute("SELECT app_private.procesar_aviso(%s,%s)", (evento, binding))


class AlmacenPostgres:
    def __init__(self, pool, autenticador: Autenticador, *, politica=None):
        if autenticador is None:
            raise ValueError("Se requiere autenticador confiable; no se aceptan user_id")
        self._pool, self._autenticador = pool, autenticador
        self._politica = politica if politica is not None else PoliticaConfianza()

    @contextmanager
    def transaccion(self, credencial, *, lectura=False):
        principal = self._autenticador.verificar(credencial)
        if not isinstance(principal, Principal):
            raise PermissionError("No se recibio una identidad validada")
        principal.comprobar()
        try:
            with self._pool.connection() as conexion:
                with conexion.transaction():
                    if lectura:
                        conexion.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    comprobar_identidad(conexion)
                    conexion.execute("SELECT set_config('tinotify.subject',%s,true)", (str(principal.sujeto),))
                    conexion.execute("SELECT set_config('row_security','on',true), set_config('lock_timeout','3s',true), set_config('statement_timeout','15s',true)")
                    yield UnidadPostgres(conexion, self._politica)
                    principal.comprobar()
        except psycopg.Error as error:
            if isinstance(error, psycopg.OperationalError) and (
                error.sqlstate is None or error.sqlstate.startswith("08")
                or error.sqlstate in ("57P01", "57P02", "57P03")
            ):
                raise ConexionInterrumpida("Conexion interrumpida; resolver con la misma clave de idempotencia") from None
            if error.sqlstate in ("42501", "P0002"):
                raise PermissionError("Operacion no autorizada") from None
            raise ConflictoPersistencia(f"Operacion revertida (SQLSTATE {error.sqlstate})") from None
