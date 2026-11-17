"""Adaptador SQLite EXCLUSIVO de desarrollo local para el contrato `AlmacenSeguimiento`.

Reutiliza `ServicioSeguimiento` y `ServicioAvisos` sin duplicar su lógica: solo implementa las
operaciones de almacenamiento con la misma semántica que las funciones SQL de PostgreSQL
(idempotencia de la reserva, generación y fencing, confirmación atómica de registros y eventos,
sin borrar actuaciones por ausencia, avisos pendientes). No es un autenticador ni una frontera de
seguridad: acepta únicamente la credencial local fija y nunca credenciales de SIGAC ni de usuarios.
No se usa en producción; no hay conexión con Supabase ni Render.
"""

from contextlib import closing, contextmanager
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import os
import shutil
import sqlite3
import tempfile
import time
from uuid import UUID, uuid4

from tinotify.domain.identificadores import PoliticaConfianza
from tinotify.persistence.codec_postgres import binario, validar_confianza
from tinotify.persistence.interfaces import Reserva, Seguimiento
from tinotify.persistence.monitor import _nuevo_estado


# Identidad local fija de desarrollo (no es un secreto ni un usuario real).
CREDENCIAL_LOCAL = "tinotify-desarrollo-local"
BINDING_LOCAL = UUID("00000000-0000-4000-8000-0000000000b1")
WORKER_LOCAL = UUID("00000000-0000-4000-8000-0000000000b2")
_ESQUEMA = 2
_LEASE_SEGUNDOS = 60
PERFILES = ("sintetico", "real")


class AlmacenLocalNoDisponible(RuntimeError):
    """Fallo del archivo SQLite; la transacción se revierte y el estado anterior se conserva."""


class ConflictoPersistenciaLocal(RuntimeError):
    pass


class ResultadoCommitIncierto(AlmacenLocalNoDisponible):
    """No inferir rollback: consultar el recibo usando otra conexión."""


_DDL = """
CREATE TABLE IF NOT EXISTS meta(clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seguimientos(
    id TEXT PRIMARY KEY, instancia TEXT NOT NULL UNIQUE, politica TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS expedientes(
    id TEXT PRIMARY KEY, estado_id TEXT NOT NULL REFERENCES seguimientos(id), caso TEXT NOT NULL,
    generacion INTEGER NOT NULL DEFAULT 0, fencing INTEGER NOT NULL DEFAULT 0,
    incluido INTEGER NOT NULL DEFAULT 0, UNIQUE(estado_id, caso), UNIQUE(id, generacion));
CREATE TABLE IF NOT EXISTS actuaciones(
    expediente_id TEXT NOT NULL REFERENCES expedientes(id), local_id TEXT NOT NULL, orden INTEGER NOT NULL,
    version_hash TEXT NOT NULL, status TEXT NOT NULL, source_id TEXT, contract_ref TEXT, origin_scope TEXT,
    PRIMARY KEY(expediente_id, local_id), UNIQUE(expediente_id, local_id, version_hash));
CREATE TABLE IF NOT EXISTS sincronizaciones(
    id TEXT PRIMARY KEY, expediente_id TEXT NOT NULL REFERENCES expedientes(id), clave TEXT NOT NULL,
    estado TEXT NOT NULL, generacion_base INTEGER NOT NULL, fencing INTEGER NOT NULL, token TEXT,
    lease_hasta REAL, generacion_confirmada INTEGER, contenido_hash TEXT, digest_version INTEGER,
    UNIQUE(clave), CHECK ((contenido_hash IS NULL) = (digest_version IS NULL)));
CREATE TABLE IF NOT EXISTS eventos(
    id TEXT PRIMARY KEY, expediente_id TEXT NOT NULL REFERENCES expedientes(id),
    sincronizacion_id TEXT NOT NULL REFERENCES sincronizaciones(id), ordinal INTEGER NOT NULL,
    local_id TEXT NOT NULL, generacion INTEGER NOT NULL, tipo TEXT NOT NULL, prioridad TEXT NOT NULL,
    disposicion TEXT NOT NULL DEFAULT 'pendiente' CHECK (disposicion IN ('pendiente','procesado')),
    creado REAL NOT NULL, UNIQUE(sincronizacion_id, ordinal),
    FOREIGN KEY(expediente_id, local_id) REFERENCES actuaciones(expediente_id, local_id));
CREATE TABLE IF NOT EXISTS vista_casos(
    expediente_id TEXT PRIMARY KEY REFERENCES expedientes(id), titulo TEXT NOT NULL, actualizado REAL NOT NULL,
    generacion INTEGER NOT NULL,
    FOREIGN KEY(expediente_id, generacion) REFERENCES expedientes(id, generacion) DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE IF NOT EXISTS vista_actuaciones(
    expediente_id TEXT NOT NULL REFERENCES expedientes(id), orden INTEGER NOT NULL, local_id TEXT NOT NULL,
    generacion INTEGER NOT NULL, huella TEXT NOT NULL, contenido TEXT NOT NULL,
    PRIMARY KEY(expediente_id, local_id), UNIQUE(expediente_id, orden),
    FOREIGN KEY(expediente_id, local_id, huella) REFERENCES actuaciones(expediente_id, local_id, version_hash)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY(expediente_id, generacion) REFERENCES expedientes(id, generacion) DEFERRABLE INITIALLY DEFERRED);
"""


