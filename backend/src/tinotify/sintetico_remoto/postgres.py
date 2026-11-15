"""Almacen PostgreSQL del backend SINTETICO (esquema `tinotify_sintetico`), con la misma API que el servicio SQLite.

Aislamiento: no usa `tinotify.persistence.postgres`, ni los esquemas `app`/`app_private`/`app_fixture`, ni `auth`.
No importa nada de SIGAC. Solo datos ficticios: la propia base rechaza ids de caso fuera del espacio sintetico y
contenido sin la marca SINTETICO.

Conexion: componentes (nunca un DSN), TLS `verify-full` con CA explicita, usuario restringido `tinotify_sintetico_*`,
sin pooler transaccional. El pool se abre sin conectar: si PostgreSQL no responde al arrancar, la API sigue viva y
responde 503 hasta que vuelva. Los mensajes de error son fijos y no incluyen host, usuario, SQL ni contenido.
"""

from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
import logging
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout

from tinotify.sintetico_remoto.datos import TITULO_OBSERVADO, ObservacionRechazada, _contenido
from tinotify.domain.actuaciones import Actuacion, TipoCambio
from tinotify.domain.notificaciones import clasificar_prioridad, crear_notificacion
from tinotify.parsers.parser import ErrorParseoHistorial, parse_actuaciones
from tinotify.sintetico_remoto.config import ConfigPg
from tinotify.sintetico_remoto.errores import AlmacenIncompatible, AlmacenNoDisponible

registro = logging.getLogger("tinotify.sintetico_remoto")

CLAVE_EXCLUSION_MONITOR = 7402100001   # bigint arbitrario y fijo para pg_try_advisory_lock
MAX_ACTUACIONES = 200
LIMITE_NOVEDADES = 100

_VERIFICACION = """
SELECT current_user = session_user
   AND NOT r.rolsuper AND NOT r.rolbypassrls AND NOT r.rolcreaterole AND NOT r.rolcreatedb AND NOT r.rolreplication
   AND r.rolname ~ '^tinotify_sintetico_'
   AND pg_catalog.pg_has_role(session_user, 'tinotify_sintetico_app', 'USAGE')
   AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles p WHERE p.oid <> r.oid
        AND (p.rolsuper OR p.rolbypassrls OR p.rolcreaterole OR p.rolcreatedb OR p.rolname IN
             ('postgres','service_role','supabase_admin','authenticator','anon','authenticated',
              'supabase_auth_admin','supabase_storage_admin'))
        AND pg_catalog.pg_has_role(session_user, p.oid, 'MEMBER'))
   AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
        WHERE n.nspname IN ('app','app_private','app_fixture','auth','storage','public','tinotify_sintetico')
          AND pg_catalog.has_schema_privilege(session_user, n.oid, 'CREATE'))
   AND NOT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace n
        WHERE n.nspname IN ('app','app_private','app_fixture','auth','storage')
          AND pg_catalog.has_schema_privilege(session_user, n.oid, 'USAGE'))
FROM pg_catalog.pg_roles r WHERE r.rolname = session_user
"""


def opciones_conexion(cfg: ConfigPg):
    opciones = dict(host=cfg.host, port=cfg.puerto, dbname=cfg.base, user=cfg.usuario, password=cfg.password,
                    sslmode="verify-full", sslrootcert=str(cfg.ca), connect_timeout=max(1, int(cfg.espera_s)),
                    application_name="tinotify-sintetico")
    if cfg.hostaddr:
        opciones["hostaddr"] = cfg.hostaddr
    return opciones


def verificar_conexion(conexion):
    """TLS efectivo, identidad restringida y marca de esquema sintetico. Lanza AlmacenIncompatible si no se cumple."""
    if not conexion.pgconn.ssl_in_use or conexion.info.get_parameters().get("sslmode") != "verify-full":
        raise AlmacenIncompatible("La conexion no usa TLS con verificacion completa")
    try:
        fila = conexion.execute(_VERIFICACION).fetchone()
        marca = conexion.execute("SELECT proposito, version_esquema FROM tinotify_sintetico.entorno").fetchall()
    except psycopg.errors.InsufficientPrivilege:
        raise AlmacenIncompatible("Privilegios insuficientes sobre el almacen sintetico") from None
    except psycopg.errors.UndefinedTable:
        raise AlmacenIncompatible("El almacen sintetico no esta instalado") from None
    if fila is None or fila[0] is not True:
        raise AlmacenIncompatible("La identidad de base de datos no es la restringida esperada")
    if marca != [("sintetico", 1)]:
        raise AlmacenIncompatible("El esquema no esta marcado como almacen sintetico compatible")


