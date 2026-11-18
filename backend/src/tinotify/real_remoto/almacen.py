"""Almacén PostgreSQL (Supabase) del monitor real: esquema `tinotify_real`, solo con el login restringido.

Una conexión por operación (hay ~3 ejecuciones al día): sin pool, sin estado compartido. TLS `verify-full` con la CA explícita.
Los mensajes de error nunca incluyen SQL, parámetros, credenciales ni datos: solo un tipo de fallo estable.
"""

from collections import Counter
import copy
from contextlib import contextmanager

from tinotify.real_remoto.config import ConfigPg
from tinotify.real_remoto.monitor import EstadoPrevio, planificar

CLAVE_BLOQUEO_EJECUCION = 7402100003  # distinta de las del esquema sintético


class AlmacenNoDisponible(Exception):
    """La base no responde o rechazó la operación."""


class AlmacenIncompatible(Exception):
    """El esquema no es el esperado (marca de entorno ausente o de otra versión)."""


class AlmacenPg:
    def __init__(self, config: ConfigPg):
        self._c = config
        self._u = None  # dueño de los datos: None = propietario (tu cuenta de siempre); si no, el id de un usuario

    def de(self, usuario):
        """Vista del almacén ligada a un usuario (None = propietario). Comparte la configuración; no abre conexiones."""
        vista = copy.copy(self)
        vista._u = usuario
        return vista

    def usuarios_con_credenciales(self):
        with self._tx() as con:
            return [str(f[0]) for f in con.execute("SELECT usuario_id FROM tinotify_real.credenciales_usuario ORDER BY creado_en").fetchall()]

    @contextmanager
    def _tx(self):
        c = self._c
        try:
            import psycopg  # carga perezosa: la biblioteca nativa solo se necesita al usar la base
        except ImportError:
            raise AlmacenNoDisponible from None
        try:
            with psycopg.connect(
                host=c.host, port=c.puerto, dbname=c.base, user=c.usuario, password=c.password,
                sslmode="verify-full" if c.tls else "disable", sslrootcert=str(c.ca) if c.tls and c.ca else None,
                connect_timeout=max(1, int(c.espera_s)), application_name="tinotify-real",
            ) as con:
                with con.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '30s'")
                    cur.execute("SET LOCAL lock_timeout = '10s'")
                yield con
        except psycopg.Error:
            raise AlmacenNoDisponible from None

    def verificar(self):
        with self._tx() as con:
            fila = con.execute("SELECT proposito, version_esquema FROM tinotify_real.entorno").fetchone()
        if fila != ("real", 1):
            raise AlmacenIncompatible

    # --- credenciales cifradas ---------------------------------------------------------------------------------------
    def credenciales(self):
        with self._tx() as con:
            if self._u is None:
                fila = con.execute("SELECT version_llave, nonce, cifrado FROM tinotify_real.credenciales").fetchone()
            else:
                fila = con.execute("SELECT version_llave, nonce, cifrado FROM tinotify_real.credenciales_usuario WHERE usuario_id = %s::uuid",
                                   (self._u,)).fetchone()
        return None if fila is None else (fila[0], bytes(fila[1]), bytes(fila[2]))

    def guardar_credenciales(self, version, nonce, cifrado):
        with self._tx() as con:
            if self._u is None:
                con.execute(
                    "INSERT INTO tinotify_real.credenciales (version_llave, nonce, cifrado) VALUES (%s, %s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET version_llave = EXCLUDED.version_llave, nonce = EXCLUDED.nonce, "
                    "cifrado = EXCLUDED.cifrado, actualizado_en = clock_timestamp()", (version, nonce, cifrado))
            else:
                con.execute(
                    "INSERT INTO tinotify_real.credenciales_usuario (usuario_id, version_llave, nonce, cifrado) VALUES (%s::uuid, %s, %s, %s) "
                    "ON CONFLICT (usuario_id) DO UPDATE SET version_llave = EXCLUDED.version_llave, nonce = EXCLUDED.nonce, "
                    "cifrado = EXCLUDED.cifrado, actualizado_en = clock_timestamp()", (self._u, version, nonce, cifrado))

    def olvidar_credenciales(self):
        with self._tx() as con:
            if self._u is None:
                return con.execute("DELETE FROM tinotify_real.credenciales").rowcount > 0
            return con.execute("DELETE FROM tinotify_real.credenciales_usuario WHERE usuario_id = %s::uuid", (self._u,)).rowcount > 0

    # --- ejecuciones y estado ----------------------------------------------------------------------------------------
    def iniciar_ejecucion(self):
        with self._tx() as con:
            return str(con.execute("INSERT INTO tinotify_real.ejecuciones (usuario_id) VALUES (%s::uuid) RETURNING id", (self._u,)).fetchone()[0])

    def cerrar_ejecucion(self, ejecucion, resultado, expedientes=None, novedades=None, codigo=None):
        with self._tx() as con:
            con.execute(
                "UPDATE tinotify_real.ejecuciones SET fin = clock_timestamp(), resultado = %s, expedientes = %s, "
                "novedades = %s, codigo = %s WHERE id = %s", (resultado, expedientes, novedades, codigo, ejecucion))

    def aplicar(self, lecturas, semillas):
        """Transacción EXCLUSIVA: lee el estado, planifica con él, lo escribe y deja el aviso en la bandeja, todo o nada.

        El bloqueo cubre solo esta fase: dos ejecuciones simultáneas leen SIGAC por separado, pero se aplican en serie y la
        segunda parte del estado ya actualizado por la primera (no hay avisos duplicados por la misma novedad)."""
        with self._tx() as con:
            con.execute("SELECT pg_advisory_xact_lock(%s)", (CLAVE_BLOQUEO_EJECUCION,))
            previos = {}
            for ref, acreditado, generacion, anomalia in con.execute(
                    "SELECT caso_ref, acreditado, generacion, anomalia FROM tinotify_real.estado_expediente "
                    "WHERE usuario_id IS NOT DISTINCT FROM %s::uuid", (self._u,)):
                previos[ref] = [Counter(), acreditado, generacion, anomalia]
            for ref, huella, cantidad in con.execute(
                    "SELECT h.caso_ref, h.huella, h.cantidad FROM tinotify_real.huellas h JOIN tinotify_real.estado_expediente e "
                    "ON e.caso_ref = h.caso_ref WHERE e.usuario_id IS NOT DISTINCT FROM %s::uuid", (self._u,)):
                previos[ref][0][huella] = cantidad
            plan = planificar({r: EstadoPrevio(h, a, g, an) for r, (h, a, g, an) in previos.items()}, lecturas, semillas)
            for c in plan.cambios:
                total = c.huellas.total()
                if not c.en_bd:
                    con.execute("INSERT INTO tinotify_real.estado_expediente (caso_ref, acreditado, actuaciones, generacion, anomalia, usuario_id) "
                                "VALUES (%s, %s, %s, %s, %s, %s::uuid)", (c.caso_ref, c.acreditado, total, c.generacion, c.anomalia, self._u))
                else:
                    con.execute("UPDATE tinotify_real.estado_expediente SET acreditado = %s, actuaciones = %s, generacion = %s, "
                                "anomalia = %s, ultima_lectura = clock_timestamp() WHERE caso_ref = %s",
                                (c.acreditado, total, c.generacion, c.anomalia, c.caso_ref))
                if c.accion == "anomalia" and c.en_bd:
                    continue  # el estado de huellas no se toca
                if c.accion in ("nuevo", "novedades") or not c.en_bd:
                    with con.cursor() as cur:
                        cur.executemany(
                            "INSERT INTO tinotify_real.huellas (caso_ref, huella, cantidad) VALUES (%s, %s, %s) "
                            "ON CONFLICT (caso_ref, huella) DO UPDATE SET cantidad = EXCLUDED.cantidad",
                            [(c.caso_ref, h, n) for h, n in sorted(c.huellas.items())])
            aviso = None
            if plan.requiere_aviso:
                aviso = str(con.execute(
                    "INSERT INTO tinotify_real.avisos (expedientes_con_novedades, novedades, expedientes_nuevos, anomalias, usuario_id) "
                    "VALUES (%s, %s, %s, %s, %s::uuid) RETURNING id",
                    (plan.expedientes_con_novedades, plan.novedades, plan.expedientes_nuevos, plan.anomalias, self._u)).fetchone()[0])
        return plan, aviso

    # --- avisos y estado visible ------------------------------------------------------------------------------------
    def avisos_pendientes(self):
        with self._tx() as con:
            filas = con.execute(
                "SELECT id, expedientes_con_novedades, novedades, expedientes_nuevos, anomalias, intentos "
                "FROM tinotify_real.avisos WHERE entregado_en IS NULL AND usuario_id IS NOT DISTINCT FROM %s::uuid "
                "ORDER BY creado_en, id", (self._u,)).fetchall()
        return [{"id": str(f[0]), "expedientes_con_novedades": f[1], "novedades": f[2], "expedientes_nuevos": f[3],
                 "anomalias": f[4], "intentos": f[5]} for f in filas]

    def avisos_pendientes_todos(self):
        """Para el ciclo de Actions (token del monitor): los avisos pendientes de TODOS, con su dueño (None = propietario)."""
        with self._tx() as con:
            filas = con.execute(
                "SELECT id, expedientes_con_novedades, novedades, expedientes_nuevos, anomalias, intentos, usuario_id "
                "FROM tinotify_real.avisos WHERE entregado_en IS NULL ORDER BY creado_en, id").fetchall()
        return [{"id": str(f[0]), "expedientes_con_novedades": f[1], "novedades": f[2], "expedientes_nuevos": f[3],
                 "anomalias": f[4], "intentos": f[5], "usuario": None if f[6] is None else str(f[6])} for f in filas]

    def marcar_entregado(self, aviso):
        with self._tx() as con:
            return con.execute("UPDATE tinotify_real.avisos SET entregado_en = clock_timestamp(), intentos = intentos + 1 "
                               "WHERE id = %s AND entregado_en IS NULL RETURNING id", (aviso,)).fetchone() is not None

    def estado(self):
        with self._tx() as con:
            ultima = con.execute("SELECT resultado, inicio, fin FROM tinotify_real.ejecuciones "
                                 "WHERE usuario_id IS NOT DISTINCT FROM %s::uuid ORDER BY inicio DESC LIMIT 1", (self._u,)).fetchone()
            expedientes = con.execute("SELECT count(*) FROM tinotify_real.estado_expediente "
                                      "WHERE usuario_id IS NOT DISTINCT FROM %s::uuid", (self._u,)).fetchone()[0]
            pendientes = con.execute("SELECT count(*) FROM tinotify_real.avisos WHERE entregado_en IS NULL "
                                     "AND usuario_id IS NOT DISTINCT FROM %s::uuid", (self._u,)).fetchone()[0]
            if self._u is None:
                credenciales = con.execute("SELECT count(*) FROM tinotify_real.credenciales").fetchone()[0] > 0
            else:
                credenciales = con.execute("SELECT count(*) FROM tinotify_real.credenciales_usuario WHERE usuario_id = %s::uuid",
                                           (self._u,)).fetchone()[0] > 0
        return {"credenciales_guardadas": credenciales, "expedientes_en_estado": expedientes, "avisos_pendientes": pendientes,
                "ultima_ejecucion": None if ultima is None else {
                    "resultado": ultima[0], "inicio": ultima[1].isoformat(), "fin": ultima[2].isoformat() if ultima[2] else None}}

    # --- dispositivos (push) -------------------------------------------------------------------------------------------
    def registrar_dispositivo(self, token):
        with self._tx() as con:
            con.execute("INSERT INTO tinotify_real.dispositivos (token, usuario_id) VALUES (%s, %s::uuid) "
                        "ON CONFLICT (token) DO UPDATE SET ultimo_uso = clock_timestamp(), usuario_id = EXCLUDED.usuario_id",
                        (token, self._u))

    def dispositivos(self):
        with self._tx() as con:
            return [f[0] for f in con.execute("SELECT token FROM tinotify_real.dispositivos "
                                              "WHERE usuario_id IS NOT DISTINCT FROM %s::uuid ORDER BY creado_en", (self._u,)).fetchall()]

    def borrar_dispositivo(self, token):
        with self._tx() as con:
            return con.execute("DELETE FROM tinotify_real.dispositivos WHERE token = %s AND usuario_id IS NOT DISTINCT FROM %s::uuid",
                               (token, self._u)).rowcount > 0

    def ejecuciones_recientes(self, limite):
        """Últimas ejecuciones, de la más reciente a la más antigua: solo estados de catálogo y conteos, más el estado de los canales
        del aviso que esa ejecución creó (si creó alguno)."""
        with self._tx() as con:
            filas = con.execute(
                "SELECT e.inicio, e.fin, e.resultado, e.expedientes, e.novedades, e.codigo, a.id IS NOT NULL, a.push_estado, a.correo_estado "
                "FROM tinotify_real.ejecuciones e LEFT JOIN LATERAL ("
                "  SELECT id, push_estado, correo_estado FROM tinotify_real.avisos x "
                "  WHERE x.creado_en >= e.inicio AND x.creado_en <= coalesce(e.fin, e.inicio + interval '15 minutes') "
                "  AND x.usuario_id IS NOT DISTINCT FROM e.usuario_id ORDER BY x.creado_en LIMIT 1) a ON true "
                "WHERE e.usuario_id IS NOT DISTINCT FROM %s::uuid "
                "ORDER BY e.inicio DESC LIMIT %s", (self._u, max(1, min(int(limite), 100)))).fetchall()
        return [{"inicio": f[0].isoformat(), "fin": f[1].isoformat() if f[1] else None, "resultado": f[2],
                 "expedientes": f[3], "novedades": f[4], "codigo": f[5],
                 "aviso": {"push": f[7], "correo": f[8]} if f[6] else None} for f in filas]

    def fijar_canal_aviso(self, aviso, canal, estado):
        """Registra cómo salió un aviso por un canal. `canal` es push o correo (lista cerrada)."""
        columna = {"push": "push_estado", "correo": "correo_estado"}[canal]
        with self._tx() as con:
            return con.execute(f"UPDATE tinotify_real.avisos SET {columna} = %s WHERE id = %s", (estado, aviso)).rowcount > 0

    # --- listado de expedientes (cifrado) ------------------------------------------------------------------------------
    def guardar_expedientes(self, filas):
        """filas: (caso_ref, version_llave, nonce, cifrado, sumar_novedades, es_nuevo)."""
        with self._tx() as con:
            for ref, version, nonce, cifrado, sumar, nuevo in filas:
                con.execute(
                    "INSERT INTO tinotify_real.expedientes (caso_ref, version_llave, nonce, cifrado, novedades_no_vistas, nuevo, ultima_novedad) "
                    "VALUES (%(r)s, %(v)s, %(n)s, %(c)s, %(s)s, %(u)s, CASE WHEN %(s)s > 0 OR %(u)s THEN clock_timestamp() END) "
                    "ON CONFLICT (caso_ref) DO UPDATE SET version_llave = EXCLUDED.version_llave, nonce = EXCLUDED.nonce, "
                    "cifrado = EXCLUDED.cifrado, actualizado_en = clock_timestamp(), "
                    "novedades_no_vistas = least(tinotify_real.expedientes.novedades_no_vistas + %(s)s, 100000), "
                    "ultima_novedad = CASE WHEN %(s)s > 0 OR %(u)s THEN clock_timestamp() ELSE tinotify_real.expedientes.ultima_novedad END, "
                    "nuevo = tinotify_real.expedientes.nuevo OR %(u)s",
                    {"r": ref, "v": version, "n": nonce, "c": cifrado, "s": sumar, "u": nuevo})

    def expedientes(self):
        with self._tx() as con:
            filas = con.execute("SELECT x.caso_ref, x.version_llave, x.nonce, x.cifrado, x.novedades_no_vistas, x.nuevo, x.ultima_novedad "
                                "FROM tinotify_real.expedientes x JOIN tinotify_real.estado_expediente e ON e.caso_ref = x.caso_ref "
                                "WHERE e.usuario_id IS NOT DISTINCT FROM %s::uuid", (self._u,)).fetchall()
        return [(f[0], f[1], bytes(f[2]), bytes(f[3]), f[4], f[5], f[6].isoformat() if f[6] else None) for f in filas]

    def marcar_vistos(self, caso_ref=None):
        with self._tx() as con:
            propios = "caso_ref IN (SELECT caso_ref FROM tinotify_real.estado_expediente WHERE usuario_id IS NOT DISTINCT FROM %s::uuid)"
            if caso_ref is None:
                return con.execute("UPDATE tinotify_real.expedientes SET novedades_no_vistas = 0, nuevo = false "
                                   f"WHERE (novedades_no_vistas > 0 OR nuevo) AND {propios}", (self._u,)).rowcount
            return con.execute("UPDATE tinotify_real.expedientes SET novedades_no_vistas = 0, nuevo = false "
                               f"WHERE caso_ref = %s AND {propios}", (caso_ref, self._u)).rowcount