def _json(valor):
    return None if valor is None else json.dumps(valor, sort_keys=True, ensure_ascii=False)


def _de_json(texto):
    return None if texto is None else json.loads(texto)


def _firma_esquema(conexion):
    objetos = conexion.execute("SELECT type, name, tbl_name, sql FROM sqlite_schema "
                               "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
    return hashlib.sha256(_json([tuple(f) for f in objetos]).encode()).hexdigest()


@lru_cache(maxsize=1)
def _firma_esperada():
    with closing(sqlite3.connect(':memory:')) as conexion:
        conexion.executescript(_DDL)
        return _firma_esquema(conexion)


class UnidadSqliteLocal:
    def __init__(self, conexion, politica, reloj, lectura, perfil="sintetico", lectura_sigac=None):
        self._c, self._politica, self._reloj, self._lectura = conexion, politica, reloj, lectura
        self._perfil = perfil
        self._lectura_sigac = lectura_sigac
        self._rechazo_alcance = False

    def _escritura(self):
        self._validar_alcance_final()
        if self._lectura:
            raise PermissionError("Transaccion de solo lectura")
        if self._perfil == 'real':
            from tinotify.integrations.sigac.lectura_validada import _resolver_lectura
            _resolver_lectura(self._lectura_sigac)

    def _validar_alcance_final(self):
        if self._rechazo_alcance:
            raise PermissionError('Unidad abortada por operacion fuera del expediente acreditado')

    def _denegar_alcance(self):
        self._rechazo_alcance = True
        raise PermissionError('Operacion fuera del expediente acreditado')

    def _alcance_caso(self, instancia, caso):
        if self._perfil != 'real':
            return
        self._escritura()
        from tinotify.integrations.sigac.lectura_validada import _referencia_local
        if instancia != 'sigac-real' or caso != _referencia_local(self._lectura_sigac):
            self._denegar_alcance()

    def _alcance_expediente(self, expediente_id, estado_id=None):
        if self._perfil != 'real':
            return
        self._escritura()
        fila = self._c.execute(
            'SELECT e.caso,e.estado_id,s.instancia FROM expedientes e '
            'JOIN seguimientos s ON s.id=e.estado_id WHERE e.id=?', (str(expediente_id),),
        ).fetchone()
        if fila is None or (estado_id is not None and fila['estado_id'] != str(estado_id)):
            self._denegar_alcance()
        self._alcance_caso(fila['instancia'], fila['caso'])

    def _alcance_reserva(self, reserva):
        if self._perfil != 'real':
            return
        self._alcance_expediente(reserva.seguimiento.expediente_id, reserva.seguimiento.estado_id)
        # Resolver el dueño REAL del trabajo: no confiar solo en Seguimiento
        # incluido en un dataclass Reserva que el llamador puede reconstruir.
        trabajo = self._c.execute('SELECT expediente_id FROM sincronizaciones WHERE id=?',
                                  (str(reserva.trabajo_id),)).fetchone()
        if trabajo is None:
            self._denegar_alcance()
        self._alcance_expediente(trabajo['expediente_id'])
        if trabajo['expediente_id'] != str(reserva.seguimiento.expediente_id):
            self._denegar_alcance()

    @staticmethod
    def _binding(binding):
        if binding != BINDING_LOCAL:
            raise PermissionError("Operacion no autorizada")

    # --- Contrato UnidadSeguimiento -------------------------------------------------------------
    def buscar_seguimiento(self, instancia, caso):
        fila = self._c.execute("SELECT e.id, e.estado_id FROM expedientes e JOIN seguimientos s ON s.id=e.estado_id "
                               "WHERE s.instancia=? AND e.caso=?", (instancia, caso)).fetchone()
        return Seguimiento(UUID(fila['estado_id']), UUID(fila['id'])) if fila else None

    def generacion(self, seguimiento):
        fila = self._c.execute("SELECT generacion FROM expedientes WHERE id=? AND estado_id=?",
                              (str(seguimiento.expediente_id), str(seguimiento.estado_id))).fetchone()
        if fila is None:
            raise ConflictoPersistenciaLocal('Seguimiento inexistente')
        return fila['generacion']

    def recibo_operacion(self, seguimiento, clave, digest):
        fila = self._c.execute("SELECT * FROM sincronizaciones WHERE clave=?", (str(clave),)).fetchone()
        if fila is None:
            return None
        if (seguimiento is None or fila['expediente_id'] != str(seguimiento.expediente_id)
                or fila['contenido_hash'] != digest or fila['digest_version'] != 1):
            raise ConflictoPersistenciaLocal('Clave reutilizada con contenido distinto o no verificable')
        if fila['estado'] != 'confirmada':
            raise ConflictoPersistenciaLocal('Operacion sin confirmacion; no se reintenta automaticamente')
        from tinotify.persistence.interfaces import Recibo
        return Recibo(UUID(fila['id']), fila['generacion_confirmada'], True)

    def asociar_digest(self, reserva, digest):
        self._escritura()
        self._alcance_reserva(reserva)
        self._c.execute("UPDATE sincronizaciones SET contenido_hash=?, digest_version=1 WHERE id=? "
                        "AND estado='ejecutando' AND token=? AND contenido_hash IS NULL",
                        (digest, str(reserva.trabajo_id), str(reserva.token)))
    def seguir(self, instancia, caso, politica):
        self._escritura()
        self._alcance_caso(instancia, caso)
        binario(instancia), binario(caso)
        fila = self._c.execute("SELECT id, politica FROM seguimientos WHERE instancia=?", (instancia,)).fetchone()
        if fila is None:
            estado_id = str(uuid4())
            self._c.execute("INSERT INTO seguimientos(id, instancia, politica) VALUES (?,?,?)",
                            (estado_id, instancia, politica))
        else:
            estado_id = fila["id"]
            if fila["politica"] != politica:
                raise ConflictoPersistenciaLocal("Transicion explicita de politica requerida")
        self._c.execute("INSERT OR IGNORE INTO expedientes(id, estado_id, caso) VALUES (?,?,?)",
                        (str(uuid4()), estado_id, caso))
        expediente = self._c.execute("SELECT id FROM expedientes WHERE estado_id=? AND caso=?",
                                     (estado_id, caso)).fetchone()["id"]
        return Seguimiento(UUID(estado_id), UUID(expediente))

    def reservar(self, seguimiento, clave, worker, binding):
        self._escritura()
        self._alcance_expediente(seguimiento.expediente_id, seguimiento.estado_id)
        self._binding(binding)
        e = self._c.execute("SELECT * FROM expedientes WHERE id=? AND estado_id=?",
                            (str(seguimiento.expediente_id), str(seguimiento.estado_id))).fetchone()
        if e is None:
            raise PermissionError("Seguimiento no autorizado")
        previa = self._c.execute("SELECT * FROM sincronizaciones WHERE expediente_id=? AND clave=?",
                                 (e["id"], str(clave))).fetchone()
        if previa is not None:
            if previa["estado"] == "confirmada":
                return Reserva(seguimiento, UUID(previa["id"]), None, previa["generacion_confirmada"], "confirmada")
            raise ConflictoPersistenciaLocal("Clave de operacion ya reservada; revisar recibo")
        ahora = self._reloj()
        self._c.execute("UPDATE sincronizaciones SET estado='expirada' WHERE expediente_id=? "
                        "AND estado='ejecutando' AND lease_hasta<=?", (e["id"], ahora))
        fencing = e["fencing"] + 1
        self._c.execute("UPDATE expedientes SET fencing=? WHERE id=?", (fencing, e["id"]))
        trabajo, token = uuid4(), uuid4()
        self._c.execute(
            "INSERT INTO sincronizaciones(id, expediente_id, clave, estado, generacion_base, fencing, token, lease_hasta) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (str(trabajo), e["id"], str(clave), "ejecutando", e["generacion"], fencing, str(token),
             ahora + _LEASE_SEGUNDOS))
        return Reserva(seguimiento, trabajo, token, e["generacion"], "ejecutando")

    def _registros(self, expediente):
        filas = self._c.execute("SELECT * FROM actuaciones WHERE expediente_id=? ORDER BY orden", (expediente,)).fetchall()
        return [{"local_id": f["local_id"], "source_id": f["source_id"],
                 "contract_ref": _de_json(f["contract_ref"]), "origin_scope": _de_json(f["origin_scope"]),
                 "version_hash": f["version_hash"], "status": f["status"]} for f in filas]

    def leer_caso(self, seguimiento, binding):
        self._binding(binding)
        e = self._c.execute("SELECT * FROM expedientes WHERE id=? AND estado_id=?",
                            (str(seguimiento.expediente_id), str(seguimiento.estado_id))).fetchone()
        if e is None:
            raise PermissionError("Seguimiento no autorizado")
        return {"records": self._registros(e["id"])} if e["incluido"] else None

    def confirmar(self, reserva, registros, eventos, politica):
        self._escritura()
        self._alcance_reserva(reserva)
        e = self._c.execute("SELECT * FROM expedientes WHERE id=? AND estado_id=?",
                            (str(reserva.seguimiento.expediente_id), str(reserva.seguimiento.estado_id))).fetchone()
        cabecera = self._c.execute("SELECT * FROM seguimientos WHERE id=?",
                                   (str(reserva.seguimiento.estado_id),)).fetchone()
        j = self._c.execute("SELECT * FROM sincronizaciones WHERE id=? AND expediente_id=?",
                            (str(reserva.trabajo_id), str(reserva.seguimiento.expediente_id))).fetchone()
        if (
            e is None or cabecera is None or j is None or cabecera["politica"] != politica
            or j["estado"] != "ejecutando" or reserva.token is None or j["token"] != str(reserva.token)
            or j["lease_hasta"] <= self._reloj() or j["generacion_base"] != reserva.generacion
            or e["generacion"] != reserva.generacion or j["fencing"] != e["fencing"]
        ):
            raise ConflictoPersistenciaLocal("Reserva o generacion no vigente")
        if not isinstance(registros, list) or not isinstance(eventos, list) \
                or len(registros) > 100000 or len(eventos) > 100000:
            raise ValueError("Cuota o formato de lote no valido")
        locales = [r["local_id"] for r in registros]
        if len(set(locales)) != len(locales):
            raise ValueError("Identidades locales repetidas")
        anteriores = {f["local_id"]: f for f in self._c.execute(
            "SELECT * FROM actuaciones WHERE expediente_id=?", (e["id"],)).fetchall()}
        if set(anteriores) - set(locales):
            raise ValueError("No se permite eliminar actuaciones por ausencia")
        for orden, r in enumerate(registros):
            viejo = anteriores.get(r["local_id"])
            if viejo is not None and (viejo["source_id"], viejo["contract_ref"], viejo["origin_scope"]) != (
                    r["source_id"], _json(r["contract_ref"]), _json(r["origin_scope"])):
                raise ValueError("Identidad persistente inmutable")
            self._c.execute(
                "INSERT INTO actuaciones(expediente_id, local_id, orden, version_hash, status, source_id, contract_ref, "
                "origin_scope) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(expediente_id, local_id) DO UPDATE SET "
                "orden=excluded.orden, version_hash=excluded.version_hash, status=excluded.status",
                (e["id"], r["local_id"], orden, r["version_hash"], r["status"], r["source_id"],
                 _json(r["contract_ref"]), _json(r["origin_scope"])))
        for ordinal, ev in enumerate(eventos):
            if ev["local_id"] not in set(locales):
                raise ValueError("Evento sin registro asociado")
            self._c.execute(
                "INSERT INTO eventos(id, expediente_id, sincronizacion_id, ordinal, local_id, generacion, tipo, "
                "prioridad, creado) VALUES (?,?,?,?,?,?,?,?,?)",
                (str(uuid4()), e["id"], j["id"], ordinal, ev["local_id"], reserva.generacion + 1,
                 ev["tipo"], ev["prioridad"], self._reloj()))
        self._c.execute("UPDATE expedientes SET generacion=?, incluido=1 WHERE id=?",
                        (reserva.generacion + 1, e["id"]))
        self._c.execute("UPDATE sincronizaciones SET estado='confirmada', generacion_confirmada=?, token=NULL, "
                        "lease_hasta=NULL WHERE id=?", (reserva.generacion + 1, j["id"]))
        # Incluso la interfaz interna de seguimiento deja una proyección mínima
        # de la generación confirmada en esta misma transacción.
        self.guardar_vista(e['caso'], 'Expediente local',
                          [(r['local_id'], r['version_hash'], {}) for r in registros])
        return reserva.generacion + 1

    def exportar(self, instancia, binding):
        self._binding(binding)
        cabecera = self._c.execute("SELECT * FROM seguimientos WHERE instancia=?", (instancia,)).fetchone()
        if cabecera is None:
            return None
        if cabecera["politica"] != self._politica.firma(instancia):
            raise ConflictoPersistenciaLocal("Transicion requerida")
        estado = _nuevo_estado(politica=self._politica, instancia=instancia)
        for e in self._c.execute("SELECT * FROM expedientes WHERE estado_id=? AND incluido=1", (cabecera["id"],)):
            estado["cases"][e["caso"]] = {"records": self._registros(e["id"])}
        validar_confianza(estado, self._politica, instancia)
        return estado

    def pendientes(self, binding, limite):
        self._binding(binding)
        if not isinstance(limite, int) or not 1 <= limite <= 100:
            raise ValueError("Limite de consulta no valido")
        filas = self._c.execute(
            "SELECT id, tipo, prioridad FROM eventos WHERE disposicion='pendiente' "
            "ORDER BY CASE prioridad WHEN 'alta' THEN 0 ELSE 1 END, creado, rowid LIMIT ?", (limite,)).fetchall()
        return [{"id": f["id"], "tipo": f["tipo"], "prioridad": f["prioridad"]} for f in filas]

    def procesar_aviso(self, evento, binding):
        self._escritura()
        self._binding(binding)
        fila = self._c.execute("SELECT expediente_id FROM eventos WHERE id=?", (str(evento),)).fetchone()
        if fila is None:
            raise ConflictoPersistenciaLocal("Aviso inexistente")
        self._alcance_expediente(fila['expediente_id'])
        self._c.execute("UPDATE eventos SET disposicion='procesado' WHERE id=? AND disposicion='pendiente'",
                        (str(evento),))

    # --- Proyección vinculada a identidad y generación; contenido detallado solo sintético ----------
    def _expediente(self, caso):
        filas = self._c.execute("SELECT * FROM expedientes WHERE caso=? AND incluido=1", (caso,)).fetchall()
        if not filas:
            raise KeyError(caso)
        if len(filas) != 1:
            raise ConflictoPersistenciaLocal('Caso ambiguo entre instancias locales')
        return filas[0]

    def guardar_vista(self, caso, titulo, filas):
        """Proyección en la misma transacción: [(local_id, huella, contenido)]."""
        self._escritura()
        self._alcance_caso('sigac-real', caso)
        e = self._expediente(caso)
        self._alcance_expediente(e['id'], e['estado_id'])
        registros = {r['local_id']: r['version_hash'] for r in self._registros(e['id'])}
        if (len(filas) != len(registros) or {local for local, _, _ in filas} != set(registros)
                or any(registros[local] != huella for local, huella, _ in filas)):
            raise ValueError('La proyeccion no corresponde a los registros confirmados')
        if self._perfil == 'real':
            titulo = 'Expediente local'
            if any(contenido for _, _, contenido in filas):
                raise ValueError('El perfil real solo permite metadatos minimos')
        self._c.execute("DELETE FROM vista_actuaciones WHERE expediente_id=?", (e["id"],))
        for orden, (local_id, huella, contenido) in enumerate(filas):
            self._c.execute("INSERT INTO vista_actuaciones(expediente_id, orden, local_id, generacion, huella, contenido) "
                            "VALUES (?,?,?,?,?,?)", (e['id'], orden, local_id, e['generacion'], huella, _json(contenido)))
        self._c.execute("INSERT INTO vista_casos(expediente_id, titulo, actualizado, generacion) VALUES (?,?,?,?) "
                        "ON CONFLICT(expediente_id) DO UPDATE SET titulo=excluded.titulo, actualizado=excluded.actualizado, "
                        "generacion=excluded.generacion", (e['id'], titulo, self._reloj(), e['generacion']))

    def casos(self):
        return [{"caso": f["caso"], "titulo": f["titulo"], "generacion": f["generacion"]} for f in self._c.execute(
            "SELECT e.caso, e.generacion, v.titulo FROM expedientes e JOIN vista_casos v ON v.expediente_id=e.id "
            "WHERE e.incluido=1 ORDER BY e.caso")]

    def vista(self, caso):
        e = self._expediente(caso)
        titulo = self._c.execute("SELECT titulo FROM vista_casos WHERE expediente_id=?", (e["id"],)).fetchone()
        filas = self._c.execute("SELECT local_id, generacion, huella, contenido FROM vista_actuaciones WHERE expediente_id=? ORDER BY orden",
                                (e["id"],)).fetchall()
        return {"caso": caso, "titulo": titulo["titulo"] if titulo else "", "generacion": e["generacion"],
                "actuaciones": [{"local_id": f['local_id'], "generacion": f['generacion'],
                                 "huella": f["huella"], **_de_json(f["contenido"])} for f in filas]}

    def eventos_pendientes_con_caso(self, ids):
        """Para cada aviso pendiente: caso, tipo y huella de la actuación afectada."""
        resultado = {}
        for i in ids:
            f = self._c.execute(
                "SELECT ev.id, ev.local_id, ex.caso, a.version_hash FROM eventos ev JOIN expedientes ex ON ex.id=ev.expediente_id "
                "LEFT JOIN actuaciones a ON a.expediente_id=ev.expediente_id AND a.local_id=ev.local_id "
                "WHERE ev.id=? AND ev.disposicion='pendiente'", (str(i),)).fetchone()
            if f is not None:
                resultado[f["id"]] = {"caso": f["caso"], "huella": f["version_hash"], "local_id": f['local_id']}
        return resultado

    def observaciones_internas(self):
        """Consulta de eventos, incluso procesados; no crea avisos ni concede entrega.

        La disposición heredada no determina si una observación puede consultarse.
        No devuelve huellas, prioridades ni contenido judicial.
        """
        return [dict(f) for f in self._c.execute(
            "SELECT ev.id, ex.caso, ev.local_id, ev.generacion, ev.tipo "
            "FROM eventos ev JOIN expedientes ex ON ex.id=ev.expediente_id "
            "ORDER BY ex.caso, ev.generacion, ev.ordinal, ev.id")]

    def pendientes_por_caso(self):
        return {f["caso"]: f["n"] for f in self._c.execute(
            "SELECT ex.caso, COUNT(*) AS n FROM eventos ev JOIN expedientes ex ON ex.id=ev.expediente_id "
            "WHERE ev.disposicion='pendiente' GROUP BY ex.caso")}

    def eventos_de_generacion(self, caso, generacion):
        e = self._expediente(caso)
        return self._c.execute("SELECT COUNT(*) AS n FROM eventos WHERE expediente_id=? AND generacion=?",
                               (e["id"], generacion)).fetchone()["n"]