def _traducir(error):
    """Convierte errores de psycopg en errores propios de mensaje fijo (nunca incluye el detalle del servidor)."""
    if isinstance(error, (PoolTimeout, PoolClosed)):
        return AlmacenNoDisponible("PostgreSQL no disponible")
    if isinstance(error, psycopg.errors.InsufficientPrivilege):
        return AlmacenIncompatible("Privilegios insuficientes sobre el almacen sintetico")
    if isinstance(error, psycopg.errors.CheckViolation) or getattr(error, "sqlstate", None) == "54000":
        return ObservacionRechazada("El almacen sintetico rechazo los datos; estado sin cambios.")
    if isinstance(error, psycopg.OperationalError):
        return AlmacenNoDisponible("PostgreSQL no disponible")
    return RuntimeError("Operacion del almacen revertida")


class AlmacenPg:
    def __init__(self, cfg: ConfigPg):
        self._cfg = cfg
        self._pool = ConnectionPool(
            conninfo="", kwargs={**opciones_conexion(cfg), "autocommit": True, "prepare_threshold": None},
            min_size=0, max_size=cfg.max_conexiones, timeout=cfg.espera_s, configure=verificar_conexion,
            reset=_limpiar, check=ConnectionPool.check_connection, open=False)
        self._pool.open(wait=False)

    @property
    def cfg(self):
        return self._cfg

    def cerrar(self):
        try:
            self._pool.close(timeout=5)
        except Exception:  # noqa: BLE001
            pass

    def verificar_inicio(self):
        """Comprobacion directa y precisa al arrancar: AlmacenIncompatible aborta el arranque; indisponible se tolera."""
        try:
            with psycopg.connect(**opciones_conexion(self._cfg), autocommit=True) as conexion:
                verificar_conexion(conexion)
        except (AlmacenIncompatible, AlmacenNoDisponible):
            raise
        except psycopg.Error as error:
            raise _traducir(error) from None

    @contextmanager
    def transaccion(self, *, lectura=False):
        try:
            with self._pool.connection() as conexion:
                with conexion.transaction():
                    if lectura:
                        conexion.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    conexion.execute("SELECT set_config('lock_timeout','3s',true), "
                                     "set_config('statement_timeout','15s',true), set_config('row_security','on',true)")
                    yield conexion
        except (psycopg.Error, PoolTimeout, PoolClosed) as error:
            raise _traducir(error) from None


def _limpiar(conexion):
    conexion.execute("RESET ALL")


class ExclusionMonitor:
    """Un solo monitor por base: bloqueo asesor de SESION sobre una conexion dedicada.

    Si el proceso muere o pierde la conexion, PostgreSQL libera el bloqueo solo: no hay archivos ni filas huerfanas
    que limpiar a mano. Requiere conexion de sesion (directa o pooler de sesion), nunca el pooler transaccional.
    """

    def __init__(self, cfg: ConfigPg):
        self._cfg, self._conexion = cfg, None

    def adquirir(self):
        if self._conexion is not None:
            return True
        try:
            conexion = psycopg.connect(**opciones_conexion(self._cfg), autocommit=True)
            try:
                verificar_conexion(conexion)
                if conexion.execute("SELECT pg_try_advisory_lock(%s)", (CLAVE_EXCLUSION_MONITOR,)).fetchone()[0]:
                    self._conexion = conexion
                    return True
            except BaseException:
                conexion.close()
                raise
            conexion.close()
            return False
        except psycopg.Error as error:
            raise _traducir(error) from None

    def mantiene(self):
        if self._conexion is None:
            return False
        try:
            self._conexion.execute("SELECT 1")
            return True
        except psycopg.Error:
            self.liberar()
            return False

    def liberar(self):
        conexion, self._conexion = self._conexion, None
        if conexion is not None:
            try:
                conexion.close()
            except psycopg.Error:
                pass


