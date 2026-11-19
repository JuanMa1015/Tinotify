"""Almacén PostgreSQL de cuentas (tablas usuarios, invitaciones y sesiones del esquema `tinotify_real`).

Reutiliza la conexión restringida de AlmacenPg. Las operaciones compuestas son una sola transacción.
NO probado contra una base real todavía: se valida en un contenedor Linux con PostgreSQL desechable (la biblioteca nativa de PostgreSQL no carga en este Windows).
"""

import hmac

from tinotify.real_remoto.almacen import AlmacenPg
from tinotify.real_remoto.servicio_cuentas import RegistroNoValido

_USUARIO = "id, activo, es_admin, pass_hash, intentos_fallidos, bloqueado_hasta"


def _usuario(fila):
    return None if fila is None else {"id": str(fila[0]), "activo": fila[1], "es_admin": fila[2], "pass_hash": fila[3],
                                      "intentos_fallidos": fila[4], "bloqueado_hasta": fila[5]}


class AlmacenCuentasPg(AlmacenPg):
    def crear_invitacion(self, codigo_hash, expira_en):
        with self._tx() as con:
            con.execute("INSERT INTO tinotify_real.invitaciones (codigo_hash, expira_en) VALUES (%s, %s)", (codigo_hash, expira_en))

    def registrar_usuario(self, invitacion_hash, correo_ref, pass_hash, consentimiento_version, ahora, correo=None):
        with self._tx() as con:
            inv = con.execute("SELECT 1 FROM tinotify_real.invitaciones WHERE codigo_hash = %s AND usado_en IS NULL AND expira_en > %s "
                              "FOR UPDATE", (invitacion_hash, ahora)).fetchone()
            if inv is None:
                raise RegistroNoValido
            fila = con.execute(
                "INSERT INTO tinotify_real.usuarios (correo_ref, pass_hash, consentimiento_version, consentimiento_en, correo_nonce, correo_cifrado) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (correo_ref) DO NOTHING RETURNING id",
                (correo_ref, pass_hash, consentimiento_version, ahora, correo[0] if correo else None, correo[1] if correo else None)).fetchone()
            if fila is None:
                raise RegistroNoValido
            con.execute("UPDATE tinotify_real.invitaciones SET usado_por = %s, usado_en = %s WHERE codigo_hash = %s",
                        (fila[0], ahora, invitacion_hash))
            return str(fila[0])

    def correo_cifrado_de(self, usuario_id):
        with self._tx() as con:
            fila = con.execute("SELECT correo_nonce, correo_cifrado FROM tinotify_real.usuarios WHERE id = %s::uuid AND activo",
                               (usuario_id,)).fetchone()
        return None if fila is None or fila[0] is None else (bytes(fila[0]), bytes(fila[1]))

    def usuario_por_correo_ref(self, ref):
        with self._tx() as con:
            return _usuario(con.execute(f"SELECT {_USUARIO} FROM tinotify_real.usuarios WHERE correo_ref = %s", (ref,)).fetchone())

    def usuario_por_id(self, usuario_id):
        with self._tx() as con:
            return _usuario(con.execute(f"SELECT {_USUARIO} FROM tinotify_real.usuarios WHERE id = %s", (usuario_id,)).fetchone())

    def registrar_fallo(self, usuario_id, fallos, bloqueado_hasta):
        with self._tx() as con:
            con.execute("UPDATE tinotify_real.usuarios SET intentos_fallidos = least(%s, 1000), bloqueado_hasta = %s WHERE id = %s",
                        (fallos, bloqueado_hasta, usuario_id))

    def limpiar_fallos(self, usuario_id):
        with self._tx() as con:
            con.execute("UPDATE tinotify_real.usuarios SET intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = %s", (usuario_id,))

    def crear_sesion(self, usuario_id, token_hash, dispositivo, expira_en):
        with self._tx() as con:
            con.execute("INSERT INTO tinotify_real.sesiones (usuario_id, token_hash, dispositivo, expira_en) VALUES (%s, %s, %s, %s)",
                        (usuario_id, token_hash, dispositivo, expira_en))

    def usuario_por_token(self, token_hash, ahora):
        with self._tx() as con:
            fila = con.execute(
                "SELECT u.id, u.es_admin FROM tinotify_real.sesiones s JOIN tinotify_real.usuarios u ON u.id = s.usuario_id "
                "WHERE s.token_hash = %s AND s.revocada_en IS NULL AND s.expira_en > %s AND u.activo", (token_hash, ahora)).fetchone()
        return None if fila is None else {"id": str(fila[0]), "es_admin": fila[1]}

    def revocar_sesion(self, token_hash, ahora):
        with self._tx() as con:
            con.execute("UPDATE tinotify_real.sesiones SET revocada_en = %s WHERE token_hash = %s AND revocada_en IS NULL", (ahora, token_hash))

    def revocar_todas(self, usuario_id, ahora):
        with self._tx() as con:
            con.execute("UPDATE tinotify_real.sesiones SET revocada_en = %s WHERE usuario_id = %s AND revocada_en IS NULL", (ahora, usuario_id))

    def revocar_todas_menos(self, usuario_id, token_hash, ahora):
        with self._tx() as con:
            con.execute("UPDATE tinotify_real.sesiones SET revocada_en = %s WHERE usuario_id = %s AND token_hash <> %s AND revocada_en IS NULL",
                        (ahora, usuario_id, token_hash))

    def crear_recuperacion(self, usuario_id, codigo_hash, expira_en, ahora, maximo_por_hora=3):
        """Guarda un código de recuperación (solo su hash). False si ya hubo `maximo_por_hora` solicitudes en la última hora. Anula el anterior."""
        with self._tx() as con:
            con.execute("DELETE FROM tinotify_real.recuperaciones WHERE creada_en < %s - interval '1 day'", (ahora,))
            hechas = con.execute("SELECT count(*) FROM tinotify_real.recuperaciones WHERE usuario_id = %s::uuid "
                                 "AND creada_en > %s - interval '1 hour'", (usuario_id, ahora)).fetchone()[0]
            if hechas >= maximo_por_hora:
                return False
            con.execute("UPDATE tinotify_real.recuperaciones SET usado_en = %s WHERE usuario_id = %s::uuid AND usado_en IS NULL", (ahora, usuario_id))
            con.execute("INSERT INTO tinotify_real.recuperaciones (usuario_id, codigo_hash, expira_en, creada_en) VALUES (%s::uuid, %s, %s, %s)",
                        (usuario_id, codigo_hash, expira_en, ahora))
            return True

    def consumir_recuperacion(self, usuario_id, codigo_hash, ahora, max_intentos=5):
        """True (y queda usado) si el hash es el del código vigente de esa cuenta. Cada fallo cuenta; tras `max_intentos` el código muere."""
        with self._tx() as con:
            fila = con.execute("SELECT id, codigo_hash, intentos FROM tinotify_real.recuperaciones WHERE usuario_id = %s::uuid "
                               "AND usado_en IS NULL AND expira_en > %s ORDER BY creada_en DESC LIMIT 1 FOR UPDATE", (usuario_id, ahora)).fetchone()
            if fila is None or fila[2] >= max_intentos:
                return False
            if hmac.compare_digest(fila[1], codigo_hash):
                con.execute("UPDATE tinotify_real.recuperaciones SET usado_en = %s WHERE id = %s", (ahora, fila[0]))
                return True
            con.execute("UPDATE tinotify_real.recuperaciones SET intentos = intentos + 1 WHERE id = %s", (fila[0],))
            return False

    def cambiar_pass(self, usuario_id, pass_hash):
        with self._tx() as con:
            con.execute("UPDATE tinotify_real.usuarios SET pass_hash = %s WHERE id = %s", (pass_hash, usuario_id))

    def borrar_usuario(self, usuario_id):
        with self._tx() as con:
            con.execute("DELETE FROM tinotify_real.usuarios WHERE id = %s", (usuario_id,))