class AlmacenSqliteLocal:
    """Un archivo SQLite local. Sin red, sin credenciales reales, solo para desarrollo."""

    def __init__(self, ruta, *, politica=None, reloj=time.time, perfil="sintetico"):
        if perfil not in PERFILES:
            raise ValueError("Perfil de almacen no valido")
        self.ruta, self._perfil = Path(ruta), perfil
        self._politica = politica if politica is not None else PoliticaConfianza()
        self._reloj = reloj
        self.ruta = self.ruta.resolve()
        try:
            if self.ruta.exists():
                self._verificar_existente()
            else:
                self.ruta.parent.mkdir(parents=True, exist_ok=True)
                # Exclusión de creación: nunca interpretar un archivo vacío
                # preexistente como permiso para inicializarlo.
                fd = os.open(self.ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                with closing(self._abrir()) as conexion:
                    conexion.execute('BEGIN IMMEDIATE')
                    try:
                        for sentencia in _DDL.split(';'):
                            if sentencia.strip():
                                conexion.execute(sentencia)
                        conexion.executemany('INSERT INTO meta(clave, valor) VALUES (?,?)', [
                            ('esquema', str(_ESQUEMA)), ('perfil', perfil), ('ddl_firma', _firma_esperada())])
                        conexion.execute('COMMIT')
                    except BaseException:
                        if conexion.in_transaction:
                            conexion.execute('ROLLBACK')
                        raise
        except (sqlite3.Error, OSError, ValueError):
            raise AlmacenLocalNoDisponible('Archivo no disponible o incompatible; no se migra ni repara') from None

    @property
    def perfil(self):
        return self._perfil

    def _validar_formato(self, conexion):
        meta = dict(conexion.execute('SELECT clave, valor FROM meta').fetchall())
        if meta != {'esquema': str(_ESQUEMA), 'perfil': self.perfil, 'ddl_firma': _firma_esperada()}:
            raise AlmacenLocalNoDisponible('Se exige SQLite local v2 del mismo perfil; archivo intacto')
        if _firma_esquema(conexion) != _firma_esperada():
            raise AlmacenLocalNoDisponible('Esquema incompatible; archivo intacto')

    def _verificar_existente(self):
        # immutable evita crear sidecars, ejecutar recuperación o escribir en
        # archivos v1/desconocidos antes de reconocer el formato.
        conexion = sqlite3.connect(self.ruta.as_uri() + '?mode=ro&immutable=1', uri=True)
        try:
            self._validar_formato(conexion)
        finally:
            conexion.close()
        if any(Path(str(self.ruta) + sufijo).exists() for sufijo in ('-wal', '-shm')):
            raise AlmacenLocalNoDisponible('Modo WAL no soportado por este formato local')
        # Verificar integridad y posible rollback journal en una copia privada.
        # Solo un v2 verificado podrá abrirse luego para recuperación normal de
        # SQLite; nunca se repara ni sobrescribe un original rechazado.
        with tempfile.TemporaryDirectory(prefix='tinotify-verificacion-') as temporal:
            copia = Path(temporal) / 'verificar.sqlite3'
            shutil.copyfile(self.ruta, copia)
            journal = Path(str(self.ruta) + '-journal')
            if journal.exists():
                shutil.copyfile(journal, Path(str(copia) + '-journal'))
            conexion = sqlite3.connect(copia)
            try:
                self._validar_formato(conexion)
                if conexion.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise AlmacenLocalNoDisponible('Integridad no verificada; original intacto')
                if conexion.execute('PRAGMA foreign_key_check').fetchone() is not None:
                    raise AlmacenLocalNoDisponible('Integridad referencial no verificada; original intacto')
                if conexion.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
                    raise AlmacenLocalNoDisponible('Modo de journal incompatible')
            finally:
                conexion.close()

    def _abrir(self):
        conexion = sqlite3.connect(self.ruta.as_uri() + '?mode=rw', uri=True, isolation_level=None, timeout=5)
        try:
            conexion.row_factory = sqlite3.Row
            conexion.execute("PRAGMA foreign_keys=ON")
            conexion.execute("PRAGMA synchronous=FULL")
        except BaseException:
            conexion.close()
            raise
        return conexion

    def _commit(self, conexion):
        conexion.execute('COMMIT')

    @contextmanager
    def transaccion(self, credencial, *, lectura=False):
        if not lectura and self.perfil == 'real':
            raise PermissionError('Escritura real reservada al observador de respuestas validadas')
        with self._transaccion(credencial, lectura=lectura) as unidad:
            yield unidad

    @contextmanager
    def _transaccion_sigac(self, lectura, caso):
        from tinotify.integrations.sigac.lectura_validada import _referencia_local
        if self.perfil != 'real' or caso != _referencia_local(lectura):
            raise PermissionError('Respuesta y almacenamiento no corresponden')
        with self._transaccion(CREDENCIAL_LOCAL, lectura_sigac=lectura, caso_sigac=caso) as unidad:
            yield unidad

    @contextmanager
    def _transaccion(self, credencial, *, lectura=False, lectura_sigac=None, caso_sigac=None):
        if credencial != CREDENCIAL_LOCAL:
            raise PermissionError("Operacion no autorizada")
        if self.perfil == 'real' and not lectura:
            from tinotify.integrations.sigac.lectura_validada import _referencia_local
            if caso_sigac != _referencia_local(lectura_sigac):
                raise PermissionError('Lectura y caso no corresponden')
        try:
            conexion = self._abrir()
        except sqlite3.Error:
            raise AlmacenLocalNoDisponible("No se pudo abrir el almacen local.") from None
        try:
            if lectura:
                conexion.execute('PRAGMA query_only=ON')
            conexion.execute("BEGIN" if lectura else "BEGIN IMMEDIATE")
            try:
                self._validar_formato(conexion)
                unidad = UnidadSqliteLocal(conexion, self._politica, self._reloj, lectura, self.perfil, lectura_sigac)
                yield unidad
                unidad._validar_alcance_final()
                try:
                    self._commit(conexion)
                except sqlite3.Error:
                    if not conexion.in_transaction:
                        raise ResultadoCommitIncierto('Resultado de commit incierto; consultar recibo') from None
                    raise
            except BaseException:
                if conexion.in_transaction:
                    conexion.execute("ROLLBACK")
                raise
        except sqlite3.Error:
            raise AlmacenLocalNoDisponible("Operacion revertida; estado anterior conservado.") from None
        finally:
            conexion.close()
