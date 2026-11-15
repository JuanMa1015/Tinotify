"""Configuración segura del backend sintético remoto. Todo se valida al arrancar y falla cerrado.

Los mensajes de error nunca incluyen valores de configuración (ni el token ni rutas), solo un código estable.
"""

from dataclasses import dataclass, field
import ipaddress
import os
from pathlib import Path
import re
import sqlite3
import math

MODO_LOCAL = "pruebas-locales"
MODO_REMOTO = "remoto"
TLS_DIRECTO = "directo"
TLS_PROXY = "proxy"

PREFIJOS_PROHIBIDOS = ("TINOTIFY_REAL_", "TINOTIFY_SIGAC_", "SIGAC_")
# Credenciales de otro tipo que nunca deben alimentar este entorno (p. ej. la clave service_role de Supabase).
NOMBRES_PROHIBIDOS = ("DATABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_DB_URL")
ALMACENES = ("sqlite", "postgres")
PROXIES_PRIVADAS = "privadas"       # palabra clave: solo pares TCP con IP privada (plataforma que aisla el contenedor)
REDES_PRIVADAS = tuple(ipaddress.ip_network(r) for r in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
SUFIJOS_BD = (".sqlite3", ".sqlite", ".db")
MAX_ACTUACIONES_TOPE = 200          # tope duro del generador sintético
MAX_BD_BYTES_TOPE = 64 * 1024 * 1024
_TOKEN_DEBIL = ("changeme", "password", "secret", "example", "ejemplo", "tinotify-desarrollo-local", "contrasena")


class ConfiguracionInsegura(ValueError):
    """Configuración rechazada. `codigo` es estable y no contiene valores sensibles."""

    def __init__(self, codigo):
        super().__init__(f"Configuracion rechazada: {codigo}")
        self.codigo = codigo


def _rechazar(codigo):
    raise ConfiguracionInsegura(codigo)


def validar_token(token):
    if not isinstance(token, str) or not token:
        _rechazar("token_ausente")
    if len(token) < 32 or len(token) > 256 or re.search(r"\s", token) or not token.isascii() or not token.isprintable():
        _rechazar("token_inseguro")
    if len(set(token)) < 12 or any(p in token.lower() for p in _TOKEN_DEBIL):
        _rechazar("token_inseguro")
    return token


def _rechazar_entorno_real(entorno):
    for clave in entorno:
        nombre = str(clave).upper()
        if nombre.startswith(PREFIJOS_PROHIBIDOS):
            _rechazar("variable_del_entorno_real_presente")
        if nombre in NOMBRES_PROHIBIDOS:
            _rechazar("credencial_ajena_presente")


def validar_ruta_bd(ruta):
    """Ruta propia del entorno sintético: nunca el almacenamiento reservado del entorno local real."""
    if not isinstance(ruta, str) or not ruta.strip() or "\x00" in ruta:
        _rechazar("bd_ausente")
    try:
        resuelta = Path(ruta).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        _rechazar("bd_invalida")
    if resuelta.suffix.lower() not in SUFIJOS_BD:
        _rechazar("bd_extension_no_permitida")
    if any(parte.lower() == ".local" for parte in resuelta.parts) or resuelta.name.lower().startswith("real"):
        _rechazar("bd_ruta_reservada_del_entorno_real")
    if resuelta.is_dir():
        _rechazar("bd_invalida")
    if resuelta.exists() and resuelta.stat().st_size > 0:
        # Comprobación de solo lectura: un archivo existente debe ser una base del perfil sintético.
        try:
            conexion = sqlite3.connect(resuelta.as_uri() + "?mode=ro", uri=True, timeout=5)
            try:
                fila = conexion.execute("SELECT valor FROM meta WHERE clave='perfil'").fetchone()
            finally:
                conexion.close()
        except sqlite3.Error:
            _rechazar("bd_no_es_sintetica")
        if fila is not None and fila[0] != "sintetico":
            _rechazar("bd_de_perfil_real")
    return resuelta


def _proxies(texto):
    if not texto or not texto.strip():
        _rechazar("proxies_confiables_ausentes")
    if texto.strip().lower() == PROXIES_PRIVADAS:
        return REDES_PRIVADAS
    redes = []
    for trozo in texto.split(","):
        trozo = trozo.strip()
        if not trozo or "*" in trozo:
            _rechazar("proxies_confiables_invalidos")
        try:
            red = ipaddress.ip_network(trozo, strict=True)
        except ValueError:
            _rechazar("proxies_confiables_invalidos")
        minimo = 24 if red.version == 4 else 64
        if red.network_address.is_unspecified or red.prefixlen < minimo:
            _rechazar("proxies_confiables_demasiado_amplios")
        redes.append(red)
    return tuple(redes)


def _numero(texto, minimo, maximo, codigo, *, tipo=float):
    try:
        valor = tipo(texto)
    except (TypeError, ValueError):
        _rechazar(codigo)
    if not minimo <= valor <= maximo or not math.isfinite(valor):
        _rechazar(codigo)
    return valor


@dataclass(frozen=True)
class ConfigPg:
    """Conexion a PostgreSQL por componentes (nunca un DSN): TLS verify-full obligatorio y CA explicita."""

    host: str
    puerto: int
    base: str
    usuario: str
    password: str = field(repr=False)
    ca: Path
    modo: str = "sesion"          # "sesion" (pooler de sesion de Supabase) o "directa"
    max_conexiones: int = 3
    hostaddr: str | None = None   # solo para pruebas con un servidor desechable; no se lee del entorno
    espera_s: float = 5.0         # plazo de conexion y de espera en el pool; las pruebas lo reducen

    def __repr__(self):
        return f"ConfigPg(host=<oculto>, usuario=<oculto>, modo={self.modo!r})"


_USUARIO_PG = re.compile(r"^tinotify_sintetico_[a-z0-9_]{1,40}(\.[a-z0-9]{8,40})?$")
_HOST_PG = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")


def _config_pg(e):
    if any(str(k).upper().startswith("PG") for k in e):
        _rechazar("variables_libpq_presentes")   # PGSSLMODE, PGOPTIONS, PGPASSWORD...: no se heredan del entorno
    permitidas = {"TINOTIFY_SR_PG_" + x for x in ("HOST", "PORT", "DBNAME", "USER", "PASSWORD", "MODO", "CA_FILE",
                                                  "MAX_CONEXIONES")}
    if any(str(k).upper().startswith("TINOTIFY_SR_PG_") and str(k).upper() not in permitidas for k in e):
        _rechazar("opcion_postgres_desconocida")   # p. ej. un intento de configurar sslmode: no es configurable
    host = e.get("TINOTIFY_SR_PG_HOST", "")
    if not _HOST_PG.fullmatch(host) or host.startswith("-"):
        _rechazar("pg_host_no_valido")
    puerto = _numero(e.get("TINOTIFY_SR_PG_PORT", "5432"), 1, 65535, "pg_puerto_no_valido", tipo=int)
    if puerto == 6543:
        _rechazar("pg_pooler_transaccional_no_admitido")
    base = e.get("TINOTIFY_SR_PG_DBNAME", "postgres")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,63}", base):
        _rechazar("pg_base_no_valida")
    usuario = e.get("TINOTIFY_SR_PG_USER", "")
    if not _USUARIO_PG.fullmatch(usuario):
        _rechazar("pg_usuario_no_restringido")    # solo tinotify_sintetico_*[.<ref del proyecto>]; nunca postgres ni service_role
    password = e.get("TINOTIFY_SR_PG_PASSWORD", "")
    if len(password) < 16 or len(password) > 256 or re.search(r"[\x00-\x1f\x7f]", password) or password != password.strip():
        _rechazar("pg_password_ausente_o_insegura")
    modo = e.get("TINOTIFY_SR_PG_MODO", "sesion")
    if modo not in ("sesion", "directa"):
        _rechazar("pg_modo_no_valido")
    ca_ruta = e.get("TINOTIFY_SR_PG_CA_FILE", "")
    try:
        ca = Path(ca_ruta).resolve()
        ok = bool(ca_ruta) and ca.is_file() and ca.stat().st_size < 1_000_000 and b"BEGIN CERTIFICATE" in ca.read_bytes()
    except (OSError, ValueError):
        ok = False
    if not ok:
        _rechazar("pg_ca_ausente_o_invalida")
    maximo = _numero(e.get("TINOTIFY_SR_PG_MAX_CONEXIONES", "3"), 1, 4, "pg_max_conexiones_no_valido", tipo=int)
    return ConfigPg(host=host, puerto=puerto, base=base, usuario=usuario, password=password, ca=ca, modo=modo,
                    max_conexiones=maximo)


