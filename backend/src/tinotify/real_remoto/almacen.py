"""Almacén PostgreSQL (Supabase) del monitor real: esquema `tinotify_real`, solo con el login restringido.

Una conexión por operación (hay ~3 ejecuciones al día): sin pool, sin estado compartido. TLS `verify-full` con la CA explícita.
Los mensajes de error nunca incluyen SQL, parámetros, credenciales ni datos: solo un tipo de fallo estable.
"""

from collections import Counter
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
            fila = con.execute("SELECT version_llave, nonce, cifrado FROM tinotify_real.credenciales").fetchone()
        return None if fila is None else (fila[0], bytes(fila[1]), bytes(fila[2]))

    def guardar_credenciales(self, version, nonce, cifrado):
        with self._tx() as con:
            con.execute(
                "INSERT INTO tinotify_real.credenciales (version_llave, nonce, cifrado) VALUES (%s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET version_llave = EXCLUDED.version_llave, nonce = EXCLUDED.nonce, "
                "cifrado = EXCLUDED.cifrado, actualizado_en = clock_timestamp()", (version, nonce, cifrado))

    def olvidar_credenciales(self):
        with self._tx() as con:
            return con.execute("DELETE FROM tinotify_real.credenciales").rowcount > 0

    # --- ejecuciones y estado ----------------------------------------------------------------------------------------
    def iniciar_ejecucion(self):
        with self._tx() as con:
            return str(con.execute("INSERT INTO tinotify_real.ejecuciones DEFAULT VALUES RETURNING id").fetchone()[0])

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
                    "SELECT caso_ref, acreditado, generacion, anomalia FROM tinotify_real.estado_expediente"):
                previos[ref] = [Counter(), acreditado, generacion, anomalia]
            for ref, huella, cantidad in con.execute("SELECT caso_ref, huella, cantidad FROM tinotify_real.huellas"):
                previos[ref][0][huella] = cantidad
            plan = planificar({r: EstadoPrevio(h, a, g, an) for r, (h, a, g, an) in previos.items()}, lecturas, semillas)
            for c in plan.cambios:
                total = c.huellas.total()
                if not c.en_bd:
                    con.execute("INSERT INTO tinotify_real.estado_expediente (caso_ref, acreditado, actuaciones, generacion, anomalia) "
                                "VALUES (%s, %s, %s, %s, %s)", (c.caso_ref, c.acreditado, total, c.generacion, c.anomalia))
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
                    "INSERT INTO tinotify_real.avisos (expedientes_con_novedades, novedades, expedientes_nuevos, anomalias) "
                    "VALUES (%s, %s, %s, %s) RETURNING id",
                    (plan.expedientes_con_novedades, plan.novedades, plan.expedientes_nuevos, plan.anomalias)).fetchone()[0])
        return plan, aviso

    # --- avisos y estado visible ------------------------------------------------------------------------------------
    def avisos_pendientes(self):
        with self._tx() as con:
            filas = con.execute(
                "SELECT id, expedientes_con_novedades, novedades, expedientes_nuevos, anomalias, intentos "
                "FROM tinotify_real.avisos WHERE entregado_en IS NULL ORDER BY creado_en, id").fetchall()
        return [{"id": str(f[0]), "expedientes_con_novedades": f[1], "novedades": f[2], "expedientes_nuevos": f[3],
                 "anomalias": f[4], "intentos": f[5]} for f in filas]

    def marcar_entregado(self, aviso):
        with self._tx() as con:
            return con.execute("UPDATE tinotify_real.avisos SET entregado_en = clock_timestamp(), intentos = intentos + 1 "
                               "WHERE id = %s AND entregado_en IS NULL RETURNING id", (aviso,)).fetchone() is not None

    def estado(self):
        with self._tx() as con:
            ultima = con.execute("SELECT resultado, inicio, fin FROM tinotify_real.ejecuciones ORDER BY inicio DESC LIMIT 1").fetchone()
            expedientes = con.execute("SELECT count(*) FROM tinotify_real.estado_expediente").fetchone()[0]
            pendientes = con.execute("SELECT count(*) FROM tinotify_real.avisos WHERE entregado_en IS NULL").fetchone()[0]
            credenciales = con.execute("SELECT count(*) FROM tinotify_real.credenciales").fetchone()[0] > 0
        return {"credenciales_guardadas": credenciales, "expedientes_en_estado": expedientes, "avisos_pendientes": pendientes,
                "ultima_ejecucion": None if ultima is None else {
                    "resultado": ultima[0], "inicio": ultima[1].isoformat(), "fin": ultima[2].isoformat() if ultima[2] else None}}

    # --- dispositivos (push) -------------------------------------------------------------------------------------------
    def registrar_dispositivo(self, token):
        with self._tx() as con:
            con.execute("INSERT INTO tinotify_real.dispositivos (token) VALUES (%s) "
                        "ON CONFLICT (token) DO UPDATE SET ultimo_uso = clock_timestamp()", (token,))

    def dispositivos(self):
        with self._tx() as con:
            return [f[0] for f in con.execute("SELECT token FROM tinotify_real.dispositivos ORDER BY creado_en").fetchall()]

    def borrar_dispositivo(self, token):
        with self._tx() as con:
            return con.execute("DELETE FROM tinotify_real.dispositivos WHERE token = %s", (token,)).rowcount > 0