class EstadoMonitorPg:
    def __init__(self, almacen: AlmacenPg):
        self._almacen = almacen

    def cargar(self):
        with self._almacen.transaccion(lectura=True) as c:
            fila = c.execute("SELECT ciclos_correctos, ciclos_fallidos, motivo, ultimo_ciclo "
                             "FROM tinotify_sintetico.monitor_estado").fetchone()
        return None if fila is None else {"ciclos_correctos": fila[0], "ciclos_fallidos": fila[1],
                                         "motivo": fila[2], "ultimo_ciclo": fila[3]}

    def guardar(self, estado):
        with self._almacen.transaccion() as c:
            c.execute("UPDATE tinotify_sintetico.monitor_estado SET ciclos_correctos=%s, ciclos_fallidos=%s, motivo=%s, "
                      "ultimo_ciclo=%s, actualizado_en=clock_timestamp()",
                      (estado["ciclos_correctos"], estado["ciclos_fallidos"], estado["motivo"],
                       None if estado["ultimo_ciclo"] is None else Jsonb(estado["ultimo_ciclo"])))


class ServicioSinteticoPostgres:
    """Misma superficie que `ServicioNovedadesLocal` (observar_html, listar_casos, detalle, novedades)."""

    sintetico = True

    def __init__(self, almacen: AlmacenPg):
        self.almacen = almacen

    # --- Escritura (solo el monitor) -------------------------------------------------------------------------------
    def observar_html(self, caso, html, *, titulo=TITULO_OBSERVADO):
        try:
            actuaciones = parse_actuaciones(html, caso)
        except ErrorParseoHistorial as error:
            raise ObservacionRechazada(f"Extraccion rechazada ({error.codigo.value}); estado sin cambios.") from None
        return self.observar(caso, actuaciones, titulo=titulo)

    def observar(self, caso, actuaciones, *, titulo=TITULO_OBSERVADO):
        caso = str(UUID(caso))
        actuaciones = list(actuaciones)
        if not actuaciones or len(actuaciones) > MAX_ACTUACIONES or any(not isinstance(a, Actuacion) for a in actuaciones):
            raise ObservacionRechazada("Observacion vacia o invalida; estado sin cambios.")
        huellas = [a.huella_version for a in actuaciones]
        with self.almacen.transaccion() as c:
            # El bloqueo de la fila del caso serializa a los escritores concurrentes (p. ej. dos instancias de Render).
            c.execute("INSERT INTO tinotify_sintetico.casos(id, titulo) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                      (caso, titulo))
            generacion = c.execute("SELECT generacion FROM tinotify_sintetico.casos WHERE id=%s FOR UPDATE",
                                   (caso,)).fetchone()[0]
            previas = Counter(f[0] for f in c.execute(
                "SELECT huella FROM tinotify_sintetico.actuaciones WHERE caso_id=%s", (caso,)).fetchall())
            faltantes = sum((previas - Counter(huellas)).values())
            if faltantes:
                raise ObservacionRechazada(
                    f"{faltantes} de {sum(previas.values())} actuaciones previas no coinciden en la nueva observacion; "
                    "posible extraccion incompleta. Estado sin cambios.")
            restantes, nuevas = Counter(previas), []
            for i, huella in enumerate(huellas):
                if restantes[huella] > 0:
                    restantes[huella] -= 1
                else:
                    nuevas.append(i)
            if generacion > 0 and not nuevas:   # idempotente: misma observacion, ninguna escritura
                n = c.execute("SELECT count(*) FROM tinotify_sintetico.novedades WHERE caso_id=%s AND generacion=%s",
                              (caso, generacion)).fetchone()[0]
                return {"baseline": False, "novedades_nuevas": n, "actuaciones": len(actuaciones),
                        "generacion": generacion}
            c.execute("DELETE FROM tinotify_sintetico.actuaciones WHERE caso_id=%s", (caso,))
            with c.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO tinotify_sintetico.actuaciones(caso_id, orden, huella, contenido) VALUES (%s,%s,%s,%s)",
                    [(caso, i, huellas[i], Jsonb(_contenido(a))) for i, a in enumerate(actuaciones)])
            nueva_generacion, creadas = generacion + 1, 0
            if generacion > 0:   # la primera observacion es una linea base silenciosa
                for i in nuevas:
                    base = crear_notificacion(0, "", TipoCambio.PRIMERA_OBSERVACION)
                    notificacion = replace(base, prioridad=clasificar_prioridad(actuaciones[i].direccion))
                    creadas += c.execute(
                        "INSERT INTO tinotify_sintetico.novedades(caso_id, actuacion_huella, generacion, tipo, prioridad, "
                        "titulo, mensaje) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (caso_id, actuacion_huella) DO NOTHING",
                        (caso, huellas[i], nueva_generacion, notificacion.tipo.value, notificacion.prioridad.value,
                         notificacion.titulo, notificacion.mensaje)).rowcount
            c.execute("UPDATE tinotify_sintetico.casos SET titulo=%s, generacion=%s, actualizado_en=clock_timestamp() "
                      "WHERE id=%s", (titulo, nueva_generacion, caso))
        return {"baseline": generacion == 0, "novedades_nuevas": creadas, "actuaciones": len(actuaciones),
                "generacion": nueva_generacion}

    # --- Lectura (la API solo usa estos metodos) ---------------------------------------------------------------------
    def listar_casos(self):
        with self.almacen.transaccion(lectura=True) as c:
            filas = c.execute("""
                SELECT c.id::text, c.titulo, c.generacion,
                       (SELECT count(*) FROM tinotify_sintetico.actuaciones a WHERE a.caso_id = c.id),
                       (SELECT count(*) FROM tinotify_sintetico.novedades n
                         WHERE n.caso_id = c.id AND n.disposicion = 'pendiente')
                FROM tinotify_sintetico.casos c WHERE c.generacion > 0 ORDER BY c.creado_en, c.id""").fetchall()
        return [{"id": f[0], "titulo": f[1], "generacion": f[2], "total_actuaciones": f[3],
                 "novedades_pendientes": f[4], "demo": True} for f in filas]

    def detalle(self, caso):
        """KeyError si el caso no existe o aun no tiene linea base."""
        caso = str(UUID(caso))
        with self.almacen.transaccion(lectura=True) as c:
            cabecera = c.execute("SELECT titulo, generacion FROM tinotify_sintetico.casos WHERE id=%s AND generacion>0",
                                 (caso,)).fetchone()
            if cabecera is None:
                raise KeyError(caso)
            filas = c.execute("SELECT huella, contenido FROM tinotify_sintetico.actuaciones WHERE caso_id=%s ORDER BY orden",
                              (caso,)).fetchall()
            afectadas = {f[0] for f in c.execute(
                "SELECT actuacion_huella FROM tinotify_sintetico.novedades WHERE caso_id=%s AND disposicion='pendiente'",
                (caso,)).fetchall()}
        return {"id": caso, "titulo": cabecera[0], "generacion": cabecera[1], "baseline": True,
                "total_actuaciones": len(filas), "novedades_pendientes": len(afectadas),
                "demo": True, "sintetico": True,
                "actuaciones": [{**contenido, "nueva": huella in afectadas} for huella, contenido in filas]}

    def novedades(self):
        with self.almacen.transaccion(lectura=True) as c:
            filas = c.execute("""
                SELECT n.id::text, n.caso_id::text, n.tipo, n.prioridad, n.titulo, n.mensaje, a.contenido
                FROM tinotify_sintetico.novedades n
                LEFT JOIN LATERAL (SELECT contenido FROM tinotify_sintetico.actuaciones a
                                   WHERE a.caso_id = n.caso_id AND a.huella = n.actuacion_huella
                                   ORDER BY a.orden LIMIT 1) a ON true
                WHERE n.disposicion = 'pendiente'
                ORDER BY CASE n.prioridad WHEN 'alta' THEN 0 ELSE 1 END, n.creado_en, n.id LIMIT %s""",
                              (LIMITE_NOVEDADES,)).fetchall()
        return [{"id": f[0], "caso": f[1], "tipo": f[2], "prioridad": f[3], "titulo": f[4], "mensaje": f[5],
                 "actuacion": f[6]} for f in filas]

    def tamano_bytes(self):
        with self.almacen.transaccion(lectura=True) as c:
            return int(c.execute("""
                SELECT coalesce(sum(pg_total_relation_size(c.oid)), 0) FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'tinotify_sintetico' AND c.relkind = 'r'""").fetchone()[0])

    def cerrar(self):
        self.almacen.cerrar()