@dataclass(frozen=True)
class Config:
    modo: str
    token: str = field(repr=False)
    ruta_bd: Path | None = None
    tls: str | None = None
    proxies_confiables: tuple = ()
    monitor_activo: bool = True
    intervalo_s: float = 300.0
    max_actuaciones: int = 60
    max_bd_bytes: int = 8 * 1024 * 1024
    almacenamiento: str = "sqlite"
    pg: ConfigPg | None = None

    @property
    def remoto(self):
        return self.modo == MODO_REMOTO

    @classmethod
    def desde_entorno(cls, entorno=None):
        e = os.environ if entorno is None else entorno
        _rechazar_entorno_real(e)
        modo = e.get("TINOTIFY_SR_MODO", "")
        if modo not in (MODO_LOCAL, MODO_REMOTO):
            _rechazar("modo_no_valido")
        token = validar_token(e.get("TINOTIFY_SR_TOKEN"))
        almacenamiento = e.get("TINOTIFY_SR_ALMACEN", "sqlite")
        if almacenamiento not in ALMACENES:
            _rechazar("almacenamiento_no_valido")
        ruta, pg = None, None
        if almacenamiento == "sqlite":
            ruta = validar_ruta_bd(e.get("TINOTIFY_SR_DB"))
            if any(str(k).upper().startswith("TINOTIFY_SR_PG_") for k in e):
                _rechazar("opciones_postgres_con_almacen_sqlite")
        else:
            if e.get("TINOTIFY_SR_DB"):
                _rechazar("almacenamiento_ambiguo")
            pg = _config_pg(e)
        tls, proxies = e.get("TINOTIFY_SR_TLS") or None, ()
        if modo == MODO_LOCAL:
            if tls or e.get("TINOTIFY_SR_PROXIES_CONFIABLES"):
                _rechazar("opciones_de_transporte_no_aplican_en_pruebas_locales")
        else:
            if tls not in (TLS_DIRECTO, TLS_PROXY):
                _rechazar("tls_obligatorio_en_remoto")
            if tls == TLS_PROXY:
                proxies = _proxies(e.get("TINOTIFY_SR_PROXIES_CONFIABLES"))
            elif e.get("TINOTIFY_SR_PROXIES_CONFIABLES"):
                _rechazar("proxies_confiables_solo_con_tls_proxy")
        monitor = e.get("TINOTIFY_SR_MONITOR", "1")
        if monitor not in ("0", "1"):
            _rechazar("monitor_no_valido")
        minimo = 60.0 if modo == MODO_REMOTO else 0.5
        return cls(
            modo=modo, token=token, ruta_bd=ruta, tls=tls, proxies_confiables=proxies, monitor_activo=monitor == "1",
            intervalo_s=_numero(e.get("TINOTIFY_SR_INTERVALO_S", "300"), minimo, 86400.0, "intervalo_no_valido"),
            max_actuaciones=_numero(e.get("TINOTIFY_SR_MAX_ACTUACIONES", "60"), 3, MAX_ACTUACIONES_TOPE,
                                    "limite_actuaciones_no_valido", tipo=int),
            max_bd_bytes=_numero(e.get("TINOTIFY_SR_MAX_BD_BYTES", str(8 * 1024 * 1024)), 256 * 1024,
                                 MAX_BD_BYTES_TOPE, "limite_disco_no_valido", tipo=int),
            almacenamiento=almacenamiento, pg=pg)
